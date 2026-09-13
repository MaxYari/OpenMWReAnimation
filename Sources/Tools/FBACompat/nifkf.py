"""Minimal Morrowind (NIF 4.0.0.2) .kf reader/writer."""
import struct


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u32(self):
        v, = struct.unpack_from('<I', self.d, self.p); self.p += 4; return v

    def i32(self):
        v, = struct.unpack_from('<i', self.d, self.p); self.p += 4; return v

    def u16(self):
        v, = struct.unpack_from('<H', self.d, self.p); self.p += 2; return v

    def f32(self, n=1):
        v = struct.unpack_from('<%df' % n, self.d, self.p); self.p += 4 * n
        return v[0] if n == 1 else v

    def string(self):
        n = self.u32(); v = self.d[self.p:self.p + n].decode('latin1'); self.p += n; return v


class Writer:
    def __init__(self):
        self.parts = []

    def u32(self, v): self.parts.append(struct.pack('<I', v))
    def i32(self, v): self.parts.append(struct.pack('<i', v))
    def u16(self, v): self.parts.append(struct.pack('<H', v))
    def f32(self, *v): self.parts.append(struct.pack('<%df' % len(v), *v))

    def string(self, s):
        b = s.encode('latin1'); self.u32(len(b)); self.parts.append(b)

    def bytes(self):
        return b''.join(self.parts)


# ---- key groups -------------------------------------------------------------
# A key group is {'itype': int, 'keys': [(time, value, extra)]}; value is a float
# or a tuple, extra holds tangents (itype 2) or TBC (itype 3) as a flat tuple.

def _read_group(r, width):
    n = r.u32()
    if n == 0:
        return {'itype': 0, 'keys': []}
    itype = r.u32()
    keys = []
    for _ in range(n):
        t = r.f32()
        v = r.f32(width)
        extra = ()
        if itype == 2:
            extra = r.f32(2 * width) if width > 1 else r.f32(2)
        elif itype == 3:
            extra = r.f32(3)
        elif itype != 1:
            raise ValueError('unsupported key type %d' % itype)
        keys.append((t, v, tuple(extra) if isinstance(extra, tuple) else (extra,)))
    return {'itype': itype, 'keys': keys}


def _write_group(w, g, width):
    w.u32(len(g['keys']))
    if not g['keys']:
        return
    w.u32(g['itype'])
    for t, v, extra in g['keys']:
        w.f32(t)
        if width == 1:
            w.f32(v)
        else:
            w.f32(*v)
        if extra:
            w.f32(*extra)


class KeyframeData:
    def __init__(self):
        self.rot_type = 0
        self.quat_keys = []      # (t, (w,x,y,z), extra)
        self.xyz_order = 0
        self.xyz = None          # 3 float key groups when rot_type == 4
        self.trans = {'itype': 0, 'keys': []}
        self.scale = {'itype': 0, 'keys': []}

    @staticmethod
    def read(r):
        k = KeyframeData()
        n = r.u32()
        if n:
            k.rot_type = r.u32()
            if k.rot_type == 4:
                k.xyz_order = r.u32()
                k.xyz = [_read_group(r, 1) for _ in range(3)]
            else:
                for _ in range(n):
                    t = r.f32(); q = r.f32(4)
                    extra = r.f32(3) if k.rot_type == 3 else ()
                    k.quat_keys.append((t, q, extra))
        k.trans = _read_group(r, 3)
        k.scale = _read_group(r, 1)
        return k

    def write(self, w):
        if self.rot_type == 4:
            w.u32(1)  # key count is irrelevant for XYZ, vanilla writes 1
            w.u32(4); w.u32(self.xyz_order)
            for g in self.xyz:
                _write_group(w, g, 1)
        else:
            w.u32(len(self.quat_keys))
            if self.quat_keys:
                w.u32(self.rot_type)
                for t, q, extra in self.quat_keys:
                    w.f32(t); w.f32(*q)
                    if extra:
                        w.f32(*extra)
        _write_group(w, self.trans, 3)
        _write_group(w, self.scale, 1)


class KF:
    """Blocks are kept as (type, payload) where payload is raw bytes, or a parsed
    object for NiKeyframeData / NiTextKeyExtraData / NiStringExtraData / NiKeyframeController."""

    @staticmethod
    def load(path):
        kf = KF()
        d = open(path, 'rb').read()
        r = Reader(d)
        hdr_end = d.index(b'\n') + 1
        r.p = hdr_end + 4
        n = r.u32()
        kf.header = d[:r.p]
        kf.blocks = []
        for _ in range(n):
            t = r.string()
            start = r.p
            if t == 'NiSequenceStreamHelper':
                payload = {'name': r.string(), 'extra': r.i32(), 'ctrl': r.i32()}
            elif t == 'NiTextKeyExtraData':
                nxt = r.i32(); unk = r.u32(); cnt = r.u32()
                keys = []
                for _ in range(cnt):
                    tm = r.f32(); keys.append((tm, r.string()))
                payload = {'next': nxt, 'unk': unk, 'keys': keys}
            elif t == 'NiStringExtraData':
                payload = {'next': r.i32(), 'bytes': r.u32(), 'value': r.string()}
            elif t == 'NiKeyframeController':
                payload = {'next': r.i32(), 'flags': r.u16(), 'freq': r.f32(), 'phase': r.f32(),
                           'start': r.f32(), 'stop': r.f32(), 'target': r.i32(), 'data': r.i32()}
            elif t == 'NiKeyframeData':
                payload = KeyframeData.read(r)
            else:
                raise ValueError('unknown block %s at %d in %s' % (t, start, path))
            kf.blocks.append((t, payload))
        kf.footer = d[r.p:]
        kf._index()
        return kf

    def _index(self):
        helper = self.blocks[0][1]
        # extra chain: text keys, then bone names; controller chain pairs with names in order
        names = []
        tk = None
        e = helper['extra']
        while e >= 0:
            t, p = self.blocks[e]
            if t == 'NiTextKeyExtraData':
                tk = e
            elif t == 'NiStringExtraData':
                names.append(p['value'])
            e = p['next']
        ctrls = []
        c = helper['ctrl']
        while c >= 0:
            ctrls.append(c)
            c = self.blocks[c][1]['next']
        self.textkey_block = tk
        self.bone_data = {}  # bone name -> NiKeyframeData block index
        # Controllers can come without data (ref -1; _xReanimationv1.kf has four, for extra rig
        # bones). They animate nothing and must not index the block list, where -1 is the last one.
        self.dataless = []
        for nm, c in zip(names, ctrls):
            ref = self.blocks[c][1]['data']
            if ref < 0:
                self.dataless.append(nm)
            else:
                self.bone_data[nm] = ref

    def data(self, bone):
        return self.blocks[self.bone_data[bone]][1]

    def text_keys(self):
        return self.blocks[self.textkey_block][1]['keys']

    def groups(self):
        """{groupname_lower: {key_lower: time}} plus raw markers list per group."""
        out = {}
        for tm, txt in self.text_keys():
            for line in txt.replace('\r', '').split('\n'):
                if ':' not in line:
                    continue
                g, k = line.split(':', 1)
                out.setdefault(g.strip().lower(), []).append((tm, k.strip().lower()))
        return out

    def save(self, path):
        w = Writer()
        w.parts.append(self.header)
        for t, p in self.blocks:
            w.string(t)
            if t == 'NiSequenceStreamHelper':
                w.string(p['name']); w.i32(p['extra']); w.i32(p['ctrl'])
            elif t == 'NiTextKeyExtraData':
                w.i32(p['next']); w.u32(p['unk']); w.u32(len(p['keys']))
                for tm, s in p['keys']:
                    w.f32(tm); w.string(s)
            elif t == 'NiStringExtraData':
                w.i32(p['next']); w.u32(p['bytes']); w.string(p['value'])
            elif t == 'NiKeyframeController':
                w.i32(p['next']); w.u16(p['flags']); w.f32(p['freq'], p['phase'], p['start'], p['stop'])
                w.i32(p['target']); w.i32(p['data'])
            elif t == 'NiKeyframeData':
                p.write(w)
        w.parts.append(self.footer)
        open(path, 'wb').write(w.bytes())
