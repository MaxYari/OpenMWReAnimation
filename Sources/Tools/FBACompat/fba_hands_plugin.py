"""Writes a plugin that gives the 1st-person view its 1st-person hand meshes back.

FBA's plugin points the ".1st" hand body parts (skin, gloves, gauntlets) at the full 3rd-person
meshes, skinned for the 3rd-person rig: two-jointed fingers at other lengths and rest angles. Our
animations drive the 1st-person rig's five three-jointed fingers, so on those meshes thumbs twist and
fingers bend at the wrong joints. FBA plays everything on the 1st-person skeleton anyway, and
vanilla's ".1st" hand meshes are made for it, so this copies back the vanilla records of every hand
part FBA overrides. Load it after FBA's plugin.

Usage: python3 fba_hands_plugin.py <FBA plugin> <Morrowind Data Files> <output plugin>
"""
import os
import struct
import sys

HAND_PARTS = (5, 6)  # BYDT mesh part: hand, wrist
MASTERS = ('Morrowind.esm', 'Tribunal.esm', 'Bloodmoon.esm')


def records(path):
    """(type, raw record bytes, {subrecord: data}) for every record of a TES3 plugin."""
    d = open(path, 'rb').read()
    i = 0
    while i < len(d):
        kind = d[i:i + 4]
        size, = struct.unpack_from('<I', d, i + 4)
        raw = d[i:i + 16 + size]
        body = raw[16:]
        i += 16 + size
        sub = {}
        j = 0
        while j < len(body):
            name = body[j:j + 4]
            n, = struct.unpack_from('<I', body, j + 4)
            sub.setdefault(name, body[j + 8:j + 8 + n])
            j += 8 + n
        yield kind, raw, sub


def record_id(sub):
    return sub[b'NAME'].rstrip(b'\0').decode('latin1')


def subrecord(name, data):
    return name + struct.pack('<I', len(data)) + data


def build(fba_plugin, data_files, out_path):
    """Returns (records written, FBA hand parts vanilla does not have)."""
    fba_hands = sorted(record_id(sub) for kind, _, sub in records(fba_plugin)
                       if kind == b'BODY' and sub[b'BYDT'][0] in HAND_PARTS)
    vanilla = {}
    for master in MASTERS:
        for kind, raw, sub in records(os.path.join(data_files, master)):
            if kind == b'BODY':
                vanilla[record_id(sub).lower()] = raw
    restored = [vanilla[i.lower()] for i in fba_hands if i.lower() in vanilla]
    missing = [i for i in fba_hands if i.lower() not in vanilla]

    hedr = (struct.pack('<fI', 1.3, 0) + b'ReAnimation'.ljust(32, b'\0')
            + b'Vanilla 1st-person hand meshes for ReAnimation with FBA'.ljust(256, b'\0')
            + struct.pack('<I', len(restored)))
    header = subrecord(b'HEDR', hedr)
    for master in MASTERS:
        header += subrecord(b'MAST', master.encode('latin1') + b'\0')
        header += subrecord(b'DATA', struct.pack('<Q', os.path.getsize(os.path.join(data_files, master))))
    with open(out_path, 'wb') as f:
        f.write(b'TES3' + struct.pack('<III', len(header), 0, 0) + header)
        for raw in restored:
            f.write(raw)
    return len(restored), missing


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    count, missing = build(*sys.argv[1:])
    print('restored %d vanilla hand parts%s' % (count, ('; not in vanilla: %s' % missing) if missing else ''))
