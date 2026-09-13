"""Evaluate kf tracks the way OpenMW does, plus quaternion helpers (Hamilton, (w,x,y,z))."""
import bisect
import math


def qmul(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return (aw*bw - ax*bx - ay*by - az*bz,
            aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw)


def qconj(q):
    return (q[0], -q[1], -q[2], -q[3])


def qnorm(q):
    n = math.sqrt(sum(c*c for c in q)); return tuple(c/n for c in q)


def qrot(q, v):
    r = qmul(qmul(q, (0.0,) + tuple(v)), qconj(q)); return r[1:]


def qslerp(a, b, t):
    d = sum(x*y for x, y in zip(a, b))
    if d < 0:
        b = tuple(-c for c in b); d = -d
    if d > 0.9995:
        return qnorm(tuple(x + (y - x)*t for x, y in zip(a, b)))
    th = math.acos(d); s = math.sin(th)
    wa = math.sin((1-t)*th)/s; wb = math.sin(t*th)/s
    return tuple(wa*x + wb*y for x, y in zip(a, b))


def qangle(a, b):
    d = abs(sum(x*y for x, y in zip(a, b)))
    return math.degrees(2*math.acos(min(1.0, d)))


def axis_quat(angle, axis):
    s = math.sin(angle/2)
    return (math.cos(angle/2),) + tuple(s*c for c in axis)


def _interp_group(keys, itype, t, width):
    """keys: [(time, value, extra)]; OpenMW interpKey semantics."""
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    times = [k[0] for k in keys]
    i = bisect.bisect_right(times, t)
    if i >= len(keys):
        return keys[-1][1]
    a, b = keys[i-1], keys[i]
    if b[0] == a[0]:
        return a[1]
    f = (t - a[0]) / (b[0] - a[0])
    va = a[1] if width > 1 else (a[1],)
    vb = b[1] if width > 1 else (b[1],)
    if itype in (2, 3) and a[2] and b[2]:
        # Hermite: a.value*b1 + b.value*b2 + a.outTan*b3 + b.inTan*b4; extra = (inTan, outTan)
        a_out = a[2][width:2*width]; b_in = b[2][0:width]
        t2 = f*f; t3 = t2*f
        b1 = 2*t3 - 3*t2 + 1; b2 = -2*t3 + 3*t2; b3 = t3 - 2*t2 + f; b4 = t3 - t2
        out = tuple(va[k]*b1 + vb[k]*b2 + a_out[k]*b3 + b_in[k]*b4 for k in range(width))
    else:
        out = tuple(va[k] + (vb[k] - va[k])*f for k in range(width))
    return out if width > 1 else out[0]


def rotation(data, t):
    """Local rotation of a KeyframeData at time t, or None if it has no rotation keys."""
    if data.rot_type == 4:
        ang = [(_interp_group(g['keys'], g['itype'], t, 1) or 0.0) for g in data.xyz]
        if data.xyz_order != 0:
            raise ValueError('only XYZ axis order supported')
        # OpenMW: osg xr*yr*zr == Hamilton zr (x) yr (x) xr
        xr = axis_quat(ang[0], (1, 0, 0)); yr = axis_quat(ang[1], (0, 1, 0)); zr = axis_quat(ang[2], (0, 0, 1))
        return qmul(zr, qmul(yr, xr))
    keys = data.quat_keys
    if not keys:
        return None
    if t <= keys[0][0]:
        return keys[0][1]
    times = [k[0] for k in keys]
    i = bisect.bisect_right(times, t)
    if i >= len(keys):
        return keys[-1][1]
    a, b = keys[i-1], keys[i]
    if b[0] == a[0]:
        return a[1]
    return qslerp(a[1], b[1], (t - a[0]) / (b[0] - a[0]))


def translation(data, t):
    return _interp_group(data.trans['keys'], data.trans['itype'], t, 3)


PARENT = {
    'Bip01 Pelvis': 'Bip01', 'Bip01 Spine': 'Bip01 Pelvis', 'Bip01 Spine1': 'Bip01 Spine',
    'Bip01 Spine2': 'Bip01 Spine1', 'Bip01 Neck': 'Bip01 Spine2', 'Bip01 Head': 'Bip01 Neck',
    'Bip01 L Thigh': 'Bip01 Pelvis', 'Bip01 R Thigh': 'Bip01 Pelvis',
    'Bip01 L Calf': 'Bip01 L Thigh', 'Bip01 R Calf': 'Bip01 R Thigh',
    'Bip01 L Foot': 'Bip01 L Calf', 'Bip01 R Foot': 'Bip01 R Calf',
    'Bip01 L Toe0': 'Bip01 L Foot', 'Bip01 R Toe0': 'Bip01 R Foot',
}


def world(kf, bone, t, override=None):
    """(rotation, position) of bone in the object-root frame. override: {bone: (rot, trans)}."""
    chain = []
    b = bone
    while b:
        chain.append(b); b = PARENT.get(b)
    rot = (1.0, 0.0, 0.0, 0.0); pos = (0.0, 0.0, 0.0)
    for b in reversed(chain):
        if override and b in override:
            lr, lt = override[b]
        else:
            d = kf.data(b); lr = rotation(d, t); lt = translation(d, t)
        pos = tuple(p + c for p, c in zip(pos, qrot(rot, lt)))
        rot = qmul(rot, lr)
    return rot, pos
