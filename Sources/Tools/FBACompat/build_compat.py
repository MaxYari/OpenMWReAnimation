"""Builds the FBA Compatibility folder's animations from ReAnimation's 1st-person kfs.

1. kfs in MERGED get 3rd-person legs (fba_merge.py).
2. Every kf with a chest gets the forward chest lean (fba_posture.py), merged ones included.

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
# Weapon sets merged so far: one-handed (the v2 set lives in _xReanimationv1.kf), 2c and 2w.
MERGED = sorted(n for n in os.listdir(SRC)
                if n.endswith('.kf') and (re.match(r'x(1h|2c|2w)', n) or n == '_xReanimationv1.kf'))
# Our rig's pose for parent bones a kf does not key (the bow set has no Bip01, for one).
REFERENCE = 'x2cIdle.kf'


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in MERGED:
        print('== merge', name)
        fba_merge.report(fba_merge.build(os.path.join(SRC, name), THIRD_PERSON, os.path.join(OUT, name)))

    reference = nifkf.KF.load(os.path.join(SRC, REFERENCE))

    leaned = skipped = 0
    for name in sorted(os.listdir(SRC)):
        if not name.lower().endswith('.kf'):
            continue
        kf = nifkf.KF.load(os.path.join(OUT if name in MERGED else SRC, name))
        if not fba_posture.has_chest(kf):
            print('   does not rotate the chest, left as is:', name)
            skipped += 1
            continue
        fallbacks = fba_posture.lean(kf, reference)
        if fallbacks:
            print('   %s: %s from %s' % (name, ', '.join(fallbacks), REFERENCE))
        kf.save(os.path.join(OUT, name))
        leaned += 1
    print('leaned %d kfs by %.1f deg, skipped %d' % (leaned, fba_posture.TILT * 180 / 3.141592653589793, skipped))


if __name__ == '__main__':
    main()
