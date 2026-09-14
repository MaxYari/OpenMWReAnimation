"""Minimal Morrowind (NIF 4.0.0.2) skinned-mesh reader: nodes, trishapes, skin data, UVs, textures."""
import struct


class R:
    def __init__(self, d, p=0):
        self.d = d; self.p = p

    def u8(self): v = self.d[self.p]; self.p += 1; return v
    def u16(self): v, = struct.unpack_from('<H', self.d, self.p); self.p += 2; return v
    def u32(self): v, = struct.unpack_from('<I', self.d, self.p); self.p += 4; return v
    def i32(self): v, = struct.unpack_from('<i', self.d, self.p); self.p += 4; return v
    def boolean(self): return self.u32() != 0  # 4 bytes before 4.1.0.0

    def f(self, n=1):
        v = struct.unpack_from('<%df' % n, self.d, self.p); self.p += 4 * n
        return v[0] if n == 1 else v

    def s(self):
        n = self.u32(); v = self.d[self.p:self.p + n].decode('latin1'); self.p += n; return v

    def refs(self):
        n = self.u32()
        return [self.i32() for _ in range(n)]


def objectnet(r):
    return {'name': r.s(), 'extra': r.i32(), 'ctrl': r.i32()}


def avobject(r):
    o = objectnet(r)
    o['flags'] = r.u16()
    o['trans'] = r.f(3); o['rot'] = r.f(9); o['scale'] = r.f(); r.f(3)
    o['props'] = r.refs()
    if r.boolean():
        bvtype = r.u32()
        if bvtype == 0:
            r.f(4)
        elif bvtype == 1:
            r.f(3); r.f(9); r.f(3)
        elif bvtype != 0xFFFFFFFF:
            raise ValueError('bounding volume type %d' % bvtype)
    return o


def read_block(r, t):
    if t in ('NiNode', 'RootCollisionNode', 'AvoidNode'):
        o = avobject(r); o['children'] = r.refs(); o['effects'] = r.refs(); return o
    if t == 'NiTriShape':
        o = avobject(r); o['data'] = r.i32(); o['skin'] = r.i32(); return o
    if t == 'NiTriShapeData':
        o = {}
        n = r.u16()
        o['verts'] = [r.f(3) for _ in range(n)] if r.boolean() else []
        if r.boolean():
            r.f(3 * n)
        r.f(4)
        if r.boolean():
            r.f(4 * n)
        nuv = r.u16()
        if not r.boolean():
            nuv = 0
        o['uvs'] = [r.f(2) for _ in range(n)] if nuv else []
        for _ in range(max(0, nuv - 1)):
            r.f(2 * n)
        r.u16()  # triangles
        # Read counts first: in "r.p += 2 * r.u32()" Python takes r.p before the read advances it.
        indices = r.u32()
        r.p += 2 * indices
        for _ in range(r.u16()):
            count = r.u16()
            r.p += 2 * count
        return o
    if t == 'NiSkinInstance':
        return {'data': r.i32(), 'root': r.i32(), 'bones': r.refs()}
    if t == 'NiSkinData':
        o = {'rot': r.f(9), 'trans': r.f(3), 'scale': r.f()}
        nb = r.u32(); r.i32()  # partition ref
        bones = []
        for _ in range(nb):
            b = {'rot': r.f(9), 'trans': r.f(3), 'scale': r.f()}
            r.f(4)
            nw = r.u16()
            b['weights'] = [(r.u16(), r.f()) for _ in range(nw)]
            bones.append(b)
        o['bones'] = bones
        return o
    if t == 'NiTexturingProperty':
        objectnet(r); r.u16(); r.u32()
        o = {'sources': []}
        for i in range(r.u32()):
            if r.boolean():
                o['sources'].append(r.i32()); r.u32(); r.u32(); r.u32(); r.p += 4 + 2
                if i == 5:
                    r.f(6)
        return o
    if t == 'NiSourceTexture':
        objectnet(r)
        o = {'file': None}
        if r.u8():
            o['file'] = r.s()
        elif r.u8():
            r.i32()
        r.u32(); r.u32(); r.u32(); r.u8()
        return o
    if t == 'NiMaterialProperty':
        objectnet(r); r.u16(); r.f(3 * 4 + 2)
        return {}
    raise ValueError('unsupported block %s' % t)


def load(source):
    """source: a file path or the file's bytes."""
    d = source if isinstance(source, bytes) else open(source, 'rb').read()
    path = '<bytes>' if isinstance(source, bytes) else source
    r = R(d, d.index(b'\n') + 1)
    r.u32(); n = r.u32()
    blocks = []
    for _ in range(n):
        t = r.s()
        blocks.append((t, read_block(r, t)))
    roots = r.refs()
    if r.p != len(d):
        raise ValueError('%s: %d bytes left after the footer' % (path, len(d) - r.p))
    return blocks, roots


def skinned_shapes(source):
    """[{name, texture, verts, uvs, bones: [(bone name, rot, trans, scale)], weights: per vertex [(bone index, w)]}]"""
    blocks, _ = load(source)
    shapes = []
    for t, b in blocks:
        if t != 'NiTriShape' or b['skin'] < 0:
            continue
        data = blocks[b['data']][1]
        inst = blocks[b['skin']][1]
        sdata = blocks[inst['data']][1]
        texture = None
        for p in b['props']:
            if blocks[p][0] == 'NiTexturingProperty' and blocks[p][1]['sources']:
                texture = blocks[blocks[p][1]['sources'][0]][1]['file']
        weights = [[] for _ in data['verts']]
        bones = []
        for bi, (bone_ref, bone) in enumerate(zip(inst['bones'], sdata['bones'])):
            bones.append((blocks[bone_ref][1]['name'], bone['rot'], bone['trans'], bone['scale']))
            for vi, w in bone['weights']:
                weights[vi].append((bi, w))
        shapes.append({'name': b['name'], 'texture': texture, 'verts': data['verts'], 'uvs': data['uvs'],
                       'bones': bones, 'weights': weights})
    return shapes


def to_bone(bone, v):
    """Bone-local position of mesh vertex v (NiSkinData transform: skin space to bone space)."""
    _, m, t3, s = bone
    return tuple(s * (m[3 * i] * v[0] + m[3 * i + 1] * v[1] + m[3 * i + 2] * v[2]) + t3[i] for i in range(3))


def skinned_bone_clouds(path, min_weight=0.6):
    """{bone name: [bone-local vertex positions]} over every skinned shape of the mesh."""
    clouds = {}
    for shape in skinned_shapes(path):
        for vi, ws in enumerate(shape['weights']):
            for bi, w in ws:
                if w >= min_weight:
                    bone = shape['bones'][bi]
                    clouds.setdefault(bone[0], []).append(to_bone(bone, shape['verts'][vi]))
    return clouds
