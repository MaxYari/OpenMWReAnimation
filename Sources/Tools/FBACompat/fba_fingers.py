"""Converts FBA's animations to the 1st-person rig's fingers, for use with 1st-person hand meshes.

FBA plays 3rd-person animations on the 1st-person skeleton and points the 1st-person hand parts at
3rd-person meshes, whose fingers are rigged with two joints (Finger0/01, Finger1/11, Finger2/21) at
their own lengths and rest angles. Vanilla's 1st-person hand, glove and gauntlet meshes are made for
the 1st-person rig instead: five fingers of three joints. With those meshes back (the plugin this
writes), FBA's animations need 1st-person finger tracks, which this fits frame by frame:

The 1st-person hand mesh and the 3rd-person one are the same hand model re-rigged (same shapes,
textures and UVs; the palms coincide relative to the hand bone), so vertices with equal UVs are the
same point of the hand. For every frame this poses the 3rd-person hand mesh with FBA's finger keys and
solves the rotations of all fifteen 1st-person finger bones so the matched vertices land where the
3rd-person hand has them (weighted Horn fit around each joint, skin weights included, base joint first,
a few passes). The ring and little fingers, which the 3rd-person rig does not have, follow what the
3rd-person mesh does with them (it bends them along with its Finger2). Finger joints get the
1st-person rig's offsets; nothing else in the animations changes.

Output folder: meshes/<the FBA 1st-person kfs, converted> and a plugin restoring the vanilla
1st-person hand parts. Load both after FBA.

Usage: python3 fba_fingers.py <FBA folder> <Morrowind Data Files> <output folder>
"""
import math
import os
import re
import struct
import sys
import time

import fba_hands_plugin
import kfeval as E
import nifkf
import nifmesh

SIDES = ('L', 'R')
CHAINS = [tuple('Finger%s%s' % (f, j) for j in ('', '1', '2')) for f in '01234']
FIT_BONES = [b for chain in CHAINS for b in chain]
PARENT = {chain[i]: chain[i - 1] for chain in CHAINS for i in (1, 2)}
# A bone and the joints below it: a joint is fitted to its whole remaining finger, so a base joint
# with next to no vertices of its own (the right thumb's has one) is still well determined.
SUBTREE = {chain[i]: chain[i:] for chain in CHAINS for i in range(3)}
# The 3rd-person rig's finger bones, as FBA's animations key them.
THIRD_BONES = ['Finger0', 'Finger01', 'Finger1', 'Finger11', 'Finger2', 'Finger21']
THIRD_PARENT = {'Finger01': 'Finger0', 'Finger11': 'Finger1', 'Finger21': 'Finger2'}
MESH_1ST = 'meshes\\b\\b_n_dark elf_m_hands.1st.nif'
MESH_3RD = 'meshes\\b\\b_n_dark elf_m_skins.nif'
SKELETON_1ST = 'meshes\\xbase_anim.1st.nif'
KFS = ('xbase_anim.1st.kf', 'xbase_anim_female.1st.kf', 'xbase_animkna.1st.kf')
PLUGIN = 'FBA_1stPersonHands.omwaddon'
MIN_WEIGHT = 0.2   # vertices barely skinned to a bone say little about its rotation
PASSES = 3
IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


# ---- files -------------------------------------------------------------------------------

def bsa_file(bsa_path, name):
    """Bytes of one file from a Morrowind BSA (name lowercase, backslashes)."""
    with open(bsa_path, 'rb') as f:
        _, hash_offset, count = struct.unpack('<3I', f.read(12))
        sizes = [struct.unpack('<2I', f.read(8)) for _ in range(count)]
        name_offsets = struct.unpack('<%dI' % count, f.read(4 * count))
        names = f.read(hash_offset - 12 * count)
        base = 12 + hash_offset + 8 * count
        for i in range(count):
            s = name_offsets[i]
            if names[s:names.index(b'\0', s)].decode('latin1').lower() == name:
                size, offset = sizes[i]
                f.seek(base + offset)
                return f.read(size)
    raise ValueError('%s not in %s' % (name, bsa_path))


def find_file(folder, name):
    """Case-insensitive search for name under folder."""
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower() == name.lower():
                return os.path.join(root, f)
    return None


def matrix_quat(m):
    a = [m[0:3], m[3:6], m[6:9]]
    t = a[0][0] + a[1][1] + a[2][2]
    if t > 0:
        s = math.sqrt(t + 1) * 2
        q = (0.25 * s, (a[2][1] - a[1][2]) / s, (a[0][2] - a[2][0]) / s, (a[1][0] - a[0][1]) / s)
    elif a[0][0] > a[1][1] and a[0][0] > a[2][2]:
        s = math.sqrt(1 + a[0][0] - a[1][1] - a[2][2]) * 2
        q = ((a[2][1] - a[1][2]) / s, 0.25 * s, (a[0][1] + a[1][0]) / s, (a[0][2] + a[2][0]) / s)
    elif a[1][1] > a[2][2]:
        s = math.sqrt(1 + a[1][1] - a[0][0] - a[2][2]) * 2
        q = ((a[0][2] - a[2][0]) / s, (a[0][1] + a[1][0]) / s, 0.25 * s, (a[1][2] + a[2][1]) / s)
    else:
        s = math.sqrt(1 + a[2][2] - a[0][0] - a[1][1]) * 2
        q = ((a[1][0] - a[0][1]) / s, (a[0][2] + a[2][0]) / s, (a[1][2] + a[2][1]) / s, 0.25 * s)
    return E.qnorm(q)


def skeleton_rest(nif_bytes):
    """{node name: (rest rotation, rest translation)} of a skeleton nif (nodes found by record name)."""
    out = {}
    for m in re.finditer(rb'\x06\x00\x00\x00NiNode', nif_bytes):
        q = m.end()
        n, = struct.unpack_from('<I', nif_bytes, q)
        name = nif_bytes[q + 4:q + 4 + n].decode('latin1')
        q += 4 + n + 8 + 2
        trans = struct.unpack_from('<3f', nif_bytes, q)
        rot = struct.unpack_from('<9f', nif_bytes, q + 12)
        out[name] = (matrix_quat(rot), trans)
    return out


# ---- rigid transforms (rotation quaternion, translation) -----------------------------------

def compose(a, b):
    return E.qmul(a[0], b[0]), tuple(x + y for x, y in zip(a[1], E.qrot(a[0], b[1])))


def inverse(a):
    q = E.qconj(a[0])
    return q, tuple(-c for c in E.qrot(q, a[1]))


def apply(a, p):
    return tuple(x + y for x, y in zip(a[1], E.qrot(a[0], p)))


def horn(s):
    """Rotation (quaternion) best taking the weighted source points onto the targets, from
    s[i][j] = sum(weight * source_i * target_j), via the 4x4 symmetric eigenproblem (Jacobi)."""
    (sxx, sxy, sxz), (syx, syy, syz), (szx, szy, szz) = s
    n = [[sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
         [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
         [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
         [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz]]
    v = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for _ in range(50):
        if sum(n[i][j] ** 2 for i in range(4) for j in range(4) if i != j) < 1e-18:
            break
        for p in range(3):
            for q in range(p + 1, 4):
                if abs(n[p][q]) < 1e-15:
                    continue
                theta = (n[q][q] - n[p][p]) / (2 * n[p][q])
                t = (1 if theta >= 0 else -1) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                sn = t * c
                for k in range(4):
                    nkp, nkq = n[k][p], n[k][q]
                    n[k][p] = c * nkp - sn * nkq
                    n[k][q] = sn * nkp + c * nkq
                for k in range(4):
                    npk, nqk = n[p][k], n[q][k]
                    n[p][k] = c * npk - sn * nqk
                    n[q][k] = sn * npk + c * nqk
                for k in range(4):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - sn * vkq
                    v[k][q] = sn * vkp + c * vkq
    best = max(range(4), key=lambda i: n[i][i])
    return E.qnorm(tuple(v[k][best] for k in range(4)))


# ---- the vertex map ------------------------------------------------------------------------

def skin(shape, vi, side):
    """[(short bone name, weight, bone-local position)], or None if skinned outside the hand."""
    out = []
    prefix = 'Bip01 %s ' % side
    for bi, w in shape['weights'][vi]:
        bone = shape['bones'][bi]
        if not bone[0].startswith(prefix):
            return None
        short = bone[0][len(prefix):]
        if short not in ('Hand', 'Forearm') and not short.startswith('Finger'):
            return None
        out.append((short, w, nifmesh.to_bone(bone, shape['verts'][vi])))
    return out or None


class HandMap:
    """UV-matched vertex pairs (1st-person skin, 3rd-person skin) of the same hand model."""

    def __init__(self, first_mesh, third_mesh):
        m1 = nifmesh.skinned_shapes(first_mesh)
        m3 = nifmesh.skinned_shapes(third_mesh)
        self.pairs = {side: [] for side in SIDES}
        for s1 in m1:
            side = next((sd for sd in SIDES if any(b[0].startswith('Bip01 %s ' % sd) for b in s1['bones'])), None)
            s3 = next((s for s in m3 if s['name'] == s1['name'] and s['texture'] == s1['texture']), None)
            if side is None or s3 is None or not s1['uvs'] or not s3['uvs']:
                continue
            by_uv = {}
            for i, uv in enumerate(s3['uvs']):
                by_uv.setdefault((round(uv[0], 4), round(uv[1], 4)), i)
            for v1, uv in enumerate(s1['uvs']):
                v3 = by_uv.get((round(uv[0], 4), round(uv[1], 4)))
                if v3 is None:
                    continue
                w1, w3 = skin(s1, v1, side), skin(s3, v3, side)
                if w1 and w3:
                    self.pairs[side].append((w1, w3))
        self.by_bone = {side: {b: [i for i, (w1, _) in enumerate(self.pairs[side])
                                   if sum(w for bone, w, _ in w1 if bone in SUBTREE[b]) >= MIN_WEIGHT]
                               for b in FIT_BONES} for side in SIDES}


def blend(transforms, skin_list):
    acc = [0.0, 0.0, 0.0]
    for bone, w, g in skin_list:
        p = apply(transforms[bone], g)
        acc = [a + w * c for a, c in zip(acc, p)]
    return acc


# ---- fitting ---------------------------------------------------------------------------------

def third_person_transforms(kf, side, t):
    """Hand-space transforms of hand, forearm and the 3rd-person finger bones as the kf poses them."""
    def local(short):
        d = kf.data('Bip01 %s %s' % (side, short))
        return E.rotation(d, t), E.translation(d, t)
    out = {'Hand': IDENTITY, 'Forearm': inverse(local('Hand'))}
    for b in THIRD_BONES:
        out[b] = compose(out[THIRD_PARENT[b]] if b in THIRD_PARENT else IDENTITY, local(b))
    return out


def first_person_transforms(rots, offsets, forearm):
    out = {'Hand': IDENTITY, 'Forearm': forearm}
    for chain in CHAINS:
        parent = IDENTITY
        for b in chain:
            parent = compose(parent, (rots[b], offsets[b]))
            out[b] = parent
    return out


def fit_frame(hand_map, side, targets, forearm, offsets, previous):
    rots = dict(previous)
    for _ in range(PASSES):
        for chain in CHAINS:
            for bone in chain:
                first = first_person_transforms(rots, offsets, forearm)
                parent = first[PARENT[bone]] if bone in PARENT else IDENTITY
                inv_parent = inverse(parent)
                # From this bone's frame to each joint below it, at their current rotations.
                below = {bone: IDENTITY}
                for c in SUBTREE[bone][1:]:
                    below[c] = compose(below[PARENT[c]], (rots[c], offsets[c]))
                s = [[0.0] * 3 for _ in range(3)]
                used = 0
                for index in hand_map.by_bone[side][bone]:
                    w1, target = hand_map.pairs[side][index][0], targets[index]
                    # The vertex is known + wsub * parent(offset + R * src), src being its skin blend
                    # over this bone and the joints below it, in this bone's frame.
                    wsub = 0.0
                    src = [0.0, 0.0, 0.0]
                    known = [0.0, 0.0, 0.0]
                    for b, w, gl in w1:
                        if b in below:
                            p = apply(below[b], gl)
                            src = [a + w * c for a, c in zip(src, p)]
                            wsub += w
                        else:
                            pk = apply(first[b], gl)
                            known = [k + w * c for k, c in zip(known, pk)]
                    src = [c / wsub for c in src]
                    x = [(a - k) / wsub for a, k in zip(target, known)]
                    d = apply(inv_parent, x)
                    d = [c - o for c, o in zip(d, offsets[bone])]
                    omega = wsub * wsub
                    for i in range(3):
                        for j in range(3):
                            s[i][j] += omega * src[i] * d[j]
                    used += 1
                if used >= 2:
                    q = horn(s)
                    if sum(a * b for a, b in zip(q, rots[bone])) < 0:
                        q = tuple(-c for c in q)
                    rots[bone] = q
    return rots


def convert(kf, hand_map, rest):
    """Rewrites kf's finger tracks for the 1st-person rig. Returns {side: (frames, mean, max error)}."""
    report = {}
    for side in SIDES:
        needed = ['Bip01 %s %s' % (side, b) for b in ['Hand'] + THIRD_BONES]
        if not all(b in kf.bone_data for b in needed):
            continue
        times = set()
        for b in needed:
            d = kf.data(b)
            times |= {k[0] for k in d.quat_keys} if d.rot_type != 4 else set()
            times |= {k[0] for k in d.trans['keys']}
        times = sorted(times)
        if not times:
            continue
        offsets = {b: rest['Bip01 %s %s' % (side, b)][1] for b in FIT_BONES}
        previous = {b: rest['Bip01 %s %s' % (side, b)][0] for b in FIT_BONES}
        keys = {b: [] for b in FIT_BONES}
        errors = []
        for i, t in enumerate(times):
            third = third_person_transforms(kf, side, t)
            targets = [blend(third, w3) for _, w3 in hand_map.pairs[side]]
            rots = fit_frame(hand_map, side, targets, third['Forearm'], offsets, previous)
            previous = rots
            for b in FIT_BONES:
                keys[b].append((t, rots[b], ()))
            if i % 25 == 0:
                first = first_person_transforms(rots, offsets, third['Forearm'])
                errors += [math.dist(blend(first, w1), tg) for (w1, _), tg in zip(hand_map.pairs[side], targets)]
        for b in FIT_BONES:
            name = 'Bip01 %s %s' % (side, b)
            d = kf.data(name) if name in kf.bone_data else kf.add_bone(name)
            d.rot_type = 1
            d.xyz = None
            d.quat_keys = keys[b]
            d.trans = {'itype': 1, 'keys': [(times[0], offsets[b], ()), (times[-1], offsets[b], ())]}
            d.scale = {'itype': 0, 'keys': []}
        report[side] = (len(times), sum(errors) / len(errors), max(errors))
    return report


def main(fba_folder, data_files, out_folder):
    bsa = os.path.join(data_files, 'Morrowind.bsa')
    hand_map = HandMap(bsa_file(bsa, MESH_1ST), bsa_file(bsa, MESH_3RD))
    rest = skeleton_rest(bsa_file(bsa, SKELETON_1ST))
    print('hand map: %s vertex pairs' % {s: len(p) for s, p in hand_map.pairs.items()})
    os.makedirs(os.path.join(out_folder, 'meshes'), exist_ok=True)
    for name in KFS:
        path = find_file(fba_folder, name)
        if path is None:
            print('%s: not in the FBA folder, skipped' % name)
            continue
        started = time.time()
        kf = nifkf.KF.load(path)
        report = convert(kf, hand_map, rest)
        kf.save(os.path.join(out_folder, 'meshes', os.path.basename(path)))
        print('%s: %.0fs, %s' % (name, time.time() - started, '  '.join(
            '%s hand %d frames, fit to the 3rd-person hand mean %.2f max %.2f' % ((s,) + r)
            for s, r in sorted(report.items()))))
    plugin = next((os.path.join(r, f) for r, _, fs in os.walk(fba_folder) for f in fs
                   if f.lower().endswith(('.omwaddon', '.esp'))), None)
    if plugin is None:
        print('no FBA plugin found, hands plugin not written')
        return
    count, missing = fba_hands_plugin.build(plugin, data_files, os.path.join(out_folder, PLUGIN))
    print('%s: restored %d vanilla 1st-person hand parts%s'
          % (PLUGIN, count, ('; not in vanilla: %s' % missing) if missing else ''))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
