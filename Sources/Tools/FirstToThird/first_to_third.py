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
* Moves made from an idle. A stance following the first person that has an idle gets whatever of its
  walks, runs, turns and jump it lacks made from that idle, on the third person's legs (the engine's
  own group for it, or the one it would play instead - a thrown weapon's the one-handed sword's): the
  idle's upper body as it holds it on average, leaning as the third person leans there against its
  stance idle (a run's lean). The stances named for it get their sneaks so too, a sneaking idle and
  sneaking moves on the third person's sneaking legs, leaning into its crouch, the sneaking idle
  playing the idle itself over and over. Leaned, the arms keep the way they point and the head its
  gaze.
* Torso motion: first-person walks hold the torso still, rigid on third-person legs. On every walk,
  run and sneak it moves the way gait studies find people's bodies move over their legs, made from
  what the third person's legs do (move_torso): a nod forward as the weight comes down on each step,
  the chest rolling against the hips' sway so the neck stays over the line of the walk and leaning
  over the standing leg, the shoulders swinging against the legs - smooth and looping - and the whole
  walk is leaned forward as far as it takes never to lean back of a least lean.
* Breathing: idles whose upper body is the first person's breathe - the chest turning up, the
  shoulders lifting - one smooth, looping breath for about every four seconds of the idle's loop.
* Arm bounce: on walks, runs and sneaks made from an idle (and the first person's own, if asked) the
  elbows and wrists lag behind the body's bob and sway and spring back, simulated the same way - by
  weapon type, if you like. Where both hands hold one weapon only the right arm, which holds it,
  springs; the left reaches after it and stays on the grip.
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
# ...and its skeleton: the bones there are, which a kf keying any other gets a warning for, each time
# an actor loads it (animation.cpp, addSingleAnimSource).
SKELETON_MESHES = {skeleton: kf[:-len('.kf')] + '.nif' for skeleton, kf in SKELETONS.items()}
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
# Morrowind's skeletons hang the thighs - and a beast's tail - off the lower spine, not the pelvis
# (base_anim.nif, base_animkna.nif): whatever turns Bip01 Spine turns the legs with it.
LEG_ROOTS = ('Bip01 L Thigh', 'Bip01 R Thigh', 'Bip01 Tail')
LEGS = {side: tuple('Bip01 %s %s' % (side, part) for part in ('Thigh', 'Calf', 'Foot')) for side in 'LR'}
# What turning the hips under a twisted torso turns (untwist): the hips, and the legs to keep the feet.
TWIST_BONES = ('Bip01 Pelvis',) + LEGS['L'] + LEGS['R']
E.PARENT.update({bone: SPINE for bone in LEG_ROOTS})
E.PARENT.update({'Bip01 Tail1': 'Bip01 Tail', 'Bip01 Tail2': 'Bip01 Tail1', 'Bip01 Tail3': 'Bip01 Tail2'})
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
TORSO_MOTION = 1.0      # share of the torso's motion on walks, runs and sneaks: its nod, roll, lean and swing
TORSO_NOD = 'walk=3.5, run=6.5, sneak=2.5'  # degrees the thorax pitches through, forward and back, each step
NECK_SWAY = 0.3         # share of the hips' side-to-side sway the neck keeps: the chest rolls against the rest
SHOULDER_SWING = 'walk=10, run=24, sneak=7'  # degrees the thorax turns through each stride, shoulder against leg
STANCE_LEAN = 'walk=3.5, run=8, sneak=2.5'  # degrees the thorax tilts through each stride, toward the standing leg

# How the thorax moves against the room through a stride, from right foot strike (0.0) through left
# foot strike (0.5), as gait studies measure it - the shapes; the settings above give their size.
# Running: Preece, Mason and Bramah (2016), The coordinated movement of the spine and pelvis during
# running, Human Movement Science (28 runners, 3.9 m/s), figure 1a-c, read off every 5 % over the first
# half and made left-right symmetric (the second half mirrors it): forward flexion peaking 15 % after
# each foot strike (6.5 degrees through), a tilt toward the standing leg peaking 5-10 % after it (8),
# and a turn bringing the shoulder opposite the striking foot forward, held through flight (24; Seay et
# al. 2011 measured 25). Walking: the turn and the tilt as near-sine waves - the turn furthest just
# before each heel strike (Huthwelker et al. 2023, Human Movement Science, 201 walkers at 5 km/h: the
# mid-thorax furthest right at 97-0 %, left at 47 %; Ceccato et al. 2009, PLoS ONE: the shoulder line
# 10 degrees through, turning back just before heel on), the tilt furthest at the other foot's toe-off,
# 11 % after heel strike (Ceccato: shoulders 4 degrees through; Chung et al. 2010, Gait & Posture:
# 3.1-3.5), and the thorax leaning furthest forward just before each heel strike, twice a stride
# (Ceccato: 3 +- 1 degrees, at 18 % and 67 % of a cycle whose heel strikes fall at 21 % and 71 %).
# Sneaking is walking's, smaller: no study measures it.
RUN_FLEXION = (3.75, 5.5, 7.5, 8.75, 8.25, 6.25, 3.75, 2.6, 2.25, 2.25)      # degrees forward, both halves alike
RUN_TILT = (2.65, 3.8, 4.05, 3.55, 2.65, 1.65, 0.5, -0.55, -1.3, -1.9)       # degrees toward the right leg; mirrored
RUN_TURN = (11.0, 10.25, 7.5, 2.5, -3.5, -9.0, -11.75, -12.0, -11.65, -11.25)  # degrees to the right (left shoulder forward); mirrored
LUMBAR_MOST = 8.0       # degrees the lower back bends sideways by at most to keep the neck centred (Preece et al. 2016: 16 through)
STEADY_SPINE = 1.0      # share of the hips' tilt and twist the lower spine takes out, on walks, runs and sneaks
HARMONICS = 4           # a stride's motion as so many harmonics of it: smooth, the keys' kinks left out
ARM_SMOOTH_HARMONICS = 6  # the path the arms' spring follows, likewise
TORSO_LEAN = 'walk=3, run=8, sneak=3'  # degrees: the least a walk, run or sneak leans forward, motion and all
HEAD_STEADY = 0.7       # without --steady-head: share of the torso's motion the head takes back, keeping its gaze
IDLE_MOVES = 'all'      # stances whose missing walks, runs, turns and jump are made from their idle
IDLE_SNEAK = '2w, 2c, 1t'  # stances whose sneaks are made from their idle
IDLE_LEAN = 1.0         # share of the third person's lean (a sneak's crouch, a run's) moves made from an idle take
BREATHING = 3.0         # degrees the chest turns up by at a full breath in an idle
BREATH_SECONDS = 4.0    # about how long a breath takes: an idle's loop gets as many as fit it best
BREATH_SKEW = 0.4       # breathing in takes less of the breath than breathing out: 0.4 of it
SHRUG = 1.5             # the shoulders lift by this many times what the chest turns
PLANT_ATTACKS = True    # attacks keep the actor in place: their root travel goes on the pelvis
HELD_MOTION = 0.1       # share of a walk's torso motion on the lower spine, which an attack held over it rides
ARM_FACING = 0.0        # share of the way the arms face that they keep while a walk's torso moves under them
FACE_FORWARD = 0.9      # share of a walk's average hip turn (a strafe's) its lower spine turns back to the stance's
MAX_TWIST = 45.0        # degrees the shoulders turn against the hips before the hips turn with them (0: never)
TWIST_SOFTNESS = 12.0   # degrees: how gradually the hips' share of the twist grows around MAX_TWIST
TWIST_SMOOTH = 0.05     # seconds: the hips' turn is smoothed over about this much either way
SPLIT_FOLLOWS = True    # attacks whose follow-throughs share one recovery get one of their own each
START_FROM_IDLE = True  # attacks start on their stance idle's first frame
START_MOST = 0.1        # seconds at most - a third of the wind-up to "min attack" at most - they ease out of it
ALIGN_TO_THIRD = 'throwweapon'  # groups whose files sit where the third person has them on the timeline
STRAIGHT_STARTS = True  # a walk's lead-in and tail move the actor only the way its loop goes
SETTLE = 0.2            # seconds at most - a third of it at most - of an attack's follow-through or tail crossfaded into its idle
ALIASES = []            # [(the set's own stance name, the engine's)]: --alias
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


def node_names(nif):
    """The names of a .nif's NiNodes - a skeleton's bones. Found by each NiNode block's start (its type
    name, then its own name) rather than by reading every block: skeletons hold properties and shapes
    there is no reader for here."""
    tag = struct.pack('<I', len('NiNode')) + b'NiNode'
    out = set()
    at = nif.find(tag)
    while at >= 0:
        size, = struct.unpack_from('<I', nif, at + len(tag))
        out.add(nif[at + len(tag) + 4:at + len(tag) + 4 + size].decode('latin-1'))
        at = nif.find(tag, at + 1)
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


# ---- aliases -------------------------------------------------------------------------------------
# A set can name a stance of its own that plays where the engine plays one of its - a mod's katar
# moveset over hand-to-hand ("katar=hh"). Its groups are read under the engine's names (katar ->
# handtohand, kataralt -> handtohandalt, idlekatar -> idlehh), so they pair, and take every setting,
# as that stance's do, and are written back under their own.

LONG_OF = {}
for _long, _short in LONG_GROUPS.items():
    LONG_OF.setdefault(_short, _long)


def aliased(group, back=False):
    """A group's name with --alias applied: the set's stance to the engine's or, back, the other way."""
    for ours, short in ALIASES:
        src_long, dst_long = (LONG_OF.get(short, short), ours) if back else (ours, LONG_OF.get(short, short))
        src, dst = (short, ours) if back else (ours, short)
        if group.startswith(src_long):
            return dst_long + group[len(src_long):]
        for base in BASES:
            if group.startswith(base + src):
                return base + dst + group[len(base) + len(src):]
        for turn in TURNS:
            if group == src + turn:
                return dst + turn
    return group


def aliased_line(line, back=False):
    group, colon, key = line.partition(':')
    if not colon or not ALIASES:
        return line
    name = group.strip().lower()
    new = aliased(name, back)
    return line if new == name else new + colon + key


def alias_text_keys(kf, back=False):
    """Renames a kf's groups in its text keys, in place, with --alias."""
    if not ALIASES:
        return
    tk = kf.blocks[kf.textkey_block][1]
    tk['keys'] = [(t, '\r\n'.join(aliased_line(line, back) for line in text.replace('\r\n', '\n').split('\n')))
                  for t, text in tk['keys']]


def own_stance(stance):
    """The set's own name for a stance, where --alias gives it one."""
    for ours, short in ALIASES:
        if stance == short:
            return ours
    return stance


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


FOLLOW_SIZES = ('small', 'medium', 'large')


def nested_follows(kf):
    """[(group as spelled, section, start, {size: stop})] of the attack sections whose follow-throughs
    start together and stop apart - one recovery, the weaker ones cut short (ReAnimation's)."""
    out = []
    lines = text_lines(kf)
    for group, keys in group_keys(lines).items():
        if not is_attack(group):
            continue
        spelled = next(line.partition(':')[0].strip() for _, line in lines if split_line(line)[0] == group)
        for section in sorted({k.split()[0] for k in keys if k.endswith('follow start')}):
            starts = [keys.get('%s %s follow start' % (section, size)) for size in FOLLOW_SIZES]
            stops = {size: keys.get('%s %s follow stop' % (section, size)) for size in FOLLOW_SIZES}
            if None in starts or None in stops.values() or max(starts) - min(starts) > 0.01:
                continue
            if max(stops.values()) - min(stops.values()) < 1e-3:
                continue
            out.append((spelled, section, max(starts), stops))
    return out


def linearized(kf, end):
    """Every track of a kf as plain linear keys - at its own key times and 60 times a second - so parts
    of it can be copied elsewhere on the timeline: quadratic and Euler keys cannot be cut and moved as
    they are. {bone: (rotation keys, translation keys, scale keys)} as (time, value) lists."""
    grid = [end * i / max(1, int(end * 60)) for i in range(max(1, int(end * 60)) + 1)]
    out = {}
    for bone in kf.bone_data:
        d = kf.data(bone)
        own = {k[0] for k in d.quat_keys + d.trans['keys'] + d.scale['keys']}
        for g in d.xyz or ():
            own |= {k[0] for k in g['keys']}
        times = sorted(own | set(grid))
        rot = [(t, E.rotation(d, t)) for t in times] if (d.quat_keys or d.xyz) else []
        trans = [(t, E.translation(d, t)) for t in times] if d.trans['keys'] else []
        scale = [(t, E._interp_group(d.scale['keys'], d.scale['itype'], t, 1)) for t in times] if d.scale['keys'] else []
        out[bone] = (times, rot, trans, scale)
    return out


def split_follows(kf):
    """Gives each follow-through of an attack section its own recovery, as the game's own attacks have
    them: ReAnimation's start their three together and cut the weaker ones short, so a quick attack
    stopped mid-recovery, 60 to 90 degrees from the idle the game goes back to - and from where the next
    attack starts. The strongest stays where it is; each other one becomes the whole recovery played
    faster, in the time it had - as the game's own quick follow-throughs are - put at the end of the
    file, one after another, its keys moved there. So each ends where the strongest does: on the idle
    (`settle`) - or, where ReAnimation plays a tail after it, where the tail takes up. Returns what it
    split."""
    plans = nested_follows(kf)
    if not plans:
        return []
    tk = kf.blocks[kf.textkey_block][1]
    end = max([t for t, _ in tk['keys']] + [k[0] for b in kf.bone_data for k in
               kf.data(b).quat_keys + kf.data(b).trans['keys'] + kf.data(b).scale['keys']])
    tracks = linearized(kf, end)
    moves = {}  # (group, key) -> new time
    copies = []  # (from, to, at)
    at = end + GAP
    for group, section, start, stops in plans:
        strongest = max(stops, key=stops.get)
        for size in sorted(stops, key=stops.get, reverse=True):
            if size == strongest:
                continue
            copies.append((start, stops[strongest], at, stops[size] - start))
            moves[(group.lower(), '%s %s follow start' % (section, size))] = at
            moves[(group.lower(), '%s %s follow stop' % (section, size))] = at + stops[size] - start
            at += stops[size] - start + GAP
    by_time = {}
    for t, text in tk['keys']:
        for line in text.replace('\r\n', '\n').split('\n'):
            g, k = split_line(line)
            moved = moves.get((g, k)) if g else None
            by_time.setdefault(round(moved if moved is not None else t, 6), []).append(line)
    tk['keys'] = [(t, '\r\n'.join(lines)) for t, lines in sorted(by_time.items())]
    for bone, (times, rot, trans, scale) in tracks.items():
        d = kf.data(bone)
        for keys, attr in ((rot, 'rot'), (trans, 'trans'), (scale, 'scale')):
            if not keys:
                continue
            values = dict(keys)
            out = list(keys)
            for a, b, where, length in copies:
                span = sorted({t for t in times if a - 1e-6 <= t <= b + 1e-6} | {a, b})
                lookup = (lambda t: E.rotation(d, t)) if attr == 'rot' else (lambda t: E.translation(d, t)) \
                    if attr == 'trans' else (lambda t: E._interp_group(d.scale['keys'], d.scale['itype'], t, 1))
                pace = length / (b - a) if b > a else 1.0
                out += [(where + (t - a) * pace, values[t] if t in values else lookup(t)) for t in span]
            if attr == 'rot':
                d.rot_type, d.xyz = 1, None
                d.quat_keys = [(t, tuple(v), ()) for t, v in out]
            elif attr == 'trans':
                d.trans = {'itype': 1, 'keys': [(t, tuple(v), ()) for t, v in out]}
            else:
                d.scale = {'itype': 1, 'keys': [(t, v, ()) for t, v in out]}
    for t, p in kf.blocks:
        if t == 'NiKeyframeController':
            p['stop'] = at - GAP
    return ['%s %s' % (group, section) for group, section, _, _ in plans]


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
        # The lower spine, where every animation of the stance holds it (hold_spine) or faces it (a walk's,
        # move_torso): what plays on the upper body over another animation then sits on it as on its own.
        self.spine = mean_rotation([E.world(kf, SPINE, t)[0] for t in times])
        self.chest_local = mean_rotation([E.rotation(kf.data(CHEST), t) for t in times])
        self.torso = {b: mean_rotation([E.rotation(kf.data(b), t) for t in times]) for b in TORSO}
        self.arms = {b: mean_rotation([E.rotation(kf.data(b), t) for t in times])
                     for b in kf.bone_data if is_arm(b) and (kf.data(b).quat_keys or kf.data(b).xyz)}
        yaws = [shoulder_yaw(kf, t, lateral) for t in times]
        self.yaw = sum(yaws) / len(yaws)
        self.square = E.axis_quat(-self.yaw, (0.0, 0.0, 1.0))
        self.forward = E.qmul(self.square, self.chest)
        self.neck = E.qmul(E.qmul(self.forward, self.torso['Bip01 Spine2']), self.torso[NECK])
        self.head_ahead = None
        if HEAD in kf.bone_data:
            self.head_ahead = looking_ahead(mean_rotation([E.world(kf, HEAD, t)[0] for t in times]))
        self.label = '%s (%s)' % (group, source_name(source))


def frame_quat(x, y, z):
    """The rotation taking the axes X, Y, Z to the orthonormal directions x, y, z."""
    m = [[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]]
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        k = 0.5 / math.sqrt(trace + 1.0)
        q = (0.25 / k, (m[2][1] - m[1][2]) * k, (m[0][2] - m[2][0]) * k, (m[1][0] - m[0][1]) * k)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        k = 2.0 * math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2])
        q = ((m[2][1] - m[1][2]) / k, 0.25 * k, (m[0][1] + m[1][0]) / k, (m[0][2] + m[2][0]) / k)
    elif m[1][1] > m[2][2]:
        k = 2.0 * math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2])
        q = ((m[0][2] - m[2][0]) / k, (m[0][1] + m[1][0]) / k, 0.25 * k, (m[1][2] + m[2][1]) / k)
    else:
        k = 2.0 * math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1])
        q = ((m[1][0] - m[0][1]) / k, (m[0][2] + m[2][0]) / k, (m[1][2] + m[2][1]) / k, 0.25 * k)
    return E.qnorm(q)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def looking_ahead(head):
    """A head's rotation in the character's frame turned to look straight ahead, upright, at the angle
    below level it looked at: the head bone's own axis nearest forward (its face) put forward, the one
    nearest up kept in the upright plane - no turn to a side, no tilt. From a third-person idle, which
    looks ahead, so whatever way a skeleton's head bone is set up, its face is found."""
    signed = [tuple(sign * (1.0 if i == j else 0.0) for j in range(3)) for i in range(3) for sign in (1.0, -1.0)]
    face = max(signed, key=lambda a: E.qrot(head, a)[1])
    up = max([a for a in signed if abs(sum(x * y for x, y in zip(a, face))) < 0.5], key=lambda a: E.qrot(head, a)[2])
    looks = E.qrot(head, face)
    down = math.atan2(-looks[2], math.hypot(looks[0], looks[1]))
    face_to = (0.0, math.cos(down), -math.sin(down))
    up_to = (0.0, math.sin(down), math.cos(down))
    side, side_to = cross(face, up), cross(face_to, up_to)
    # local -> world = (face, up, side -> face_to, up_to, side_to): the target frame after the inverse
    # of the local one, whose axes are the coordinate axes signed, so its inverse is its transpose.
    target = frame_quat(*[tuple(face_to[k] * face[i] + up_to[k] * up[i] + side_to[k] * side[i] for k in range(3))
                          for i in range(3)])
    return target


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
        # The upper body, for moves made from the idle: the chest in the character's frame, the rest on it.
        'chest': mean_rotation([E.world(kf, CHEST, t)[0] for t in times]),
        'torso': {b: mean_rotation([E.rotation(kf.data(b), t) for t in times]) for b in TORSO
                  if b in kf.bone_data and (kf.data(b).quat_keys or kf.data(b).xyz)},
        'span': (times[0], times[-1]),
    }


def forward_lean(base, top):
    """How far the line from base to top leans forward from upright (radians, back is negative), in
    the character's frame: forward +Y, up +Z."""
    return math.atan2(top[1] - base[1], top[2] - base[2])


def third_lean(kf, start, stop):
    """A third-person animation's torso lean over a stretch of it, on average: the line from the
    chest's base to the neck, forward from upright."""
    leans = [forward_lean(E.world(kf, CHEST, t)[1], E.world(kf, NECK, t)[1]) for t in span(start, stop)]
    return sum(leans) / len(leans)


# ---- building -------------------------------------------------------------------------------------

class Segment:
    """One group's stretch of an output file.

    source: the third-person Source it takes its body and text keys from, over v_start..v_stop, with
    its loop (loop_start..loop_stop) repeated `loops` times. first_time(tau): when in the first-person
    animation its arms come from; without one, the first person's idle arms as they are on average
    (idle_arms), moved as the third person's arms move from its idle with arm_swing.
    keep: the keep-forward share, toward `posture`; natural_chest 'own', or 'idle' for a walk the game
    shows with the idle's upper body on top. repoint: the share of the arms' first-person direction
    kept. lower_by, bounce, grip: see lower_raised_arms, bounce_arms. Following the first person with
    no first_time (a move made from its idle), the upper body is the idle's as it is on average
    (idle_arms) too. lean: radians the torso is leaned forward by, the arms and head keeping the way
    they point (lean_torso); motion, nod, least_lean: see move_torso; breathe, breath_span: see breathe."""

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
        self.bounce_real_time = False  # the bounce in the loop's own time (bounce_arms)
        self.motion = 0.0       # the torso's motion on a walk (move_torso), as a share
        self.nod = 0.0          # degrees it folds forward by through each step
        self.swing = 0.0        # degrees the thorax turns through with the stride, shoulder against leg
        self.stance_lean = 0.0  # degrees it tilts through, toward the standing leg
        self.gait = 'walk'      # whose measured thorax motion it takes: 'walk' or 'run'
        self.least_lean = None  # degrees the torso leans forward at least, bounce and all
        self.lean = 0.0         # radians the torso is leaned forward by
        self.breathe = 0.0      # degrees the chest turns up by at a full breath
        self.breath_span = None  # (start, stop): the output times an idle breathes over
        self.settle = []        # [(start, stop)]: output times crossfaded into settle_to, an idle's first frame
        self.facing = None      # the standing stance idle's lower spine: where every lower spine of the stance faces
        self.settle_in = []     # [(start, stop)]: output times eased out of settle_to, an idle's first frame
        self.settle_onto = []   # [(start, stop, there)]: output times crossfaded into the pose at there
        self.cuts = []          # output times where its sections and follow-throughs start (smooth_within)
        self.windups = []       # [(start, min attack)] output times of its attack sections
        self.plant = []         # [(start, stop)]: sections whose root travel goes on the pelvis (plant_root)
        self.settle_to = None
        self.grip = False       # a two-handed hold: only the right arm bounces, the left hand kept on it
        self.follow = False     # the upper body is the first person's, not the third person's held forward
        self.sway_about = None  # following on a walk: the third person's spine, on average, whose sway goes on top
        self.head_forward = None  # following: the head held looking straight ahead this way, not turning
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


def bounce_arms(seg, taus, samples, strength, real_time=False):
    """Experimental. The elbows and wrists lag and spring back as the body under them moves: a point
    on a spring and damper at each, following where the animation puts it - the way Blender's
    Wiggle 2 add-on moves bones - run over the loop until it settles into a cycle of its own. That
    cycle is kept, so it loops; the lead-in and tail fade it in and out. `strength` is the share of
    it used. On a two-handed grip (seg.grip) only the right arm, which holds the weapon, springs; the
    left then reaches after it so the left hand stays where it was on the weapon (keep_grip).

    `real_time` steps it through the loop's own time. Without it - as sets were built before it, and
    still are unless asked - each sample is stepped as a frame; but every key time of the third
    person's legs is a sample too, three or four to a frame on a forward walk or run, which the spring
    then sees slowed that many times over and hardly lags behind."""
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
    if real_time:
        # In the loop's own time, on an even grid, which its samples are not.
        steps = max(1, int(round(span_time * FPS * BOUNCE_SUBSTEPS)))
        step = span_time / steps
    else:
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
        # Followed smoothed - the walk's harmonics, its keys' kinks left out - so they do not kick the spring.
        rel = [taus[i] - taus[inside[0]] for i in cycle]
        smooth = [[loop_series(rel, [g[joint][axis] for g in goals], span_time, ARM_SMOOTH_HARMONICS)
                   for axis in range(3)] for joint in range(3)]
        if real_time:
            grid = [tuple(tuple(smooth[joint][axis](k * step) for axis in range(3)) for joint in range(3))
                    for k in range(steps)]
            upper_len = math.dist(grid[0][0], grid[0][1])
            fore_len = math.dist(grid[0][1], grid[0][2])
            elbow, wrist = list(grid[0][1]), list(grid[0][2])
            elbow_prev, wrist_prev = elbow[:], wrist[:]
            states = []  # the last lap's (elbow, wrist) after each step: states[k] is at (k + 1) * step
            for lap in range(BOUNCE_LAPS):
                for shoulder, g_elbow, g_wrist in grid:
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
                        states.append((tuple(elbow), tuple(wrist)))
            kept = {}
            for i, t in zip(cycle, rel):
                # Read back at each sample's own time, between the two steps either side of it.
                x = t / step
                m = int(math.floor(x))
                f = x - m
                before, after = states[(m - 1) % steps], states[m % steps]
                kept[i] = (tuple(lerp(before[0], after[0], f)), tuple(lerp(before[1], after[1], f)))
        else:
            goals = [tuple(tuple(smooth[joint][axis](t) for axis in range(3)) for joint in range(3)) for t in rel]
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


UPPER_SPINE = 'Bip01 Spine2'
LATERAL, FORWARD, UP = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)  # the character's frame


def turn_torso(body_pose, arm_pose, turn, head_keeps=0.0, arms_keep=0.0, bend=0.5, at=CHEST):
    """Turns the upper body by `turn`, a rotation in the character's frame. About the chest's base:
    the chest by the share `bend` of it and the spine bone above it by the rest - a half each bends
    it, all of it at the chest tips it as one. Or `at` SPINE: all of it at the lower spine, the top
    bone of the lower body, so whatever the game plays on the upper body over this - an attack held
    while running - turns with it too. The head and the clavicles - the arms - go with it, but for the
    share given of the way back to where they were facing: 1.0 keeps the gaze, or the way the arms
    point, and moves them only with the shoulders. Both arms kept, hands holding one weapon stay on it."""
    path = ('Bip01', 'Bip01 Pelvis', SPINE, CHEST, UPPER_SPINE, NECK)
    if any(body_pose.get(b, (None, None))[0] is None for b in (SPINE, CHEST, UPPER_SPINE, NECK)):
        return
    shares = {SPINE: 1.0} if at == SPINE else {CHEST: bend, UPPER_SPINE: 1.0 - bend}
    old, new, rot, done = {}, {}, IDENTITY, 0.0
    for bone in path:
        r = body_pose.get(bone, (None, None))[0]
        if r is not None:
            rot = E.qmul(rot, r)
        old[bone] = rot
        done += shares.get(bone, 0.0)
        new[bone] = E.qmul(E.qslerp(IDENTITY, turn, done), rot) if done > 0 else rot
    for parent, bone in zip(path[1:], path[2:]):
        body_pose[bone] = (E.qmul(E.qconj(new[parent]), new[bone]), body_pose[bone][1])
    hung = [(HEAD, body_pose, head_keeps)] + [('Bip01 %s Clavicle' % side, arm_pose, arms_keep) for side in 'LR']
    for bone, pose, keeps in hung:
        if pose.get(bone, (None, None))[0] is None:
            continue
        was = E.qmul(old[NECK], pose[bone][0])
        pose[bone] = (E.qmul(E.qconj(new[NECK]), E.qslerp(E.qmul(turn, was), was, keeps)), pose[bone][1])


def place_spine(body_pose, place, bone=SPINE, above=CHEST):
    """Turns a spine bone - the lower spine, the top bone of the lower body, unless told otherwise - to
    `place(its rotation in the character's frame)`, the bone above keeping its own rotation. The legs
    hang off the lower spine: keep_legs turns them back."""
    path = ('Bip01', 'Bip01 Pelvis', SPINE, CHEST, UPPER_SPINE)
    below = path[:path.index(bone)]
    if any(body_pose.get(b, (None, None))[0] is None for b in below[1:] + (bone, above)):
        return
    base = IDENTITY
    for b in below:
        r = body_pose.get(b, (None, None))[0]
        if r is not None:
            base = E.qmul(base, r)
    turned = E.qmul(base, body_pose[bone][0])
    kept = E.qmul(turned, body_pose[above][0])
    placed = place(turned)
    body_pose[bone] = (E.qmul(E.qconj(base), placed), body_pose[bone][1])
    body_pose[above] = (E.qmul(E.qconj(placed), kept), body_pose[above][1])


def keep_legs(body_pose, spine_was):
    """The thighs and a beast's tail - which hang off the lower spine - turned back under it wherever it
    was turned from `spine_was` (its rotation and offset as the third person has them), so the legs
    and tail stay exactly where the third person put them."""
    rot, trans = body_pose.get(SPINE, (None, None))
    if rot is None or spine_was[0] is None:
        return
    back = E.qmul(E.qconj(rot), spine_was[0])
    shift = (0.0, 0.0, 0.0)
    if trans is not None and spine_was[1] is not None:
        shift = E.qrot(E.qconj(rot), [a - b for a, b in zip(spine_was[1], trans)])
    for bone in LEG_ROOTS:
        r, t = body_pose.get(bone, (None, None))
        if r is None:
            continue
        body_pose[bone] = (E.qmul(back, r), tuple(a + b for a, b in zip(shift, E.qrot(back, t))) if t is not None else t)


def steady_spine(body_pose, toward, share):
    """Turns the lower spine `share` of the way to the rotation `toward` in the character's frame,
    the chest keeping its own: whatever plays on the upper body over it no longer rides the hips'
    tilt and twist."""
    place_spine(body_pose, lambda spine: E.qslerp(spine, toward, share))


def chain_worlds(pose, path):
    """{bone: (rotation, position)} in the character's frame along a path of bones down from the root."""
    rot, pos, out = IDENTITY, (0.0, 0.0, 0.0), {}
    for bone in path:
        r, t = pose.get(bone, (None, None))
        if t is not None:
            pos = tuple(p + c for p, c in zip(pos, E.qrot(rot, t)))
        if r is not None:
            rot = E.qmul(rot, r)
        out[bone] = (rot, pos)
    return out


def unit_vec(v):
    size = math.sqrt(sum(c * c for c in v))
    return tuple(c / size for c in v) if size > 1e-9 else None


def flat_yaw(a, b):
    """The direction from a to b on the ground, in degrees."""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def twist_of(body_pose, arm_pose):
    """How far the shoulders turn against the hips, in degrees - the line between the shoulders on the
    ground against the line between the hip joints - or None."""
    pose = dict(body_pose)
    pose.update(arm_pose)
    needed = ('Bip01 Pelvis', SPINE, CHEST) + LEGS['L'] + LEGS['R'] + tuple(
        'Bip01 %s %s' % (s, b) for s in 'LR' for b in ('Clavicle', 'UpperArm'))
    if any(b not in pose or pose[b][0] is None or pose[b][1] is None for b in needed):
        return None
    shoulder = {s: chain_worlds(pose, TO_NECK + ('Bip01 %s Clavicle' % s, 'Bip01 %s UpperArm' % s)) for s in 'LR'}
    legs = {s: chain_worlds(pose, ('Bip01', 'Bip01 Pelvis', SPINE) + LEGS[s]) for s in 'LR'}
    hips = flat_yaw(legs['R']['Bip01 R Thigh'][1], legs['L']['Bip01 L Thigh'][1])
    shoulders = flat_yaw(shoulder['R']['Bip01 R UpperArm'][1], shoulder['L']['Bip01 L UpperArm'][1])
    return (shoulders - hips + 180.0) % 360.0 - 180.0


def hips_follow(twist, limit):
    """How far the hips turn after shoulders `twist` degrees round from them: nothing to speak of well
    short of `limit`, all of the twist past it, the share growing smoothly between (TWIST_SOFTNESS) - no
    point where the hips start following at a stroke. People twist only so far at the waist (a golf
    swing's, the most there is, is some 45 to 55 degrees) and turn the hips beyond that; a first-person
    torso, turned as far as its camera wants, on third-person hips that never meant to follow it, twists
    far past it - ReAnimation's spear chops over 110 degrees."""
    k = TWIST_SOFTNESS
    turn = lambda x: k * math.log1p(math.exp((x - limit) / k))  # noqa: E731
    return math.copysign(max(0.0, turn(abs(twist)) - turn(0.0)), twist)


def smooth_within(times, values, cuts, width):
    """`values` at `times` smoothed by a Gaussian of `width` seconds, never across a time in `cuts` -
    where a section, or a follow-through, starts afresh."""
    out = []
    for t, v in zip(times, values):
        lo = max([c for c in cuts if c <= t + 1e-6], default=-1e9)
        hi = min([c for c in cuts if c > t + 1e-6], default=1e9)
        num = den = 0.0
        for u, w in zip(times, values):
            if lo - 1e-6 <= u < hi - 1e-6 and abs(u - t) < 3 * width:
                g = math.exp(-0.5 * ((u - t) / width) ** 2)
                num += g * w
                den += g
        out.append(num / den if den > 0 else v)
    return out


def turn_hips(body_pose, arm_pose, degrees):
    """Turns the hips `degrees` about the upright through the pelvis, toward the shoulders (hips_follow
    says how far): the pelvis, the hip joints and a beast's tail with it, the legs bending to keep the
    feet where they were, the knees turning half as far. The lower spine - and the chest on it - stays
    where it is (hold_spine put it): the hip joints hang off it in Morrowind's skeletons and are moved on
    it. Turning it, an attack held over a run, which plays from the chest up on the run's lower spine,
    would face off by as much. Whether it turned anything."""
    pose = dict(body_pose)
    pose.update(arm_pose)
    needed = ('Bip01 Pelvis', SPINE, CHEST) + LEGS['L'] + LEGS['R'] + tuple(
        'Bip01 %s %s' % (s, b) for s in 'LR' for b in ('Clavicle', 'UpperArm'))
    if any(b not in pose or pose[b][0] is None or pose[b][1] is None for b in needed):
        return False
    legs = {s: chain_worlds(pose, ('Bip01', 'Bip01 Pelvis', SPINE) + LEGS[s]) for s in 'LR'}
    if abs(degrees) < 0.01:
        return False
    turn = E.axis_quat(math.radians(degrees), UP)
    root = legs['L']['Bip01'][0]
    pelvis_rot, pelvis_pos = legs['L']['Bip01 Pelvis']
    spine_rot, spine_pos = legs['L'][SPINE]

    def about_hips(p):
        return tuple(a + b for a, b in zip(pelvis_pos, E.qrot(turn, [x - y for x, y in zip(p, pelvis_pos)])))

    def on_spine(p):
        return tuple(E.qrot(E.qconj(spine_rot), [x - y for x, y in zip(p, spine_pos)]))
    new_pelvis = E.qmul(turn, pelvis_rot)
    body_pose['Bip01 Pelvis'] = (E.qmul(E.qconj(root), new_pelvis), body_pose['Bip01 Pelvis'][1])
    body_pose[SPINE] = (E.qmul(E.qconj(new_pelvis), spine_rot),
                        E.qrot(E.qconj(new_pelvis), [x - y for x, y in zip(spine_pos, pelvis_pos)]))
    tail = body_pose.get('Bip01 Tail', (None, None))
    if tail[0] is not None and tail[1] is not None:
        t_rot = E.qmul(spine_rot, tail[0])
        t_pos = tuple(a + b for a, b in zip(spine_pos, E.qrot(spine_rot, tail[1])))
        body_pose['Bip01 Tail'] = (E.qmul(E.qconj(spine_rot), E.qmul(turn, t_rot)), on_spine(about_hips(t_pos)))
    knee_turn = E.qslerp(IDENTITY, turn, 0.5)
    for side in 'LR':
        thigh, calf, foot = LEGS[side]
        (t_rot, hip), (c_rot, knee), (f_rot, ankle) = legs[side][thigh], legs[side][calf], legs[side][foot]
        new_hip = about_hips(hip)
        upper, lower = math.dist(hip, knee), math.dist(knee, ankle)
        normal = unit_vec(cross([a - b for a, b in zip(knee, hip)], [a - b for a, b in zip(ankle, knee)]))
        axis = unit_vec([a - b for a, b in zip(ankle, new_hip)])
        if normal is None or axis is None or upper < 1e-6 or lower < 1e-6:
            continue
        # The knee's hinge, turned half as far as the hips, square to the new line from hip to ankle.
        bent = E.qrot(knee_turn, normal)
        new_normal = unit_vec([a - axis[i] * sum(x * y for x, y in zip(bent, axis)) for i, a in enumerate(bent)])
        if new_normal is None:
            continue
        reach = max(abs(upper - lower) + 1e-4, min(upper + lower - 1e-4, math.dist(ankle, new_hip)))
        along = (upper * upper - lower * lower + reach * reach) / (2 * reach)
        out = math.sqrt(max(0.0, upper * upper - along * along))
        side_dir = cross(axis, new_normal)  # in the bend plane, square to the hip-ankle line, the way the knee goes
        new_knee = tuple(h + axis[i] * along + side_dir[i] * out for i, h in enumerate(new_hip))
        # Each bone turned so its direction and the hinge go where the new ones are: the knee stays a hinge.

        def moved(old_from, old_to, new_from, new_to):
            d0, d1 = unit_vec([a - b for a, b in zip(old_to, old_from)]), unit_vec([a - b for a, b in zip(new_to, new_from)])
            f0 = frame_quat(d0, normal, cross(d0, normal))
            f1 = frame_quat(d1, new_normal, cross(d1, new_normal))
            return E.qmul(f1, E.qconj(f0))
        new_t = E.qmul(moved(hip, knee, new_hip, new_knee), t_rot)
        new_c = E.qmul(moved(knee, ankle, new_knee, ankle), c_rot)
        body_pose[thigh] = (E.qmul(E.qconj(spine_rot), new_t), on_spine(new_hip))
        body_pose[calf] = (E.qmul(E.qconj(new_t), new_c), body_pose[calf][1])
        body_pose[foot] = (E.qmul(E.qconj(new_c), f_rot), body_pose[foot][1])
    return True


def hold_spine(body_pose, toward, share):
    """The lower spine turned `share` of the way to `toward` - the stance idle's, in the character's
    frame - the chest keeping its own rotation and the legs theirs (keep_legs): so every animation of a
    stance plays its chest up on one lower spine, and what plays from the chest up over another of
    them - an attack held while running or turning - sits there as it does on its own."""
    was = body_pose.get(SPINE, (None, None))
    steady_spine(body_pose, toward, share)
    keep_legs(body_pose, was)


def facing_forward(rotation, toward, share):
    """`rotation` turned about the upright by `share` of its turn away from `toward`'s."""
    rel = E.qmul(rotation, E.qconj(toward))
    if rel[0] < 0:
        rel = tuple(-c for c in rel)  # the same rotation, the short way round
    # The turn about the upright in it (swing-twist): taken off first, it leaves a lean - a sneak's crouch -
    # about the axis it leans by from `toward`, so what is held over it leans that way but keeps its heading.
    angle = 2.0 * math.atan2(rel[3], rel[0])
    return E.qmul(E.axis_quat(-share * angle, UP), rotation)


def splice_rotations(data, offset, taus, samples, changed, bones):
    """The rotation keys of `bones` - copied as the third person keys them - replaced by the samples'
    over each run of changed samples, from the unchanged sample before it to the one after; their own
    keys, and every translation, kept everywhere else."""
    runs, i = [], 0
    while i < len(taus):
        if changed[i]:
            j = i
            while j + 1 < len(taus) and changed[j + 1]:
                j += 1
            runs.append((max(0, i - 1), min(len(taus) - 1, j + 1)))
            i = j + 1
        else:
            i += 1
    for bone in bones:
        keys = data[bone].quat_keys
        for a, b in runs:
            t0, t1 = offset + taus[a], offset + taus[b]
            keys[:] = [k for k in keys if not t0 - KEY_TIME_EPS <= k[0] <= t1 + KEY_TIME_EPS]
            keys += [(offset + taus[k], E.qnorm(samples[k][0][bone][0]), ()) for k in range(a, b + 1)
                     if samples[k][0].get(bone, (None, None))[0] is not None]
        keys.sort(key=lambda k: k[0])


def straighten_ends(keys, seg):
    """A walk's lead-in and tail move the actor only the way its loop goes: the root's travel across
    that way is taken out of them - the root keys only; the body, drawn where the actor is, does as it
    did. Vanilla's two-handed strafes (and so Animation Compilation's) start with the root some 15 units
    forward of where their loop runs, and slide it back in the first steps: the actor stepped back 14
    units every time it started to strafe."""
    if seg.period <= 0 or not keys:
        return
    t0 = seg.offset + seg.lead
    t1 = t0 + seg.loops * seg.period
    a, a_next = key_value(keys, t0, False), key_value(keys, t0 + seg.period, False)
    b = key_value(keys, t1, False)
    way = unit_vec([a_next[0] - a[0], a_next[1] - a[1]])
    if way is None or a is None or b is None:
        return
    for i, (t, v, extra) in enumerate(keys):
        if seg.offset - KEY_TIME_EPS <= t < t0 - KEY_TIME_EPS:
            base = a
        elif t1 + KEY_TIME_EPS < t <= seg.offset + seg.length + KEY_TIME_EPS:
            base = b
        else:
            continue
        along = (v[0] - base[0]) * way[0] + (v[1] - base[1]) * way[1]
        keys[i] = (t, (base[0] + along * way[0], base[1] + along * way[1], v[2]), extra)


def bend_lumbar(body_pose, turn):
    """Bends the back by `turn` about the chest's base, the spine above keeping its own rotation: an
    S-bend that carries the upper body over to a side without tilting it. In the upper body, so what
    the game plays there over a move - an attack held while running - is not carried with it."""
    place_spine(body_pose, lambda spine: E.qmul(turn, spine), CHEST, UPPER_SPINE)


def lean_torso(samples, lean):
    """Leans the torso forward by `lean` radians throughout, as one from the chest's base - so the line
    from there to the neck leans that much more - the head keeping its gaze and the arms the way they
    point: a crouch's or a run's lean, under a first-person upper body held upright."""
    turn = E.axis_quat(-lean, LATERAL)
    for body_pose, arm_pose in samples:
        turn_torso(body_pose, arm_pose, turn, 1.0, 1.0, bend=1.0)


def bone_heads(body_pose, path, drift=(0.0, 0.0, 0.0)):
    """{bone: where it starts} along a path of bones down from the root, root drift taken out."""
    rot, pos, at = IDENTITY, (0.0, 0.0, 0.0), {}
    for bone in path:
        r, t = body_pose.get(bone, (None, None))
        if t is not None:
            if bone == 'Bip01':
                t = tuple(a - b for a, b in zip(t, drift))
            pos = tuple(p + c for p, c in zip(pos, E.qrot(rot, t)))
        at[bone] = pos
        if r is not None:
            rot = E.qmul(rot, r)
    return at


def torso_points(body_pose, drift=(0.0, 0.0, 0.0)):
    """Where the chest's base and the neck are, root drift taken out."""
    at = bone_heads(body_pose, TO_NECK, drift)
    return at[CHEST], at[NECK]


def loop_series(times, values, period, harmonics):
    """A looping signal as a function of time: its Fourier series up to `harmonics` times a loop, from
    samples at `times` - from the loop's start, the first at 0, unevenly spaced as they may be. Smooth
    and looping by construction: what a stride does, without the kinks a set's keys put in it
    (Animation Compilation's walks push the root on unevenly from one key to the next)."""
    pts = sorted(zip(times, values))
    pts.append((period, pts[0][1]))
    w = 2 * math.pi / period
    coeffs = []
    for k in range(harmonics + 1):
        a = b = 0.0
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            dt = t1 - t0
            a += 0.5 * (v0 * math.cos(k * w * t0) + v1 * math.cos(k * w * t1)) * dt
            b += 0.5 * (v0 * math.sin(k * w * t0) + v1 * math.sin(k * w * t1)) * dt
        scale = 1.0 / period if k == 0 else 2.0 / period
        coeffs.append((a * scale, b * scale))

    def series(t):
        return coeffs[0][0] + sum(a * math.cos(k * w * t) + b * math.sin(k * w * t)
                                  for k, (a, b) in enumerate(coeffs) if k)
    series.mean = coeffs[0][0]
    return series


def stride_shape(first_half, mirrored):
    """A stride's curve from its first half, read every 5 %: the second half the same (mirrored False:
    each step alike) or opposite (True: toward the other leg) - as a smooth looping function of the
    stride's phase, 0 to 1 from right foot strike."""
    values = list(first_half) + [(-v if mirrored else v) for v in first_half]
    return loop_series([k / 20.0 for k in range(20)], values, 1.0, 6)


GAIT_SHAPES = {
    # (forward flexion, 0..1 through the step; tilt toward the right leg and turn to the right, -1..1)
    'run': (stride_shape([(v - 2.25) / 6.5 for v in RUN_FLEXION], False),
            stride_shape([v / 4.05 for v in RUN_TILT], True),
            stride_shape([v / 12.0 for v in RUN_TURN], True)),
    'walk': (lambda p: 0.5 + 0.5 * math.cos(4 * math.pi * (p + 0.03)),
             lambda p: math.cos(2 * math.pi * (p - 0.11)),
             lambda p: math.cos(2 * math.pi * (p + 0.03))),
}


def stride_phase(seg, taus, samples, cycle, rel, period, drift):
    """Where in its stride a walk's loop is, as a function of time from the loop's start: 0 at the
    right foot's strike, 0.5 at the left's - from the third person's footstep keys ('SoundGen: Right'
    and 'Left', as sets key them where a foot comes down), each half of the stride paced to its own
    length. A strafe often keys one foot only: the other then strikes half a loop later. With none,
    the right foot strikes where it is furthest ahead."""
    strikes = {}
    for tm, line in seg.source.lines:
        group, key = split_line(line)
        if group == 'soundgen' and key in ('right', 'left') and key not in strikes \
                and seg.loop_start - 1e-6 <= tm < seg.loop_stop - 1e-6:
            strikes[key] = tm - seg.loop_start
    if 'right' not in strikes and 'left' in strikes:
        strikes['right'] = (strikes['left'] + period / 2) % period
    if 'right' not in strikes:
        path = lambda side: ('Bip01', 'Bip01 Pelvis', SPINE) + tuple('Bip01 %s %s' % (side, part) for part in ('Thigh', 'Calf', 'Foot'))  # noqa: E731
        ahead = [bone_heads(samples[i][0], path('R'), drift(i)).get('Bip01 R Foot', (0, 0, 0))[1]
                 - bone_heads(samples[i][0], path('L'), drift(i)).get('Bip01 L Foot', (0, 0, 0))[1] for i in cycle]
        strikes['right'] = rel[max(range(len(rel)), key=lambda k: ahead[k])]
    right = strikes['right']
    half = ((strikes['left'] - right) % period) if 'left' in strikes else period / 2
    if not 0.2 * period < half < 0.8 * period:
        half = period / 2

    def phase(t):
        into = (t - right) % period
        return 0.5 * into / half if into < half else 0.5 + 0.5 * (into - half) / (period - half)
    return phase


def move_torso(seg, taus, samples, neck_sway, steady, least_lean, held=0.0, face=0.0, arm_facing=0.0):
    """The torso's motion on a walk, run or sneak, made from what the legs under it do. A
    first-person walk holds the torso still, rigid on third-person legs; people's bodies move over
    their legs in patterns gait studies agree on:

    * The head is held steady in rotation and bobs up and down with the body (Pozzo et al. 1990,
      Hirasaki et al. 1999): --steady-head holds it; this leaves it riding on the neck.
    * Sway is damped from the pelvis up - the head moves least (Kavanagh et al. 2005): the neck keeps
      only `neck_sway` of the hips' side-to-side sway, the chest rolling against the rest, as the
      trunk's side benders counter the pelvis tilting (MacKinnon and Winter 1993).
    * The thorax pitches, tilts and turns against the room as GAIT_SHAPES has it - measured curves,
      running's and walking's (see there) - in step with the legs, from the third person's footstep
      keys: `seg.nod`, `seg.stance_lean` and `seg.swing` degrees through. The turn, which balances the
      legs swinging fore and aft, by as much of it as the walk goes forward or back, not to the side.

    All of it from the chest up - the upper body, which the game replaces with whatever it plays
    there over a move: an attack held while running holds its own torso - but for the share `held`,
    which goes on the lower spine below, so that attack sways a little with the walk. The arms turn with it
    but for `arm_facing`, the share of the way back to where they faced that they keep - carried along by the
    shoulders, as they are wherever they point. Under it the lower spine,
    the top bone of the lower body, takes out `steady` of the hips' tilt and twist (Animation
    Compilation's runs pass them up through it whole, and compensate higher up, in bones the first
    person's upper body replaces), so that attack rides a steady base, bobbing with the walk. The legs
    hang off the lower spine and are turned back under it (keep_legs): they, the hips and their swing
    stay the third person's.

    The measured curves and the neck's sway are smooth series of the loop, so the motion loops by
    construction; the lead-in and tail fade it in and out. Then, as
    before, where the torso would lean back of `least_lean` degrees forward anywhere in the loop, the
    whole segment is leaned forward until it does not - the arms keeping the way they point, the head
    its gaze."""
    inside = [i for i, tau in enumerate(taus) if seg.lead - 1e-6 <= tau <= seg.lead + seg.period + 1e-6]
    strength = seg.motion
    if strength > 0 and seg.period > 0 and seg.loops == 1 and len(inside) >= 4:
        cycle = inside[:-1]  # the loop's last sample is its first again
        t0 = taus[inside[0]]
        period = taus[inside[-1]] - t0
        first_root = samples[inside[0]][0].get('Bip01', (None, None))[1] or (0.0, 0.0, 0.0)
        last_root = samples[inside[-1]][0].get('Bip01', (None, None))[1] or (0.0, 0.0, 0.0)

        def drift(i):
            f = (taus[i] - t0) / period
            return tuple((b - a) * f for a, b in zip(first_root, last_root))

        def phase(i):  # where in the loop a sample falls - the lead-in and tail too
            return (taus[i] - t0) % period

        rest = seg.length - (seg.lead + seg.period)

        def fade(i):
            tau = taus[i]
            if seg.lead - 1e-6 <= tau <= seg.lead + seg.period + 1e-6:
                return 1.0
            if tau < seg.lead:
                return tau / seg.lead if seg.lead > 0 else 1.0
            return (seg.length - tau) / rest if rest > 0 else 0.0

        def weight(i):
            return strength * fade(i)

        rel = [taus[i] - t0 for i in cycle]
        # In step with the legs, the shapes measured for this gait; the turn only as much as the walk goes
        # forward or back - it balances the legs swinging that way.
        stride = stride_phase(seg, taus, samples, cycle, rel, period, drift)
        flexion, tilt, turn = GAIT_SHAPES[seg.gait]
        travel = [b - a for a, b in zip(first_root, last_root)]
        ahead_share = abs(travel[1]) / math.hypot(travel[0], travel[1]) if math.hypot(travel[0], travel[1]) > 1e-3 else 1.0
        hips_sway = [bone_heads(samples[i][0], ('Bip01', 'Bip01 Pelvis'), drift(i))['Bip01 Pelvis'][0] for i in cycle]
        if steady > 0:
            spines = []
            for body_pose, _ in samples:
                rot = IDENTITY
                for bone in ('Bip01', 'Bip01 Pelvis', SPINE):
                    r = body_pose.get(bone, (None, None))[0]
                    if r is not None:
                        rot = E.qmul(rot, r)
                spines.append(rot)
            average = mean_rotation([spines[i] for i in cycle])
            facing = seg.facing if seg.facing is not None else (seg.posture.spine if seg.posture is not None else None)
            if face > 0 and facing is not None:
                # And turned toward where the stance's lower spine faces standing: a strafe turns it the way
                # it goes (Animation Compilation's by up to 21 degrees), a sneak 32 degrees aside, and what
                # plays on the upper body over it - an attack held - turned with it.
                average = facing_forward(average, facing, face)
            for i, (body_pose, _) in enumerate(samples):
                steady_spine(body_pose, average, steady * fade(i))
        for i, (body_pose, arm_pose) in enumerate(samples):
            w = weight(i)
            if w <= 0:
                continue
            p = stride(phase(i))
            # About the trunk's own axes, as gait studies take its angles (flexion, then the tilt, then
            # the turn about its length): turned about the room's vertical, a trunk leaning into a run
            # would swing its top from side to side.
            at = bone_heads(body_pose, TO_NECK)
            length = [b - a for a, b in zip(at[SPINE], at[NECK])]
            size = math.sqrt(sum(c * c for c in length)) or 1.0
            along = tuple(c / size for c in length)
            ahead = cross(along, LATERAL)
            size = math.sqrt(sum(c * c for c in ahead)) or 1.0
            ahead = tuple(c / size for c in ahead)
            nod = E.axis_quat(-math.radians(seg.nod) * flexion(p) * w, LATERAL)
            # Turned to the right brings the left shoulder forward (negative about the length).
            swing = E.axis_quat(-math.radians(seg.swing) / 2 * turn(p) * ahead_share * w, along)
            # Tilted toward the right is positive about forward.
            lean = E.axis_quat(math.radians(seg.stance_lean) / 2 * tilt(p) * w, ahead)
            motion = E.qmul(nod, E.qmul(lean, swing))
            if held > 0:
                turn_torso(body_pose, arm_pose, E.qslerp(IDENTITY, motion, held), HEAD_STEADY, arm_facing, at=SPINE)
            turn_torso(body_pose, arm_pose, E.qslerp(IDENTITY, motion, 1.0 - held), HEAD_STEADY, arm_facing)
        # The neck kept over the line of the walk - `neck_sway` of the hips' own sway to the side - by a
        # side bend of the back that carries the upper body over without tilting it, as people do
        # (most of the trunk's side bending against the pelvis is lumbo-pelvic, Preece et al. 2016
        # figure 3h, 16 degrees through) - at the chest's base, the lowest bone of the upper body:
        # smoothed like the rest, within LUMBAR_MOST.
        heads = [bone_heads(samples[i][0], TO_NECK, drift(i)) for i in cycle]
        neck_mean = sum(at[NECK][0] for at in heads) / len(heads)
        hips_mean = sum(hips_sway) / len(hips_sway)
        needed = []
        for i, at, hips in zip(cycle, heads, hips_sway):
            lumbar = math.dist(at[CHEST], at[UPPER_SPINE])
            target = neck_mean + neck_sway * (hips - hips_mean)
            needed.append(math.asin(max(-1.0, min(1.0, (target - at[NECK][0]) / lumbar))) if lumbar > 1e-6 else 0.0)
        side = loop_series(rel, needed, period, HARMONICS - 1)
        most = math.radians(LUMBAR_MOST)
        for i, (body_pose, arm_pose) in enumerate(samples):
            w = weight(i)
            if w <= 0:
                continue
            bend_lumbar(body_pose, E.axis_quat(most * math.tanh(side(phase(i)) * w / most), FORWARD))
    if least_lean is not None:
        # Over the loop, which is what plays on and on; the lead-in and tail are leaned as much.
        measured = [samples[i] for i in inside] if seg.period > 0 and len(inside) >= 2 else samples
        short = math.radians(least_lean) - min(forward_lean(*torso_points(body_pose)) for body_pose, _ in measured)
        if short > 0:
            lean_torso(samples, short)


def breath(phase):
    """How full the lungs are, 0 to 1, one breath for each whole of `phase`: smooth, looping, and
    breathing in quicker than out."""
    f = phase % 1.0
    # Time warped to run ahead through the first part, the lungs full at about 0.4 of the breath; the
    # warp's slope is the same at both ends, so the loop stays smooth.
    warped = f + BREATH_SKEW * (1.0 - math.cos(2 * math.pi * f)) / (2 * math.pi)
    return 0.5 - 0.5 * math.cos(2 * math.pi * warped)


def shrug(arm_pose, body_pose, angle):
    """Lifts both shoulders by turning each clavicle up `angle` radians, the upper arms turned back so
    the arms keep the way they point - hands on one weapon stay on it."""
    for side in ('L', 'R'):
        names = ['Bip01 %s %s' % (side, part) for part in ARM_CHAIN]
        if any(arm_pose.get(b, (None, None))[0] is None or arm_pose[b][1] is None for b in names):
            continue
        c = chain(body_pose, arm_pose, side)
        out = [b - a for a, b in zip(c['Clavicle'][1], c['UpperArm'][1])]
        axis = (out[1] * UP[2] - out[2] * UP[1], out[2] * UP[0] - out[0] * UP[2], out[0] * UP[1] - out[1] * UP[0])
        norm = math.sqrt(sum(x * x for x in axis))
        if norm < 1e-6:
            continue
        clavicle = E.qmul(E.axis_quat(angle, [x / norm for x in axis]), c['Clavicle own'])
        arm_pose[names[0]] = (E.qmul(E.qconj(c['Clavicle'][0]), clavicle), arm_pose[names[0]][1])
        arm_pose[names[1]] = (E.qmul(E.qconj(clavicle), c['UpperArm own']), arm_pose[names[1]][1])


def breathe(seg, taus, samples):
    """An idle's breathing, as many breaths as fit its loop best at about BREATH_SECONDS each - one,
    for an idle that long: the chest turns up and back about its base by seg.breathe degrees at a full
    breath, and the shoulders lift with it (SHRUG). Rotations only, smooth and looping, at rest outside
    the loop; the head keeps its gaze and the arms the way they point."""
    start, stop = seg.breath_span
    if stop - start < 1e-3:
        return
    breaths = max(1, int(round((stop - start) / BREATH_SECONDS)))
    for tau, (body_pose, arm_pose) in zip(taus, samples):
        if not start - 1e-6 <= tau <= stop + 1e-6:
            continue
        full = breath(min(max((tau - start) / (stop - start), 0.0), 1.0) * breaths)
        if full <= 0:
            continue
        angle = math.radians(seg.breathe * full)
        turn_torso(body_pose, arm_pose, E.axis_quat(angle, LATERAL), 1.0, 1.0)
        shrug(arm_pose, body_pose, angle * SHRUG)


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
    # range (ReAnimation does, unless split_follows gave each its own) and the third person one after another.
    nested = {(k.split()[0], size) for k in fkeys if k.endswith('large follow start') for size in ('small', 'medium')
              if abs(fkeys.get('%s %s follow start' % (k.split()[0], size), -1e9) - fkeys[k]) < 0.01}
    pieces, section = [], None
    # A section's stop before the next one's start, where the two share a time.
    for k in sorted(fkeys, key=lambda k: (fkeys[k], 'stop' not in k)):
        words = k.split()
        if k not in tkeys or ('follow' in words and (words[0], words[1]) in nested):
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


def third_pieces(seg):
    """[(third-person start, stop, repeat of the loop)]: the stretches of the third person a segment
    plays, in order - the lead-in, each repeat of the loop, the tail."""
    if seg.period > 0:
        return ([(seg.v_start, seg.loop_start, 0)] if seg.lead > 1e-6 else []) + \
               [(seg.loop_start, seg.loop_stop, r) for r in range(seg.loops)] + \
               ([(seg.loop_stop, seg.v_stop, seg.loops - 1)] if seg.tail > 1e-6 else [])
    return [(seg.v_start, seg.v_stop, 0)]


def copy_track(seg, src, dst):
    """A third-person bone's own keys over a segment, as they are - repeated with the loop, and with
    keys sharing a time kept in their order, as some animations have them (Animation Compilation's:
    four to a frame) and the engine plays them. Resampling would smooth them into something else."""
    pieces = third_pieces(seg)
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
        # The lower spine turned (a walk's torso motion), the legs that hang off it turned back; the hips
        # turned under a twisted torso, the legs keeping the feet where they were (untwist).
        twist_limit = ctx['opts']['max_twist'] if seg.follow and not seg.motion and not is_move(seg.group) else 0.0
        # Following the first person but not walking: the lower spine held at the stance idle's (hold_spine).
        hold = ctx['opts']['steady_spine'] if seg.follow and not seg.motion and not is_move(seg.group) \
            and seg.posture is not None else 0.0
        resampled = {SPINE} | set(LEG_ROOTS) if seg.motion or hold > 0 or twist_limit > 0 else set()
        # Sampled at the third person's own key times as well: what is keyed anew, and where the hips may
        # turn - only there, their own keys left as they are elsewhere (splice_rotations).
        exact = resampled | (set(TWIST_BONES) if twist_limit > 0 else set())
        copied = set()
        for bone in body:
            d = kf.data(bone)
            if not seg.sample_all and bone != CHEST and bone not in TORSO and d.rot_type in (0, 1) \
                    and d.trans['itype'] in (0, 1) and bone not in resampled:
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
                for bone in sorted({'Bip01', 'Bip01 Pelvis', SPINE} | exact):
                    if bone in kf.bone_data:
                        times = key_times_of(kf, bone)
                        extra += [forward(t) for t in times[bisect.bisect_left(times, t0):bisect.bisect_right(times, t1)]]
        if exact and seg.clock is None and not seg.warp_pieces:
            # What is keyed anew here is sampled at the third person's own key times too (Animation
            # Compilation keys some walks 88 times a second), so where nothing is changed it stays
            # exactly as it has it.
            for bone in sorted(exact):
                if bone in kf.bone_data:
                    d = kf.data(bone)
                    times = sorted({t for t, *_ in d.quat_keys + d.trans['keys']})
                    for a, b, repeat in third_pieces(seg):
                        extra += [seg.out_time(t, repeat) for t in
                                  times[bisect.bisect_left(times, a - KEY_TIME_EPS):bisect.bisect_right(times, b + KEY_TIME_EPS)]]
        taus = seg.times(extra)
        t3 = [seg.third_time(tau) for tau in taus]
        t1 = [seg.first_time(tau) for tau in taus] if seg.first_time else None
        post = seg.posture
        # The chest in the character's frame. An idle keeps its own motion, turned the keep-forward
        # share of the way to square; anything else goes that share of the way to the stance idle's
        # posture, square.
        # The first person's upper body - or its idle's, held, for a move made from that.
        own_upper = seg.follow and (t1 is not None or seg.idle_arms is not None)
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
                        target = E.world(first_kf, CHEST, t1[i])[0] if t1 is not None else seg.idle_arms['chest']
                        if seg.sway_about is not None:
                            target = E.qmul(E.qmul(spine, E.qconj(seg.sway_about)), target)
                        rot = E.qmul(E.qconj(spine), target)
                    elif t1 is None:
                        rot = seg.idle_arms['torso'].get(bone, rot)
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
        spines_was = [body_pose.get(SPINE, (None, None)) for body_pose, _ in samples]
        if hold > 0:
            held_at = facing_forward(seg.posture.spine, seg.facing, 1.0) if seg.facing is not None else seg.posture.spine
            for body_pose, _ in samples:
                hold_spine(body_pose, held_at, hold)
        twisted = []
        if twist_limit > 0:
            # The hips' turn after the shoulders: a smooth share of the twist, smoothed in time, coming in
            # over each wind-up and going as the attack settles into the idle - so it starts and ends on
            # the idle's own legs.
            times = [seg.offset + tau for tau in taus]
            twists = [twist_of(body_pose, arm_pose) for body_pose, arm_pose in samples]
            wanted = [0.0 if tw is None else hips_follow(tw, twist_limit) for tw in twists]
            wanted = smooth_within(times, wanted, seg.cuts, TWIST_SMOOTH)
            for i, t in enumerate(times):
                w = 1.0
                for a, b in seg.windups:
                    if a - 1e-6 <= t <= b:
                        f = (t - a) / (b - a) if b > a else 1.0
                        w = min(w, f * f * (3 - 2 * f))
                for a, b in seg.settle:
                    if a <= t <= b + 1e-6:
                        f = (t - a) / (b - a) if b > a else 1.0
                        w = min(w, 1.0 - f * f * (3 - 2 * f))
                wanted[i] *= w
            twisted = [turn_hips(body_pose, arm_pose, angle) for (body_pose, arm_pose), angle in zip(samples, wanted)]
        if seg.lower_by:
            lower_raised_arms(samples, seg.lower_by)
        if seg.lean:
            lean_torso(samples, seg.lean)
        if seg.motion or seg.least_lean is not None:
            move_torso(seg, taus, samples, ctx['opts']['neck_sway'], ctx['opts']['steady_spine'], seg.least_lean,
                       ctx['opts']['held_motion'], ctx['opts']['face_forward'], ctx['opts']['arm_facing'])
        if seg.breathe:
            breathe(seg, taus, samples)
        if seg.head_forward is not None:
            # Looking straight ahead whatever the body under it does: a first-person head turns with
            # every swing, and often sits turned in an idle too, which its camera never shows.
            for body_pose, _ in samples:
                if body_pose.get(HEAD, (None, None))[0] is not None:
                    body_pose[HEAD] = (E.qmul(E.qconj(neck_rotation(body_pose)), seg.head_forward), body_pose[HEAD][1])
        if seg.bounce:
            bounce_arms(seg, taus, samples, seg.bounce, seg.bounce_real_time)
        if seg.motion:
            for (body_pose, _), was in zip(samples, spines_was):
                keep_legs(body_pose, was)
        for tau, (body_pose, arm_pose) in zip(taus, samples):
            t_out = seg.offset + tau
            for bone, (rot, trans) in [kv for kv in body_pose.items() if kv[0] not in copied] + list(arm_pose.items()):
                if rot is not None:
                    data[bone].quat_keys.append((t_out, E.qnorm(rot), ()))
                if trans is not None:
                    data[bone].trans['keys'].append((t_out, tuple(trans), ()))
        if any(twisted):
            splice_rotations(data, seg.offset, taus, samples, twisted, [b for b in TWIST_BONES if b in copied])

    for seg in segments:
        plant_root(data, seg.plant)
        if ctx['opts']['straight_starts'] and is_move(seg.group):
            straighten_ends(data['Bip01'].trans['keys'], seg)
    for seg in segments:
        onto = [(a, b, pose_at(data, there)) for a, b, there in seg.settle_onto]
        for start, stop, pose in onto:
            settle(data, pose, start, stop)
        for start, stop in seg.settle:
            settle(data, seg.settle_to, start, stop)
        for start, stop in seg.settle_in:
            settle(data, seg.settle_to, start, stop, out_of=True)
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
    # Placed on the timeline where the third person has it (--align-to-third): the held thrown weapon's
    # own mesh animation runs on its group's absolute time.
    shift = 0.0
    aligned = sorted((tm, g, k) for tm, line in text for g, k in [split_line(line)]
                     if g in ctx['opts']['align'] and k.endswith('start'))
    if aligned:
        tm, g, k = aligned[0]
        there = next((seg.source.groups[seg.group][k] for seg in segments
                      if seg.group == g and k in seg.source.groups.get(g, {})), None)
        if there is not None:
            shift = there - tm
    if shift:
        for d in data.values():
            d.quat_keys = [(t + shift,) + tuple(rest) for t, *rest in d.quat_keys]
            d.trans['keys'] = [(t + shift,) + tuple(rest) for t, *rest in d.trans['keys']]
            d.scale['keys'] = [(t + shift,) + tuple(rest) for t, *rest in d.scale['keys']]
        text = [(tm + shift, line) for tm, line in text]
        for t, p in out.blocks:
            if t == 'NiKeyframeController':
                p['start'] += shift
                p['stop'] += shift
    by_time = {}
    for tm, line in text:
        lines = by_time.setdefault(round(tm, 5), [])
        line = aliased_line(line, back=True)
        if line not in lines:
            lines.append(line)
    tk = out.blocks[out.textkey_block][1]
    tk['keys'] = [(t, '\r\n'.join(lines)) for t, lines in sorted(by_time.items())]
    # Bones the skeleton has not: the engine skips them, warning for each every time an actor loads the file.
    if ctx['bones'] is not None:
        out.remove_bones([b for b in list(out.bone_data) + out.dataless if b.lower() not in ctx['bones']])
    out.save(out_path)


def key_value(keys, t, rotation):
    """A key list's value at time t, linear between keys - the last of several at one instant."""
    times = [k[0] for k in keys]
    i = bisect.bisect_right(times, t + 1e-9)
    if i == 0:
        return keys[0][1]
    if i >= len(keys):
        return keys[-1][1]
    (t0, a, _), (t1, b, _) = keys[i - 1], keys[i]
    if t1 - t0 < 1e-9:
        return b
    f = (t - t0) / (t1 - t0)
    return E.qslerp(a, b, f) if rotation else lerp(a, b, f)


def key_value_before(keys, t, rotation):
    """key_value, but the first of several keys at one instant: where a section ending at t had it."""
    times = [k[0] for k in keys]
    i = bisect.bisect_left(times, t - 1e-6)
    if i < len(keys) and abs(times[i] - t) < 1e-6:
        return keys[i][1]
    return key_value(keys, t, rotation)


def section_spans(lines, group):
    """(start, stop) output times of each section of a group: the first to the last of its keys
    starting with the same word (chop, slash, equip, ...)."""
    spans = {}
    for tm, line in lines:
        g, k = split_line(line)
        if g == group and k:
            word = k.split()[0]
            a, b = spans.get(word, (tm, tm))
            spans[word] = (min(a, tm), max(b, tm))
    return sorted(span for span in spans.values() if span[1] - span[0] > 1e-4)


def plant_root(data, spans):
    """Holds the actor in place through each span (an attack's section): the root's travel over the
    ground - which the engine moves the actor by - goes onto the pelvis instead, from where the section
    starts, the root keeping only its height. The body lunges as before, the feet with it, but the actor
    stays put whatever part of a section the engine plays: a quick attack plays only some of its wind
    up, then its release from the matching point on, and the root's travel over those two need not
    cancel out - Animation Compilation's slash drifts 6-10 units back with every quick click. As
    FBACompat does it."""
    root, pelvis = data.get('Bip01'), data.get('Bip01 Pelvis')
    if not spans or root is None or pelvis is None or not root.trans['keys'] or not pelvis.trans['keys']:
        return
    roots, pelvises, turns = list(root.trans['keys']), list(pelvis.trans['keys']), list(root.quat_keys)
    planted_root, planted_pelvis = [], []
    for n, (start, stop) in enumerate(spans):
        times = sorted({round(start, 6), round(stop, 6)} | {round(t, 6) for t, _, _ in roots + pelvises
                                                           if start + 1e-6 < t < stop - 1e-6})
        x0, y0, _ = key_value(roots, start, False)
        for t in times:
            # At its stop, where this section has it, not one starting at the same instant.
            value = key_value_before if abs(t - stop) < 1e-6 else key_value
            x, y, z = value(roots, t, False)
            turn = value(turns, t, True) if turns else IDENTITY
            travel = E.qrot(E.qconj(turn), (x - x0, y - y0, 0.0))
            planted_root.append((t, n, (0.0, 0.0, z)))
            planted_pelvis.append((t, n, tuple(a + b for a, b in zip(value(pelvises, t, False), travel))))

    def outside(keys):
        return [(t, -1, v) for t, v, _ in keys if not any(a - 1e-6 <= t <= b + 1e-6 for a, b in spans)]
    for d, planted, keys in ((root, planted_root, roots), (pelvis, planted_pelvis, pelvises)):
        d.trans['keys'] = [(t, v, ()) for t, _, v in sorted(outside(keys) + planted, key=lambda k: (k[0], k[1]))]


def settle(data, pose, start, stop, out_of=False):
    """Crossfades every bone from start to stop into `pose` (bone -> (rotation, translation)), easing
    in and out, all of it there by stop - or, `out_of` it, all of it there at start and none by stop -
    over the keys a bone has there, and FPS samples a second at least. The root's travel over the
    ground is left as it is: the engine moves the actor by it, and takes it off the skeleton, so it is
    never seen - crossfaded, it would push the actor about."""
    n = max(1, int(round((stop - start) * FPS)))
    grid = {round(start + (stop - start) * i / n, 6) for i in range(n + 1)}
    for bone, d in data.items():
        goal_rot, goal_trans = pose.get(bone, (None, None))
        for keys, goal, rotation in ((d.quat_keys, goal_rot, True), (d.trans['keys'], goal_trans, False)):
            if not keys or goal is None:
                continue
            times = sorted(grid | {round(t, 6) for t, _, _ in keys if start - 1e-6 <= t <= stop + 1e-6})
            blended = []
            for t in times:
                value = key_value(keys, t, rotation)
                f = min(max((t - start) / (stop - start), 0.0), 1.0)
                f = f * f * (3 - 2 * f)
                if out_of:
                    f = 1.0 - f
                if rotation:
                    blended.append((t, tuple(E.qslerp(value, goal, f)), ()))
                else:
                    to = (value[0], value[1], goal[2]) if bone == 'Bip01' else goal
                    blended.append((t, tuple(lerp(value, to, f)), ()))
            keys[:] = [k for k in keys if k[0] < start - 1e-6] + blended + [k for k in keys if k[0] > stop + 1e-6]


def settle_windows(lines, group, tails, seconds):
    """Where an attack group crossfades into its stance idle's first frame, in output times: the last
    third of each follow-through, but no more than `seconds` of it, unless the section goes on into a tail
    (`tails`: the keys of '<group>extra', which ReAnimation plays after it), and the last of each tail.
    Not where another section starts the moment one stops: that one would start crossfaded too."""
    keys = {}
    for tm, line in lines:
        g, k = split_line(line)
        if g == group:
            keys.setdefault(k, tm)
    out = set()
    for k, stop in keys.items():
        words = k.split()
        if words[-2:] == ['follow', 'stop'] and words[0] + ' tail start' not in tails:
            begin = keys.get(' '.join(words[:-1] + ['start']), stop)
        elif len(words) == 3 and words[1:] == ['tail', 'stop']:
            begin = keys.get(words[0] + ' tail start', stop)
        else:
            continue
        if any(abs(t - stop) < 1e-3 and other.endswith('start') for other, t in keys.items()):
            continue
        # A weaker follow-through ending where a stronger one of the same section, started with it,
        # still plays on (ReAnimation keys them over one range): settled, the stronger would dip into
        # the idle on its way.
        if words[-2:] == ['follow', 'stop'] and any(
                other.split()[0] == words[0] and other.endswith('follow stop') and t > stop + 1e-3
                and keys.get(other[:-len('stop')] + 'start', t) <= stop for other, t in keys.items()):
            continue
        out.add((stop - min(seconds, (stop - begin) / 3.0), stop))
    return sorted(w for w in out if w[1] - w[0] > 1e-3)


def settle_onto_windows(lines, group, tails, seconds):
    """[(start, stop, there)]: where a weaker follow-through of a section that goes on into a tail (`tails`:
    the keys of '<group>extra') crossfades, over the last third of it - `seconds` at most - into the pose
    at `there`, where the strongest one ends: ReAnimation plays the tail after whichever ended, and the
    tail takes up from there."""
    keys = {}
    for tm, line in lines:
        g, k = split_line(line)
        if g == group:
            keys.setdefault(k, tm)
    out = []
    for section in {k.split()[0] for k in keys if k.endswith('follow stop')}:
        if section + ' tail start' not in tails:
            continue
        stops = {size: keys['%s %s follow stop' % (section, size)] for size in FOLLOW_SIZES
                 if '%s %s follow stop' % (section, size) in keys}
        if not stops:
            continue
        strongest = max(stops, key=lambda size: FOLLOW_SIZES.index(size))
        for size, stop in stops.items():
            begin = keys.get('%s %s follow start' % (section, size), stop)
            if size == strongest or stop - begin < 1e-3 or abs(stop - stops[strongest]) < 1e-3:
                continue
            out.append((stop - min(seconds, (stop - begin) / 3.0), stop, stops[strongest]))
    return sorted(out)


def pose_at(data, t):
    """{bone: (rotation, translation)} as the keys being written have it at t."""
    return {bone: (key_value(d.quat_keys, t, True) if d.quat_keys else None,
                   key_value(d.trans['keys'], t, False) if d.trans['keys'] else None) for bone, d in data.items()}


def start_windows(lines, group, seconds):
    """Where an attack eases out of its stance idle's first frame, in output times: the first third of
    each wind-up - from a section's start to its "min attack" - `seconds` at most, so a quick one still
    gets its swing."""
    keys = {}
    for tm, line in lines:
        g, k = split_line(line)
        if g == group:
            keys.setdefault(k, tm)
    out = []
    for k, start in keys.items():
        words = k.split()
        if len(words) == 2 and words[1] == 'start' and words[0] + ' min attack' in keys:
            out.append((start, start + min(seconds, (keys[words[0] + ' min attack'] - start) / 3.0)))
    return sorted(w for w in out if w[1] - w[0] > 1e-3)


def section_cuts(lines, group):
    """Output times where a group's sections, and each follow-through, start: what the hips' turn is not
    smoothed across (smooth_within)."""
    return sorted({tm for tm, line in lines for g, k in [split_line(line)]
                   if g == group and k and k.endswith('start')})


def windups(lines, group):
    """[(start, min attack)] output times of a group's attack sections."""
    keys = {}
    for tm, line in lines:
        g, k = split_line(line)
        if g == group:
            keys.setdefault(k, tm)
    return sorted((t, keys[k.split()[0] + ' min attack']) for k, t in keys.items()
                  if len(k.split()) == 2 and k.endswith(' start') and k.split()[0] + ' min attack' in keys)


def idle_frames(written, out_dir):
    """{idle group: {bone: (rotation, translation)}}: the first frame of each idle written, as written."""
    out = {}
    for name, groups in written:
        idles = [g.split()[0] for g in groups if is_idle(g.split()[0])]
        if not idles:
            continue
        kf = nifkf.KF.load(os.path.join(out_dir, name))
        alias_text_keys(kf)
        keys = group_keys(text_lines(kf))
        for idle in idles:
            if idle in keys:
                t = min(keys[idle].values())
                out[idle] = {b: (E.rotation(kf.data(b), t), E.translation(kf.data(b), t)) for b in kf.bone_data}
    return out


def right_strike(lines, start, stop):
    """Where in a loop the right foot strikes, as a share of it, from the footstep keys ('SoundGen:
    Right', or 'Left' half a loop before it) - or None."""
    steps = {}
    for tm, line in lines:
        group, key = split_line(line)
        if group == 'soundgen' and key in ('right', 'left') and key not in steps and start - 1e-6 <= tm < stop - 1e-6:
            steps[key] = tm
    if 'right' in steps:
        return (steps['right'] - start) / (stop - start)
    if 'left' in steps:
        return ((steps['left'] - start) / (stop - start) + 0.5) % 1.0
    return None


def step_shift(first_lines, fkeys, third_lines, tkeys, ls, le):
    """How far round its loop (a share of it) the first person's walk is to be entered so its feet
    strike with the third person's - or None where either has no loop or no footstep keys."""
    if 'loop start' not in fkeys or 'loop stop' not in fkeys or fkeys['loop stop'] - fkeys['loop start'] < 1e-3:
        return None
    first = right_strike(first_lines, fkeys['loop start'], fkeys['loop stop'])
    third = right_strike(third_lines, ls, le)
    if first is None or third is None:
        return None
    return (first - third) % 1.0


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


def idle_package(stance):
    """What a stance moves with, as (file kind, group): walks and runs, turns on the spot (a spell's
    'spellturnleft', as the engine names them), a jump - what moves made from its idle can be."""
    out = [('Movement', move + stance) for move in MOVES if not move.startswith('sneak')]
    out += [('Turn', (stance + turn) if stance == 'spell' else (turn + stance)) for turn in TURNS]
    return out + [('Jump', 'jump' + stance)]


def package_words(groups):
    """'walks, runs, turns, jump' - the kinds of move among the groups given."""
    words = [w for w, test in (('walks', 'walk'), ('runs', 'run'), ('turns', 'turn'), ('jump', 'jump'))
             if any(test in g for g in groups)]
    return ', '.join(words)


def free_name(name, written):
    """A file name for groups made here, not the first person's: as given, or with 'FromIdle' before
    its extension where a file of that name is written already - matched ignoring case, as the game's
    file system does (ReAnimation's xhhMovement.kf and a made xHhMovement.kf are one file to it)."""
    taken = {w.lower() for w, _ in written}
    if name.lower() not in taken:
        return name
    stem, ext = os.path.splitext(name)
    return stem + 'FromIdle' + ext


def renamed(group, paired, source):
    """What a third-person group's text keys say when it is written as another group: the third
    person's spelling of the part both share ('WalkForward' of its 'WalkForward1h', for walkforward1t;
    'WalkForward', for walkforwardspell), the rest capitalised - or None for the same group."""
    if group == paired:
        return None
    spelled = next((line.partition(':')[0].strip() for _, line in source.lines if split_line(line)[0] == paired), paired)
    base, _ = base_and_stance(paired)
    shared = len(paired) if group.startswith(paired) else len(base) if base and group.startswith(base) else 0
    rest = group[shared:]
    return spelled[:shared] + rest[:1].upper() + rest[1:]


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

    def standing(stance, group, fallback_source):
        """Where the stance's standing idle faces its lower spine, in the character's frame: what every
        lower spine of the stance faces - a sneaking one too (Animation Compilation's sneaking idle and
        sneaks turn theirs 32 degrees aside, and an attack held while sneaking turned with it)."""
        if stance and stance.endswith('sneak'):
            stance = stance[:-len('sneak')]
        return posture(stance, group, fallback_source).spine

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

    def idle_frame(stance):
        """The first frame of the stance's converted idle - a throwing star's, or its thrown weapon's -
        or None."""
        stance = stance or ''
        for s in (stance, stance[:-len('star')] if stance.endswith('star') else None):
            if s is not None and 'idle' + s in ctx['idle_frames']:
                return ctx['idle_frames']['idle' + s]
        return None

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
            if group in opts['sneaks_made']:
                info('  %-28s %s: made from its stance idle instead' % (name, group))
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
                        shift = step_shift(lines, fkeys, source.lines, tkeys, ls, le) \
                            if opts['align_steps'] and is_move(group) and seg.loops == 1 and seg.period > 0 else None
                        if shift is not None:
                            # In step: the first person's loop entered where its right foot strikes as the
                            # third person's does - lead-in and tail too, so nothing jumps where they meet.
                            fls, fle = fkeys['loop start'], fkeys['loop stop']
                            seg.first_time = (lambda fls, fle, lead, period, shift: lambda tau: fls + (
                                ((tau - lead) / period + shift) % 1.0) * (fle - fls))(fls, fle, seg.lead, seg.period, shift)
                            seg.first_points = None
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
            seg.facing = standing(stance, group, seg.source)
            ref = first_reference(stance, kf, group, fkeys)
            seg.shoulders = E.qmul(E.qconj(seg.posture.neck), ref['neck'])
            seg.keep = opts['keep']
            seg.repoint = repoint_for(stance, opts)
            walking = is_move(group) and paired is not None
            # The arms bounce on a walk of the first person's own only when asked: it moves them already.
            seg.bounce = bounce_for(stance, opts) if walking and in_stances(stance, opts['bounce_walks']) else 0.0
            seg.bounce_real_time = in_stances(stance, opts['bounce_real_time'])
            if walking:
                seg.motion, seg.least_lean = opts['torso_motion'], lean_for(group, opts)
                seg.nod = move_value(group, opts['torso_nod']) or 0.0
                seg.swing = move_value(group, opts['shoulder_swing']) or 0.0
                seg.stance_lean = move_value(group, opts['stance_lean']) or 0.0
                seg.gait = 'run' if group.startswith('run') else 'walk'
            seg.grip = opts['grip'] and stance in GRIP_STANCES
            seg.follow = not in_stances(stance, opts['hold_torso'])
            if seg.follow:
                # The upper body is the first person's, arms and all: nothing to point or square.
                seg.repoint, seg.shoulders = 0.0, IDENTITY
                if walking and not opts['torso_motion'] and opts['spine_sway']:
                    # Without its own motion, the chest sways as the third person's spine does.
                    seg.sway_about = mean_rotation([E.world(seg.source.kf, SPINE, t)[0]
                                                    for t in span(seg.loop_start, seg.loop_stop)])
                if opts['steady_head']:
                    seg.head_forward = seg.posture.head_ahead
                if is_idle(group) and opts['breathing']:
                    # Breathing over the loop the output has: the first person's at its timing, else
                    # the third person's.
                    seg.breathe = opts['breathing']
                    if seg.warp_pieces is not None or seg.clock is not None:
                        f0 = fkeys[first]
                        seg.breath_span = (fkeys.get('loop start', f0) - f0, fkeys.get('loop stop', fkeys[last]) - f0)
                    elif 'loop start' in seg.source.groups[seg.group] and seg.period > 0:
                        seg.breath_span = (seg.lead, seg.lead + seg.loops * seg.period)
                    else:
                        seg.breath_span = (0.0, seg.length)
            for spec_group, spec_section, degrees in opts['lower']:
                if spec_group == group and (spec_section is None or any(k.startswith(spec_section + ' ') for k in fkeys)):
                    seg.lower_by = degrees
            seg.offset = offset
            segments.append(seg)
            before = len(text)
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
            if is_attack(group) and opts['plant']:
                seg.plant = section_spans(text[before:], group)
            if is_attack(group):
                seg.cuts = section_cuts(text[before:], group)
                seg.windups = windups(text[before:], group)
            settle_to = idle_frame(stance) if is_attack(group) and opts['settle'] else None
            if settle_to is not None:
                # Ending where the stance idle starts, so the idle that follows picks up without a pop.
                seg.settle_to = settle_to
                seg.settle = settle_windows(text[before:], group, ctx['set_keys'].get(group + 'extra', set()),
                                            opts['settle'])
                if opts['start_from_idle']:
                    seg.settle_in = start_windows(text[before:], group, START_MOST)
                seg.settle_onto = settle_onto_windows(text[before:], group, ctx['set_keys'].get(group + 'extra', set()),
                                                      opts['settle'])
            offset += seg.length + GAP
            info('  %-28s %s: %s%s%s, %s%s%s' % (
                name, group, ('on %s from %s' % (paired, source_name(seg.source)) if paired
                              else 'its own timing on %s' % seg.group),
                ', at the first person\'s timing' if seg.warp_pieces else '',
                ', its loop x%d' % seg.loops if seg.loops > 1 else '',
                ('torso as the first person%s' % (', head looking ahead' if seg.head_forward else '')) if seg.follow
                else 'keep forward %.2f against %s' % (seg.keep, seg.posture.label),
                ', arms lowered up to %g deg' % seg.lower_by if seg.lower_by else '', effects(seg)))
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

    # The idles first: the attacks end on their first frames.
    idle_first = [i for i, (_, kf) in enumerate(first_files) if any(is_idle(g) for g in group_keys(text_lines(kf)))]
    rest = [i for i in range(len(first_files)) if i not in idle_first]
    ctx['idle_frames'] = {}
    written = [w for w in in_parallel(lambda j: convert(*first_files[idle_first[j]]), len(idle_first)) if w is not None]
    frames = idle_frames(written, out_dir)
    if skeleton in LAYERS:  # women's idles are everyone's, but where their own change them
        frames = dict(ctx.get('idle_frames_of', {}).get(LAYERS[skeleton], {}), **frames)
    ctx.setdefault('idle_frames_of', {})[skeleton] = ctx['idle_frames'] = frames
    written += [w for w in in_parallel(lambda j: convert(*first_files[rest[j]]), len(rest)) if w is not None]

    # Idle arms where the third person shows them, for the stances held forward: those following the
    # first person get theirs below.
    if opts['fill']:
        for idle, ref in ctx['first_idles'].items():
            stance = idle[len('idle'):]
            if not stance or third.find(idle, ('start', 'stop')) is None or not in_stances(stance, opts['hold_torso']):
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
                    if is_move(group):
                        seg.bounce = bounce_for(stance, opts)
                        seg.bounce_real_time = in_stances(stance, opts['bounce_real_time'])
                        seg.motion, seg.least_lean = opts['torso_motion'], lean_for(group, opts)
                        seg.nod = move_value(group, opts['torso_nod']) or 0.0
                        seg.swing = move_value(group, opts['shoulder_swing']) or 0.0
                        seg.stance_lean = move_value(group, opts['stance_lean']) or 0.0
                        seg.gait = 'run' if group.startswith('run') else 'walk'
                    seg.grip = opts['grip'] and stance in GRIP_STANCES
                    seg.offset = offset
                    segments.append(seg)
                    text += segment_text(seg, rename=renamed(name_out, group, src))
                    offset += seg.length + GAP
                file_name = free_name(opts['prefix'] + 'x%s%s.kf' % (own_stance(stance)[0].upper() + own_stance(stance)[1:], 'Turn' if kind == 'turn' else 'Movement'), written)
                os.makedirs(out_dir, exist_ok=True)
                build(ctx, os.path.join(ctx['first_dir'], idle_file), idle_kf, segments, text,
                      os.path.join(out_dir, file_name))
                written.append((file_name, [f[2] for f in chosen]))

    # Moves made from an idle, for the stances following the first person: whatever locomotion a stance
    # with an idle lacks - walks, runs, turns, a jump - and the sneaks of those asked for,
    # each on the third person's legs (the engine's own group for it, or what it would play instead:
    # a thrown weapon's walk the one-handed one) with the idle's upper body - as it is on average,
    # arms bouncing, on a move; looping as it plays, breathing, under a sneaking idle.
    for idle, ref in ctx['first_idles'].items():
        stance = idle[len('idle'):]
        if not stance or stance.endswith('sneak') or in_stances(stance, opts['hold_torso']):
            continue
        # A sneaking idle of the set's own makes the sneaks instead, and is converted as it is.
        own_sneak = idle + 'sneak' if idle + 'sneak' in ctx['first_idles'] else None
        wanted = []
        if stance in opts['idle_moves']:
            wanted += [(kind, group) for kind, group in idle_package(stance) if group not in first_groups]
        if stance in opts['idle_sneak']:
            wanted += [('SneakMovement', move + stance) for move in MOVES if move.startswith('sneak')]
            if own_sneak is None:
                wanted.append(('IdleSneak', idle + 'sneak'))
        made = []
        for kind, group in wanted:
            if skipped(group, opts):
                continue
            src = None
            for paired in pair_candidates(group, opts['legs_from']):
                src = third.find(paired, ('start', 'stop'))
                if src is not None:
                    break
            if src is None:
                if own is None:
                    print('  %s: nothing in the third person to make it on, left out' % group)
                continue
            if own is None or src in own:
                made.append((kind, group, paired, src))
        if not made:
            continue

        def upright(of):
            """How far the third person's idle of a stance leans: what a move leans more than it."""
            group, src = stance_idle(of)
            if src is None:
                return 0.0
            keys = src.groups[group]
            return third_lean(src.kf, keys['start'], keys['stop'])
        for kind in ('Movement', 'Turn', 'Jump', 'SneakMovement', 'IdleSneak'):
            chosen = [m for m in made if m[0] == kind]
            if not chosen:
                continue
            from_idle = own_sneak if kind == 'SneakMovement' and own_sneak else idle
            ref = ctx['first_idles'][from_idle]
            idle_file, idle_kf = ctx['first_idle_files'][from_idle]
            segments, text, offset = [], [], 0.0
            for _, group, paired, src in chosen:
                keys = src.groups[paired]
                loop = 'loop start' in keys and 'loop stop' in keys and keys['loop stop'] > keys['loop start']
                seg = Segment(src, paired, keys['start'], keys['stop'],
                              keys['loop start'] if loop else None, keys['loop stop'] if loop else None)
                seg.name = group
                # The posture, and the lean measured from, of the idle it is made from - the sneaking
                # one's, or, on legs given with --legs-from, that stance's idle's.
                reference = stance + 'sneak' if from_idle == own_sneak else stance
                if group in opts['legs_from'] and from_idle != own_sneak:
                    reference = stance_of(paired) or stance
                seg.posture = posture(stance + 'sneak' if from_idle == own_sneak or kind == 'IdleSneak' else stance,
                                      group, src)
                seg.facing = standing(stance, group, src)
                seg.follow = True
                seg.idle_arms = ref
                if opts['steady_head']:
                    seg.head_forward = seg.posture.head_ahead
                seg.grip = opts['grip'] and stance in GRIP_STANCES
                around = span(seg.loop_start, seg.loop_stop) if loop else span(seg.v_start, seg.v_stop)
                if not (is_move(group) and opts['torso_motion']):
                    seg.sway_about = mean_rotation([E.world(src.kf, SPINE, t)[0] for t in around])
                # Leaning as the third person does here against its stance idle: a sneak's crouch, a run.
                seg.lean = opts['idle_lean'] * (third_lean(src.kf, around[0], around[-1]) - upright(reference))
                if is_move(group):
                    seg.bounce = bounce_for(stance, opts)
                    seg.bounce_real_time = in_stances(stance, opts['bounce_real_time'])
                    seg.motion, seg.least_lean = opts['torso_motion'], lean_for(group, opts)
                    seg.nod = move_value(group, opts['torso_nod']) or 0.0
                    seg.swing = move_value(group, opts['shoulder_swing']) or 0.0
                    seg.stance_lean = move_value(group, opts['stance_lean']) or 0.0
                    seg.gait = 'run' if group.startswith('run') else 'walk'
                if kind == 'IdleSneak':
                    # The idle itself, over and over at its own pace through the third person's.
                    f0, f1 = ref['span']
                    repeats = max(1, int(round(seg.length / (f1 - f0)))) if f1 > f0 else 1
                    pace = repeats * (f1 - f0) / seg.length if seg.length > 0 else 1.0
                    seg.first_time = (lambda f0, f1, pace: lambda tau: f0 + math.fmod(tau * pace, f1 - f0)
                                      if f1 > f0 else f0)(f0, f1, pace)
                    if opts['breathing']:
                        seg.breathe = opts['breathing']
                        seg.breath_span = (seg.lead, seg.lead + seg.period) if loop else (0.0, seg.length)
                seg.offset = offset
                segments.append(seg)
                text += segment_text(seg, rename=renamed(group, paired, src))
                offset += seg.length + GAP
                info('  %-28s %s: from %s on %s from %s%s' % (
                    'x%s%s' % (stance, kind), group, from_idle, paired, source_name(src), effects(seg)))
            file_name = free_name(opts['prefix'] + 'x%s%s.kf' % (own_stance(stance), kind), written)
            os.makedirs(out_dir, exist_ok=True)
            build(ctx, os.path.join(ctx['first_dir'], idle_file), idle_kf, segments, text,
                  os.path.join(out_dir, file_name))
            written.append((file_name, [m[1] for m in chosen]))
    for name, groups in written:
        late = '' if name.lower() > 'xbase_anim.kf' else '   (sorts before "xbase_anim.kf": a mod shipping a whole copy of that there would win over it)'
        print('  %-28s %s%s' % (name, ', '.join(groups), late))
    return written


def move_value(group, values):
    """A walk's, run's or sneak's own of {'walk': ..., 'run': ..., 'sneak': ...}, or None."""
    base, _ = base_and_stance(group)
    for move in ('walk', 'run', 'sneak'):
        if base is not None and base.startswith(move):
            return values.get(move)
    return None


def lean_for(group, opts):
    """The least a walk, run or sneak leans forward, in degrees (--torso-lean), or None."""
    return move_value(group, opts['torso_lean'])


def effects(seg):
    """What a segment adds to its animation, for -v."""
    out = []
    if seg.lean:
        out.append('leaned %.0f deg' % math.degrees(seg.lean))
    if seg.motion:
        out.append('torso motion %.2f (nod %g, shoulder swing %g, stance lean %g deg)' % (
            seg.motion, seg.nod, seg.swing, seg.stance_lean))
    if seg.least_lean is not None:
        out.append('leaning at least %g deg' % seg.least_lean)
    if seg.bounce:
        out.append('arm bounce %.2f' % seg.bounce)
    if seg.breathe:
        out.append('breathing %g deg' % seg.breathe)
    return ''.join(', ' + e for e in out)


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


def parse_stances_or_yes_no(value):
    """y -> None (every stance), n -> nothing, else the stances listed, as parse_moves has them. An
    answer already parsed (None, a set) is returned as it is."""
    if value is None or isinstance(value, set):
        return value
    if isinstance(value, bool):
        return None if value else set()
    word = str(value).strip().lower()
    if word in ('y', 'yes', 'true', '1', 'on'):
        return None
    if word in ('n', 'no', 'false', '0', 'off'):
        return set()
    return parse_moves(value)


def parse_moves(text):
    """'all' -> None (every stance), 'none' -> nothing, else the stances listed ('plain' for none)."""
    words = [w.strip().lower() for w in str(text).split(',') if w.strip()]
    if not words or words == ['all']:
        return None
    if words == ['none']:
        return set()
    return {'' if w == 'plain' else w for w in words}


def parse_moves_degrees(text):
    """'walk=3.5, run=7, sneak=2.5' -> {'walk': 3.5, 'run': 7.0, 'sneak': 2.5}; 'none' -> {}"""
    return parse_leans(text)


def parse_leans(text):
    """'walk=3, run=8, sneak=3' -> {'walk': 3.0, 'run': 8.0, 'sneak': 3.0}; 'none' -> {}"""
    out = {}
    if str(text).strip().lower() == 'none':
        return out
    for item in [i.strip() for i in str(text).split(',') if i.strip()]:
        left, eq, right = item.partition('=')
        move = left.strip().lower()
        if not eq or move not in ('walk', 'run', 'sneak'):
            raise ValueError("expected 'walk=degrees, run=degrees, sneak=degrees', got %r" % item)
        out[move] = float(right)
    return out


def bounded(text, top):
    """A number from 0 to `top`; anything else is a ValueError, so a typo is asked again."""
    value = float(text)
    if not 0.0 <= value <= top:
        raise ValueError('%s is not between 0 and %g' % (text, top))
    return value


def walkable(stance):
    """A stance the engine walks in: a weapon type's (weapontype.cpp), or a mod's variant of one - a
    throwing star - but not a sneaking or shield idle's ('2wsneak', '1hshield'), nor no weapon."""
    return stance in LONG_GROUPS.values() or (stance.endswith('star') and stance[:-len('star')] in LONG_GROUPS.values())


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


def parse_aliases(text):
    """'katar=hh' -> [('katar', 'hh')]: a stance of the set's own, and the engine's it plays as."""
    out = []
    shorts = sorted(set(LONG_GROUPS.values()))
    for item in [i.strip() for i in str(text).split(',') if i.strip()]:
        left, eq, right = item.partition('=')
        ours, short = left.strip().lower(), right.strip().lower()
        if not eq or not ours or not short:
            raise ValueError("expected 'stance=engine stance', got %r" % item)
        if short not in shorts:
            raise ValueError('%s: not one of the engine\'s stances (%s)' % (short, ', '.join(shorts)))
        out.append((ours, short))
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
    p.add_argument('--steady-head', metavar='y/n', help='where the upper body follows the first person, the head '
                                                        'looks straight ahead in everything (default y)')
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
    p.add_argument('--idle-moves', metavar='STANCES', help="stances whose missing walks, runs, turns and jump are made "
                                                           "from their idle: all, none, or stances (default %s)" % IDLE_MOVES)
    p.add_argument('--idle-sneak', metavar='STANCES', help="stances whose sneaking idle and sneaks are made from their "
                                                           "idle on the third person's sneaking legs (default %s)" % IDLE_SNEAK)
    p.add_argument('--idle-lean', metavar='0..1', help="moves made from an idle lean forward as the third person's "
                                                       "do against its idle - a sneak's crouch, a run (default %g)" % IDLE_LEAN)
    p.add_argument('--torso-motion', metavar='0..2', help="walks, runs and sneaks move the torso as people's do over "
                                                          "their legs: a nod each step, a roll against the hips' sway, "
                                                          "a lean over the standing leg, the shoulders swinging against "
                                                          "the legs (default %g, 0 for none)" % TORSO_MOTION)
    p.add_argument('--torso-nod', metavar='SPEC', help="degrees the thorax pitches through each step "
                                                       "(default '%s')" % TORSO_NOD)
    p.add_argument('--neck-sway', metavar='0..1', help="share of the hips' side-to-side sway the neck keeps, the chest "
                                                       "rolling against the rest (default %g)" % NECK_SWAY)
    p.add_argument('--align-steps', metavar='y/n', help="walks, runs and sneaks of the first person's own put in step "
                                                         "with the third person's feet by their footstep keys (default y)")
    p.add_argument('--spine-sway', metavar='y/n', help="without torso motion, the chest sways as the third person's "
                                                        "spine does (default y; n keeps the first person's own)")
    p.add_argument('--steady-spine', metavar='0..1', help="share of the hips' tilt and twist the lower spine takes out "
                                                          "on walks, runs and sneaks, so what plays on the upper body "
                                                          "over them rides steady (default %g)" % STEADY_SPINE)
    p.add_argument('--held-attack-motion', metavar='0..1', help="share of a walk's torso motion an attack held over "
                                                               "it sways with (default %g)" % HELD_MOTION)
    p.add_argument('--keep-arm-facing', metavar='0..1', help="share of the way the arms face that they keep while a "
                                                             "walk's torso nods, swings and leans under them, the "
                                                             "hands carried by the shoulders (default %g)" % ARM_FACING)
    p.add_argument('--face-forward', metavar='0..1', help="share of a walk's average hip turn - a strafe's - its lower "
                                                          "spine turns back to face as the stance idle's does, so an "
                                                          "attack held over it faces forward (default %g)" % FACE_FORWARD)
    p.add_argument('--split-follows', metavar='y/n', help="attacks whose follow-throughs share one recovery get one "
                                                          "of their own each, ending on the idle (default y)")
    p.add_argument('--start-from-idle', metavar='y/n', help="attacks ease out of their stance idle's first frame over "
                                                            "a third of the wind-up, %g s at most (default y)" % START_MOST)
    p.add_argument('--align-to-third', metavar='GROUPS', help="groups whose files are placed on the timeline where the "
                                                              "third person has them (default '%s')" % ALIGN_TO_THIRD)
    p.add_argument('--max-twist', metavar='DEGREES', help="the shoulders turn this far against the hips at most; past "
                                                          "it the hips turn with them, the legs keeping the feet where "
                                                          "they were (default %g, 0 for never)" % MAX_TWIST)
    p.add_argument('--straight-starts', metavar='y/n', help="a walk's lead-in and tail move the actor only the way its "
                                                            "loop goes (default y)")
    p.add_argument('--shoulder-swing', metavar='SPEC', help="degrees the chest turns through each stride, the shoulder "
                                                            "opposite the leading leg forward (default '%s')" % SHOULDER_SWING)
    p.add_argument('--stance-lean', metavar='SPEC', help="degrees the chest leans through each stride, over the leg it "
                                                         "stands on (default '%s')" % STANCE_LEAN)
    p.add_argument('--torso-lean', metavar='SPEC', help="the least walks, runs and sneaks lean forward, in degrees, "
                                                        "bounce and all (default '%s')" % TORSO_LEAN)
    p.add_argument('--breathing', metavar='DEGREES', help='idles breathe: how far the chest turns up at a full breath '
                                                          '(default %g, 0 for none)' % BREATHING)
    p.add_argument('--remove-attack-root-motion', metavar='y/n', help="attacks keep the actor in place, their root "
                                                                    "travel moved onto the pelvis (default y)")
    p.add_argument('--settle', metavar='SECONDS', help="attacks end on their stance idle's first frame, crossfading "
                                                     "into it over the last third of the follow-through or tail, this "
                                                     "long at most (default %g, 0 for none)" % SETTLE)
    p.add_argument('--arm-bounce', metavar='0..1', help='arms lag and spring back on moves made from an idle '
                                                        '(default %g)' % ARM_BOUNCE)
    p.add_argument('--arm-bounce-by', metavar='STANCES', help="arm bounce for some weapon types of their own, "
                                                              "e.g. '2w=0.2, hh=0.5' (default: --arm-bounce for all)")
    p.add_argument('--arm-bounce-real-time', metavar='y/n|STANCES', help="arm bounce in the walk's own time rather "
                                                                         "than a frame per sample, which hardly bounced "
                                                                         "a forward walk: y, n or stances (default n, "
                                                                         "as sets were built before)")
    p.add_argument('--arm-bounce-walks', metavar='y/n|STANCES', help="arm bounce on the first person's own walks, "
                                                                     "runs and sneaks too: y, n or stances (default n)")
    p.add_argument('--grip', metavar='y/n', help='two-handed weapons: only the right arm bounces, the left hand '
                                                 'follows it on the grip (default y)')
    p.add_argument('--lower-arms', metavar='SPEC', help="'group section=degrees, ...', e.g. 'spellcast target=15'")
    p.add_argument('--moves', metavar='STANCES', help="whose walks, runs, sneaks and jumps to convert: all, none, "
                                                      "or stances such as '2w, hh' (default all)")
    p.add_argument('--skip-files', metavar='PATTERNS', help="first-person files to leave out entirely, shell patterns, "
                                                           "comma separated, e.g. '_xReanimationv1.kf'")
    p.add_argument('--alias', metavar='PAIRS', help="'stance=engine stance, ...': a stance of the set's own built "
                                                    "as the engine's it plays over, e.g. 'katar=hh' (default none)")
    p.add_argument('--skip', metavar='PATTERNS', help="groups to leave alone, shell patterns, comma separated")
    p.add_argument('--legs-from', metavar='PAIRS', help="'group=third-person group, ...': where groups the third "
                                                        "person lacks take their legs and timing from; "
                                                        "'group=third-person group@key' holds that pose")
    p.add_argument('--unpaired', metavar='y/n', help='groups with nothing to pair with keep their own timing on '
                                                     'their stance idle (default y)')
    p.add_argument('--prefix', metavar='TEXT', help='put in front of every file name written (default none)')
    p.add_argument('--data-files', metavar='DIR', help="Morrowind's Data Files, with Morrowind.bsa")
    p.add_argument('--keep-bones', action='store_true',
                   help="keep the tracks of bones the third-person skeleton lacks, for a build that works on them "
                        "and leaves them out itself afterwards (default: they are left out)")
    p.add_argument('--jobs', metavar='N', type=int, help='files converted at once (default: one per CPU, %d here)' % JOBS)
    a = p.parse_args()
    started = time.time()
    params.USE_DEFAULTS = a.yes
    VERBOSE = a.verbose
    if a.jobs:
        JOBS = max(1, a.jobs)
    settings = ('first', 'skip_files', 'alias', 'third', 'vanilla', 'out', 'beasts', 'women', 'hold_torso', 'steady_head',
                'third_timing', 'keep_forward', 'point_arms',
                'two_handed_follow', 'idle_arms', 'lower_arms', 'moves', 'idle_moves', 'idle_sneak', 'idle_lean',
                'align_steps', 'torso_motion', 'spine_sway', 'torso_nod', 'neck_sway', 'shoulder_swing', 'stance_lean', 'steady_spine', 'held_attack_motion', 'keep_arm_facing', 'face_forward', 'split_follows', 'start_from_idle', 'align_to_third', 'max_twist', 'straight_starts', 'torso_lean', 'breathing', 'remove_attack_root_motion', 'settle', 'arm_bounce', 'arm_bounce_by', 'arm_bounce_walks', 'arm_bounce_real_time', 'grip',
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

    def vanilla_file(name, needed):
        """One of vanilla's files from Morrowind.bsa, or None if there is none to read and it is not
        `needed` (a message saying what it would have been for)."""
        if 'files' not in bsa:
            data_files = a.data_files or params.find_data_files()
            path = params.child(data_files, 'Morrowind.bsa') if data_files else None
            wanted = set(SKELETONS.values()) | set(SKELETON_MESHES.values()) | {FIRST_PERSON_KF}
            bsa['files'] = bsa_files(path, wanted) if path else None
        if bsa['files'] is None:
            if needed is True:
                sys.exit('Morrowind.bsa not found from openmw.cfg - give --data-files')
            if needed:
                print('  (no Morrowind.bsa to read: %s)' % needed)
            return None
        return bsa['files'][name]

    def load_vanilla(name, needed):
        """One of vanilla's kfs from Morrowind.bsa, or None (vanilla_file)."""
        if vanilla_file(name, needed) is None:
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
    ALIASES[:] = ask_text(a.alias, "Stances of the set's own",
                          "A moveset of a stance the engine does not have, which a script plays over one it does - "
                          "a mod's katar animations over hand-to-hand - is built as that stance's: 'katar=hh' pairs "
                          "katar, kataralt, idlekatar, walkforwardkatar and so on with the third person's "
                          "handtohand, idlehh, walkforwardhh, and gives them every setting hand-to-hand gets (name "
                          "'hh' for them below). They are written back under their own names. The engine's "
                          "stances: %s. Empty: none." % ', '.join(sorted(set(LONG_GROUPS.values()))),
                          '', parse_aliases)
    for _, kf in first_files:
        alias_text_keys(kf)
    for kf in raw:
        alias_text_keys(kf)
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
    steady_head = ask(a.steady_head, 'Head looks straight ahead (y/n)',
                      "Where the upper body follows the first person: in first person the head turns with every "
                      "swing, up to 90 degrees into a punch, and often sits turned in an idle too (a thrown "
                      "weapon's, 27 degrees), which the camera never shows. y holds it looking straight ahead in "
                      "everything - idles, moves, attacks - upright, at the angle below level the third person's "
                      "stance idle looks at; it still rides on the neck, bobbing up and down with a walk. The "
                      "neck and arms move as animated.", STEADY_HEAD, yes_no)
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
               "For the stances held forward: turning on the spot with a spell ready, and walking or jumping in a "
               "stance with no walks or jump of its own (a spell), show the stance idle's arms: when the first person "
               "converts that idle, make these too, with its arms. (Stances following the first person get theirs "
               "from the next settings.)", True, yes_no)
    lower = ask_text(a.lower_arms, 'Lower raised arms',
                     "Animations whose arms sit too high in third person - first-person hands sit at the camera's "
                     "height - as 'group section=degrees', comma separated, e.g. 'spellcast target=15'; without a "
                     "section, the whole group. Empty: none. This set's groups, with their sections: %s." %
                     group_listing(set_groups, set_groups), '', parse_lower)
    idle_stances = sorted(g[len('idle'):] for g in set_groups if is_idle(g) and walkable(g[len('idle'):]))
    followers = [s for s in idle_stances if not in_stances(s, hold)]
    lacking = ['%s: %s' % (stance_label(s), package_words([g for _, g in idle_package(s) if g not in set_groups]))
               for s in followers if any(g not in set_groups for _, g in idle_package(s))]
    idle_moves = ask_text(a.idle_moves, 'Moves made from an idle',
                          "Whatever locomotion a stance with an idle lacks - walks, runs, turns on the spot, a jump - "
                          "would play in third person with whatever the engine plays instead: the third person's own "
                          "turn with its own arms, a thrown weapon the one-handed sword's walk. Made from the idle, it "
                          "plays on the third person's legs with the idle's upper body as it holds it on average: "
                          "leaning as the third person does (--idle-lean), and on walks and runs the torso moving "
                          "(--torso-motion) and the arms bouncing (--arm-bounce). Only what the first person lacks is "
                          "made. 'all', 'none', or stances, comma separated. For the stances following the first "
                          "person; those held forward get the idle arms above. In this set they lack: %s." %
                          ('; '.join(lacking) or 'nothing'), IDLE_MOVES, parse_moves)
    idle_moves = set(followers if idle_moves is None else idle_moves)
    idle_sneak = ask_text(a.idle_sneak, 'Sneaks made from an idle',
                          "Stances whose sneaking idle (idle<stance>sneak) and sneaks (sneakforward<stance>...) are "
                          "made from the stance's idle - in place of any the first person has - on the third person's "
                          "sneaking legs: the idle's upper body leaning into the crouch as the third person does "
                          "(--idle-lean), its arms keeping the way they point. The sneaking idle plays the idle "
                          "itself over and over at its own pace, breathing; the sneaks bounce as moves made from an "
                          "idle do. 'all', 'none', or stances, comma separated. This set's idles: %s." %
                          listed([stance_label(s) for s in followers]), IDLE_SNEAK, parse_moves)
    idle_sneak = set(followers if idle_sneak is None else idle_sneak)
    idle_made = sorted(({s for s in NOT_WEAPONS if fill and 'idle' + s in set_groups and in_stances(s, hold)
                         and s not in locomotion_stances(set_groups)} | idle_moves | idle_sneak) & set(idle_stances))
    moves = ask_text(a.moves, 'Walks, runs, sneaks and jumps to convert',
                     "By stance: 'all', 'none', or a list such as '2w, hh' ('plain' for no weapon; '1t' takes in "
                     "'1tstar'). The others are left alone, so the third person's own keep playing for them - made "
                     "from an idle or not. This set has them for: %s%s." % (
                         listed([stance_label(m) for m in locomotion_stances(set_groups)]),
                         '; made from its idle: %s' % listed([stance_label(m) for m in idle_made]) if idle_made else ''),
                     'all', parse_moves)
    in_moves = lambda m: moves is None or m in moves or (m.endswith('star') and m[:-len('star')] in moves)  # noqa: E731
    idle_lean = IDLE_LEAN
    if idle_made:
        idle_lean = ask(a.idle_lean, 'Lean of moves made from an idle (0.0 - 1.0)',
                        "A first-person idle holds the torso upright. Moves made from it lean forward by this share "
                        "of how far the third person's torso leans in the same move against its stance idle - a "
                        "sneak's crouch (about 60 degrees on Animation Compilation's spear sneak), a run (about 20) - "
                        "the arms keeping the way they point and the head its gaze. 0.0 keeps the idle's upright "
                        "torso, on crouching legs too.", IDLE_LEAN, unit)
    align = ask(a.align_steps, "Walks in step with the third person's feet (y/n)",
                "The first person's own walks, runs and sneaks bob, sway and swing their arms in time with their "
                "own steps, which need not fall where the third person's feet strike - Animation Compilation's "
                "beasts strike a quarter of a stride later than its people. y enters the first person's loop "
                "where its right foot strikes as the third person's does, by both sets' footstep keys ('SoundGen: "
                "Right', 'Left'), so it plays in step; n starts both loops together.", True, yes_no)
    torso_motion = ask(a.torso_motion, 'Torso motion on walks, runs and sneaks (0.0 - 2.0)',
                       "First-person walks hold the torso still, which on third-person legs looks rigid. Here it "
                       "moves the way gait studies find people's bodies move over their legs, made from what the "
                       "third person's legs do: it nods forward as the body's weight comes down on each step, the "
                       "chest rolls against the hips' side-to-side sway so the neck stays over the line of the walk "
                       "and leans over the standing leg, and the shoulders swing against the legs, the one opposite "
                       "the leading leg coming forward; the head keeps looking ahead and bobs up and down with it. "
                       "Smooth, and looping with the walk. The next settings say how much of each; this scales them "
                       "all: 1.0 as set, 2.0 twice, 0.0 none (the chest then sways as the "
                       "third person's spine does). Every walk, run and sneak: the first person's own and those "
                       "made from an idle.", TORSO_MOTION, lambda t: bounded(t, 2.0))
    spine_sway = True
    if not torso_motion:
        spine_sway = ask(a.spine_sway, "Chest sways with the third person's spine (y/n)",
                         "With no torso motion of its own, the chest of a walk following the first person can sway as "
                         "the third person's spine does (y), or keep the first person's own (n) - for a first-person "
                         "set that moves its torso already: a third-person set put on another skeleton.",
                         True, yes_no)
    torso_nod = ask_text(a.torso_nod, 'Forward nod through each step (degrees)',
                         "How far the thorax pitches forward and back with each step, twice a stride, in step with "
                         "the third person's footfalls: running, furthest forward 15% of a stride after each foot "
                         "strikes (Preece et al. 2016 measure 6.5 degrees through); walking, just before each heel "
                         "strike (Ceccato et al. 2009: 3, Chung et al. 2010: 4). As 'walk=3.5, run=6.5, sneak=2.5' "
                         "- sneaking is unmeasured, walking's made smaller. A move left out does not nod.",
                         TORSO_NOD, parse_moves_degrees)
    neck_sway = ask(a.neck_sway, "Neck sway kept (0.0 - 1.0)",
                    "The hips sway side to side with each stride; people keep the trunk nearer the line they walk "
                    "(gait studies measure 2 to 6 cm of side-to-side trunk travel), mostly by bending the lower "
                    "back sideways against the pelvis. Here the lower back bends - the chest keeping its measured "
                    "tilt - to carry the neck toward this share of the hips' sway: 0.0 toward none, 1.0 leaves it. "
                    "The bend is kept within %g degrees each way (the lower back bends 16 through in running), "
                    "which on a short lower spine centres only part of a wide sway." % LUMBAR_MOST, NECK_SWAY, unit)
    steady = ask(a.steady_spine, 'Lower spine steady over the hips (0.0 - 1.0)',
                 "The hips tilt and twist with every stride. People take that out in the lower back, so the "
                 "chest rides steady; Animation Compilation's runs pass it up through the lower spine - the top "
                 "bone of the lower body - and take it out higher up, in bones the first person's upper body "
                 "replaces. Then whatever the game plays on the upper body over a walk or run - an attack held "
                 "while running, a spell cast - sways with the hips. This is the share the lower spine takes "
                 "out. The torso motion goes on the bones above it, which such an attack replaces, so it rides "
                 "steady, bobbing with the walk. The legs hang off the lower spine in Morrowind's skeletons and "
                 "are turned back under it: they, the hips and the hips' swing stay the third person's. 0.0 "
                 "leaves the third person's lower spine as it is.",
                 STEADY_SPINE, unit)
    held_motion = ask(a.held_attack_motion, 'Held attacks sway with a walk (0.0 - 1.0)',
                      "The share of a walk's torso motion - its nod, shoulder swing and lean - that goes on the lower "
                      "spine instead of the chest, so an attack held over the walk or run (which replaces the chest "
                      "up) moves with it that much: a little keeps it from riding stiff, much swings it about. The "
                      "walk's own torso moves the same either way. 0.0 holds it steady.", HELD_MOTION, unit)
    arm_facing = ask(a.keep_arm_facing, 'Arms keep their facing on a walk (0.0 - 1.0)',
                     "While a walk's torso nods, swings and leans over the legs (the torso motion), the share of the "
                     "way the arms faced that they keep: 1.0 keeps it, the hands carried along by the shoulders "
                     "only - arms held forward, a guard or a spell ready, stay pointed ahead as the body swings "
                     "under them; 0.0 turns them with the torso.", ARM_FACING, unit)
    face = ask(a.face_forward, 'Walks face forward (0.0 - 1.0)',
               "Strafing turns the hips the way it goes - Animation Compilation's (vanilla's) hand-to-hand strafes "
               "by up to 70 degrees, the two-handed sword's 44, the one-handed 16 - and an attack held while "
               "strafing, which plays from the chest up on the strafe's lower spine, turned with them: the swing "
               "and the head off to the side. This is the share of that turn the lower spine of a walk, run or "
               "sneak turns back to face as the stance idle's does; the legs and hips stay as they are, the waist "
               "twisting between them, and the walk's own chest faces as it did. 1.0 takes it all out.",
               FACE_FORWARD, unit)
    split = ask(a.split_follows, 'Each follow-through its own recovery (y/n)',
                "An attack has a short, a medium and a long follow-through, the game picking one by how long the "
                "attack was held. The game's own run one after another, each from the hit back to the idle. "
                "ReAnimation's start together and cut the weaker ones short of the recovery, so a quick attack "
                "stopped 60 to 90 degrees from the idle the game then goes back to - and the next attack "
                "starts from - and the third person's legs, timed through the keys both share, jumped from one "
                "of its follow-throughs to another. y copies each weaker one to a place of its own, ending on "
                "the idle like the long one - or, for an attack ReAnimation plays a tail after, where the long "
                "one ends and the tail takes up.",
                SPLIT_FOLLOWS, yes_no)
    if split:
        for name, kf in first_files:
            done = split_follows(kf)
            if done:
                info('  %-28s follow-throughs split: %s' % (name, ', '.join(done)))
    start_idle = ask(a.start_from_idle, 'Attacks start on the idle (y/n)',
                     "Attacks end on their stance idle's first frame; y has them start there too, easing out of "
                     "it over the first third of the wind-up (to the attack's 'min attack'), %g seconds at most, "
                     "so a quick one still swings. Then attacks chained one into another - and into the idle - "
                     "meet without a jump in pose." % START_MOST, START_FROM_IDLE, yes_no)
    align = ask_text(a.align_to_third, 'Groups placed as the third person has them on the timeline',
                     "OpenMW drives a held thrown weapon's own mesh animation with the absolute time of the "
                     "'throwweapon' group in its file. Mesh replacers that spin the knife in flight (0 to 4 "
                     "seconds) are made for vanilla's layout, where the group sits far later; at 0 to 4 seconds "
                     "the knife in hand jumps to its flight pose. Files with these groups are moved, whole, so "
                     "the group's first key lands where the third person has it. 'none' for none.",
                     ALIGN_TO_THIRD, lambda text: [] if str(text).strip().lower() == 'none' else word_list(text))
    max_twist = ask(a.max_twist, 'Most the waist twists (degrees)',
                    "People twist only so far between hips and shoulders - a golf swing's, the most there is, some "
                    "45 to 55 degrees - and turn the hips beyond it. A first-person torso, turned as far as its camera "
                    "wants, on third-person hips that never meant to follow it, twists far past that: ReAnimation's "
                    "spear chops over 110 degrees. Past this many degrees (measured between the line of the shoulders "
                    "and the line of the hip joints), in idles, attacks, turns and jumps whose upper body is the "
                    "first person's, the hips turn after the shoulders by the rest, the chest staying where it faces "
                    "and the legs bending to keep the feet where they were, the knees turning half as far. 0 never "
                    "turns them.", MAX_TWIST, lambda text: bounded(text, 180.0))
    straight = ask(a.straight_starts, 'Walks start and stop straight (y/n)',
                   "A walk's lead-in - from standing to its loop - and its tail move the actor by their root as the "
                   "loop does. Vanilla's two-handed strafes, and so Animation Compilation's, start with the root some "
                   "15 units forward of where the loop runs and slide it back in the first steps, so the actor steps "
                   "back 14 units every time it starts to strafe. y takes the root's travel across the loop's way "
                   "out of lead-ins and tails; the body does as it did, the actor going only the way it walks.",
                   STRAIGHT_STARTS, yes_no)
    shoulder_swing = ask_text(a.shoulder_swing, 'Shoulder swing through each stride (degrees)',
                              "With every stride the thorax turns, the shoulder opposite the striking foot coming "
                              "forward - the arm swing's counter-rotation, the trunk's largest motion in running. "
                              "Running: turning over during each stance and held through flight (Preece et al. 2016 "
                              "measure 24 degrees through; Seay et al. 2011, 25). Walking: a near-sine wave, furthest "
                              "just before each heel strike (Ceccato et al. 2009: the shoulder line 10 degrees; "
                              "Huthwelker et al. 2023: the mid-thorax 15). Only as much of it as the move goes forward "
                              "or back - strafes balance no fore-aft leg swing. As 'walk=10, run=24, sneak=7' "
                              "(sneaking unmeasured); both hands on a weapon turn it with them. A move left out does "
                              "not swing.",
                              SHOULDER_SWING, parse_moves_degrees)
    stance_lean = ask_text(a.stance_lean, 'Lean over the standing leg (degrees)',
                           "With every stride the thorax tilts toward the leg it stands on, most early in the stance "
                           "- 5-10% of a stride after the foot strikes running (Preece et al. 2016: 8 degrees "
                           "through), at the other foot's toe-off walking (Ceccato et al. 2009: the shoulders 4; "
                           "Chung et al. 2010: 3.1-3.5) - on top of the roll that keeps the neck centred. As "
                           "'walk=3.5, run=8, sneak=2.5' (sneaking unmeasured); a move left out does not tilt.",
                           STANCE_LEAN, parse_moves_degrees)
    torso_lean = ask_text(a.torso_lean, 'Least forward lean of walks, runs and sneaks (degrees)',
                          "Where the torso would lean back of this anywhere - first-person torsos often stand upright "
                          "or tipped back (ReAnimation's two-handed ones, 4 degrees back), and the bounce adds its own "
                          "- the whole walk is leaned forward until it does not: so it bounces forward, down and to "
                          "the sides, and never bends back. As 'walk=3, run=8, sneak=3': degrees forward from upright "
                          "(the line from the chest's base to the neck), for walks, runs and sneaks. A move left out, "
                          "or 'none', is not leaned. The arms keep the way they point, the head its gaze.",
                          TORSO_LEAN, parse_leans)
    breathing = ask(a.breathing, 'Breathing in idles (degrees)',
                    "Idles whose upper body is the first person's hold it still. Each breathes - one breath for "
                    "about every %g seconds of its loop, so one for a %g-second idle - looping seamlessly: the chest "
                    "turns up and back about its base by this many degrees at a full breath, the shoulders lifting "
                    "with it, breathing in quicker than out. Rotations only; the head keeps its gaze and the arms "
                    "the way they point, so a weapon held in both hands stays in them. 0 for none." % (
                        BREATH_SECONDS, BREATH_SECONDS), BREATHING, lambda t: bounded(t, 10.0))
    plant = ask(a.remove_attack_root_motion, 'Remove root motion from attacks (y/n)',
                "Attack sections move the root over the ground - a lunge - and the engine moves the actor by "
                "it. A quick attack plays only part of its wind up and then its release from the matching "
                "point on, so the root's travel over the two need not cancel out: spamming Animation "
                "Compilation's two-handed slash drifts the actor back 6 to 10 units a click. y moves that "
                "travel onto the pelvis instead - the body and feet lunge as before, the actor stays put - "
                "for every section of every attack group, equips and tails included.", PLANT_ATTACKS, yes_no)
    settle_for = ask(a.settle, "Attacks end on the idle's first frame (seconds)",
                     "Each attack's follow-through - its tail, where ReAnimation plays one after it - crossfades "
                     "into the first frame of its stance's converted idle over its last third, but this many "
                     "seconds at most, so the idle picks up where the attack ends without a pop. Every bone but the root's travel "
                     "over the ground, which moves the actor. Where an attack starts needs nothing: the game "
                     "blends into it. 0 for none.", SETTLE, lambda t: bounded(t, 2.0))
    bounce = ask(a.arm_bounce, 'Arm bounce on moves made from an idle (0.0 - 1.0)',
                 "On walks, runs and sneaks made from an idle, whose arms would otherwise be held still: the elbows "
                 "and wrists lag behind the body's bob and sway and spring back, as a spring would move them - "
                 "looping as they do. 1.0 is the whole of what the spring does; 0.0 is off.", ARM_BOUNCE, unit)
    # A default comes back as it is (False): through the parser, every answer is a stance set or None.
    bounce_walks = parse_stances_or_yes_no(ask(a.arm_bounce_walks, "Arm bounce on the first person's own walks too (y/n, or stances)",
                       "The first person's own walks, runs and sneaks move the arms already; y bounces them on top, "
                       "by the same amount; stances, comma separated, only theirs.", False, parse_stances_or_yes_no))
    bounce_real_time = parse_stances_or_yes_no(ask(a.arm_bounce_real_time, "Arm bounce in the walk's own time (y/n, or stances)",
                           "The spring is run over the walk's samples. n steps each as a frame, as sets were built "
                           "before this setting: a forward walk or run has three or four samples to a frame (every "
                           "key time of the third person's legs), so its arms barely bounce while the other "
                           "directions' do. y runs it in the walk's own time, so every walk bounces as much as "
                           "--arm-bounce says. Stances, comma separated: only theirs.", False, parse_stances_or_yes_no))
    moving = set(idle_made) | {base_and_stance(g)[1] for g in set_groups
                               if is_move(g) and in_stances(base_and_stance(g)[1], bounce_walks)}
    moving = [m for m in sorted(moving) if in_moves(m)]
    if a.arm_bounce_by is not None:
        bounce_by = parse_stance_values(a.arm_bounce_by)
    else:
        bounce_by = {}
        if bounce and moving and ask(None, 'Arm bounce by weapon type (y/n)',
                                     "Set the arm bounce for each weapon type whose arms bounce, one question each - "
                                     "%d: %s. n: %g for all of them. (On the command line: --arm-bounce-by "
                                     "'2w=0.2, hh=0.5'.)" % (len(moving), listed([stance_label(m) for m in moving]),
                                                              bounce), False, yes_no):
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
                 "'bowandarrow1=bowandarrow@shoot max attack'. Moves made from an idle take legs given here too: "
                 "'walkforwardkatar=walkforward1h'. Empty: none.")
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
    legs_from = {aliased(group): pair for group, pair in legs_from.items()}  # a set's own names, as read
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
    ctx = {'first_rest': rest_of(raw, reference), 'first_dir': first_dir, 'set_keys': set_groups,
           'first_idles': first_idles, 'first_idle_files': first_idle_files}
    # What the sneaks made from an idle take the place of: the first person's own, if it has any.
    sneaks_made = {group for s in idle_sneak if 'idle' + s in first_idles
                   for group in [m + s for m in MOVES if m.startswith('sneak')]
                   + ([] if 'idle%ssneak' % s in first_idles else ['idle%ssneak' % s])}
    opts = {'keep': keep, 'fill': fill, 'hold_torso': hold, 'steady_head': steady_head, 'third_timing': third_timing, 'lower': lower, 'repoint': repoint, 'two_handed_follow': two_handed,
            'bounce': bounce, 'bounce_by': bounce_by, 'bounce_walks': bounce_walks, 'bounce_real_time': bounce_real_time, 'grip': grip, 'moves': moves,
            'idle_moves': idle_moves, 'idle_sneak': idle_sneak, 'idle_lean': idle_lean, 'sneaks_made': sneaks_made,
            'align_steps': align, 'spine_sway': spine_sway, 'torso_motion': torso_motion, 'torso_nod': torso_nod, 'neck_sway': neck_sway, 'shoulder_swing': shoulder_swing, 'stance_lean': stance_lean, 'steady_spine': steady, 'held_motion': held_motion, 'arm_facing': arm_facing, 'face_forward': face, 'max_twist': max_twist, 'start_from_idle': start_idle, 'align': align, 'straight_starts': straight,
            'torso_lean': torso_lean, 'breathing': breathing, 'settle': settle_for, 'plant': plant,
            'skip': skip, 'legs_from': legs_from, 'unpaired': unpaired, 'prefix': prefix}
    ctx['opts'] = opts
    def stance_set(chosen):
        return 'all' if chosen is None else listed(sorted('plain' if m == '' else m for m in chosen))
    print('\n%d first-person files from %s%s (root and legs where missing: %s); torso held forward for %s, '
          'the first person\'s for the rest%s; the third person\'s timing for %s; keep forward %.2f, arms '
          'pointed %.2f%s; moves made from the idle for %s, sneaks for %s (leaning %.2f as the third person); '
          'torso motion %.2f (nod %s, shoulder swing %s, stance lean %s, neck sway %.2f, lower spine steady %.2f, arms keeping %.2f of their facing), leaning at least %s; breathing %g deg; attacks settling over %g s%s; arm bounce %.2f%s%s%s%s%s%s' % (
        len(first_files), first_dir, ' (left out: %s)' % ', '.join(left_out) if left_out else '', reference_label,
        stance_set(hold), ' (head looking straight ahead)' if steady_head else '', stance_set(third_timing),
        keep, repoint, ' (two-handed on the torso)' if two_handed else '', stance_set(idle_moves),
        stance_set(idle_sneak), idle_lean, torso_motion,
        listed(['%s %g deg' % (m, torso_nod[m]) for m in ('walk', 'run', 'sneak') if m in torso_nod]),
        listed(['%s %g deg' % (m, shoulder_swing[m]) for m in ('walk', 'run', 'sneak') if m in shoulder_swing]),
        listed(['%s %g deg' % (m, stance_lean[m]) for m in ('walk', 'run', 'sneak') if m in stance_lean]), neck_sway, steady,
        arm_facing,
        listed(['%s %g deg' % (m, torso_lean[m]) for m in ('walk', 'run', 'sneak') if m in torso_lean]), breathing, settle_for,
        ', in place' if plant else ', root motion kept',
        bounce, (' (on the first person\'s own walks too)' if bounce_walks is None
                 else ' (on moves made from an idle, and %s\'s own walks)' % stance_set(bounce_walks) if bounce_walks
                 else ' (on moves made from an idle)')
        + (' in real time' if bounce_real_time is None
           else ' in real time for %s' % stance_set(bounce_real_time) if bounce_real_time else ''),
        ''.join(', %s %g' % (m or 'plain', v) for m, v in sorted(bounce_by.items())),
        ' (two-handed: the left hand on the grip)' if grip and bounce else '',
        '' if fill else ', no idle-arm turns, walks and jumps',
        ''.join(', %s%s arms lowered up to %g deg' % (g, ' ' + s if s else '', d) for g, s, d in lower),
        '' if moves is None else ', walks, runs, sneaks and jumps of %s only' % listed(
            sorted('plain' if m == '' else m for m in moves))))
    chosen = [sk for sk in SKELETONS if (beasts or sk != 'xbase_animkna') and (women or sk != 'xbase_anim_female')]
    work = work_seconds(first_files, opts)
    fills = bool(idle_made)
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
        # The skeleton's bones: the first person's extra finger joints, and toes a human's lacks, left out.
        mesh = None if a.keep_bones else vanilla_file(SKELETON_MESHES[skeleton],
                                                      "%s's bones, to leave out what it lacks" % skeleton)
        ctx['bones'] = {b.lower() for b in node_names(mesh)} if mesh is not None else None
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
