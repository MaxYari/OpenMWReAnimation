"""Concatenate scaled copies of the CURRENT action into one multi-move action.

Blender 5.1+. Source is whatever action is active on the selected object, using
its bound slot. Bake it first (Bizarre Anim > Bake Animation): concatenating
raw curves would drop looped extrapolation, since only the keys are copied.

Output is tagged [Baked] so exporting it does not bake a second time.

Move types go in bare -- 'RunForward', 'WalkLeft'. The weapon type ('1h', '2c')
is taken from the source action's markers ("RunForward2c: loop start") and added
to every group written.
"""

import bpy

# ---------------------------------------------------------------- Configuration

weapon_type = None            # None = detect from markers ('2c')
originalMoveType = None       # None = detect which MOVESET the source belongs to
frame_gap = 50                # Gap between each scaled copy

# Which moveset to build is decided by the source action's own marker group.
# Walking and running come out of the same source, so they share one config;
# sneaking has its own pace and its own pair of directions.
#
# Move types are written BARE here -- 'SneakForward', not 'SneakForward1h'. The
# weapon type is read off the source markers and appended to every group, so one
# config covers 1h, 2c, 2w and the rest.

NORMAL_MOVEMENT = [
    {'moveType': 'RunForward',  'scale': 1,    'alias': 'RunBack'},
    {'moveType': 'RunLeft',     'scale': 1.05, 'alias': 'RunRight'},
    {'moveType': 'WalkForward', 'scale': 1.05, 'alias': 'WalkBack'},
    {'moveType': 'WalkRight',   'scale': 1.1,  'alias': 'WalkLeft'},
]

SNEAK_MOVEMENT = [
    {'moveType': 'SneakForward', 'scale': 2.7, 'alias': 'SneakBack'},
    {'moveType': 'SneakLeft',    'scale': 2.5, 'alias': 'SneakRight'},
]

MOVESETS = {
    'RunForward':   {'name': '[Baked] {weapon} Movement',       'config': NORMAL_MOVEMENT},
    'WalkForward':  {'name': '[Baked] {weapon} Movement',       'config': NORMAL_MOVEMENT},
    'SneakForward': {'name': '[Baked] {weapon} Sneak Movement', 'config': SNEAK_MOVEMENT},
}

# Everything that defines a key's shape, beyond its position and handles.
KEY_PROPERTIES = (
    "interpolation",        # CONSTANT / LINEAR / BEZIER / SINE / ... / BOUNCE
    "easing",               # AUTO / EASE_IN / EASE_OUT / EASE_IN_OUT
    "type",                 # KEYFRAME / BREAKDOWN / EXTREME / JITTER / MOVING_HOLD
    "handle_left_type",     # FREE / ALIGNED / VECTOR / AUTO / AUTO_CLAMPED
    "handle_right_type",
    "amplitude",            # ELASTIC / BACK easing parameters
    "back",
    "period",
)

# ---------------------------------------------------------------------- Helpers


def channelbag_fcurves(action, slot):
    """F-curves belonging to `slot` in `action`."""
    for layer in action.layers:
        for strip in layer.strips:
            channelbag = strip.channelbag(slot)
            if channelbag:
                return channelbag.fcurves
    return None


def split_marker(name):
    """'RunForward2c: loop start' -> ('RunForward2c', 'loop start'), else None."""
    if ':' not in name:
        return None
    group, text = name.split(':', 1)
    return group.strip(), text.strip()


# --------------------------------------------------------------------- Validate

obj = bpy.context.object
if obj is None:
    raise ValueError("No active object. Select the armature holding the source action.")

anim_data = obj.animation_data
if anim_data is None or anim_data.action is None:
    raise ValueError(f"Object '{obj.name}' has no active action to use as the source.")

original_action = anim_data.action
source_slot = anim_data.action_slot
if source_slot is None:
    raise ValueError(f"Action '{original_action.name}' is assigned but not bound to a slot.")

if not original_action.pose_markers:
    raise ValueError(f"Action '{original_action.name}' has no pose markers.")

marker_groups = sorted({split_marker(m.name)[0]
                        for m in original_action.pose_markers
                        if split_marker(m.name)})

# ------------------------------------------------------- Resolve the weapon type
# The move type is configured bare ('RunForward'); whatever follows it in the
# source action's group name is the weapon type ('2c'), and it gets appended to
# every group this script writes.

# ------------------------------------------------------ Resolve which moveset
# The source's marker group says what it is: 'SneakForward1h: loop start' picks
# the sneak config, 'RunForward2c: ...' the normal one.

if originalMoveType is None:
    matches = sorted({base for base in MOVESETS
                      for group in marker_groups if group.startswith(base)})
    if not matches:
        raise ValueError(
            f"Action '{original_action.name}' does not start from a known moveset.\n"
            f"Expected a marker group beginning with one of: {', '.join(sorted(MOVESETS))}.\n"
            f"Marker groups present: {', '.join(marker_groups) if marker_groups else '(none)'}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"Action '{original_action.name}' matches several movesets: {', '.join(matches)}.\n"
            f"Set originalMoveType explicitly at the top of the script."
        )
    originalMoveType = matches[0]

moveset = MOVESETS.get(originalMoveType)
if moveset is None:
    raise ValueError(
        f"No moveset configured for '{originalMoveType}'. "
        f"Known: {', '.join(sorted(MOVESETS))}."
    )
config = moveset['config']
new_action_name = moveset['name']
print(f"Moveset '{originalMoveType}' -- {len(config)} entries.")

if weapon_type is None:
    suffixes = sorted({group[len(originalMoveType):] for group in marker_groups
                       if group.startswith(originalMoveType)})
    if not suffixes:
        raise ValueError(
            f"Move type '{originalMoveType}' not found in action '{original_action.name}'.\n"
            f"Marker groups present: {', '.join(marker_groups) if marker_groups else '(none)'}"
        )
    if len(suffixes) > 1:
        candidates = ', '.join(f"'{originalMoveType}{s}'" for s in suffixes)
        raise ValueError(
            f"Ambiguous weapon type for '{originalMoveType}' in action "
            f"'{original_action.name}': {candidates}.\n"
            f"Set weapon_type explicitly at the top of the script."
        )
    weapon_type = suffixes[0]

source_group = f"{originalMoveType}{weapon_type}"
if source_group not in marker_groups:
    raise ValueError(
        f"Group '{source_group}' not found in action '{original_action.name}'.\n"
        f"Marker groups present: {', '.join(marker_groups) if marker_groups else '(none)'}"
    )

new_action_name = new_action_name.format(weapon=weapon_type)
print(f"Source group '{source_group}' -- weapon type '{weapon_type}'.")

# ------------------------------------------------------------ Snapshot the source

source_fcurves = channelbag_fcurves(original_action, source_slot)
if not source_fcurves:
    raise ValueError(
        f"Slot '{source_slot.name_display}' of action '{original_action.name}' has no F-curves."
    )

# Snapshot the source keys before we touch anything -- the new action is a copy,
# so its curves would otherwise be read back mid-edit. Curve-level properties
# (extrapolation, modifiers, group, colour, mute/lock) need no snapshot: they
# survive automatically because the target is a copy.
source_keys = {}
for fcurve in source_fcurves:
    source_keys[(fcurve.data_path, fcurve.array_index)] = [
        {
            "co": (kf.co.x, kf.co.y),
            "handle_left": (kf.handle_left.x, kf.handle_left.y),
            "handle_right": (kf.handle_right.x, kf.handle_right.y),
            "properties": {name: getattr(kf, name) for name in KEY_PROPERTIES},
        }
        for kf in fcurve.keyframe_points
    ]

source_markers = [(m.name, float(m.frame)) for m in original_action.pose_markers]

frames = [record["co"][0] for key_data in source_keys.values() for record in key_data]
if not frames:
    raise ValueError(f"Action '{original_action.name}' has F-curves but no keyframes.")
source_length = max(frames) - min(frames)

# ----------------------------------------------------------------- Build target
# Copying the source action gives us its slot / layer / strip / channelbag
# skeleton and all data paths for free, so no part of the layered action API has
# to be constructed by hand.

existing = bpy.data.actions.get(new_action_name)
if existing is not None and existing is not original_action:
    bpy.data.actions.remove(existing)

new_action = original_action.copy()
new_action.name = new_action_name
new_action.use_fake_user = False

# The copy preserves slot order, so the source slot's index locates its twin.
new_slot = new_action.slots[list(original_action.slots).index(source_slot)]

target_curves = {}
for fcurve in channelbag_fcurves(new_action, new_slot):
    fcurve.keyframe_points.clear()
    target_curves[(fcurve.data_path, fcurve.array_index)] = fcurve

for marker in list(new_action.pose_markers):
    new_action.pose_markers.remove(marker)

# ------------------------------------------------------------------- Concatenate

frame_start_offset = 0.0

for cfg in config:
    move_type = cfg['moveType']
    scale = cfg['scale']
    alias = cfg.get('alias')

    for key, key_data in source_keys.items():
        fcurve = target_curves.get(key)
        if fcurve is None or not key_data:
            continue

        # Map source frames into this block. The control point is rounded to a
        # whole frame, so both handles get the same rounding shift applied on top
        # of the scale -- otherwise the tangents drift relative to their key.
        placed = {}
        for record in key_data:
            source_x, y = record["co"]
            scaled_x = frame_start_offset + (source_x * scale)
            new_x = round(scaled_x)
            shift = new_x - scaled_x

            def transform(point):
                px, py = point
                return (frame_start_offset + (px * scale) + shift, py)

            # Keyed by frame so a scale that collapses two keys onto one frame
            # keeps the last, rather than leaving duplicates stacked on it.
            placed[new_x] = {
                "co": (new_x, y),
                "handle_left": transform(record["handle_left"]),
                "handle_right": transform(record["handle_right"]),
                "properties": record["properties"],
            }

        # add() appends in bulk, so index from the current end to leave the
        # earlier blocks in this curve untouched.
        points = fcurve.keyframe_points
        first = len(points)
        points.add(len(placed))
        for offset, frame in enumerate(sorted(placed)):
            record = placed[frame]
            point = points[first + offset]
            # Types before positions: update() recomputes AUTO/VECTOR handles from
            # the type, but leaves FREE/ALIGNED positions as written.
            for name, value in record["properties"].items():
                setattr(point, name, value)
            point.co = record["co"]
            point.handle_left = record["handle_left"]
            point.handle_right = record["handle_right"]

    for name, frame in source_markers:
        split = split_marker(name)
        new_frame = int(round(frame_start_offset + (frame * scale)))

        # Markers outside the source group -- SoundGen footsteps and the like --
        # ride along unrenamed. Each block is its own move group in the .kf, so
        # it needs its own copy of them at the scaled frame.
        if split is None or split[0] != source_group:
            new_action.pose_markers.new(name=name).frame = new_frame
            continue

        text = split[1]
        new_action.pose_markers.new(name=f"{move_type}{weapon_type}: {text}").frame = new_frame

        # The alias group occupies the same frames under a different name, so it
        # shares this block's non-group markers rather than duplicating them.
        if alias:
            new_action.pose_markers.new(name=f"{alias}{weapon_type}: {text}").frame = new_frame

    frame_start_offset += (source_length * scale) + frame_gap

for fcurve in target_curves.values():
    fcurve.update()   # sorts keys and recalculates handles

anim_data.action = new_action
anim_data.action_slot = new_slot

groups_written = ', '.join(
    f"{cfg['moveType']}{weapon_type}" + (f"/{cfg['alias']}{weapon_type}" if cfg.get('alias') else '')
    for cfg in config
)
print(
    f"New action '{new_action.name}': {groups_written}\n"
    f"{len(target_curves)} F-curves, {len(new_action.pose_markers)} markers, "
    f"frames {new_action.curve_frame_range[0]:.0f}-{new_action.curve_frame_range[1]:.0f}."
)
