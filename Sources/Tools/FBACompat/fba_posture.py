"""Leans the chest of a 1st-person kf forward, the way FBA's 3rd-person poses hold it, without
moving the hands or the camera's view.

Our 1st-person rig keeps the chest leaning slightly back. With FBA's visible body that tips the
chest front and the armor's neck opening up toward the camera when looking down; FBA's own poses
lean the chest forward, so it falls away beneath the camera.

The lean is split between Bip01 Spine1 and Bip01 Spine2, about the character's right axis. Bip01
Neck is then re-solved to keep its original world orientation. The head (and the camera under it)
and both clavicles hang off the neck, so arms, weapon and view keep their exact framing and only
slide forward with the neck base.

Every animation that owns the torso has to carry the same lean, or the chest (and with it the
camera and arms) would jump between them, so this runs over every 1st-person kf with one angle.
"""
import math

import kfeval as E

TILT = math.radians(15.0)
SPINE1_SHARE = 0.5
FPS = 30.0

CHAIN = ['Bip01', 'Bip01 Pelvis', 'Bip01 Spine']
CHEST = ['Bip01 Spine1', 'Bip01 Spine2', 'Bip01 Neck']
# Leaning forward tips the chest's up axis toward +Y: a positive rotation about -X.
LEAN_AXIS = (-1.0, 0.0, 0.0)


def rotation_key_times(data):
    if data.rot_type == 4:
        return {k[0] for g in data.xyz for k in g['keys']}
    return {k[0] for k in data.quat_keys}


def keys_rotation(kf, bone):
    return bone in kf.bone_data and bool(rotation_key_times(kf.data(bone)))


def has_chest(kf):
    """Only kfs that rotate the whole chest chain own it; keying it in others would change them."""
    return all(keys_rotation(kf, b) for b in CHEST)


def pose_rotation(kf, reference, bone, t):
    """The bone's rotation from kf, or the rig's rest-like one from the reference kf when kf does
    not key it (in game another animation, or the skeleton, provides it)."""
    if keys_rotation(kf, bone):
        return E.rotation(kf.data(bone), t)
    d = reference.data(bone)
    return E.rotation(d, min(rotation_key_times(d)))


def pose_translation(kf, reference, bone, t):
    if bone in kf.bone_data and kf.data(bone).trans['keys']:
        return E.translation(kf.data(bone), t)
    d = reference.data(bone)
    return E.translation(d, d.trans['keys'][0][0])


def lean(kf, reference):
    """Applies the lean in place. Returns the chain bones that came from the reference."""
    if not has_chest(kf):
        raise ValueError('kf does not rotate the whole chest chain')
    fallbacks = [b for b in CHAIN if not keys_rotation(kf, b)]

    times = set()
    for b in CHAIN + CHEST:
        if keys_rotation(kf, b):
            times |= rotation_key_times(kf.data(b))
    first, last = min(times), max(times)
    n = int(math.ceil((last - first) * FPS))
    times |= {min(first + i / FPS, last) for i in range(n + 1)}

    t1 = E.axis_quat(TILT * SPINE1_SHARE, LEAN_AXIS)
    t2 = E.axis_quat(TILT * (1 - SPINE1_SHARE), LEAN_AXIS)
    out = {b: [] for b in CHEST}
    for t in sorted(times):
        spine = (1.0, 0.0, 0.0, 0.0)
        for b in CHAIN:
            spine = E.qmul(spine, pose_rotation(kf, reference, b, t))
        w1 = E.qmul(spine, E.rotation(kf.data('Bip01 Spine1'), t))
        w2 = E.qmul(w1, E.rotation(kf.data('Bip01 Spine2'), t))
        wn = E.qmul(w2, E.rotation(kf.data('Bip01 Neck'), t))
        w1_new = E.qmul(t1, w1)
        w2_new = E.qmul(E.qmul(t2, t1), w2)
        out['Bip01 Spine1'].append((t, E.qmul(E.qconj(spine), w1_new)))
        out['Bip01 Spine2'].append((t, E.qmul(E.qconj(w1_new), w2_new)))
        out['Bip01 Neck'].append((t, E.qmul(E.qconj(w2_new), wn)))

    for b, keys in out.items():
        d = kf.data(b)
        fixed = []
        for t, q in keys:
            q = E.qnorm(q)
            if fixed and sum(a * c for a, c in zip(fixed[-1][1], q)) < 0:
                q = tuple(-c for c in q)
            fixed.append((t, q, ()))
        d.rot_type = 1
        d.xyz = None
        d.quat_keys = fixed
    return fallbacks
