"""Builds Full Body Awareness versions of 1st-person animations (the FBA Compatibility folder).

1. Every kf is offered to the merge (fba_merge.py): 3rd-person legs and root motion under our upper
   body. Groups it does not recognise keep their own legs, with a warning.
2. Every kf with a chest gets the forward chest lean (fba_posture.py), merged ones included.

Hands come from the separate "FBA 1st-Person Hands" package (fba_fingers.py): vanilla 1st-person
hand meshes back, and FBA's own animations converted to the 1st-person fingers.

Always starts from the originals, so re-running never stacks anything. Parameters not given on the
command line are asked for with their default pre-filled (Enter keeps it); without a console the
defaults are used.

Usage: python3 build_compat.py [-y] [-v] [--fba DIR] [--anims DIR] [--out DIR] [--lean DEG]
                               [--hip-motion 0..1] [--sway 0..1] [--idle-when-feet-lift y/n]
See README.md next to this file.
"""
import argparse
import math
import os
import sys

import fba_merge
import fba_posture
import nifkf
import params
from params import ask, yes_no

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
# Defaults: this mod's animations, the compatibility folder next to it in the mods folder, FBA as
# installed here.
SRC = os.path.join(MOD, 'Animations', 'xbase_anim.1st')
OUT = os.path.join(os.path.dirname(MOD), 'ReAnimation FBA Compatibility', 'Animations', 'xbase_anim.1st')
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
    sys.exit('No kf in %s keys the whole spine and legs - is that an Animations/xbase_anim.1st folder?' % folder)


LEAN = 15.0
HIP_MOTION = 0.5
SWAY = 0.33
IDLE_WHEN_FEET_LIFT = True


def parameters():
    p = argparse.ArgumentParser(
        description='Builds the ReAnimation FBA Compatibility folder. Settings not given here are asked '
                    'for, with the default filled in (Enter keeps it).')
    p.add_argument('-y', '--yes', action='store_true', help='use the defaults for everything not given, no questions')
    p.add_argument('-v', '--verbose', action='store_true', help='print per-group detail while building')
    p.add_argument('--fba', metavar='DIR', help="FBA's folder (has meshes/xbase_anim.1st.kf)")
    p.add_argument('--anims', metavar='DIR', help='1st-person animations to convert')
    p.add_argument('--out', metavar='DIR', help='where the converted animations go')
    p.add_argument('--lean', metavar='DEG', help='extra forward chest lean (default %g)' % LEAN)
    p.add_argument('--hip-motion', metavar='0..1', help='share of the attack hip lunge kept (default %g)' % HIP_MOTION)
    p.add_argument('--sway', metavar='0..1', help='share of the walk/run hip swing kept (default %g)' % SWAY)
    p.add_argument('--idle-when-feet-lift', metavar='y/n',
                   help='idle legs where FBA lifts both feet (default %s)' % ('y' if IDLE_WHEN_FEET_LIFT else 'n'))
    a = p.parse_args()
    params.USE_DEFAULTS = a.yes
    fba_merge.VERBOSE = a.verbose
    fba = ask(a.fba, 'FBA folder', 'The one with meshes/xbase_anim.1st.kf.', params.find_fba(), str)
    anims = ask(a.anims, 'Animations to convert', "ReAnimation's Animations/xbase_anim.1st folder.", SRC, str)
    out = ask(a.out, 'Output folder', 'Load its data folder after ReAnimation and FBA.', OUT, str)
    lean = ask(a.lean, 'Chest lean (degrees)',
               "Leans the chest forward so it doesn't fill the view when looking down.", LEAN, float)
    hip = ask(a.hip_motion, 'Hip motion during attacks (0.0 - 1.0)',
              "Share of FBA's hip lunge kept. Below 1.0 steps shorten to match; if feet glitch, use 1.0.",
              HIP_MOTION, float)
    sway = ask(a.sway, 'Hip swing while moving (0.0 - 1.0)',
               'Share of the walk/run hip swing passed to the upper body.', SWAY, float)
    idle = ask(a.idle_when_feet_lift, 'Idle legs where FBA lifts both feet (y/n)',
               'Keeps the crossbow reload from becoming a mid-air squat.', IDLE_WHEN_FEET_LIFT, yes_no)
    for name, value in (('hip motion', hip), ('spine swing', sway)):
        if not 0.0 <= value <= 1.0:
            sys.exit('%s must be between 0.0 and 1.0, got %s' % (name, value))
    return fba, anims, out, lean, hip, sway, idle


def main():
    fba, anims, out, lean, hip, sway, idle = parameters()
    third_person = find_file(fba, 'xbase_anim.1st.kf')
    if third_person is None:
        sys.exit('No xbase_anim.1st.kf under %s - is that the FBA folder?' % fba)
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
    for i, name in enumerate(names, 1):
        fba_merge.info('== merge ' + name)
        segments = fba_merge.build(os.path.join(anims, name), third_person, os.path.join(out, name), reference)
        if segments is not None:
            if fba_merge.VERBOSE:
                fba_merge.report(segments)
            merged.add(name)
        if not fba_merge.VERBOSE:
            print('%3d/%d  %s' % (i, len(names), name))

    leaned = 0
    for name in names:
        kf = nifkf.KF.load(os.path.join(out if name in merged else anims, name))
        changed = False
        if fba_posture.has_chest(kf):
            fallbacks = fba_posture.lean(kf, reference)
            if fallbacks:
                fba_merge.info('   %s: %s from %s' % (name, ', '.join(fallbacks), reference_name))
            leaned += 1
            changed = True
        else:
            fba_merge.info('   does not rotate the chest, not leaned: ' + name)
        if changed or name in merged:
            kf.save(os.path.join(out, name))
    print('merged %d of %d kfs, leaned %d by %.1f deg' % (len(merged), len(names), leaned, lean))
    if fba_merge.WARNINGS:
        print('\n%d warnings - left as they were:' % len(fba_merge.WARNINGS))
        for w in fba_merge.WARNINGS:
            print('  ' + w)


if __name__ == '__main__':
    main()
