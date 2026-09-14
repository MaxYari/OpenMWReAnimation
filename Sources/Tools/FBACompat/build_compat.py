"""Builds the FBA Compatibility folder's animations from ReAnimation's 1st-person kfs.

1. kfs in MERGED get 3rd-person legs (fba_merge.py).
2. Every kf with a chest gets the forward chest lean (fba_posture.py), merged ones included.
Hands come from the separate "FBA 1st-Person Hands" package (fba_fingers.py): vanilla 1st-person
hand meshes back, and FBA's own animations converted to the 1st-person fingers.

Always starts from the originals, so re-running never stacks the lean.

Usage: python3 build_compat.py
"""
import os
import re

import fba_merge
import fba_posture
import nifkf

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
SRC = os.path.join(MOD, 'Animations', 'xbase_anim.1st')
OUT = os.path.join(MOD, 'FBA Compatibility', 'Animations', 'xbase_anim.1st')
THIRD_PERSON = ('/run/media/deck/350243d8-7578-45fe-a92c-ff83eadd4827/Games/openmw mods/'
                '(FBA Bodies-Wearables) Vanilla and Pluginless VSBR-56625-2-3-1748243171/'
                'OpenMW Full Body Awareness/meshes/xbase_anim.1st.kf')
# Every kf is offered to the merge; groups it does not recognise keep their legs, with a warning.
ALL_KFS = sorted(n for n in os.listdir(SRC) if n.lower().endswith('.kf'))
# Our rig's pose for parent bones a kf does not key (the bow set has no Bip01, for one).
REFERENCE = 'x2cIdle.kf'


def main():
    os.makedirs(OUT, exist_ok=True)
    reference = nifkf.KF.load(os.path.join(SRC, REFERENCE))
    merged = set()
    for name in ALL_KFS:
        print('== merge', name)
        segments = fba_merge.build(os.path.join(SRC, name), THIRD_PERSON, os.path.join(OUT, name), reference)
        if segments is not None:
            fba_merge.report(segments)
            merged.add(name)

    leaned = 0
    for name in ALL_KFS:
        kf = nifkf.KF.load(os.path.join(OUT if name in merged else SRC, name))
        changed = False
        if fba_posture.has_chest(kf):
            fallbacks = fba_posture.lean(kf, reference)
            if fallbacks:
                print('   %s: %s from %s' % (name, ', '.join(fallbacks), REFERENCE))
            leaned += 1
            changed = True
        else:
            print('   does not rotate the chest, not leaned:', name)
        if changed or name in merged:
            kf.save(os.path.join(OUT, name))
    print('merged %d of %d kfs, leaned %d by %.1f deg'
          % (len(merged), len(ALL_KFS), leaned, fba_posture.TILT * 180 / 3.141592653589793))
    if fba_merge.WARNINGS:
        print('\n%d warnings - left as they were:' % len(fba_merge.WARNINGS))
        for w in fba_merge.WARNINGS:
            print('  ' + w)


if __name__ == '__main__':
    main()
