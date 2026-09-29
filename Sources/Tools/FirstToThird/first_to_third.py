#!/usr/bin/env python3
"""First-person animations to third person: their arms, on a third-person body.

Merges any set of first-person animations (a mod's animations/xbase_anim.1st) with any set of
third-person ones - vanilla's, a whole-set replacer like Animation Compilation, a mod's additions, or
several over each other - into third-person versions of the first-person set: what NPCs play, and the
player with the camera pulled back. They go into the third-person skeleton folders (animations/
xbase_anim, xbase_animkna for beasts, xbase_anim_female for what women's own animations change),
where OpenMW finds them by their group names like any animation replacer. No scripts are involved.

Each one is the first person's upper body on the third person's legs, hips and root motion - of the
third-person animation of the same name, or the one the engine plays in its place. By stance:

* Following the first person (weapons, by default): the chest, spine and arms are turned the way the
  first person turns them, in the character's frame, on the third person's hips, and the head looks
  ahead through attacks (a first-person head turns with every swing, which its camera never shows).
  Timing is the first person's: its text keys, the third person's legs sped up and slowed down
  between the keys both have so each lands on the first person's.
* Held forward (spells, by default): the torso is the third person's, turned toward facing ahead - its
  stance idle's posture, shoulders square - by a share you choose, and the arms are the first
  person's, held against the chest as in its stance's idle, or pointed where the first person points
  them in the character's frame whatever the torso does (two-handed stances left on the torso). Timing
  is the third person's: the first person's arms sped up and slowed down between the keys both have.
* Walks, runs, sneaks and turns keep the third person's timing whatever the stance, and its legs, hips,
  root motion and footsteps as its own keys, copied as they are - several to an instant, where a set
  has them (Animation Compilation's walks) - since the engine paces movement by them. Following, the
  chest sways with the third person's spine on top of the first person's.
* A loop much longer than the third person's (an idle) keeps its own pace, over the third person's loop
  repeated as many times as fits it best.
* Idle arms where the third person shows them. Turning on the spot with a spell ready
  (spellturnleft, spellturnright), and walking or jumping in a stance that is not a weapon and has
  no walks or jump of its own (a spell: the engine moves the legs only and keeps the idle on top,
  character.cpp refreshMovementAnims and refreshJumpAnims, where the spine under it tips the arms)
  show the stance's idle arms. When the first person converts that idle but has none of these, they
  are made too: the third person's turns, walks and jump, with the converted idle's arms.
* Arms held too high - first-person hands sit at the camera's height, which in third person is the
  head's - can be lowered per animation, pivoting down at the shoulder by up to so many degrees where
  the hands are highest, the hands still pointing the way they did.
* Arm bounce (experimental): on walks, runs and sneaks the elbows and wrists can lag behind the
  body's bob and sway and spring back, simulated the way Blender's Wiggle 2 add-on moves bones and
  looped with the walk - by weapon type, if you like. Where both hands hold one weapon only the right
  arm, which holds it, springs; the left reaches after it and stays on the grip.
* Which groups: every first-person group, on the third person's of the same name - or, for one the
  third person lacks, the group the engine would play instead (a dagger's walk the one-handed one's,
  an alternate attack the attack it varies). Walks, runs, sneaks and jumps can be left to the third
  person for the weapon types you name, and any group left out by name.

    python3 first_to_third.py

asks for everything, with defaults filled in: Enter keeps one, -y takes them all. See README.md.
Morrowind.bsa (found from openmw.cfg, or --data-files) is read for vanilla's animations when they are
underneath, and for the skeletons' rest pose where the animations given do not key a bone.
"""
import argparse
import bisect
import contextlib
import fnmatch
import io
import math
import multiprocessing
import os
import shutil
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'FBACompat'))
import fba_merge  # noqa: E402  (add_rest_bones: a first-person kf's missing root and legs)
import kfeval as E  # noqa: E402
import nifkf  # noqa: E402
import params  # noqa: E402
from params import ask, yes_no  # noqa: E402

# Third-person skeleton folder -> vanilla's kf for it. Beasts load theirs over the humans'.
SKELETONS = {'xbase_anim': 'meshes\\xbase_anim.kf', 'xbase_animkna': 'meshes\\xbase_animkna.kf',
             'xbase_anim_female': 'meshes\\xbase_anim_female.kf'}
# Skeletons whose animations the engine loads over the base one's (npcanimation.cpp, updateNpcBase):
# beasts, whose own set is nearly whole, and women, whose own is a few groups.
LAYERS = {'xbase_animkna': 'xbase_anim', 'xbase_anim_female': 'xbase_anim'}
FIRST_PERSON_KF = 'meshes\\xbase_anim.1st.kf'

# The engine's weapon types: attack group -> the short group its idle and walks end in
# (weapontype.cpp).
LONG_GROUPS = {'spellcast': 'spell', 'handtohand': 'hh', 'weapononehand': '1h', 'shortbladeonehand': '1s',
               'bluntonehand': '1b', 'weapontwohand': '2c', 'blunttwohand': '2b', 'weapontwowide': '2w',
               'bowandarrow': 'bow', 'crossbow': 'crossbow', 'throwweapon': '1t', 'pickprobe': '1h'}
# Stances whose missing groups the engine fills from another's (fallbackShortWeaponGroup): two-handed
# melee weapons from the two-handed sword's, every other weapon from the one-handed sword's.
FALLBACK = {'1s': '1h', '1b': '1h', '1t': '1h', 'bow': '1h', 'crossbow': '1h', '2b': '2c', '2w': '2c',
            'pickprobe': '1h'}
# Stances that are not weapons: with no walks of their own the engine walks the legs only.
NOT_WEAPONS = ('spell', 'hh')
MOVES = [move + way for move in ('walk', 'run', 'sneak') for way in ('forward', 'back', 'left', 'right')]
BASES = sorted(['idle', 'jump', 'turnleft', 'turnright'] + MOVES +
               ['swim' + m for m in MOVES if not m.startswith('sneak')], key=len, reverse=True)
TURNS = ('turnleft', 'turnright')  # the engine's spell turns are "spell" + these

NECK = 'Bip01 Neck'  # the clavicles' parent, in every skeleton
HEAD = 'Bip01 Head'
SPINE, CHEST = 'Bip01 Spine', 'Bip01 Spine1'  # the last of the lower body, the first of the upper
TORSO = ('Bip01 Spine2', 'Bip01 Neck', 'Bip01 Head')
TO_NECK = ('Bip01', 'Bip01 Pelvis', SPINE, CHEST, 'Bip01 Spine2', NECK)
ARM_PARTS = ('Clavicle', 'UpperArm', 'Forearm', 'Hand', 'Finger', 'Weapon Bone', 'Shield Bone')
ARM_CHAIN = ('Clavicle', 'UpperArm', 'Forearm', 'Hand')
IDENTITY = (1.0, 0.0, 0.0, 0.0)
FPS = 30.0
GAP = 0.2              # seconds between groups in a file
PACE_RATIO = 1.5       # a first-person loop this much longer than the third person's keeps its pace
KEY_TIME_EPS = 1e-4     # seconds: a key this near a text key is on it (32-bit float times)
ANGLE_TOLERANCE = 0.05  # degrees: keys their neighbours reproduce this closely are left out
MOVE_TOLERANCE = 0.01   # units
THIN_RUN = 60           # keys: the most thinning leaves out in a row, where the bone moves

# A rough idea of how long a build takes, measured on TIMING_MACHINE with TIMING_JOBS files at once:
# seconds per second of first-person animation converted, for each skeleton - beasts get a whole set of
# their own, women only what their own animations change (ReAnimation's set on Animation Compilation) -
# and about as long again as FILL_SECONDS for each skeleton's idle-arm turns and walks, made one at a time.
TIMING_MACHINE = 'a Steam Deck'
TIMING_JOBS = 8
TIMING_RATE = {'xbase_anim': 47 / 215.0, 'xbase_animkna': 41 / 215.0, 'xbase_anim_female': 2 / 215.0}
FILL_SECONDS = 15
TIMING_EXAMPLES = ("ReAnimation's first-person set, 95 files, took a minute and a half; Magic Animations Generally "
                   "Improved Completely's spell casting, 4 files, half a minute")

KEEP_FORWARD = 0.75
HOLD_TORSO = 'spell'    # stances whose torso is the third person's, held forward; the rest follow the first person
THIRD_TIMING = 'spell'  # stances that keep the third person's timing; the rest play at the first person's
STEADY_HEAD = True
REPOINT = 1.0
TWO_HANDED = ('2c', '2b', '2w', 'bow', 'crossbow')  # stances that hold one thing in both hands
GRIP_STANCES = ('2c', '2b', '2w', 'crossbow')  # the weapon in the right hand, the left hand on it
STANCE_NAMES = {'': 'no weapon', 'hh': 'hand-to-hand', 'spell': 'spell', '1h': 'one-handed long blades and axes',
                '1s': 'short blades', '1b': 'one-handed blunt', '2c': 'two-handed long blades and axes',
                '2b': 'two-handed blunt', '2w': 'spears and staves', 'bow': 'bows', 'crossbow': 'crossbows',
                '1t': 'thrown weapons', '1tstar': 'throwing stars'}
ARM_BOUNCE = 0.3
BOUNCE_HZ = 3.5         # the arms' own spring: how fast they swing back
BOUNCE_DAMPING = 0.35   # share of critical damping
BOUNCE_SUBSTEPS = 8
BOUNCE_LAPS = 12        # loops run before the one kept, to settle
VERBOSE = False
JOBS = os.cpu_count() or 1  # files converted at once


def info(text):
    if VERBOSE:
        print(text)


def is_arm(bone):
    return any(part in bone for part in ARM_PARTS)


# ---- vanilla ------------------------------------------------------------------------------------

def bsa_files(path, wanted):
    """{name: bytes} of the wanted files (lowercase, backslashes) in a Morrowind BSA."""
    data = open(path, 'rb').read()
    _version, hash_offset, count = struct.unpack('<III', data[:12])
    records = [struct.unpack('<II', data[12 + 8 * i:20 + 8 * i]) for i in range(count)]
    names_at = 12 + 8 * count
    name_offsets = struct.unpack('<%dI' % count, data[names_at:names_at + 4 * count])
    names_start = names_at + 4 * count
    data_start = 12 + hash_offset + 8 * count
    out = {}
    for i in range(count):
        start = names_start + name_offsets[i]
        name = data[start:data.index(b'\0', start)].decode('latin-1').lower()
        if name in wanted:
            size, offset = records[i]
            out[name] = data[data_start + offset:data_start + offset + size]
    missing = set(wanted) - set(out)
    if missing:
        sys.exit('%s has no %s' % (path, ', '.join(sorted(missing))))
    return out


# ---- text keys -----------------------------------------------------------------------------------

def text_lines(kf):
    out = []
    for tm, text in kf.text_keys():
        for line in text.replace('\r\n', '\n').split('\n'):
            out.append((tm, line))
    return out


def split_line(line):
    group, colon, key = line.partition(':')
    return (group.strip().lower(), key.strip().lower()) if colon else (None, None)


def group_keys(lines):
    """{group: {key: time}}, the first time each key appears."""
    out = {}
    for tm, line in lines:
        group, key = split_line(line)
        if group and group not in ('soundgen', 'sound'):
            out.setdefault(group, {}).setdefault(key, tm)
    return out


def is_footstep_line(line):
    return split_line(line)[0] in ('soundgen', 'sound')


# ---- stances -------------------------------------------------------------------------------------

def stance_of(group):
    """The short group a group's stance goes by - 'spell' for spellcast and spellturnleft, '1h' for
    walkforward1h, '2c' for weapontwohandaltextra (a variant of an attack, or its tail), '1tstar' for
    throwweaponaltstar - or None."""
    if group in LONG_GROUPS:
        return LONG_GROUPS[group]
    for long in sorted(LONG_GROUPS, key=len, reverse=True):
        if group.startswith(long):
            return LONG_GROUPS[long] + ('star' if group.endswith('star') else '')
    for turn in TURNS:
        if group.endswith(turn) and group != turn:
            return group[:-len(turn)]
    for base in BASES:
        if group.startswith(base):
            return group[len(base):]
    return None


def is_idle(group):
    return group.startswith('idle')


def base_and_stance(group):
    """('walkforward', '1h') for walkforward1h - the engine group and the stance it ends in - or
    (None, None) for a group that is not one of those."""
    for base in BASES:
        if group.startswith(base):
            return base, group[len(base):]
    return None, None


def pair_candidates(group, legs_map):
    """Third-person groups a first-person group could take its legs and timing from, best first: one
    given with --legs-from; the same group; for a sneaking idle the third person's own, then the
    stance's idle; for an engine group of a stance the third person has none for, the group the
    engine would play instead (a dagger's walk the one-handed walk, a throwing star's the thrown
    one's); for anything else, the groups its name begins with, longest first (weapononehand1 - an
    alternate attack - on weapononehand)."""
    out = []
    if group in legs_map and legs_map[group][1] is None:
        out.append(legs_map[group][0])
    out.append(group)
    if group.startswith('idle') and group.endswith('sneak') and group != 'idlesneak':
        out.append('idlesneak')
        out += pair_candidates(group[:-len('sneak')], legs_map)
    base, stance = base_and_stance(group)
    if base is not None and stance:
        for s in (stance[:-len('star')] if stance.endswith('star') else None, FALLBACK.get(stance),
                  FALLBACK.get(stance[:-len('star')]) if stance.endswith('star') else None):
            if s is not None:
                out.append(base + s)
        out.append(base)
    return out


def pair_group(group, keys, third, legs_map):
    """(third-person group, its source) to pair a first-person group with - one having the group's
    first and last text keys - or (None, None)."""
    for candidate in pair_candidates(group, legs_map):
        source = third.find(candidate, keys)
        if source is not None:
            return candidate, source
    base, _ = base_and_stance(group)
    if base is None:
        names = sorted({g for src in third.sources for g in src.groups
                        if group.startswith(g) and g != group and len(g) >= 4}, key=len, reverse=True)
        for candidate in names:
            source = third.find(candidate, keys)
            if source is not None:
                return candidate, source
    return None, None


LOCOMOTION = ('walk', 'run', 'sneak', 'swim', 'jump')  # the groups --moves picks by stance


def skipped(group, opts):
    """Left alone: named with --skip, or a walk, run, sneak or jump of a stance --moves does not list."""
    if any(fnmatch.fnmatchcase(group, pattern) for pattern in opts['skip']):
        return True
    base, stance = base_and_stance(group)
    if base is not None and base.startswith(LOCOMOTION) and opts['moves'] is not None:
        family = stance[:-len('star')] if stance.endswith('star') else stance
        return stance not in opts['moves'] and family not in opts['moves']
    return False


def in_stances(stance, chosen):
    """Whether a stance is among those a per-stance setting names (None: all of them): a sneaking
    idle's stance goes by its weapon's, a throwing star's by its thrown weapon's too, and a group with
    no stance (a hit, a knockdown) by 'plain'."""
    if chosen is None:
        return True
    family = stance or ''
    if family.endswith('sneak'):
        family = family[:-len('sneak')]
    return family in chosen or (family.endswith('star') and family[:-len('star')] in chosen)


def is_locomotion(group):
    """Walks, runs, sneaks, swims and turns: the engine paces them by the actor's movement, and moves
    the actor by their root, so they keep the third person's timing."""
    base, _ = base_and_stance(group)
    return base is not None and base.startswith(('walk', 'run', 'sneak', 'swim', 'turn'))


def is_attack(group):
    """A weapon's own group - its attacks, equip and unequip - or a variant or tail of one."""
    return any(group.startswith(long) for long in LONG_GROUPS)


def is_move(group):
    return any(group.startswith(m) for m in MOVES)


# ---- sources -------------------------------------------------------------------------------------

class Source:
    def __init__(self, label, kf):
        self.label, self.kf = label, kf
        self.lines = text_lines(kf)
        self.groups = group_keys(self.lines)


class ThirdPerson:
    """Third-person animations as OpenMW resolves them: vanilla's (when underneath), then each folder's
    .kf files in name order, the last to have a group winning."""

    def __init__(self, vanilla, extra):
        self.sources = ([vanilla] if vanilla is not None else []) + extra

    def find(self, group, keys=()):
        for source in reversed(self.sources):
            have = source.groups.get(group)
            if have is not None and all(k in have for k in keys):
                return source
        return None


def third_person_files(given, skeleton, out_dirs):
    """(base, extra) - the .kf files for one skeleton among the paths given, as the engine loads them.

    base: the last whole-set file given for it - a mod or Data Files folder's meshes/<skeleton>.kf (as
    Animation Compilation ships), a meshes folder's, or a .kf named after the skeleton. The engine
    loads one such file, and it takes vanilla's place. extra: the rest, in load order, going over it -
    a mod's animations/<skeleton>/*.kf, an animations folder's <skeleton>/*.kf, a skeleton folder's
    own. Loose .kf files in a folder that is none of these count as the base skeleton's extras."""
    base, extra = None, []

    def kfs(folder):
        return [os.path.join(folder, n) for n in sorted(os.listdir(folder), key=str.lower) if n.lower().endswith('.kf')]

    def in_output(path):
        if os.path.abspath(os.path.dirname(path)) in [os.path.abspath(d) for d in out_dirs]:
            print('  (not building on %s: it is in the output)' % path)
            return True
        return False

    def add(paths):
        for path in paths:
            if path and os.path.isfile(path) and path not in extra and not in_output(path):
                extra.append(path)

    for item in given:
        name = os.path.basename(os.path.normpath(item)).lower()
        if os.path.isfile(item):
            stem = os.path.splitext(name)[0]
            if stem == skeleton:
                base = item
            elif stem not in SKELETONS and skeleton == 'xbase_anim':
                add([item])
        elif not os.path.isdir(item):
            print('  (%s: no such file or folder)' % item)
        elif name in SKELETONS:
            if name == skeleton:
                add(kfs(item))
        elif name == 'animations':
            folder = params.child(item, skeleton)
            add(kfs(folder) if folder else [])
        elif name == 'meshes':
            base = params.child(item, skeleton + '.kf') or base
        else:
            meshes = params.child(item, 'meshes')
            base = (params.child(meshes, skeleton + '.kf') if meshes else None) or base
            animations = params.child(item, 'animations')
            folder = params.child(animations, skeleton) if animations else None
            add(kfs(folder) if folder else [])
            if skeleton == 'xbase_anim' and not meshes and not animations:
                add(kfs(item))
    return base, extra


def load_files(paths):
    out = []
    for path in paths:
        try:
            out.append(Source(path, nifkf.KF.load(path)))
        except Exception as e:  # noqa: BLE001 - a broken file is skipped, not fatal
            print('  cannot read %s (%s), skipped' % (path, e))
    return out


def where(path, parts=3):
    """The last few parts of a path, for saying where something came from."""
    return os.path.join(*os.path.normpath(path).split(os.sep)[-parts:])


def source_name(source):
    return source.label if source.label.startswith('vanilla') else where(source.label, 4)


# ---- maths ---------------------------------------------------------------------------------------

def mean_rotation(rotations):
    rotations = [q for q in rotations if q is not None]
    if not rotations:
        return None
    total, first = [0.0, 0.0, 0.0, 0.0], rotations[0]
    for q in rotations:
        if sum(a * b for a, b in zip(q, first)) < 0:
            q = tuple(-c for c in q)
        total = [a + b for a, b in zip(total, q)]
    return E.qnorm(total)


def span(start, stop, step=1.0 / FPS):
    n = int(math.ceil((stop - start) / step - 1e-6))
    return [start + min(i * step, stop - start) for i in range(n + 1)]


def lerp(a, b, f):
    return tuple(x + (y - x) * f for x, y in zip(a, b))


def thin(keys, interpolate, close):
    """Linear keys without those their neighbours already give."""
    if len(keys) <= 2:
        return keys
    kept = [keys[0]]
    anchor = 0
    still = True  # every key since the anchor has the anchor's value exactly: a bone held still
    for i in range(1, len(keys) - 1):
        a, b = keys[anchor], keys[i + 1]
        width = b[0] - a[0]
        still = still and keys[i][1] == a[1]
        if still and b[1] == a[1] and width > 0:
            # Held still to here and beyond: the line between two equal keys gives each one exactly.
            # Checked one by one this is quadratic in the length of the hold - minutes, on a set's
            # finger bones.
            continue
        # A key at least every THIN_RUN: checked back to the last one kept, a long run costs its length
        # squared, which a long idle's full-rate samples made minutes.
        fits = width > 0 and i - anchor < THIN_RUN and all(
            close(interpolate(a[1], b[1], (keys[j][0] - a[0]) / width), keys[j][1]) for j in range(anchor + 1, i + 1))
        if not fits:
            kept.append(keys[i])
            anchor = i
            still = True
    kept.append(keys[-1])
    return kept


def clamped(xs, ys):
    """piecewise(xs, ys), held at its ends rather than carried on past them."""
    f = piecewise(xs, ys)
    return lambda x: f(min(max(x, xs[0]), xs[-1]))


def piecewise(xs, ys):
    """x -> y, linear between the points given (x increasing)."""
    def f(x):
        for (x0, x1), (y0, y1) in zip(zip(xs, xs[1:]), zip(ys, ys[1:])):
            if x <= x1 + 1e-9:
                return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return ys[-1]
    return f


def rest_translations(kf):
    out = {}
    for bone in kf.bone_data:
        keys = kf.data(bone).trans['keys']
        if keys:
            out[bone] = keys[0][1]
    return out


def rest_of(kfs, fallback=None):
    """Each bone's offset as a set of animations holds it - the first of them to key the bone - and the
    fallback's for any none of them key. What the arms' offsets are moved from and to: the skeleton
    the animations were made on, which need not be vanilla's."""
    out = {}
    for kf in kfs:
        for bone, t in rest_translations(kf).items():
            out.setdefault(bone, t)
    if fallback is not None:
        for bone, t in rest_translations(fallback).items():
            out.setdefault(bone, t)
    return out


REFERENCE_BONES = ('Bip01', 'Bip01 Pelvis', 'Bip01 Spine', 'Bip01 Spine1', 'Bip01 Spine2', 'Bip01 Neck',
                   'Bip01 L Thigh', 'Bip01 R Thigh', 'Bip01 L Calf', 'Bip01 R Calf', 'Bip01 L Foot', 'Bip01 R Foot')


def add_torso(kf, reference):
    """Gives a first-person kf that keys only an arm or two (a layer over another animation - a
    shield arm, a torch) the torso its arms hang from, held in the reference's pose: fba_merge's
    add_rest_bones fills in the root and legs only."""
    times = [tm for tm, _ in kf.text_keys()]
    first, last = min(times), max(times)
    for bone in TO_NECK:
        have = kf.data(bone) if bone in kf.bone_data else None
        if have is not None and (have.quat_keys or have.xyz) and have.trans['keys']:
            continue
        if bone not in reference.bone_data:
            continue
        ref = reference.data(bone)
        at = ref.xyz[0]['keys'][0][0] if ref.rot_type == 4 else ref.quat_keys[0][0]
        rot, trans = E.rotation(ref, at), tuple(E.translation(ref, at))
        d = have if have is not None else kf.add_bone(bone)
        d.rot_type, d.xyz = 1, None
        d.quat_keys = [(first, rot, ()), (last, rot, ())]
        d.trans = {'itype': 1, 'keys': [(first, trans, ()), (last, trans, ())]}


def keys_whole_body(kf):
    return all(b in kf.bone_data and kf.data(b).trans['keys'] and (kf.data(b).quat_keys or kf.data(b).xyz)
               for b in REFERENCE_BONES)


# ---- the stance idle's posture -------------------------------------------------------------------

class Posture:
    """A stance idle's torso as it holds it on average - the chest in the character's frame, the
    rest on it - turned square to where the character faces, and its arms, in the third person.

    Third-person stances often stand side-on (vanilla's spell idle turns the shoulders 11 degrees, a
    beast's 37, hand-to-hand 43): forward is with the shoulders square, as a first-person animation
    holds them for the camera."""

    def __init__(self, source, group, lateral):
        kf, keys = source.kf, source.groups[group]
        times = span(min(keys.values()), max(keys.values()))
        self.chest = mean_rotation([E.world(kf, CHEST, t)[0] for t in times])
        self.chest_local = mean_rotation([E.rotation(kf.data(CHEST), t) for t in times])
        self.torso = {b: mean_rotation([E.rotation(kf.data(b), t) for t in times]) for b in TORSO}
        self.arms = {b: mean_rotation([E.rotation(kf.data(b), t) for t in times])
                     for b in kf.bone_data if is_arm(b) and (kf.data(b).quat_keys or kf.data(b).xyz)}
        yaws = [shoulder_yaw(kf, t, lateral) for t in times]
        self.yaw = sum(yaws) / len(yaws)
        self.square = E.axis_quat(-self.yaw, (0.0, 0.0, 1.0))
        self.forward = E.qmul(self.square, self.chest)
        self.neck = E.qmul(E.qmul(self.forward, self.torso['Bip01 Spine2']), self.torso[NECK])
        self.label = '%s (%s)' % (group, source_name(source))


def shoulder_yaw(kf, t, lateral):
    """How far the shoulders are turned about the vertical from square (radians): the neck's own
    left-to-right - the line between the clavicles as the skeleton rests - against the character's
    right (+X; forward is +Y, up +Z). From the rest offsets, not the animated ones: some skeletons'
    animations move the clavicles about (a beast's), where the arms here hang from the rest."""
    side = E.qrot(E.world(kf, NECK, t)[0], lateral)
    return math.atan2(side[1], side[0])


def lateral_axis(rest):
    """The neck's left-to-right, in its own frame: from the left clavicle's rest offset to the right's."""
    left, right = rest['Bip01 L Clavicle'], rest['Bip01 R Clavicle']
    d = [b - a for a, b in zip(left, right)]
    n = math.sqrt(sum(x * x for x in d))
    return tuple(x / n for x in d)


def first_person_idle(kf, group, keys):
    """A first-person idle's arms as it holds them on average, and its neck in the character's
    frame: what 'as the first person holds them' is measured against."""
    times = span(min(keys.values()), max(keys.values()))
    arms = [b for b in kf.bone_data if is_arm(b)]
    return {
        'rot': {b: mean_rotation([E.rotation(kf.data(b), t) for t in times]) for b in arms
                if kf.data(b).quat_keys or kf.data(b).xyz},
        'trans': {b: E.translation(kf.data(b), times[0]) for b in arms},
        'neck': mean_rotation([E.world(kf, NECK, t)[0] for t in times]),
        'head': mean_rotation([E.world(kf, HEAD, t)[0] for t in times]) if HEAD in kf.bone_data else None,
    }


# ---- building -------------------------------------------------------------------------------------

class Segment:
    """One group's stretch of an output file.

    source: the third-person Source it takes its body and text keys from, over v_start..v_stop, with
    its loop (loop_start..loop_stop) repeated `loops` times. first_time(tau): when in the first-person
    animation its arms come from; without one, the first person's idle arms as they are on average
    (idle_arms), moved as the third person's arms move from its idle with arm_swing.
    keep: the keep-forward share, toward `posture`; natural_chest 'own', or 'idle' for a walk the game
    shows with the idle's upper body on top. repoint: the share of the arms' first-person direction
    kept. lower_by, bounce, grip: see lower_raised_arms, bounce_arms."""

    def __init__(self, source, group, v_start, v_stop, loop_start=None, loop_stop=None, loops=1):
        self.source, self.group = source, group
        self.v_start, self.v_stop = v_start, v_stop
        self.loop_start = v_start if loop_start is None else loop_start
        self.loop_stop = v_stop if loop_stop is None else loop_stop
        self.loops = loops
        self.lead = self.loop_start - v_start
        self.period = self.loop_stop - self.loop_start
        self.tail = v_stop - self.loop_stop
        self.length = self.lead + loops * self.period + self.tail
        self.first_time = None
        self.first_neck = None
        self.idle_arms = None
        self.arm_swing = False
        self.keep = 0.0
        self.posture = None
        self.natural_chest = 'own'
        self.shoulders = IDENTITY
        self.repoint = 0.0
        self.lower_by = 0.0
        self.bounce = 0.0
        self.grip = False       # a two-handed hold: only the right arm bounces, the left hand kept on it
        self.follow = False     # the upper body is the first person's, not the third person's held forward
        self.sway_about = None  # following on a walk: the third person's spine, on average, whose sway goes on top
        self.head_forward = None  # following: the head held looking this way (the stance idle's), not turning
        self.warp_pieces = None  # at the first person's timing: [[(output time, third-person time)]] - see warp_pieces
        self.first_points = None
        self.name = group       # the group it is written as
        self.clock = None       # tau -> third-person time, for a segment on a held idle or pose
        self.sample_all = False  # nothing copied as it is: the body is sampled like the rest
        self.offset = 0.0

    def times(self, extra=()):
        """Sample times over the segment: even steps of about 1/FPS in the lead-in, each repeat of the
        loop and the tail - so the loop's ends are samples, and a loop closes on itself - and `extra`."""
        def grid(a, b):
            n = max(1, int(round((b - a) * FPS)))
            return [a + (b - a) * i / n for i in range(n + 1)]
        ts = set()
        if self.period > 0:
            if self.lead > 1e-6:
                ts.update(grid(0.0, self.lead))
            for r in range(self.loops):
                ts.update(grid(self.lead + r * self.period, self.lead + (r + 1) * self.period))
            if self.tail > 1e-6:
                ts.update(grid(self.length - self.tail, self.length))
        else:
            ts.update(grid(0.0, self.length))
        ts.update(t for t in extra if 0.0 <= t <= self.length)
        return sorted({round(t, 6) for t in ts if t <= self.length + 1e-6})

    def third_time(self, tau):
        if self.clock is not None:
            return self.clock(tau)
        if tau < self.lead:
            return self.v_start + tau
        looped = tau - self.lead
        if looped < self.loops * self.period - 1e-6:
            return self.loop_start + math.fmod(looped, self.period) if self.period > 0 else self.loop_start
        return self.loop_stop + (looped - self.loops * self.period)

    def out_time(self, t, repeat=0):
        """Where third-person time t lands in the output, in the given repeat of the loop."""
        if t < self.loop_start - 1e-6 or self.period <= 0:
            return t - self.v_start
        if t > self.loop_stop + 1e-6:
            return self.lead + self.loops * self.period + (t - self.loop_stop)
        return self.lead + repeat * self.period + (t - self.loop_start)


def neck_rotation(body_pose):
    rot = IDENTITY
    for bone in TO_NECK:
        r = body_pose.get(bone, (None, None))[0]
        if r is not None:
            rot = E.qmul(rot, r)
    return rot


def chain(body_pose, arm_pose, side, drift=(0.0, 0.0, 0.0)):
    """World (rotation, position) of the shoulder, elbow and wrist - the heads of the upper arm,
    forearm and hand - and each bone's own world rotation, root drift taken out."""
    rot, pos = IDENTITY, (0.0, 0.0, 0.0)
    for bone in TO_NECK:
        r, t = body_pose.get(bone, (None, None))
        if t is not None:
            if bone == 'Bip01':
                t = tuple(a - b for a, b in zip(t, drift))
            pos = tuple(p + c for p, c in zip(pos, E.qrot(rot, t)))
        if r is not None:
            rot = E.qmul(rot, r)
    out = {}
    for part in ARM_CHAIN:
        r, t = arm_pose['Bip01 %s %s' % (side, part)]
        pos = tuple(p + c for p, c in zip(pos, E.qrot(rot, t)))
        out[part] = (rot, pos)  # the parent's rotation, and this bone's head
        rot = E.qmul(rot, r)
        out[part + ' own'] = rot
    return out


def rotation_between(a, b):
    """The shortest rotation taking direction a to direction b."""
    la, lb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if la < 1e-9 or lb < 1e-9:
        return IDENTITY
    a, b = [x / la for x in a], [x / lb for x in b]
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    dot = sum(x * y for x, y in zip(a, b))
    if dot < -0.999999:
        return IDENTITY  # opposite: not a lag a spring makes
    return E.qnorm((1.0 + dot,) + cross)


def lower_raised_arms(samples, degrees):
    """Lowers each arm at the shoulder: by `degrees` where its hand is highest, not at all where it is
    no higher than at either end, pivoting down in the character's own frame (up +Z, forward +Y), the
    hand keeping the way it faces."""
    for side in ('L', 'R'):
        names = ['Bip01 %s %s' % (side, part) for part in ARM_CHAIN]
        if any(samples[0][1].get(b, (None, None))[0] is None or samples[0][1][b][1] is None for b in names):
            continue
        heights = []
        for body_pose, arm_pose in samples:
            rot, pos = neck_rotation(body_pose), (0.0, 0.0, 0.0)
            for bone in names:
                r, t = arm_pose[bone]
                pos = tuple(p + c for p, c in zip(pos, E.qrot(rot, t)))
                rot = E.qmul(rot, r)
            heights.append(pos[2])
        rest, top = max(heights[0], heights[-1]), max(heights)
        if top - rest < 1e-3:
            continue
        for (body_pose, arm_pose), height in zip(samples, heights):
            f = min(1.0, max(0.0, (height - rest) / (top - rest)))
            weight = f * f * (3 - 2 * f)
            if weight <= 0:
                continue
            clavicle = E.qmul(neck_rotation(body_pose), arm_pose[names[0]][0])
            upper = E.qmul(clavicle, arm_pose[names[1]][0])
            hand = E.qmul(E.qmul(upper, arm_pose[names[2]][0]), arm_pose[names[3]][0])
            lowered = E.qmul(E.axis_quat(math.radians(-degrees * weight), (1.0, 0.0, 0.0)), upper)
            arm_pose[names[1]] = (E.qmul(E.qconj(clavicle), lowered), arm_pose[names[1]][1])
            forearm = E.qmul(lowered, arm_pose[names[2]][0])
            arm_pose[names[3]] = (E.qmul(E.qconj(forearm), hand), arm_pose[names[3]][1])


def bounce_arms(seg, taus, samples, strength):
    """Experimental. The elbows and wrists lag and spring back as the body under them moves: a point
    on a spring and damper at each, following where the animation puts it - the way Blender's
    Wiggle 2 add-on moves bones - run over the loop until it settles into a cycle of its own. That
    cycle is kept, so it loops; the lead-in and tail fade it in and out. `strength` is the share of
    it used. On a two-handed grip (seg.grip) only the right arm, which holds the weapon, springs; the
    left then reaches after it so the left hand stays where it was on the weapon (keep_grip)."""
    if seg.period <= 0 or seg.loops != 1:
        return
    inside = [i for i, tau in enumerate(taus) if seg.lead - 1e-6 <= tau <= seg.lead + seg.period + 1e-6]
    if len(inside) < 4:
        return
    cycle = inside[:-1]  # the loop's last sample is its first again
    first_root = samples[inside[0]][0].get('Bip01', (None, None))[1] or (0.0, 0.0, 0.0)
    last_root = samples[inside[-1]][0].get('Bip01', (None, None))[1] or (0.0, 0.0, 0.0)
    span_time = taus[inside[-1]] - taus[inside[0]]

    def drift(i):
        f = (taus[i] - taus[inside[0]]) / span_time if span_time > 0 else 0.0
        return tuple((b - a) * f for a, b in zip(first_root, last_root))

    stiffness = (2 * math.pi * BOUNCE_HZ) ** 2
    damping = 2 * BOUNCE_DAMPING * 2 * math.pi * BOUNCE_HZ
    step = 1.0 / (FPS * BOUNCE_SUBSTEPS)
    grip = grip_holds(samples) if seg.grip else None
    moved = set()
    for side in (('R',) if grip is not None else ('L', 'R')):
        names = ['Bip01 %s %s' % (side, part) for part in ARM_CHAIN]
        if any(samples[0][1].get(b, (None, None))[0] is None or samples[0][1][b][1] is None for b in names):
            continue
        goals = []
        for i in cycle:
            c = chain(samples[i][0], samples[i][1], side, drift(i))
            goals.append((c['UpperArm'][1], c['Forearm'][1], c['Hand'][1]))
        upper_len = math.dist(goals[0][0], goals[0][1])
        fore_len = math.dist(goals[0][1], goals[0][2])
        elbow, wrist = list(goals[0][1]), list(goals[0][2])
        elbow_prev, wrist_prev = elbow[:], wrist[:]
        kept = {}
        for lap in range(BOUNCE_LAPS):
            for j in range(len(cycle)):
                a, b = goals[j], goals[(j + 1) % len(cycle)]
                for sub in range(BOUNCE_SUBSTEPS):
                    f = sub / BOUNCE_SUBSTEPS
                    shoulder, g_elbow, g_wrist = [lerp(p, q, f) for p, q in zip(a, b)]
                    for point, prev, goal, anchor, length in (
                            (elbow, elbow_prev, g_elbow, shoulder, upper_len),
                            (wrist, wrist_prev, None, None, fore_len)):
                        if goal is None:  # the wrist follows the forearm hung from the moving elbow
                            goal = tuple(e + (w - ge) for e, w, ge in zip(elbow, g_wrist, g_elbow))
                            anchor = elbow
                        velocity = [(p - q) * (1.0 - damping * step) for p, q in zip(point, prev)]
                        new = [p + v + stiffness * (g - p) * step * step for p, v, g in zip(point, velocity, goal)]
                        d = [n - s for n, s in zip(new, anchor)]
                        norm = math.sqrt(sum(x * x for x in d)) or 1.0
                        new = [s + x * length / norm for s, x in zip(anchor, d)]
                        prev[:] = point
                        point[:] = new
                if lap == BOUNCE_LAPS - 1:
                    kept[cycle[(j + 1) % len(cycle)]] = (tuple(elbow), tuple(wrist))
        kept[inside[-1]] = kept[cycle[0]]
        loop_start_value = kept[cycle[0]]
        for i, tau in enumerate(taus):
            if i in kept:
                weight, sim = strength, kept[i]
            elif tau < seg.lead:  # the lead-in and tail fade it in and out
                weight, sim = strength * (tau / seg.lead if seg.lead > 0 else 1.0), loop_start_value
            else:
                rest = seg.length - (seg.lead + seg.loops * seg.period)
                weight = strength * ((seg.length - tau) / rest if rest > 0 else 0.0)
                sim = loop_start_value
            if weight <= 0:
                continue
            body_pose, arm_pose = samples[i]
            c = chain(body_pose, arm_pose, side, drift(i) if i in kept else (0.0, 0.0, 0.0))
            shoulder, elbow_now, wrist_now = c['UpperArm'][1], c['Forearm'][1], c['Hand'][1]
            if i not in kept:
                # Outside the loop the drift-free frame differs; the lag is carried as offsets.
                j0 = cycle[0]
                c0 = chain(samples[j0][0], samples[j0][1], side, drift(j0))
                sim = (tuple(e + (s - g) for e, s, g in zip(elbow_now, sim[0], c0['Forearm'][1])),
                       tuple(w + (s - g) for w, s, g in zip(wrist_now, sim[1], c0['Hand'][1])))
            turn_upper = E.qslerp(IDENTITY, rotation_between(
                [a - b for a, b in zip(elbow_now, shoulder)], [a - b for a, b in zip(sim[0], shoulder)]), weight)
            upper = E.qmul(turn_upper, c['UpperArm own'])
            forearm = E.qmul(turn_upper, c['Forearm own'])
            moved_wrist_dir = E.qrot(turn_upper, [a - b for a, b in zip(wrist_now, elbow_now)])
            turn_fore = E.qslerp(IDENTITY, rotation_between(moved_wrist_dir, [a - b for a, b in zip(sim[1], sim[0])]), weight)
            forearm = E.qmul(turn_fore, forearm)
            clavicle = c['Clavicle own']
            arm_pose[names[1]] = (E.qmul(E.qconj(clavicle), upper), arm_pose[names[1]][1])
            arm_pose[names[2]] = (E.qmul(E.qconj(upper), forearm), arm_pose[names[2]][1])
            moved.add(i)
    if grip is not None:
        keep_grip(samples, grip, moved)


def grip_holds(samples):
    """Where the left hand is on the right, sample by sample - its position and rotation in the
    right hand's frame - or None where an arm is not keyed."""
    names = ['Bip01 %s %s' % (side, part) for side in ('L', 'R') for part in ARM_CHAIN]
    if any(samples[0][1].get(b, (None, None))[0] is None or samples[0][1][b][1] is None for b in names):
        return None
    holds = []
    for body_pose, arm_pose in samples:
        left, right = chain(body_pose, arm_pose, 'L'), chain(body_pose, arm_pose, 'R')
        r_rot, r_pos = right['Hand own'], right['Hand'][1]
        holds.append((E.qrot(E.qconj(r_rot), [a - b for a, b in zip(left['Hand'][1], r_pos)]),
                      E.qmul(E.qconj(r_rot), left['Hand own'])))
    return holds


def keep_grip(samples, holds, moved):
    """Puts the left hand back where it holds the weapon, on the right hand as it now is: a two-bone
    reach of the upper arm and forearm, the elbow bending the way it did, then the hand turned as it
    held. Samples in `moved` only - the rest were never parted."""
    names = ['Bip01 L %s' % part for part in ARM_CHAIN]
    for i in sorted(moved):
        body_pose, arm_pose = samples[i]
        right, left = chain(body_pose, arm_pose, 'R'), chain(body_pose, arm_pose, 'L')
        at, turn = holds[i]
        target = tuple(p + c for p, c in zip(right['Hand'][1], E.qrot(right['Hand own'], at)))
        hand = E.qmul(right['Hand own'], turn)
        shoulder, elbow, wrist = left['UpperArm'][1], left['Forearm'][1], left['Hand'][1]
        upper_len, fore_len = math.dist(shoulder, elbow), math.dist(elbow, wrist)
        to_target = [a - b for a, b in zip(target, shoulder)]
        reach = math.sqrt(sum(x * x for x in to_target))
        if reach < 1e-6:
            continue
        axis = [x / reach for x in to_target]
        reach = min(max(reach, abs(upper_len - fore_len) + 1e-4), upper_len + fore_len - 1e-4)
        # The elbow on the side it was, in the plane through the shoulder and the target.
        bend = [a - b for a, b in zip(elbow, shoulder)]
        along = sum(x * y for x, y in zip(bend, axis))
        pole = [x - along * y for x, y in zip(bend, axis)]
        norm = math.sqrt(sum(x * x for x in pole))
        if norm < 1e-6:
            continue
        pole = [x / norm for x in pole]
        cos_a = (upper_len ** 2 + reach ** 2 - fore_len ** 2) / (2 * upper_len * reach)
        sin_a = math.sqrt(max(0.0, 1.0 - cos_a * cos_a))
        new_elbow = [s + upper_len * (cos_a * x + sin_a * y) for s, x, y in zip(shoulder, axis, pole)]
        new_wrist = [s + reach * x for s, x in zip(shoulder, axis)]
        turn_upper = rotation_between(bend, [a - b for a, b in zip(new_elbow, shoulder)])
        upper = E.qmul(turn_upper, left['UpperArm own'])
        forearm = E.qmul(turn_upper, left['Forearm own'])
        swung = E.qrot(turn_upper, [a - b for a, b in zip(wrist, elbow)])
        forearm = E.qmul(rotation_between(swung, [a - b for a, b in zip(new_wrist, new_elbow)]), forearm)
        arm_pose[names[1]] = (E.qmul(E.qconj(left['Clavicle own']), upper), arm_pose[names[1]][1])
        arm_pose[names[2]] = (E.qmul(E.qconj(upper), forearm), arm_pose[names[2]][1])
        arm_pose[names[3]] = (E.qmul(E.qconj(forearm), hand), arm_pose[names[3]][1])


# Sections of a group: the engine plays one at a time, from its start key to its stop key, never across.
SECTION_WORDS = ('chop', 'slash', 'thrust', 'shoot', 'equip', 'unequip', 'block', 'self', 'touch', 'target')


def warp_pieces(fkeys, tkeys):
    """How a group at the first person's timing takes its body from the third person's:
    [[(output time, third-person time), ...], ...], each piece's points increasing in both, the third
    person's time jumping between pieces. None if nothing maps.

    A looping group (an idle, a jump's hang in the air) maps loop onto loop: the third person's loop
    repeated as many times as fits the first person's best and fitted to it exactly, the lead-in and
    the tail - a jump's take-off and landing - onto theirs. Anything else maps through the keys both
    have, section by section (a chop, an equip): each is played on its own, and the first person's
    equip can end where its unequip starts while the third person's are a whole attack set apart."""
    f0, f1 = min(fkeys.values()), max(fkeys.values())
    if ('loop start' in fkeys or 'loop stop' in fkeys) and 'start' in tkeys and 'stop' in tkeys:
        t0, t1 = tkeys['start'], tkeys['stop']
        ls, le = tkeys.get('loop start', t0), tkeys.get('loop stop', t1)
        fl0, fl1 = fkeys.get('loop start', f0), fkeys.get('loop stop', f1)
        pieces = []
        if fl0 > f0 + 1e-6:
            pieces.append([(0.0, t0), (fl0 - f0, ls)])
        span_ = fl1 - fl0
        if span_ > 1e-6:
            n = max(1, int(round(span_ / (le - ls)))) if le - ls > 1e-6 else 1
            pieces += [[(fl0 - f0 + i * span_ / n, ls), (fl0 - f0 + (i + 1) * span_ / n, le)] for i in range(n)]
        else:
            pieces.append([(fl0 - f0, ls)])
        if f1 > fl1 + 1e-6:
            pieces.append([(fl1 - f0, le), (f1 - f0, t1)])
        return pieces
    # Every strength of a follow-through over the large one's, where the first person keys them over one
    # range (ReAnimation does) and the third person one after another.
    large = {k.split()[0] for k in fkeys if 'follow' in k.split() and 'large' in k.split()}
    pieces, section = [], None
    # A section's stop before the next one's start, where the two share a time.
    for k in sorted(fkeys, key=lambda k: (fkeys[k], 'stop' not in k)):
        words = k.split()
        if k not in tkeys or ('follow' in words and ('small' in words or 'medium' in words) and words[0] in large):
            continue
        here = words[0] if words[0] in SECTION_WORDS else ''
        point = (fkeys[k] - f0, tkeys[k])
        if not pieces or here != section:
            pieces.append([point])
            section = here
        elif point[0] > pieces[-1][-1][0] + 1e-6 and point[1] > pieces[-1][-1][1] + 1e-6:
            pieces[-1].append(point)
    return pieces if any(len(piece) > 1 for piece in pieces) else None


def pieces_clock(pieces):
    """Output time -> third-person time over warp pieces: through the piece it falls in, held at the
    end of the last one before it, or at the start of the first."""
    maps = [(piece[0][0], piece[-1][0], clamped([o for o, _ in piece], [t for _, t in piece]) if len(piece) > 1
             else (lambda t: lambda tau: t)(piece[0][1])) for piece in pieces]

    def clock(tau):
        before = pieces[0][0][1]
        for (start, end, f), piece in zip(maps, pieces):
            if tau < start - 1e-9:
                return before
            if tau <= end + 1e-9:
                return f(tau)
            before = piece[-1][1]
        return before
    return clock


def copy_warped_track(seg, src, dst):
    """A third-person bone's own keys over a segment at the first person's timing: each one where the
    warp puts it, a piece sped up or slowed down as a whole; held between pieces and outside them, and
    jumping to the next piece's first pose where it starts."""
    for keys, evaluate, out in ((src.quat_keys, E.rotation, dst.quat_keys),
                                (src.trans['keys'], E.translation, dst.trans['keys'])):
        if not keys:
            continue
        last = None  # (output time, value) of the last piece's end
        for piece in seg.warp_pieces:
            o_first, t_first = piece[0]
            if last is None and o_first > 1e-6:
                out.append((seg.offset, tuple(evaluate(src, t_first)), ()))
            elif last is not None and o_first > last[0] + 1e-6:
                out.append((seg.offset + o_first, last[1], ()))
            for i, ((o0, t0), (o1, t1)) in enumerate(zip(piece, piece[1:])):
                if t1 - t0 < 1e-6:  # the third person holding a frame
                    for o in ((o0, o1) if i == 0 else (o1,)):
                        out.append((seg.offset + o, tuple(evaluate(src, t0)), ()))
                    continue
                inside = [(t, v) for t, v, _ in keys if (t0 - KEY_TIME_EPS if i == 0 else t0 + KEY_TIME_EPS) <= t
                          <= t1 + KEY_TIME_EPS]
                ends = [(t, evaluate(src, t)) for t in ((t0, t1) if i == 0 else (t1,))
                        if not any(abs(k - t) < KEY_TIME_EPS for k, _ in inside)]
                for t, v in sorted(ends + inside, key=lambda kv: kv[0]):
                    o = o0 + (min(max(t, t0), t1) - t0) * (o1 - o0) / (t1 - t0)
                    out.append((seg.offset + o, tuple(v), ()))
            if len(piece) == 1:
                out.append((seg.offset + o_first, tuple(evaluate(src, t_first)), ()))
            last = (piece[-1][0], tuple(evaluate(src, piece[-1][1])))
        if last[0] < seg.length - 1e-6:
            out.append((seg.offset + seg.length, last[1], ()))


_key_times = {}


def key_times_of(kf, bone):
    """A bone's rotation key times, sorted; kept, since a set's whole-file kf is asked again and again."""
    at = (id(kf), bone)
    if at not in _key_times:
        _key_times[at] = sorted(t for t, _, _ in kf.data(bone).quat_keys)
    return _key_times[at]


def copy_track(seg, src, dst):
    """A third-person bone's own keys over a segment, as they are - repeated with the loop, and with
    keys sharing a time kept in their order, as some animations have them (Animation Compilation's:
    four to a frame) and the engine plays them. Resampling would smooth them into something else."""
    if seg.period > 0:
        pieces = ([(seg.v_start, seg.loop_start, 0)] if seg.lead > 1e-6 else []) + \
                 [(seg.loop_start, seg.loop_stop, r) for r in range(seg.loops)] + \
                 ([(seg.loop_stop, seg.v_stop, seg.loops - 1)] if seg.tail > 1e-6 else [])
    else:
        pieces = [(seg.v_start, seg.v_stop, 0)]
    for keys, evaluate, out in ((src.quat_keys, E.rotation, dst.quat_keys),
                                (src.trans['keys'], E.translation, dst.trans['keys'])):
        if not keys:
            continue
        for a, b, repeat in pieces:
            # Key times are 32-bit floats: far into a file they sit a little off the text keys'.
            inside = [(t, v) for t, v, _ in keys if a - KEY_TIME_EPS <= t <= b + KEY_TIME_EPS]
            ends = [(t, evaluate(src, t)) for t in (a, b) if not any(abs(k - t) < KEY_TIME_EPS for k, _ in inside)]
            for t, v in sorted(ends + inside, key=lambda kv: kv[0]):
                out.append((seg.offset + seg.out_time(t, repeat), tuple(v), ()))


def build(ctx, template_path, first_kf, segments, text, out_path):
    """Writes one kf: `segments` laid end to end, `text` [(output time, line)] its text keys."""
    out = nifkf.KF.load(template_path)
    arms = [b for b in first_kf.bone_data if is_arm(b)]
    body_all = []
    for seg in segments:
        body_all += [b for b in seg.source.kf.bone_data if not is_arm(b) and b not in body_all]
    for bone in body_all + arms:
        if bone not in out.bone_data:
            out.add_bone(bone)
    data = {b: nifkf.KeyframeData() for b in out.bone_data}
    for d in data.values():
        d.rot_type = 1
        d.trans = {'itype': 1, 'keys': []}
        d.scale = {'itype': 1, 'keys': []}

    for seg in segments:
        kf = seg.source.kf
        body = [b for b in kf.bone_data if not is_arm(b)]
        # What is not changed here - legs, hips, spine, root motion - keeps its own keys; what is -
        # the chest up - is sampled.
        copied = set()
        for bone in body:
            d = kf.data(bone)
            if not seg.sample_all and bone != CHEST and bone not in TORSO and d.rot_type in (0, 1) \
                    and d.trans['itype'] in (0, 1):
                (copy_warped_track if seg.warp_pieces else copy_track)(seg, d, data[bone])
                copied.add(bone)
        extra = [o for piece in seg.warp_pieces for o, _ in piece] if seg.warp_pieces else []
        if seg.first_points and not seg.bounce:
            # The first person's own keys, where it turns sharply between two even steps - its chest and
            # spine's too, where the upper body is its.
            xs, ys = seg.first_points
            back = piecewise(ys, xs)
            for bone in arms + ([CHEST] + list(TORSO) if seg.follow else []):
                if bone not in first_kf.bone_data:
                    continue
                d = first_kf.data(bone)
                for t, _, _ in d.quat_keys + d.trans['keys']:
                    if ys[0] <= t <= ys[-1]:
                        extra.append(back(t))
        if seg.follow and seg.warp_pieces:
            # And the third person's hips and spine's, which the chest is turned on.
            for piece in seg.warp_pieces:
                (o0, t0), (o1, t1) = piece[0], piece[-1]
                if len(piece) < 2 or t1 <= t0:
                    continue
                forward = clamped([b for _, b in piece], [a for a, _ in piece])
                for bone in ('Bip01', 'Bip01 Pelvis', SPINE):
                    if bone in kf.bone_data:
                        times = key_times_of(kf, bone)
                        extra += [forward(t) for t in times[bisect.bisect_left(times, t0):bisect.bisect_right(times, t1)]]
        taus = seg.times(extra)
        t3 = [seg.third_time(tau) for tau in taus]
        t1 = [seg.first_time(tau) for tau in taus] if seg.first_time else None
        post = seg.posture
        # The chest in the character's frame. An idle keeps its own motion, turned the keep-forward
        # share of the way to square; anything else goes that share of the way to the stance idle's
        # posture, square.
        own_upper = seg.follow and t1 is not None  # the first person's upper body
        chests = None
        if post is not None and seg.keep > 0 and not own_upper:
            if seg.natural_chest == 'idle':
                natural = [E.qmul(E.world(kf, SPINE, t)[0], post.chest_local) for t in t3]
            else:
                natural = [E.world(kf, CHEST, t)[0] for t in t3]
            if is_idle(seg.group):
                turn = E.qslerp(IDENTITY, post.square, seg.keep)
                chests = [E.qmul(turn, n) for n in natural]
            else:
                chests = [E.qslerp(n, post.forward, seg.keep) for n in natural]
        samples = []
        for i, t in enumerate(t3):
            body_pose = {}
            for bone in body:
                src = kf.data(bone)
                rot, trans = E.rotation(src, t), E.translation(src, t)
                if own_upper and (bone == CHEST or bone in TORSO):
                    if bone == CHEST:
                        # The chest turned the way the first person has it, in the character's frame,
                        # on the third person's spine - and on a walk, swaying as that spine sways.
                        spine = E.world(kf, SPINE, t)[0]
                        target = E.world(first_kf, CHEST, t1[i])[0]
                        if seg.sway_about is not None:
                            target = E.qmul(E.qmul(spine, E.qconj(seg.sway_about)), target)
                        rot = E.qmul(E.qconj(spine), target)
                    elif bone in first_kf.bone_data and (first_kf.data(bone).quat_keys or first_kf.data(bone).xyz):
                        rot = E.rotation(first_kf.data(bone), t1[i])
                elif post is not None and (bone == CHEST or bone in TORSO):
                    if seg.natural_chest == 'idle':
                        # What the game shows on such a walk: the idle's upper body on its spine.
                        rot = post.chest_local if bone == CHEST else post.torso.get(bone, rot)
                    if chests is not None and bone == CHEST:
                        rot = E.qmul(E.qconj(E.world(kf, SPINE, t)[0]), chests[i])
                    elif chests is not None and rot is not None and post.torso.get(bone) is not None \
                            and not is_idle(seg.group):
                        rot = E.qslerp(rot, post.torso[bone], seg.keep)
                body_pose[bone] = (rot, trans)
            if own_upper and seg.head_forward is not None and HEAD in body_pose:
                # Looking ahead, as in the stance idle: a first-person head turns with every swing,
                # which its camera never shows.
                body_pose[HEAD] = (E.qmul(E.qconj(neck_rotation(body_pose)), seg.head_forward), body_pose[HEAD][1])
            neck = neck_rotation(body_pose)
            first_neck = E.world(first_kf, NECK, t1[i])[0] if t1 is not None else seg.idle_arms['neck']
            arm_pose = {}
            for bone in arms:
                src = first_kf.data(bone)
                if t1 is not None:
                    rot, trans = E.rotation(src, t1[i]), E.translation(src, t1[i])
                else:
                    rot, trans = seg.idle_arms['rot'].get(bone), seg.idle_arms['trans'].get(bone)
                    if seg.arm_swing and rot is not None and post is not None and bone in post.arms \
                            and bone in kf.bone_data:
                        # Moved as the third person's arms move from its idle.
                        swing = E.qmul(E.rotation(kf.data(bone), t), E.qconj(post.arms[bone]))
                        rot = E.qmul(swing, rot)
                if rot is not None and 'Clavicle' in bone:
                    # Following the torso: as the first person holds them against its chest, with the
                    # third-person torso in its forward posture. Pointed: as the first person points
                    # them in the character's frame, whatever the torso does.
                    follow = E.qmul(neck, E.qmul(seg.shoulders, rot))
                    pointed = E.qmul(first_neck, rot)
                    rot = E.qmul(E.qconj(neck), E.qslerp(follow, pointed, seg.repoint))
                if trans is not None:
                    shift = (0.0, 0.0, 0.0)
                    if bone in ctx['first_rest'] and bone in ctx['third_rest']:
                        shift = tuple(b - a for a, b in zip(ctx['first_rest'][bone], ctx['third_rest'][bone]))
                    trans = tuple(a + b for a, b in zip(trans, shift))
                arm_pose[bone] = (rot, trans)
            samples.append((body_pose, arm_pose))
        if seg.lower_by:
            lower_raised_arms(samples, seg.lower_by)
        if seg.bounce:
            bounce_arms(seg, taus, samples, seg.bounce)
        for tau, (body_pose, arm_pose) in zip(taus, samples):
            t_out = seg.offset + tau
            for bone, (rot, trans) in [kv for kv in body_pose.items() if kv[0] not in copied] + list(arm_pose.items()):
                if rot is not None:
                    data[bone].quat_keys.append((t_out, E.qnorm(rot), ()))
                if trans is not None:
                    data[bone].trans['keys'].append((t_out, tuple(trans), ()))

    for d in data.values():
        fixed = []
        for t, q, extra in d.quat_keys:
            if fixed and sum(a * b for a, b in zip(fixed[-1][1], q)) < 0:
                q = tuple(-c for c in q)
            fixed.append((t, q, extra))
        d.quat_keys = thin(fixed, lambda a, b, f: E.qslerp(a, b, f), lambda a, b: E.qangle(a, b) < ANGLE_TOLERANCE)
        d.trans['keys'] = thin(d.trans['keys'], lerp,
                               lambda a, b: max(abs(x - y) for x, y in zip(a, b)) < MOVE_TOLERANCE)
        if not d.quat_keys:
            d.rot_type = 0
        for channel in ('trans', 'scale'):
            if not d.__dict__[channel]['keys']:
                d.__dict__[channel] = {'itype': 0, 'keys': []}
    for bone, di in out.bone_data.items():
        out.blocks[di] = (out.blocks[di][0], data[bone])
    end = segments[-1].offset + segments[-1].length
    for t, p in out.blocks:
        if t == 'NiKeyframeController':
            p['start'] = 0.0
            p['stop'] = end
    by_time = {}
    for tm, line in text:
        lines = by_time.setdefault(round(tm, 5), [])
        if line not in lines:
            lines.append(line)
    tk = out.blocks[out.textkey_block][1]
    tk['keys'] = [(t, '\r\n'.join(lines)) for t, lines in sorted(by_time.items())]
    out.save(out_path)


def first_timing_text(seg, lines, group, f0, f1):
    """Text keys over a segment at the first person's timing: its group's own and its sounds (a bow's
    pull and release) as the first person has them, and the third person's footsteps and landings
    where its legs, warped, now make them."""
    out = [(seg.offset + tm - f0, line) for tm, line in lines
           if f0 - 1e-6 <= tm <= f1 + 1e-6 and split_line(line)[0] in (group, 'sound')]
    for piece in seg.warp_pieces:
        if len(piece) < 2 or piece[-1][1] - piece[0][1] < 1e-6:
            continue
        back = clamped([t for _, t in piece], [o for o, _ in piece])
        for tm, line in seg.source.lines:
            if piece[0][1] - 1e-6 <= tm <= piece[-1][1] + 1e-6 and split_line(line)[0] == 'soundgen':
                out.append((seg.offset + back(tm), line))
    return out


def segment_text(seg, rename=None, sections=None):
    """The third person's text keys over a segment: its group's own - only those whose first word is
    one of `sections`, when given (a group split into sections across files) - renamed to `rename`,
    and the footsteps and sounds, repeated with the loop."""
    out = []
    for tm, line in seg.source.lines:
        if tm < seg.v_start - 1e-6 or tm > seg.v_stop + 1e-6:
            continue
        group, key = split_line(line)
        own = group == seg.group
        if own and sections is not None and key.split()[0] not in sections:
            continue
        if not own and not is_footstep_line(line):
            continue
        if own and rename:
            line = rename + ':' + line.partition(':')[2]
        inside = seg.period > 0 and seg.loop_start - 1e-6 <= tm <= seg.loop_stop + 1e-6
        if own and key in ('loop stop', 'stop'):
            repeats = [seg.loops - 1]
        elif own or not inside:
            repeats = [0]
        else:
            repeats = range(seg.loops)  # a footstep in the loop sounds in every repeat of it
        for r in repeats:
            out.append((seg.offset + seg.out_time(tm, r), line))
    return out


# ---- per skeleton ---------------------------------------------------------------------------------

def run_skeleton(ctx, skeleton, third, first_files, first_groups, out_dir, opts, own=None):
    """Builds one skeleton's set. `own`: for a skeleton loaded over the base one (women), the sources
    of its own - only what they change is built, the rest being the base set's already."""
    posture_cache = {}

    def posture(stance, group, fallback_source):
        """The stance idle's posture in the third person - or, with no such idle, the group's own."""
        idle, src = stance_idle(stance)
        if idle is not None:
            if idle not in posture_cache:
                posture_cache[idle] = Posture(src, idle, ctx['lateral'])
            return posture_cache[idle]
        return Posture(fallback_source, group, ctx['lateral'])

    def stance_idle(stance):
        """The third person's idle for a stance - or the one the engine would play for it - and its
        source: idle1tstar tries idle1tstar, idle1t, idle1h, idle; a sneaking one, idle1hsneak, tries
        itself and then idlesneak, the one the engine plays for anyone sneaking."""
        tries = [stance] if stance is not None else []
        if stance and stance.endswith('sneak'):
            tries.append('sneak')
        if stance and stance.endswith('star'):
            tries.append(stance[:-len('star')])
        tries += [FALLBACK.get(t) for t in list(tries)] + ['']
        for s in tries:
            if s is None:
                continue
            src = third.find('idle' + s, ('start', 'stop'))
            if src is not None:
                return 'idle' + s, src
        return None, None

    def first_reference(stance, kf, group, keys):
        """The first person's idle of the stance, as it holds its arms and neck - or the group's own."""
        idle = 'idle' + (stance or '')
        if idle in first_groups:
            return ctx['first_idles'][idle]
        return first_person_idle(kf, group, keys)

    def convert(name, kf):
        """One first-person file: (the file written, its groups), or None if nothing was."""
        lines = text_lines(kf)
        groups = group_keys(lines)
        order = sorted(groups, key=lambda g: (min(groups[g].values()), g))
        segments, text, offset = [], [], 0.0
        for group in order:
            if skipped(group, opts):
                info('  %-28s %s: left alone' % (name, group))
                continue
            fkeys = groups[group]
            ordered = sorted(fkeys, key=lambda k: fkeys[k])
            first, last = ordered[0], ordered[-1]
            spelled = next((line.partition(':')[0].strip() for _, line in lines
                            if split_line(line)[0] == group), group)
            paired, source = pair_group(group, (first, last), third, opts['legs_from'])
            if own is not None and (source is None or source not in own):
                continue
            stance = stance_of(group) or (stance_of(paired) if paired else None)
            seg = None
            if source is not None:
                tkeys = source.groups[paired]
                # Keys both have, in an order both agree on.
                pairs = []
                for k in [k for k in ordered if k in tkeys]:
                    if not pairs or (tkeys[k] > pairs[-1][1] + 1e-6 and fkeys[k] > pairs[-1][2] + 1e-6):
                        pairs.append((k, tkeys[k], fkeys[k]))
                v_start, v_stop = tkeys[first], tkeys[last]
                loop_keys = 'loop start' in tkeys and 'loop stop' in tkeys and \
                    v_start <= tkeys['loop start'] and tkeys['loop stop'] <= v_stop
                ls, le = (tkeys['loop start'], tkeys['loop stop']) if loop_keys else (v_start, v_stop)
                loops = 1
                if set(k for k, _, _ in pairs) <= {'start', 'stop', 'loop start', 'loop stop'} and \
                        (loop_keys or is_idle(group)):
                    f_len = (fkeys.get('loop stop', fkeys[last]) - fkeys.get('loop start', fkeys[first]))
                    ratio = f_len / (le - ls) if le > ls else 1.0
                    if ratio >= PACE_RATIO:
                        loops = max(1, int(round(ratio)))
                pieces = None
                if not is_locomotion(group) and not in_stances(stance, opts['third_timing']):
                    # At the first person's timing: the third person's body sped up and slowed down
                    # so each key both have lands on the first person's.
                    pieces = warp_pieces(fkeys, tkeys)
                if pieces:
                    f0, f1 = fkeys[first], fkeys[last]
                    thirds = [t for piece in pieces for _, t in piece]
                    seg = Segment(source, paired, min(thirds), max(thirds))
                    seg.period, seg.lead, seg.tail = 0.0, 0.0, 0.0
                    seg.length = f1 - f0
                    seg.warp_pieces = pieces
                    seg.clock = pieces_clock(pieces)
                    seg.first_time = (lambda f0: lambda tau: f0 + tau)(f0)
                    seg.first_points = ([0.0, seg.length], [f0, f1])
                else:
                    seg = Segment(source, paired, v_start, v_stop, ls, le, loops)
                    # Output time -> first-person time, through the keys both have.
                    xs, ys = [], []
                    for k, t, f in pairs:
                        x = seg.out_time(t, seg.loops - 1 if k in ('loop stop', 'stop') else 0)
                        if not xs or x > xs[-1] + 1e-6:
                            xs.append(x)
                            ys.append(f)
                    if len(xs) < 2:
                        seg = None
                    else:
                        seg.first_time = piecewise(xs, ys)
                        seg.first_points = (xs, ys)
            held = opts['legs_from'].get(group)
            if seg is None and held is not None and held[1] is not None:
                # Given a third-person pose to hold (a bow's draw, held at full draw): its own timing
                # and text keys, on that pose.
                held_src = third.find(held[0], (held[1],))
                if held_src is None:
                    print('  %-28s %s: the third person has no %s: %s to hold, left to its stance idle' % (
                        name, group, held[0], held[1]))
                elif own is None or held_src in own:
                    at = held_src.groups[held[0]][held[1]]
                    seg = Segment(held_src, held[0], at, at)
                    seg.clock = (lambda a: lambda tau: a)(at)
            if seg is None:
                # Nothing in the third person to pair with (a tail, a hold): its own timing and text
                # keys, on its stance's idle, held.
                idle, idle_src = stance_idle(stance)
                if not opts['unpaired'] or idle is None or own is not None:
                    if own is None:
                        print('  %-28s %s: nothing in the third person to pair it with, left out' % (name, group))
                    continue
                ikeys = idle_src.groups[idle]
                i0, i1 = ikeys['start'], ikeys['stop']
                seg = Segment(idle_src, idle, i0, i1)
                seg.clock = (lambda a, b: lambda tau: a + math.fmod(tau, b - a) if b > a else a)(i0, i1)
            if seg.clock is not None and seg.warp_pieces is None:
                seg.period, seg.lead, seg.tail = 0.0, 0.0, 0.0
                seg.length = fkeys[last] - fkeys[first]
                seg.sample_all = True
                f0 = fkeys[first]
                seg.first_time = (lambda f0: lambda tau: f0 + tau)(f0)
                seg.first_points = ([0.0, seg.length], [f0, f0 + seg.length])
                paired = None
            seg.name = group
            seg.posture = posture(stance, group, seg.source)
            ref = first_reference(stance, kf, group, fkeys)
            seg.shoulders = E.qmul(E.qconj(seg.posture.neck), ref['neck'])
            seg.keep = opts['keep']
            seg.repoint = repoint_for(stance, opts)
            seg.bounce = bounce_for(stance, opts) if is_move(group) and paired else 0.0
            seg.grip = opts['grip'] and stance in GRIP_STANCES
            seg.follow = not in_stances(stance, opts['hold_torso'])
            if seg.follow:
                # The upper body is the first person's, arms and all: nothing to point or square.
                seg.repoint, seg.shoulders = 0.0, IDENTITY
                if is_move(group) and paired:
                    seg.sway_about = mean_rotation([E.world(seg.source.kf, SPINE, t)[0]
                                                    for t in span(seg.loop_start, seg.loop_stop)])
                if opts['steady_head'] and is_attack(group):
                    seg.head_forward = ref.get('head')
            for spec_group, spec_section, degrees in opts['lower']:
                if spec_group == group and (spec_section is None or any(k.startswith(spec_section + ' ') for k in fkeys)):
                    seg.lower_by = degrees
            seg.offset = offset
            segments.append(seg)
            if seg.warp_pieces is not None:
                text += first_timing_text(seg, lines, group, fkeys[first], fkeys[last])
            elif paired is not None:
                # Only this file's sections of the group - some split one across files, a cast in each
                # - under the first person's name for it.
                text += segment_text(seg, rename=spelled if paired != group else None,
                                     sections={k.split()[0] for k in fkeys})
            else:
                f0, f1 = fkeys[first], fkeys[last]
                text += [(offset + tm - f0, line) for tm, line in lines if f0 - 1e-6 <= tm <= f1 + 1e-6
                         and (split_line(line)[0] == group or is_footstep_line(line))]
            offset += seg.length + GAP
            info('  %-28s %s: %s%s%s, %s%s' % (
                name, group, ('on %s from %s' % (paired, source_name(seg.source)) if paired
                              else 'its own timing on %s' % seg.group),
                ', at the first person\'s timing' if seg.warp_pieces else '',
                ', its loop x%d' % seg.loops if seg.loops > 1 else '',
                ('torso as the first person%s' % (', head steady' if seg.head_forward else '')) if seg.follow
                else 'keep forward %.2f against %s' % (seg.keep, seg.posture.label),
                ', arms lowered up to %g deg' % seg.lower_by if seg.lower_by else ''))
        if segments:
            write_name = opts['prefix'] + name
            os.makedirs(out_dir, exist_ok=True)
            build(ctx, os.path.join(ctx['first_dir'], name), kf, segments, text, os.path.join(out_dir, write_name))
            rules = os.path.splitext(os.path.join(ctx['first_dir'], name))[0] + '.yaml'
            if os.path.isfile(rules):  # its blending rules, as the engine pairs them: by file name
                shutil.copyfile(rules, os.path.join(out_dir, os.path.splitext(write_name)[0] + '.yaml'))
            return write_name, [s.name if s.clock is None or s.warp_pieces else '%s (own timing on %s)' % (s.name, s.group)
                                for s in segments]
        return None

    written = [w for w in in_parallel(lambda i: convert(*first_files[i]), len(first_files)) if w is not None]

    # Idle arms where the third person shows them.
    if opts['fill']:
        for idle, ref in ctx['first_idles'].items():
            stance = idle[len('idle'):]
            if not stance or third.find(idle, ('start', 'stop')) is None:
                continue
            idle_file, idle_kf = ctx['first_idle_files'][idle]
            post = posture(stance, idle, third.find(idle, ('start', 'stop')))
            fills = []
            for turn in TURNS:
                group = stance + turn
                src = third.find(group, ('start', 'stop'))
                if src is not None and group not in first_groups and (own is None or src in own) \
                        and not skipped(group, opts):
                    fills.append(('turn', group, group, src))
            has_walks = any(third.find(m + stance, ('start', 'stop')) for m in MOVES)
            if stance in NOT_WEAPONS and not has_walks:
                for move in MOVES:
                    src = third.find(move, ('start', 'stop'))
                    if src is not None and move + stance not in first_groups and (own is None or src in own) \
                            and not skipped(move + stance, opts):
                        fills.append(('walk', move, move + stance, src))
            # A jump likewise: with no jump of the stance's own, the engine jumps the legs only and
            # shows the idle's upper body on top (refreshJumpAnims).
            if stance in NOT_WEAPONS and third.find('jump' + stance, ('start', 'stop')) is None:
                src = third.find('jump', ('start', 'stop'))
                if src is not None and 'jump' + stance not in first_groups and (own is None or src in own) \
                        and not skipped('jump' + stance, opts):
                    fills.append(('walk', 'jump', 'jump' + stance, src))
            for kind in ('turn', 'walk'):
                chosen = [f for f in fills if f[0] == kind]
                if not chosen:
                    continue
                segments, text, offset = [], [], 0.0
                for _, group, name_out, src in chosen:
                    keys = src.groups[group]
                    loop = 'loop start' in keys and 'loop stop' in keys
                    seg = Segment(src, group, keys['start'], keys['stop'],
                                  keys.get('loop start') if loop else None, keys.get('loop stop') if loop else None)
                    seg.name = name_out
                    seg.idle_arms = ref
                    seg.arm_swing = kind == 'turn'
                    seg.posture = post
                    seg.shoulders = E.qmul(E.qconj(post.neck), ref['neck'])
                    seg.keep = opts['keep']
                    seg.natural_chest = 'own' if kind == 'turn' else 'idle'
                    seg.repoint = repoint_for(stance, opts)
                    seg.bounce = bounce_for(stance, opts) if is_move(group) else 0.0
                    seg.grip = opts['grip'] and stance in GRIP_STANCES
                    seg.offset = offset
                    segments.append(seg)
                    spelled = group[0].upper() + group[1:]  # as the third person writes the group
                    rename = None
                    for tm, line in src.lines:
                        if split_line(line)[0] == group:
                            spelled = line.partition(':')[0].strip()
                            break
                    if name_out != group:
                        rename = spelled + stance[0].upper() + stance[1:]
                    text += segment_text(seg, rename=rename)
                    offset += seg.length + GAP
                file_name = opts['prefix'] + 'x%s%s.kf' % (stance[0].upper() + stance[1:], 'Turn' if kind == 'turn' else 'Movement')
                os.makedirs(out_dir, exist_ok=True)
                build(ctx, os.path.join(ctx['first_dir'], idle_file), idle_kf, segments, text,
                      os.path.join(out_dir, file_name))
                written.append((file_name, [f[2] for f in chosen]))
    for name, groups in written:
        late = '' if name.lower() > 'xbase_anim.kf' else '   (sorts before "xbase_anim.kf": a mod shipping a whole copy of that there would win over it)'
        print('  %-28s %s%s' % (name, ', '.join(groups), late))
    return written


def bounce_for(stance, opts):
    """A stance's arm bounce: its own, given with --arm-bounce-by - a throwing star's, its thrown
    weapon's - or everyone's."""
    by = opts['bounce_by']
    stance = stance or ''
    for s in (stance, stance[:-len('star')] if stance.endswith('star') else None):
        if s is not None and s in by:
            return by[s]
    return opts['bounce']


_job = None


def _run_job(i):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _job(i)
    return buffer.getvalue(), result


def in_parallel(job, count):
    """[job(0), ..., job(count - 1)], JOBS at a time in forked processes where the system has fork -
    the work in hand is theirs already, nothing to send - and one by one where it has not. What each
    prints comes out whole and in order."""
    global _job
    if JOBS < 2 or count < 2 or 'fork' not in multiprocessing.get_all_start_methods():
        return [job(i) for i in range(count)]
    _job = job
    results = []
    with multiprocessing.get_context('fork').Pool(min(JOBS, count)) as pool:
        for printed, result in pool.imap(_run_job, range(count)):
            sys.stdout.write(printed)
            sys.stdout.flush()
            results.append(result)
    return results


def repoint_for(stance, opts):
    """How much of the arms' first-person direction a stance keeps: none, when asked, for one
    holding something in both hands - pointed separately, the hands would come apart."""
    if opts['two_handed_follow'] and stance in TWO_HANDED:
        return 0.0
    return opts['repoint']


def parse_lower(text):
    """'spellcast target=15, weapononehand=10' -> [('spellcast', 'target', 15.0), ('weapononehand', None, 10.0)]"""
    out = []
    for item in [i.strip() for i in str(text).split(',') if i.strip()]:
        left, eq, degrees = item.partition('=')
        if not eq:
            raise ValueError("expected 'group section=degrees', got %r" % item)
        words = left.lower().split()
        if not 1 <= len(words) <= 2:
            raise ValueError("expected 'group section=degrees', got %r" % item)
        out.append((words[0], words[1] if len(words) > 1 else None, float(degrees)))
    return out


def parse_moves(text):
    """'all' -> None (every stance), 'none' -> nothing, else the stances listed ('plain' for none)."""
    words = [w.strip().lower() for w in str(text).split(',') if w.strip()]
    if not words or words == ['all']:
        return None
    if words == ['none']:
        return set()
    return {'' if w == 'plain' else w for w in words}


def parse_stance_values(text):
    """'2w=0.2, hh=0.5, plain=0' -> {'2w': 0.2, 'hh': 0.5, '': 0.0}"""
    out = {}
    for item in [i.strip() for i in str(text).split(',') if i.strip()]:
        left, eq, right = item.partition('=')
        if not eq or not left.strip():
            raise ValueError("expected 'stance=value', got %r" % item)
        value = float(right)
        if not 0.0 <= value <= 1.0:
            raise ValueError('%s: %s is not between 0.0 and 1.0' % (left.strip(), value))
        stance = left.strip().lower()
        out['' if stance == 'plain' else stance] = value
    return out


def parse_pairs(text):
    """'weapononehand1=weapononehand, bowandarrow1=bowandarrow@shoot max attack' ->
    {first-person group: (third-person group, the key its pose is held at, or None)}"""
    out = {}
    for item in [i.strip() for i in str(text).split(',') if i.strip()]:
        left, eq, right = item.partition('=')
        group, at, key = right.partition('@')
        if not eq or not left.strip() or not group.strip() or (at and not key.strip()):
            raise ValueError("expected 'group=third-person group' or 'group=third-person group@key', got %r" % item)
        out[left.strip().lower()] = (group.strip().lower(), key.strip().lower() if at else None)
    return out


def word_list(text):
    return [w.strip().lower() for w in str(text).split(',') if w.strip()]


def folder_list(text):
    return [os.path.expanduser(f.strip().strip('"')) for f in str(text).split(',') if f.strip()]


def prompting(given):
    """Whether ask() will put this setting's question, and so its explanation, on screen."""
    return given is None and not params.USE_DEFAULTS and sys.stdin.isatty()


def ask_text(given, label, explanation, default, parse):
    """ask() for a setting written as text: checked as it is typed, and parsed the same way when the
    default is kept - ask() hands a default back as it is."""
    return parse(ask(given, label, explanation, default, lambda text: (parse(text), text)[1]))


def sections_of(keys):
    """The sections a group's text keys name: chop, slash, thrust; self, target, touch."""
    return sorted({k.split()[0] for k in keys if ' ' in k} - {'loop'})


def locomotion_stances(groups):
    """The stances a set has walks, runs, sneaks or jumps for ('' for none)."""
    out = set()
    for group in groups:
        base, stance = base_and_stance(group)
        if base is not None and base.startswith(LOCOMOTION):
            out.add(stance)
    return sorted(out)


def group_listing(groups, sections=None):
    """A set's groups for a question, every one of them: a stance's walks, runs and sneaks in one
    word where it has all twelve, the rest by name - with their sections, given {group: keys}."""
    whole = [st for st in sorted({base_and_stance(g)[1] for g in groups if is_move(g)})
             if all(m + st in groups for m in MOVES)]
    named = []
    for g in sorted(groups):
        if is_move(g) and base_and_stance(g)[1] in whole:
            continue
        found = sections_of(sections[g]) if sections else []
        named.append('%s (%s)' % (g, ', '.join(found)) if found else g)
    text = listed(named)
    if whole:
        text += "; and every walk, run and sneak (walkforward, walkback, walkleft, walkright, run..., sneak..., " \
                "each followed by the stance) of: %s" % ', '.join(st or 'plain (no weapon: walkforward...)' for st in whole)
    return text


def duration(seconds):
    return '%dm %02ds' % divmod(int(round(seconds)), 60)


def work_seconds(first_files, opts):
    """How much first-person animation a build converts: the length of every group it does not leave
    alone, in seconds."""
    total = 0.0
    for _, kf in first_files:
        for group, keys in group_keys(text_lines(kf)).items():
            if not skipped(group, opts):
                total += max(keys.values()) - min(keys.values())
    return total


def estimate(work, files, skeletons, fills):
    """Roughly how long a build of `work` seconds of animation in `files` files for `skeletons` takes
    here, going by TIMING_RATE: scaled by how many files go at once, not by how fast this machine is."""
    at_once = min(JOBS, os.cpu_count() or 1, files) if 'fork' in multiprocessing.get_all_start_methods() else 1
    return (sum(TIMING_RATE[sk] for sk in skeletons) * work * TIMING_JOBS / max(1, at_once)
            + (FILL_SECONDS * len(skeletons) if fills else 0))


def rough(seconds):
    minutes = max(1, int(round(seconds / 60.0)))
    return 'roughly %d minute%s' % (minutes, '' if minutes == 1 else 's')


def listed(names):
    return ', '.join(names) if names else 'none'


def stance_label(stance):
    """'2w (spears and staves)', 'plain (no weapon)'; one of a mod's own, as it is."""
    return '%s (%s)' % (stance or 'plain', STANCE_NAMES[stance]) if stance in STANCE_NAMES else stance


def unit(text):
    """A share from 0.0 to 1.0; anything else is a ValueError, so a typo is asked again."""
    value = float(text)
    if not 0.0 <= value <= 1.0:
        raise ValueError('%s is not between 0.0 and 1.0' % text)
    return value


def main():
    global VERBOSE, JOBS
    p = argparse.ArgumentParser(description='First-person animations to third person. Anything not given is '
                                            'asked for, with its default filled in. See README.md.')
    p.add_argument('-y', '--yes', action='store_true', help='use the defaults for everything not given, no questions')
    p.add_argument('-v', '--verbose', action='store_true', help='print what each group is built from')
    p.add_argument('--first', metavar='DIR', help="first-person animations: a mod's animations/xbase_anim.1st")
    p.add_argument('--third', metavar='PATHS', help='third-person animations to build on: mod, meshes, animations '
                                                    'or skeleton folders, or .kf files, comma separated, later winning')
    p.add_argument('--vanilla', metavar='y/n', help="vanilla's third-person animations underneath them (default y)")
    p.add_argument('--out', metavar='DIR', help='the animations folder the skeleton folders are written into')
    p.add_argument('--beasts', metavar='y/n', help='also build for beast races (default y)')
    p.add_argument('--women', metavar='y/n', help="also build what women's own animations change (default y)")
    p.add_argument('--hold-torso', metavar='STANCES', help="stances whose torso is the third person's, held "
                                                          "forward; the others' upper body follows the first "
                                                          "person (default %s)" % HOLD_TORSO)
    p.add_argument('--steady-head', metavar='y/n', help='attacks whose upper body follows the first person look '
                                                        'ahead, the head not turning with the swing (default y)')
    p.add_argument('--third-timing', metavar='STANCES', help="stances whose animations keep the third person's "
                                                            "timing; the others play at the first person's "
                                                            "(default %s)" % THIRD_TIMING)
    p.add_argument('--keep-forward', metavar='0..1', help='torso and head held facing forward, shoulders square (default %g)' % KEEP_FORWARD)
    p.add_argument('--point-arms', metavar='0..1', help='arms point as in first person, whatever the torso '
                                                          'does (default %g)' % REPOINT)
    p.add_argument('--two-handed-follow', metavar='y/n', help='two-handed stances keep their arms on the torso '
                                                              'instead (default y)')
    p.add_argument('--idle-arms', metavar='y/n', help="give stance turns, walks and jumps the converted idle's arms "
                                                      "(default y)")
    p.add_argument('--arm-bounce', metavar='0..1', help='experimental: arms lag and spring back while moving '
                                                        '(default %g)' % ARM_BOUNCE)
    p.add_argument('--arm-bounce-by', metavar='STANCES', help="arm bounce for some weapon types of their own, "
                                                              "e.g. '2w=0.2, hh=0.5' (default: --arm-bounce for all)")
    p.add_argument('--grip', metavar='y/n', help='two-handed weapons: only the right arm bounces, the left hand '
                                                 'follows it on the grip (default y)')
    p.add_argument('--lower-arms', metavar='SPEC', help="'group section=degrees, ...', e.g. 'spellcast target=15'")
    p.add_argument('--moves', metavar='STANCES', help="whose walks, runs, sneaks and jumps to convert: all, none, "
                                                      "or stances such as '2w, hh' (default all)")
    p.add_argument('--skip-files', metavar='PATTERNS', help="first-person files to leave out entirely, shell patterns, "
                                                           "comma separated, e.g. '_xReanimationv1.kf'")
    p.add_argument('--skip', metavar='PATTERNS', help="groups to leave alone, shell patterns, comma separated")
    p.add_argument('--legs-from', metavar='PAIRS', help="'group=third-person group, ...': where groups the third "
                                                        "person lacks take their legs and timing from; "
                                                        "'group=third-person group@key' holds that pose")
    p.add_argument('--unpaired', metavar='y/n', help='groups with nothing to pair with keep their own timing on '
                                                     'their stance idle (default y)')
    p.add_argument('--prefix', metavar='TEXT', help='put in front of every file name written (default none)')
    p.add_argument('--data-files', metavar='DIR', help="Morrowind's Data Files, with Morrowind.bsa")
    p.add_argument('--jobs', metavar='N', type=int, help='files converted at once (default: one per CPU, %d here)' % JOBS)
    a = p.parse_args()
    started = time.time()
    params.USE_DEFAULTS = a.yes
    VERBOSE = a.verbose
    if a.jobs:
        JOBS = max(1, a.jobs)
    settings = ('first', 'skip_files', 'third', 'vanilla', 'out', 'beasts', 'women', 'hold_torso', 'steady_head',
                'third_timing', 'keep_forward', 'point_arms',
                'two_handed_follow', 'idle_arms', 'lower_arms', 'moves', 'arm_bounce', 'arm_bounce_by', 'grip',
                'skip', 'legs_from', 'unpaired', 'prefix')
    open_settings = [n for n in settings if getattr(a, n) is None]
    if open_settings and prompting(None):
        params.USE_DEFAULTS = ask(
            None, 'Use the defaults for the %d settings not given on the command line (y), or go through them '
                  'one by one (n)?' % len(open_settings),
            "Building can take a while - on %s, for all three skeletons, %s - and it says roughly how long "
            "yours will before it starts. Not given: %s. One by one, each is explained with its default filled in - "
            "Enter keeps it - up to %d questions, and one more for each weapon type if you choose to set arm "
            "bounce by weapon type. The first-person folder is asked for either way when there is none here to "
            "default to." % (TIMING_MACHINE, TIMING_EXAMPLES,
                             ', '.join('--' + n.replace('_', '-') for n in open_settings), len(open_settings)),
            True, yes_no)

    scratch = tempfile.TemporaryDirectory()
    bsa = {}

    def load_vanilla(name, needed):
        """One of vanilla's kfs from Morrowind.bsa, or None if there is none to read and it is not
        `needed` (a message saying what it would have been for)."""
        if 'files' not in bsa:
            data_files = a.data_files or params.find_data_files()
            path = params.child(data_files, 'Morrowind.bsa') if data_files else None
            bsa['files'] = bsa_files(path, set(SKELETONS.values()) | {FIRST_PERSON_KF}) if path else None
        if bsa['files'] is None:
            if needed is True:
                sys.exit('Morrowind.bsa not found from openmw.cfg - give --data-files')
            if needed:
                print('  (no Morrowind.bsa to read: %s)' % needed)
            return None
        path = os.path.join(scratch.name, name.split('\\')[-1])
        if not os.path.isfile(path):
            with open(path, 'wb') as fh:
                fh.write(bsa['files'][name])
        return nifkf.KF.load(path)

    guess = None
    for c in (os.path.join(os.getcwd(), 'animations', 'xbase_anim.1st'), os.path.join(os.getcwd(), 'xbase_anim.1st')):
        found = params.child(os.path.dirname(c), os.path.basename(c)) if os.path.isdir(os.path.dirname(c)) else None
        if found:
            guess = found
            break
    defaults, params.USE_DEFAULTS = params.USE_DEFAULTS, params.USE_DEFAULTS and (a.yes or guess is not None)
    first_dir = ask(a.first, 'First-person animations',
                    "The folder of first-person .kf files to convert - a mod's animations/xbase_anim.1st.", guess, str)
    params.USE_DEFAULTS = defaults
    first_dir = os.path.abspath(os.path.expanduser(first_dir))
    if not os.path.isdir(first_dir):
        sys.exit('%s is not a folder' % first_dir)
    first_files, raw = [], []
    for name in sorted(os.listdir(first_dir), key=str.lower):
        if name.lower().endswith('.kf'):
            try:
                first_files.append((name, nifkf.KF.load(os.path.join(first_dir, name))))
                raw.append(nifkf.KF.load(os.path.join(first_dir, name)))
            except Exception as e:  # noqa: BLE001 - a broken file is skipped, not fatal
                print('  cannot read %s (%s), skipped' % (name, e))
    if not first_files:
        sys.exit('No .kf files in %s' % first_dir)
    skip_files = ask_text(a.skip_files, 'First-person files to leave out',
                          "Files of the set not to convert at all - an old version of an animation the set keeps "
                          "for compatibility, say - comma separated; * and ? work. Left out, a file is not used "
                          "for anything else either, such as the stance idles the others' arms are measured "
                          "against. Empty: none. This set's files: %s." % listed([n for n, _ in first_files]),
                          '', word_list)
    left_out = [n for n, _ in first_files if any(fnmatch.fnmatch(n.lower(), pat) for pat in skip_files)]
    if left_out:
        kept = [i for i, (n, _) in enumerate(first_files) if n not in left_out]
        first_files, raw = [first_files[i] for i in kept], [raw[i] for i in kept]
        if not first_files:
            sys.exit('Every file in %s is left out' % first_dir)
    # The set's groups, each with every key any of its files gives it - for the questions below.
    set_groups = {}
    for _, kf in first_files:
        for group, keys in group_keys(text_lines(kf)).items():
            set_groups.setdefault(group, set()).update(keys)

    third_dirs = folder_list(ask(a.third, 'Third-person animations to build on',
                                 "Mod folders (a whole-set replacer's meshes/xbase_anim.kf and its animations/ folders "
                                 "both count), meshes, animations or skeleton folders, or .kf files, comma separated, "
                                 "later ones winning as they would in the load order. Empty: vanilla's.", '', str))
    under = ask(a.vanilla, 'Vanilla underneath (y/n)',
                "Build on vanilla's third-person animations too, as the game would: the folders above go over them, "
                "and a whole-set replacer among them (a meshes/xbase_anim.kf) takes their place. n: only the "
                "folders above - any set of first-person animations merged with any set of third-person ones.",
                True, yes_no)
    if not under and not third_dirs:
        sys.exit('Nothing to build on: give third-person folders, or keep vanilla underneath')
    out_root = ask(a.out, 'Output folder',
                   'The animations folder the third-person skeleton folders (xbase_anim, xbase_animkna) are written '
                   'into - by default the one the first-person folder is in, so they ship with it.',
                   os.path.dirname(first_dir), str)
    out_dirs = [os.path.join(out_root, sk) for sk in SKELETONS]
    third_cache = {}

    def third_for(skeleton):
        """A skeleton's third-person animations as the engine loads them - the skeleton it is loaded
        over first, then its own: (ThirdPerson, its own sources, what they are, [(the sources given,
        vanilla's kf) per layer])."""
        if skeleton in third_cache:
            return third_cache[skeleton]
        layers = ([LAYERS[skeleton]] if skeleton in LAYERS else []) + [skeleton]
        sources, own, used, rest_from = [], [], [], []
        for layer in layers:
            base, extra = third_person_files(third_dirs, layer, out_dirs)
            v = None
            if (under and base is None) or layer == skeleton:
                v = load_vanilla(SKELETONS[layer], True if under and base is None else
                                 'bones the animations given do not key get no rest offset')
            given = load_files(([base] if base else []) + extra)
            layer_sources = ([Source('vanilla ' + SKELETONS[layer].split('\\')[-1], v)]
                             if under and base is None and v else []) + given
            sources += layer_sources
            if layer == skeleton:
                own = layer_sources
            if under and base is None and v:
                used.append('vanilla ' + SKELETONS[layer].split('\\')[-1])
            if base:
                used.append(where(base, 4))
            if extra:
                used.append('%d from %s' % (len(extra), ', '.join(sorted({where(os.path.dirname(x), 3) for x in extra}))))
            rest_from.append((given, v))
        third_cache[skeleton] = (ThirdPerson(None, sources), own, used, rest_from)
        return third_cache[skeleton]

    beasts = ask(a.beasts, 'Beasts too (y/n)',
                 'Also build for beast races (xbase_animkna), on their own third-person animations.', True, yes_no)
    women = ask(a.women, 'Women too (y/n)',
                "Women play a few third-person animations of their own (xbase_anim_female - a walk, say) over "
                "everyone's; build those again on theirs.", True, yes_no)
    stances = sorted({(stance_of(g) or '') for g in set_groups} - {None})
    stances = sorted({st[:-len('sneak')] if st.endswith('sneak') else st for st in stances})
    stance_list = listed([stance_label(st) for st in stances])
    hold = ask_text(a.hold_torso, "Stances whose torso is held forward",
                    "The rest move their whole upper body as the first person does - chest, spine and head "
                    "turned the way the first person turns them, on the third person's hips and legs - which is "
                    "what a weapon's swings and lunges want. Held forward instead, the torso is the third "
                    "person's, turned toward facing ahead (the next settings say how much), and only the arms "
                    "are the first person's: for what points the arms at something, as a spell cast does. "
                    "'all', 'none', or stances, comma separated. This set's: %s." % stance_list,
                    HOLD_TORSO, parse_moves)
    steady_head = ask(a.steady_head, 'Head looks ahead through attacks (y/n)',
                      "Where the upper body follows the first person: in first person the head turns with every "
                      "swing, up to 90 degrees into a punch, which the camera never shows. y holds it looking "
                      "ahead, as in the stance idle; the neck and arms still move as animated.", STEADY_HEAD, yes_no)
    third_timing = ask_text(a.third_timing, "Stances that keep the third person's timing",
                            "The rest play at the first person's timing, with its text keys - when a swing hits, "
                            "when an arrow flies - and the third person's legs sped up and slowed down between "
                            "the keys both have to match. Keeping the third person's instead plays the first "
                            "person's arms faster or slower between them. Walks, runs, sneaks and turns always "
                            "keep the third person's, which paces the character's movement. 'all', 'none', or "
                            "stances, comma separated. This set's: %s." % stance_list, THIRD_TIMING, parse_moves)
    keep = ask(a.keep_forward, 'Keep forward (0.0 - 1.0)',
               "For the stances held forward: how much the torso and head are held facing forward - in their stance idle's posture, shoulders "
               "square - through every animation; idles keep their breathing and are only turned that share of the "
               "way square. 1.0 holds them still; 0.0 leaves the third person's own leans, twists and side-on stances, "
               "which were made for its own arms and can aim the first person's far off.", KEEP_FORWARD, unit)
    repoint = ask(a.point_arms, 'Point arms as in first person (0.0 - 1.0)',
                  "For the stances held forward: how much the arms keep the direction the first person gives them - the way the character "
                  "faces - whatever the third-person torso does. 1.0 points them exactly so: a cast goes straight "
                  "ahead even where the body turns. 0.0 hangs them on the torso and turns them with it. Pointed "
                  "separately the two arms no longer move as one, which can go badly wrong where both hands hold "
                  "one thing - a two-handed weapon, a bow; the next setting leaves those alone.", REPOINT, unit)
    two_handed = ask(a.two_handed_follow, 'Leave two-handed stances on the torso (y/n)',
                     "Two-handed weapons, bows and crossbows (2c, 2b, 2w, bow, crossbow) keep their arms on the torso "
                     "instead of pointing them, so both hands stay on the weapon.", True, yes_no)
    fill = ask(a.idle_arms, 'Idle arms where the third person shows them (y/n)',
               "Turning on the spot with a spell ready, and walking or jumping in a stance with no walks or jump of "
               "its own (a spell), show the stance idle's arms: when the first person converts that idle, make these "
               "too, with its arms.", True, yes_no)
    lower = ask_text(a.lower_arms, 'Lower raised arms',
                     "Animations whose arms sit too high in third person - first-person hands sit at the camera's "
                     "height - as 'group section=degrees', comma separated, e.g. 'spellcast target=15'; without a "
                     "section, the whole group. Empty: none. This set's groups, with their sections: %s." %
                     group_listing(set_groups, set_groups), '', parse_lower)
    idle_made = [s for s in NOT_WEAPONS if fill and 'idle' + s in set_groups
                 and s not in locomotion_stances(set_groups)]
    moves = ask_text(a.moves, 'Walks, runs, sneaks and jumps to convert',
                     "By stance: 'all', 'none', or a list such as '2w, hh' ('plain' for no weapon; '1t' takes in "
                     "'1tstar'). The others are left alone, so the third person's own keep playing for them. This "
                     "set has them for: %s%s." % (
                         listed([stance_label(m) for m in locomotion_stances(set_groups)]),
                         '; made from its idle: %s' % listed([stance_label(m) for m in idle_made]) if idle_made else ''),
                     'all', parse_moves)
    moving = sorted({base_and_stance(g)[1] for g in set_groups if is_move(g)} | set(idle_made))
    moving = [m for m in moving if moves is None or m in moves or (m.endswith('star') and m[:-len('star')] in moves)]
    bounce = ask(a.arm_bounce, 'Arm bounce while moving (experimental, 0.0 - 1.0)',
                 "The elbows and wrists lag behind the body's bob and sway and spring back, as a spring would move "
                 "them, on walks, runs and sneaks - looping as they do. 1.0 is the whole of what the spring does; "
                 "0.0 is off.", ARM_BOUNCE, unit)
    if a.arm_bounce_by is not None:
        bounce_by = parse_stance_values(a.arm_bounce_by)
    else:
        bounce_by = {}
        if moving and ask(None, 'Arm bounce by weapon type (y/n)',
                          "Set the arm bounce for each weapon type whose walks, runs and sneaks are converted, one "
                          "question each - %d: %s. n: %g for all of them. (On the command line: --arm-bounce-by "
                          "'2w=0.2, hh=0.5'.)" % (len(moving), listed([stance_label(m) for m in moving]), bounce),
                          False, yes_no):
            for m in moving:
                bounce_by[m] = ask(None, 'Arm bounce for %s (0.0 - 1.0)' % stance_label(m), '', bounce, unit)
    if bounce or any(bounce_by.values()):
        grip = ask(a.grip, 'Keep the left hand on a two-handed grip (y/n)',
                   "Two-handed weapons and crossbows (%s): arm bounce moves only the right arm, the one holding "
                   "the weapon, and the left arm reaches after it so the left hand stays where it was on the "
                   "weapon. n: both arms bounce on their own, and the hands can come apart." % ', '.join(GRIP_STANCES),
                   True, yes_no)
    else:
        grip = True if a.grip is None else yes_no(a.grip)
    skip = ask_text(a.skip, 'Groups to leave alone',
                    "Animation groups not to convert at all, comma separated; * and ? work, e.g. 'torch*, "
                    "runbounce*'; 'walk*1h' is every one-handed walk. Empty: none. This set's groups: %s." %
                    group_listing(set_groups), '', word_list)
    legs_text = ("Groups of the first person's own - an alternate attack, a throwing star's walk - take the legs "
                 "and timing of the one they vary, found by name and by the engine's own weapon fallbacks. Pair "
                 "any it gets wrong here, as 'group=third-person group', comma separated - or hold a third-person "
                 "pose for one, as 'group=third-person group@key': a bow's tension hold on the full draw, "
                 "'bowandarrow1=bowandarrow@shoot max attack'. Empty: none.")
    if prompting(a.legs_from):
        third = third_for('xbase_anim')[0]
        now = {'skip': skip, 'moves': moves}
        paired, alone = {}, []
        for _, kf in first_files:
            for group, keys in group_keys(text_lines(kf)).items():
                if group in paired or group in alone or skipped(group, now):
                    continue
                ordered = sorted(keys, key=lambda k: keys[k])
                other, _ = pair_group(group, (ordered[0], ordered[-1]), third, {})
                if other is None:
                    alone.append(group)
                elif other != group:
                    paired[group] = other
        third_groups = sorted({g for src in third.sources for g in src.groups})
        legs_text += (" Paired so now: %s. Nothing to pair with (they keep their own timing on the stance idle): "
                      "%s. The third person's groups: %s." % (
                          listed(['%s=%s' % (g, paired[g]) for g in sorted(paired)]), listed(sorted(alone)),
                          listed(third_groups)))
    legs_from = ask_text(a.legs_from, 'Legs and timing for groups the third person lacks', legs_text, '', parse_pairs)
    unpaired = ask(a.unpaired, 'Keep groups with nothing to pair with (y/n)',
                   "A group the third person has nothing like (a flourish, a hold) keeps its own timing and text keys, "
                   "on its stance's idle; n leaves such groups out.", True, yes_no)
    prefix = ask(a.prefix, 'File name prefix',
                 "Put in front of every file written. Within a skeleton folder the file that sorts last wins a group, "
                 "so a prefix sorting after 'xbase_anim.kf' (some mods ship a whole copy of it there) keeps these "
                 "winning. Empty: the first person's names.", '', str)

    # The root and legs a first-person file may not key, so its shoulders can be placed in the
    # character's frame: from a file of the same set that keys the whole body, else from vanilla's
    # first-person skeleton.
    reference = next((kf for kf in raw if keys_whole_body(kf)), None)
    reference_label = 'this set'
    if reference is None:
        reference = load_vanilla(FIRST_PERSON_KF, None)
        reference_label = "vanilla's first-person skeleton"
    for name, kf in first_files:
        if not keys_whole_body(kf):
            if reference is None:
                sys.exit('%s does not key the root and legs, no file of its set does, and there is no '
                         'Morrowind.bsa for the first-person skeleton - give --data-files' % name)
            fba_merge.add_rest_bones(kf, reference)
            add_torso(kf, reference)
    first_groups, first_idles, first_idle_files = {}, {}, {}
    for name, kf in first_files:
        for group, keys in group_keys(text_lines(kf)).items():
            first_groups.setdefault(group, name)
            if is_idle(group) and group not in first_idles and not skipped(group, {'skip': skip, 'moves': moves}):
                first_idles[group] = first_person_idle(kf, group, keys)
                first_idle_files[group] = (name, kf)
    ctx = {'first_rest': rest_of(raw, reference), 'first_dir': first_dir,
           'first_idles': first_idles, 'first_idle_files': first_idle_files}
    opts = {'keep': keep, 'fill': fill, 'hold_torso': hold, 'steady_head': steady_head, 'third_timing': third_timing, 'lower': lower, 'repoint': repoint, 'two_handed_follow': two_handed,
            'bounce': bounce, 'bounce_by': bounce_by, 'grip': grip, 'moves': moves, 'skip': skip, 'legs_from': legs_from,
            'unpaired': unpaired, 'prefix': prefix}
    def stance_set(chosen):
        return 'all' if chosen is None else listed(sorted('plain' if m == '' else m for m in chosen))
    print('\n%d first-person files from %s%s (root and legs where missing: %s); torso held forward for %s, '
          'the first person\'s for the rest%s; the third person\'s timing for %s; keep forward %.2f, arms '
          'pointed %.2f%s, arm bounce %.2f%s%s%s%s%s' % (
        len(first_files), first_dir, ' (left out: %s)' % ', '.join(left_out) if left_out else '', reference_label,
        stance_set(hold), ' (head steady in attacks)' if steady_head else '', stance_set(third_timing),
        keep, repoint, ' (two-handed on the torso)' if two_handed else '', bounce,
        ''.join(', %s %g' % (m or 'plain', v) for m, v in sorted(bounce_by.items())),
        ' (two-handed: the left hand on the grip)' if grip and bounce else '',
        '' if fill else ', no idle-arm turns, walks and jumps',
        ''.join(', %s%s arms lowered up to %g deg' % (g, ' ' + s if s else '', d) for g, s, d in lower),
        '' if moves is None else ', walks, runs, sneaks and jumps of %s only' % listed(
            sorted('plain' if m == '' else m for m in moves))))
    chosen = [sk for sk in SKELETONS if (beasts or sk != 'xbase_animkna') and (women or sk != 'xbase_anim_female')]
    work = work_seconds(first_files, opts)
    fills = fill and any(s in NOT_WEAPONS for s in (g[len('idle'):] for g in first_idles))
    print('Should take %s (%s of animation in %d files, for %s, going by %s).' % (
        rough(estimate(work, len(first_files), chosen, fills)), duration(work), len(first_files), ', '.join(chosen),
        TIMING_MACHINE))

    for skeleton in SKELETONS:
        if (skeleton == 'xbase_animkna' and not beasts) or (skeleton == 'xbase_anim_female' and not women):
            continue
        out_dir = os.path.join(out_root, skeleton)
        third, own, used, rest_from = third_for(skeleton)
        if not own:
            print('%s: no third-person animations of its own among those given, skipped' % skeleton)
            continue
        # The skeleton the animations were made on: theirs first - this skeleton's own, then the one it
        # is loaded over - and vanilla's where they key nothing.
        kfs = [g.kf for given, _ in reversed(rest_from) for g in given]
        ctx['third_rest'] = rest_of(kfs + [v for _, v in reversed(rest_from) if v is not None])
        if not all(b in ctx['third_rest'] for b in ('Bip01 L Clavicle', 'Bip01 R Clavicle')):
            print('%s: the third-person animations do not key the clavicles, skipped' % skeleton)
            continue
        ctx['lateral'] = lateral_axis(ctx['third_rest'])
        print('%s: on %s -> %s' % (skeleton, ' + '.join(used), out_dir))
        began = time.time()
        run_skeleton(ctx, skeleton, third, first_files, first_groups, out_dir, opts,
                     own=own if skeleton == 'xbase_anim_female' else None)
        print('%s: done in %s' % (skeleton, duration(time.time() - began)))
    scratch.cleanup()
    print('\nDone in %s.' % duration(time.time() - started))

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit('\nStopped.')
