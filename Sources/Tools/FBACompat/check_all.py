"""Checks built compat kfs against the originals, group by group (merged kfs have a new timeline,
so times are matched relative to each group).

Per group: Spine and Neck world rotation against ours (the base the upper body sits on, and what
carries head, camera and arms: ~0, or the kept swing in locomotion), how far the chest (Spine2)
turned (the lean), the feet's height range, and root motion (velocity in locomotion, none else).
Locomotion also shows which foot is lower at each step marker ('!' when it is the other one).

Usage: python3 check_all.py [--anims DIR] [--out DIR] [kf names...]
"""
import argparse
import math
import os

import kfeval as E
import nifkf
from build_compat import SRC, OUT, REFERENCE, find_reference, kf_names
from fba_merge import LOCOMOTION, Group, all_group_keys, text_lines
from fba_posture import pose_rotation, pose_translation

# The rig pose for bones a kf does not key, set by main().
_reference = None


class _World:
    """E.world, with bones a kf does not key taken from the rig reference (the bow set has no Bip01)."""

    @staticmethod
    def world(kf, bone, t):
        chain = []
        b = bone
        while b:
            chain.append(b)
            b = E.PARENT.get(b)
        rot = (1.0, 0.0, 0.0, 0.0)
        pos = (0.0, 0.0, 0.0)
        for b in reversed(chain):
            lt = pose_translation(kf, _reference, b, t)
            pos = tuple(p + c for p, c in zip(pos, E.qrot(rot, lt)))
            rot = E.qmul(rot, pose_rotation(kf, _reference, b, t))
        return rot, pos


E.world = _World.world


def horizontal(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def check(name, anims, built):
    ours = nifkf.KF.load(os.path.join(anims, name))
    if not os.path.exists(os.path.join(built, name)):
        print('== %s: not in the compat folder' % name)
        return
    out = nifkf.KF.load(os.path.join(built, name))
    our_lines, out_lines = text_lines(ours), text_lines(out)
    our_groups, out_groups = all_group_keys(our_lines), all_group_keys(out_lines)
    print('== %s' % name)
    for g, km in sorted(out_groups.items(), key=lambda x: min(x[1].values())):
        ko = our_groups[g]
        loco = LOCOMOTION.match(g) and 'start' in km
        if loco:
            gm, go = Group(out_lines, g), Group(our_lines, g)
            a, b = gm.loop_start, gm.loop_stop
            mapped = lambda t: go.loop_start + ((t - a) % go.period)
        else:
            a, b = min(km.values()), max(km.values())
            mapped = lambda t, d=min(ko.values()) - a: t + d
        ts = [a + (b - a) * i / 60 for i in range(61)]
        spine = neck = 0.0
        turn = []
        for t in ts:
            to = mapped(t)
            spine = max(spine, E.qangle(E.world(out, 'Bip01 Spine', t)[0], E.world(ours, 'Bip01 Spine', to)[0]))
            neck = max(neck, E.qangle(E.world(out, 'Bip01 Neck', t)[0], E.world(ours, 'Bip01 Neck', to)[0]))
            turn.append(E.qangle(E.world(out, 'Bip01 Spine2', t)[0], E.world(ours, 'Bip01 Spine2', to)[0]))
        lz = [E.world(out, 'Bip01 L Foot', t)[1][2] for t in ts]
        rz = [E.world(out, 'Bip01 R Foot', t)[1][2] for t in ts]
        # Bip01 from the rig reference when the kf does not key it (the bow set).
        root = lambda t: pose_translation(out, _reference, 'Bip01', t)
        if loco and b > a:
            motion = 'vel %6.1f' % (horizontal(root(a), root(b)) / (b - a))
            steps = []
            for phase, foot in gm.steps:
                t = a + phase
                l, r = E.world(out, 'Bip01 L Foot', t)[1][2], E.world(out, 'Bip01 R Foot', t)[1][2]
                steps.append('%s%s' % (foot[0].upper(), '' if (l < r) == (foot == 'left') else '!'))
            motion += ' steps ' + ''.join(steps)
        else:
            motion = 'root xy %.2f' % max(math.hypot(*root(t)[:2]) for t in ts)
        print('  %-24s spine %5.2f neck %5.2f | chest turned %4.1f..%4.1f | feet z L %5.1f..%5.1f R %5.1f..%5.1f | %s'
              % (g, spine, neck, min(turn), max(turn), min(lz), max(lz), min(rz), max(rz), motion))


def main():
    global _reference
    p = argparse.ArgumentParser(description='Compares built FBA compatibility kfs with the originals.')
    p.add_argument('names', nargs='*', metavar='KF', help='kf names (default: every kf in --anims)')
    p.add_argument('--anims', metavar='DIR', default=SRC, help="the original animations (default: ReAnimation's)")
    p.add_argument('--out', metavar='DIR', default=OUT, help='the converted ones (default: 01 FBA Compatibility)')
    a = p.parse_args()
    names = a.names or kf_names(a.anims)
    if os.path.exists(os.path.join(a.anims, REFERENCE)):
        _reference = nifkf.KF.load(os.path.join(a.anims, REFERENCE))
    else:
        _reference = find_reference(a.anims, names)[1]
    for n in names:
        check(n, a.anims, a.out)


if __name__ == '__main__':
    main()
