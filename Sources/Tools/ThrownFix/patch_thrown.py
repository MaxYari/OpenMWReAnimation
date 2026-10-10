"""Builds the installer's thrown weapon fix folders ("02 Thrown Weapon Projectiles Fix" and the patches
after it) from Improved Thrown Weapon Projectiles, its Glass Glowset patch, and Improved Weapon
Meshes - Organic's own patch for it. See README.md next to this file.

  python3 patch_thrown.py <Improved Thrown Weapon Projectiles folder> [--glowset DIR] [--organic DIR] [--out DIR]

--glowset: the extracted "Glass Throwables patch for Glass Glowset" (an optional file on ITWP's page).
--organic: Improved Weapon Meshes - Organic's folder (its "04 Improved Thrown Weapons Patch").
--out: where the folders go, by default this mod's root. A source not given is left out.

Byte-level changes, every other byte of each mesh is kept:

1. A keyframe channel that ends on two keys at the same time gets its last key moved 0.0001 s later,
   and the controller's stop time with it. OpenMW 0.51 finds the key pair for a time with
   lower_bound, so at exactly the shared end time it lands on the first of the two keys, and the
   controller clamps to that time for every later one.
2. The X channel's full-turn end value (5 turns over the 4 s flight) becomes SPIN_TURNS turns,
   keeping its sign, so knives and stars spin faster over the same time.
3. In the stars, every Y rotation key takes the in-hand value (-90), so the star stays flat in
   flight and the X spin turns it about the vertical axis, instead of Y = 0 standing it on edge.
"""
import argparse, os, shutil, struct

STEP = 0.0001
TURN = 2 * 3.141592653589793
SPIN_TURNS = 16  # 4 turns a second over the 4 s flight

ITWP, ORGANIC, GLOWSET = 'itwp', 'organic', 'glowset'
HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
CORE = '02 Thrown Weapon Projectiles Fix/meshes/w/'
IRON = '03 Thrown Fix - Iron Mesh Improvements/meshes/w/'
STEEL = '04 Thrown Fix - Improved Weapon Meshes Steel/meshes/w/'
EBONY = '05 Thrown Fix - Improved Weapon Meshes Ebony/meshes/w/'
ORGA = '06 Thrown Fix - Improved Weapon Meshes Organic/meshes/w/'
GLOW = '07 Thrown Fix - Glass Glowset/meshes/w/'

# (source root, source file, output file, what to do)
# knife: end key fix + spin; star: end key fix + spin + flat; copy: unchanged.
# "w_steel_star .nif" has that space in the vanilla record too, so it stays.
FILES = [
    (ITWP, 'Data Files/Meshes/w/w_chitin_star.nif', CORE + 'w_chitin_star.nif', 'star'),
    (ITWP, 'Data Files/Meshes/w/w_knife_glass.nif', CORE + 'w_knife_glass.nif', 'knife'),
    (ITWP, 'Data Files/Meshes/w/w_knife_iron.nif', CORE + 'w_knife_iron.nif', 'knife'),
    (ITWP, 'Data Files/Meshes/w/w_silver_star.nif', CORE + 'w_silver_star.nif', 'star'),
    (ITWP, 'Data Files/Meshes/w/w_star_ebony.nif', CORE + 'w_star_ebony.nif', 'star'),
    (ITWP, 'Data Files/Meshes/w/w_star_glass.nif', CORE + 'w_star_glass.nif', 'star'),
    (ITWP, 'Data Files/Meshes/w/w_steel_knife.nif', CORE + 'w_steel_knife.nif', 'knife'),
    (ITWP, 'Data Files/Meshes/w/w_steel_star .nif', CORE + 'w_steel_star .nif', 'star'),
    (ITWP, 'Patches/w_knife_iron.nif', IRON + 'w_knife_iron.nif', 'knife'),
    (ITWP, 'Patches/w_steel_knife.nif', STEEL + 'w_steel_knife.nif', 'knife'),
    (ITWP, 'Patches/w_steel_star .nif', STEEL + 'w_steel_star .nif', 'star'),
    (ITWP, 'Patches/w_dart_steel.nif', STEEL + 'w_dart_steel.nif', 'copy'),
    (ITWP, 'Patches/w_star_ebony.nif', EBONY + 'w_star_ebony.nif', 'star'),
    (ITWP, 'Patches/w_dart_ebony.nif', EBONY + 'w_dart_ebony.nif', 'copy'),
    (ORGANIC, '04 Improved Thrown Weapons Patch/meshes/w/w_chitin_star.nif', ORGA + 'w_chitin_star.nif', 'star'),
    (GLOWSET, 'Meshes/w/w_knife_glass.nif', GLOW + 'w_knife_glass.nif', 'knife'),
    (GLOWSET, 'Meshes/w/w_star_glass.nif', GLOW + 'w_star_glass.nif', 'star'),
]


def patch(src, dst, spin_turns=None, flat=False):
    d = bytearray(open(src, 'rb').read())
    ctag = struct.pack('<I', 20) + b'NiKeyframeController'
    dtag = struct.pack('<I', 14) + b'NiKeyframeData'
    assert d.count(ctag) == 1 and d.count(dtag) == 1, 'expected one controller and one data block'
    p = d.find(dtag) + len(dtag)

    def u32():
        nonlocal p
        v, = struct.unpack_from('<I', d, p); p += 4; return v

    itypes = []

    def group(width):
        """Returns [(time offset, time, first value)] of a key group, advancing p."""
        nonlocal p
        n = u32()
        itypes.append(None)
        if n == 0:
            return []
        itype = itypes[-1] = u32()
        extra = {1: 0, 2: 2 * width, 3: 3}[itype]
        out = []
        for _ in range(n):
            t, v = struct.unpack_from('<ff', d, p)
            out.append((p, t, v))
            p += 4 * (1 + width + extra)
        return out

    channels = []
    nrot = u32()
    if nrot:
        rtype = u32()
        assert rtype == 4, 'only XYZ rotations handled'
        p += 4  # axis order
        channels += [group(1) for _ in range(3)]
    channels.append(group(3))   # translation
    channels.append(group(1))   # scale

    changes = []
    if spin_turns is not None:
        spins = [(off, v) for off, t, v in channels[0] if abs(v) > TURN and abs(v / TURN - round(v / TURN)) < 1e-4]
        assert len(spins) == 1, 'expected one full-turn key on X'
        off, v = spins[0]
        nv = spin_turns * TURN * (1 if v > 0 else -1)
        struct.pack_into('<f', d, off + 4, nv)
        changes.append('spin %g -> %g turns' % (abs(v) / TURN, spin_turns))
    if flat:
        assert itypes[1] == 1, 'Y keys must be linear'
        hold = channels[1][0][2]
        moved = [off for off, t, v in channels[1] if v != hold]
        for off in moved:
            struct.pack_into('<f', d, off + 4, hold)
        changes.append('%d Y key(s) held at %g deg' % (len(moved), round(hold / TURN * 360, 3)))
    last = 0.0
    for keys in channels:
        if len(keys) >= 2 and keys[-1][1] == keys[-2][1]:
            off, t, _ = keys[-1]
            nt = struct.unpack('<f', struct.pack('<f', t + STEP))[0]
            struct.pack_into('<f', d, off, nt)
            changes.append('end key %.4f -> %.4f s' % (t, nt))
            last = max(last, nt)
        elif keys:
            last = max(last, keys[-1][1])

    stop_off = d.find(ctag) + len(ctag) + 4 + 2 + 4 + 4 + 4  # next, flags, frequency, phase, start
    old_stop, = struct.unpack_from('<f', d, stop_off)
    if last > old_stop:
        struct.pack_into('<f', d, stop_off, last)
        changes.append('stop %.4f -> %.4f s' % (old_stop, last))
    open(dst, 'wb').write(bytes(d))
    return changes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('itwp', help="Improved Thrown Weapon Projectiles' folder (has Data Files and Patches)")
    ap.add_argument('--glowset', help="the Glass Glowset patch's folder (has Meshes/w)")
    ap.add_argument('--organic', help="Improved Weapon Meshes - Organic's folder")
    ap.add_argument('--out', default=MOD, help="where the folders go (default: this mod's root)")
    args = ap.parse_args()
    roots = {ITWP: args.itwp, ORGANIC: args.organic, GLOWSET: args.glowset}
    out = args.out
    for root, rel, dst_rel, what in FILES:
        if roots[root] is None:
            continue
        src, dst = os.path.join(roots[root], rel), os.path.join(out, dst_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if what == 'copy':
            shutil.copyfile(src, dst)
            print('%-72s copied unchanged' % dst_rel)
            continue
        changes = patch(src, dst, SPIN_TURNS, flat=what == 'star')
        a, b = open(src, 'rb').read(), open(dst, 'rb').read()
        assert len(a) == len(b)
        print('%-72s %d byte(s) differ: %s' % (dst_rel, sum(x != y for x, y in zip(a, b)), '; '.join(changes)))


if __name__ == '__main__':
    main()
