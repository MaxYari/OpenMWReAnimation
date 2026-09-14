"""Builds Full Body Awareness versions of 1st-person animations (the FBA Compatibility folder).

1. Every kf is offered to the merge (fba_merge.py): 3rd-person legs and root motion under our upper
   body. Groups it does not recognise keep their own legs, with a warning.
2. Every kf with a chest gets the forward chest lean (fba_posture.py), merged ones included.

Hands come from the separate "FBA 1st-Person Hands" package (fba_fingers.py): vanilla 1st-person
hand meshes back, and FBA's own animations converted to the 1st-person fingers.

Always starts from the originals, so re-running never stacks anything. Parameters not given on the
command line are asked for with their default pre-filled (Enter keeps it); without a console the
defaults are used.

Usage: python3 build_compat.py [--fba DIR] [--anims DIR] [--out DIR] [--lean DEG]
                               [--hip-motion 0..1] [--sway 0..1] [--idle-when-feet-lift y/n]
"""
import argparse
import math
import os

import fba_merge
import fba_posture
import nifkf
from params import ask, yes_no

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
# Defaults: this mod's animations, the compatibility folder next to it in the mods folder, FBA as
# installed here.
SRC = os.path.join(MOD, 'Animations', 'xbase_anim.1st')
OUT = os.path.join(os.path.dirname(MOD), 'ReAnimation FBA Compatibility', 'Animations', 'xbase_anim.1st')
FBA_FOLDER = ('/run/media/deck/350243d8-7578-45fe-a92c-ff83eadd4827/Games/openmw mods/'
              '(FBA Bodies-Wearables) Vanilla and Pluginless VSBR-56625-2-3-1748243171/'
              'OpenMW Full Body Awareness')
THIRD_PERSON = os.path.join(FBA_FOLDER, 'meshes', 'xbase_anim.1st.kf')
ALL_KFS = sorted(n for n in os.listdir(SRC) if n.lower().endswith('.kf'))
REFERENCE = 'x2cIdle.kf'  # check_all's rig pose; builds pick one themselves (find_reference)

REFERENCE_BONES = fba_merge.LOWER_BONES + ['Bip01 Spine1', 'Bip01 Spine2', 'Bip01 Neck', 'Bip01 Head']


def find_file(folder, name):
    """Case-insensitive search for name under folder."""
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower() == name.lower():
                return os.path.join(root, f)
    return None


def find_reference(folder, names):
    """The rig's pose for bones a kf does not key: the first kf keying the whole spine and legs."""
    for name in names:
        kf = nifkf.KF.load(os.path.join(folder, name))
        if all(b in kf.bone_data and kf.data(b).trans['keys'] and (kf.data(b).quat_keys or kf.data(b).xyz)
               for b in REFERENCE_BONES):
            return name, kf
    raise ValueError('no kf in %s keys the whole spine and legs to take the rig pose from' % folder)


def parameters():
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--fba')
    p.add_argument('--anims')
    p.add_argument('--out')
    p.add_argument('--lean')
    p.add_argument('--hip-motion')
    p.add_argument('--sway')
    p.add_argument('--idle-when-feet-lift')
    a = p.parse_args()
    fba = ask(a.fba, 'FBA folder',
              "OpenMW Full Body Awareness's folder, the one with meshes/xbase_anim.1st.kf: its 3rd-person "
              'animations give the legs.', FBA_FOLDER, str)
    anims = ask(a.anims, '1st-person animations folder',
                "The animation mod's Animations/xbase_anim.1st folder, whose kfs get converted.", SRC, str)
    out = ask(a.out, 'Output folder',
              "Where the converted kfs go: Animations/xbase_anim.1st inside a data folder loaded after "
              'the animation mod.', OUT, str)
    lean = ask(a.lean, 'Additional chest lean (degrees)',
               "Leans the chest forward the way FBA's own poses do, which keeps it from filling most of the "
               'screen when looking down. The neck is counter-rotated, so arms and view stay framed as '
               'animated.', 15.0, float)
    hip = ask(a.hip_motion, 'Amount of hip motion during attacks (0.0 - 1.0)',
              "FBA uses 3rd-person animations as a base, and those lunge the hips forward and back during "
              'attacks (20-40 units). At 1.0 all of it is kept: body and camera lunge with the swing while '
              'the feet stay planted and your position does not change. Below 1.0 the lunge is scaled '
              'down and the feet are placed intelligently (steps shortened by the same amount) so they '
              "don't slide, but they might glitch out in some way; if they do, use 1.0.", 1.0, float)
    sway = ask(a.sway, 'Spine swing kept while moving (0.0 - 1.0)',
               "Share of the 3rd-person walk and run hip swing passed on to the upper body. Its average lean "
               'is always removed, so weapons stay centered.', 0.33, float)
    idle = ask(a.idle_when_feet_lift, 'Idle legs where FBA lifts both feet off the floor (y/n)',
               "Some FBA attack sections leave the floor once our upper body is kept upright: the crossbow "
               "reload bends over in 3rd person, which becomes a mid-air squat. Yes gives those sections "
               "the weapon's idle legs.", True, yes_no)
    for name, value in (('hip motion', hip), ('spine swing', sway)):
        if not 0.0 <= value <= 1.0:
            raise ValueError('%s must be between 0.0 and 1.0, got %s' % (name, value))
    return fba, anims, out, lean, hip, sway, idle


def main():
    fba, anims, out, lean, hip, sway, idle = parameters()
    third_person = find_file(fba, 'xbase_anim.1st.kf')
    if third_person is None:
        raise ValueError('no xbase_anim.1st.kf under %s: is this the FBA folder?' % fba)
    fba_posture.TILT = math.radians(lean)
    fba_merge.HIP_MOTION = hip
    fba_merge.SWAY = sway
    fba_merge.IDLE_WHEN_FEET_LIFT = idle

    names = sorted(n for n in os.listdir(anims) if n.lower().endswith('.kf'))
    os.makedirs(out, exist_ok=True)
    reference_name, reference = find_reference(anims, names)
    print('\nrig pose from %s; lean %.1f deg, hip motion %.2f, spine swing %.2f, idle legs where feet lift: %s'
          % (reference_name, lean, hip, sway, 'yes' if idle else 'no'))

    merged = set()
    for name in names:
        print('== merge', name)
        segments = fba_merge.build(os.path.join(anims, name), third_person, os.path.join(out, name), reference)
        if segments is not None:
            fba_merge.report(segments)
            merged.add(name)

    leaned = 0
    for name in names:
        kf = nifkf.KF.load(os.path.join(out if name in merged else anims, name))
        changed = False
        if fba_posture.has_chest(kf):
            fallbacks = fba_posture.lean(kf, reference)
            if fallbacks:
                print('   %s: %s from %s' % (name, ', '.join(fallbacks), reference_name))
            leaned += 1
            changed = True
        else:
            print('   does not rotate the chest, not leaned:', name)
        if changed or name in merged:
            kf.save(os.path.join(out, name))
    print('merged %d of %d kfs, leaned %d by %.1f deg' % (len(merged), len(names), leaned, lean))
    if fba_merge.WARNINGS:
        print('\n%d warnings - left as they were:' % len(fba_merge.WARNINGS))
        for w in fba_merge.WARNINGS:
            print('  ' + w)


if __name__ == '__main__':
    main()
