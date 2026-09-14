"""Builds Full Body Awareness versions of 1st-person kfs.

FBA shows the whole body in 1st person and plays 3rd-person animations on it. Our 1st-person
kfs key every bone, so with FBA the legs hang in the 1st-person rig pose and, having no root
motion, the player gets stuck (the engine falls back to FBA's 3rd-person velocity).

This keeps our upper body and takes the lower body (Bip01, Pelvis, Spine, legs - OpenMW's
LowerBody blend layer) from the 3rd-person kf. Every group gets its own segment on a new
timeline, since groups sharing a time range in our kf (forward/back, idle1h/idleshield...) need
different legs. Text keys move with their group; relative timings are kept exactly.

* Locomotion (walk/run/sneak): the 3rd-person time is warped so its SoundGen Left/Right markers
  land on ours, same foot to same foot, with a smooth monotone (PCHIP) curve between them. When
  the step counts per loop differ, the segment spans the least common multiple of both, so our
  loop repeats and both sides loop seamlessly. Root motion comes with the warped 3rd-person Bip01.
  Without usable markers on either side it falls back to a plain loop-to-loop stretch.
* Everything else (idles, attacks, equip, jump, hits...): the matching 3rd-person group, warped
  piecewise-linearly through the text keys both share, section by section (chop, slash, equip...).
  Attack tails blend from the 3rd-person follow-through's end into the idle; groups with no match
  get the weapon's 3rd-person idle legs. No root motion: 3rd-person attack hips travel far enough
  to push the player around.
* Bip01 Spine, the top bone of the lower body layer, is counter-rotated so it keeps exactly its
  1st-person orientation in the character frame. The camera takes only the head's position, never
  its rotation, so whatever plays on the upper body over this is framed as without FBA. During
  locomotion SWAY of the 3rd-person spine's swing around its average is let back through.

Usage: python3 fba_merge.py <1st-person kf> <3rd-person kf> <output kf>
"""
import math
import re
import sys

import kfeval as E
import nifkf

LOWER_BONES = ['Bip01', 'Bip01 Pelvis', 'Bip01 Spine',
               'Bip01 L Thigh', 'Bip01 R Thigh', 'Bip01 L Calf', 'Bip01 R Calf',
               'Bip01 L Foot', 'Bip01 R Foot']
COMPENSATED_BONE = 'Bip01 Spine'
# Share of the 3rd-person spine swing let through to the upper body during locomotion. Only the
# swing: the 3rd-person spine's average lean over the loop is always removed, or thrusts would sit
# off-center.
SWAY = 0.33
IDENTITY = (1.0, 0.0, 0.0, 0.0)
FPS = 30.0
SEGMENT_GAP = 0.2
EPS = 1e-4

LOCOMOTION = re.compile(r'^(walk|run|sneak)(forward|back|left|right)')
# Sections within a group: keys starting with these words form separate warps (the engine never
# plays across them, and e.g. our equip stop and unequip start share a time).
SECTION_WORDS = ('chop', 'slash', 'thrust', 'shoot', 'equip', 'unequip', 'block', 'self', 'touch', 'target')
# We key the large, medium and small follow-through over the same range; the 3rd person plays them
# one after another. Ours follow the large one.
FOLLOW_KEPT = 'large'
FOLLOW_OTHERS = ('medium', 'small')
# Which 3rd-person idle gives the legs for a group with no match of its own.
ATTACK_IDLES = {'weapononehand': 'idle1h', 'weapontwohand': 'idle2c', 'weapontwowide': 'idle2w',
                'handtohand': 'idlehh', 'bowandarrow': 'idlebow', 'crossbow': 'idlecrossbow',
                'throwweapon': 'idle1t'}
IDLE_TOKENS = ('crossbow', 'bow', '1h', '2c', '2w', 'hh', '1t')

# Everything left as it was, for the caller to report: "<kf>: <group>: <why>".
WARNINGS = []
_current_file = ['']


def warn(message):
    WARNINGS.append('%s: %s' % (_current_file[0], message))
    print('  warning: ' + message)


# ---- text keys --------------------------------------------------------------

def text_lines(kf):
    """[(time, line)] with every line of every text key."""
    out = []
    for tm, txt in kf.text_keys():
        for line in txt.replace('\r', '').split('\n'):
            if line.strip():
                out.append((tm, line.strip()))
    return out


def split_line(line):
    g, k = line.split(':', 1)
    return g.strip().lower(), k.strip().lower()


def group_keys(lines, group):
    keys = {}
    for tm, line in lines:
        if ':' in line:
            g, k = split_line(line)
            if g == group:
                keys[k] = tm
    return keys


def all_group_keys(lines):
    """{group: {key: time}} for every group, soundgen excluded."""
    out = {}
    for tm, line in lines:
        if ':' in line:
            g, k = split_line(line)
            if g != 'soundgen':
                out.setdefault(g, {})[k] = tm
    return out


def their_group_for(name, their_groups):
    """The 3rd-person group whose legs this group takes, or None."""
    if name.endswith('extra'):
        return None
    if name in their_groups:
        return name
    if name.startswith('idle') and name.endswith('sneak') and 'idlesneak' in their_groups:
        return 'idlesneak'
    candidates = [g for g in their_groups if name.startswith(g)]
    return max(candidates, key=len) if candidates else None


def idle_group_for(name, their_groups):
    for base, idle in ATTACK_IDLES.items():
        if name.startswith(base) and idle in their_groups:
            return idle
    for token in IDLE_TOKENS:
        if token in name and 'idle' + token in their_groups:
            return 'idle' + token
    return 'idle'


# ---- poses ----------------------------------------------------------------------

def their_lower_pose(kf, t):
    return {b: (E.rotation(kf.data(b), t), E.translation(kf.data(b), t)) for b in LOWER_BONES}


def blend_pose(a, b, w):
    return {bone: (E.qslerp(a[bone][0], b[bone][0], w),
                   tuple(x + (y - x) * w for x, y in zip(a[bone][1], b[bone][1]))) for bone in a}


def pelvis_world_rotation(kf, t):
    return E.qmul(E.rotation(kf.data('Bip01'), t), E.rotation(kf.data('Bip01 Pelvis'), t))


def key_times(data):
    if data.rot_type == 4:
        ts = {k[0] for g in data.xyz for k in g['keys']}
    else:
        ts = {k[0] for k in data.quat_keys}
    return ts | {k[0] for k in data.trans['keys']} | {k[0] for k in data.scale['keys']}


# ---- locomotion -------------------------------------------------------------------

class Group:
    """A group's start/loop/stop times and its footstep phases within the loop."""

    def __init__(self, lines, name):
        k = group_keys(lines, name)
        self.name = name
        self.start = k['start']
        self.stop = k['stop']
        self.loop_start = k.get('loop start', self.start)
        self.loop_stop = k.get('loop stop', self.stop)
        self.period = self.loop_stop - self.loop_start
        steps = {}
        for tm, line in lines:
            if ':' not in line:
                continue
            g, foot = split_line(line)
            if g != 'soundgen' or foot not in ('left', 'right'):
                continue
            if self.loop_start - EPS <= tm <= self.loop_stop + EPS:
                phase = (tm - self.loop_start) % self.period
                if self.period - phase < EPS:
                    phase = 0.0
                steps[round(phase, 4)] = foot
        self.steps = sorted(steps.items())

    def steps_usable(self):
        if len(self.steps) < 2:
            return False
        return all(a != b for (_, a), (_, b) in zip(self.steps, self.steps[1:] + self.steps[:1]))

    def relabel_by_feet(self, kf):
        """Takes each step's foot from the animation itself: the lower foot at the marker.
        Some 3rd-person groups have Left and Right swapped (FBA's sneakforward2c, sneakright2c)."""
        fixed = []
        for phase, foot in self.steps:
            t = self.loop_start + phase
            lz = E.world(kf, 'Bip01 L Foot', t)[1][2]
            rz = E.world(kf, 'Bip01 R Foot', t)[1][2]
            actual = 'left' if lz < rz else 'right'
            if actual != foot:
                print('  %s: SoundGen %s at %.3f has the %s foot down, using %s' % (
                    self.name, foot, t, actual, actual))
            fixed.append((phase, actual))
        self.steps = fixed


class Warp:
    """Monotone map from our unrolled loop time (0 = our loop start) to unrolled
    3rd-person loop time (0 = their loop start), through matched footsteps."""

    def __init__(self, ours, theirs):
        n1, n3 = len(ours.steps), len(theirs.steps)
        n = n1 * n3 // math.gcd(n1, n3)
        self.our_loops = n // n1
        self.their_loops = n // n3
        p1, p3 = ours.period, theirs.period
        e1 = [p for p, _ in ours.steps]
        e3 = [p for p, _ in theirs.steps]
        f1 = [f for _, f in ours.steps]
        f3 = [f for _, f in theirs.steps]

        def pair(k, j0):
            x = e1[k % n1] + (k // n1) * p1
            j = j0 + k
            return x, e3[j % n3] + (j // n3) * p3

        # Of the same-foot alignments, take the one closest to a uniform stretch.
        slope = self.their_loops * p3 / (self.our_loops * p1)
        best = None
        for j0 in range(n3):
            if f3[j0] != f1[0]:
                continue
            pts = [pair(k, j0) for k in range(n)]
            c = sum(y - slope * x for x, y in pts) / n
            err = sum((y - slope * x - c) ** 2 for x, y in pts)
            if best is None or err < best[0]:
                best = (err, j0)
        if best is None:
            raise ValueError('%s: no matching foot in the 3rd-person steps' % ours.name)
        j0 = best[1]
        for k in range(n):
            if f3[(j0 + k) % n3] != f1[k % n1]:
                raise ValueError('%s: foot sequences cannot be matched' % ours.name)
        self.xs, self.ys = zip(*[pair(k, j0) for k in range(-2 * n, 3 * n)])
        self._tangents()

    def _tangents(self):
        xs, ys = self.xs, self.ys
        h = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        d = [(ys[i + 1] - ys[i]) / h[i] for i in range(len(h))]
        m = [d[0]]
        for i in range(1, len(xs) - 1):
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m.append((w1 + w2) / (w1 / d[i - 1] + w2 / d[i]))
        m.append(d[-1])
        self.m = m

    def __call__(self, x):
        xs = self.xs
        lo, hi = 0, len(xs) - 1
        if not xs[0] <= x <= xs[-1]:
            raise ValueError('warp input %f outside %f..%f' % (x, xs[0], xs[-1]))
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= x:
                lo = mid
            else:
                hi = mid
        h = xs[hi] - xs[lo]
        t = (x - xs[lo]) / h
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * self.ys[lo] + (t3 - 2 * t2 + t) * h * self.m[lo]
                + (-2 * t3 + 3 * t2) * self.ys[hi] + (t3 - t2) * h * self.m[hi])


class LocomotionSegment:
    """Our intro, our loop repeated, our outro; legs and root motion from the warped 3rd person."""
    sway = SWAY

    def __init__(self, ours, theirs, theirs_kf, offset):
        self.name = ours.name
        self.ours = ours
        self.theirs = theirs
        self.theirs_kf = theirs_kf
        self.warp = Warp(ours, theirs)
        self.offset = offset
        self.intro = ours.loop_start - ours.start
        self.loop_len = self.warp.our_loops * ours.period
        self.length = self.intro + self.loop_len + (ours.stop - ours.loop_stop)
        root = theirs_kf.data('Bip01')
        self.root_a = E.translation(root, theirs.loop_start)
        self.root_b = E.translation(root, theirs.loop_stop)
        self.r0 = self._root(0.0)
        self.waist_twist = []
        self.swing = []

    def group_key_time(self, key):
        return {'start': 0.0, 'loop start': self.intro,
                'loop stop': self.intro + self.loop_len, 'stop': self.length}.get(key)

    def local_times_of(self, t):
        """Output-local times at which our source time t shows up."""
        g = self.ours
        if g.start - EPS <= t < g.loop_start:
            return [t - g.start]
        if g.loop_start <= t <= g.loop_stop + EPS:
            return [self.intro + (t - g.loop_start) + r * g.period for r in range(self.warp.our_loops)]
        if g.loop_stop < t <= g.stop + EPS:
            return [self.intro + self.loop_len + (t - g.loop_stop)]
        return []

    def our_time(self, tau):
        g = self.ours
        if tau < self.intro:
            return g.start + tau
        if tau <= self.intro + self.loop_len + EPS:
            ph = tau - self.intro
            r = min(int(ph // g.period), self.warp.our_loops - 1)
            return g.loop_start + min(ph - r * g.period, g.period)
        return g.loop_stop + (tau - self.intro - self.loop_len)

    def their_time(self, tau):
        """(time in the 3rd-person kf, completed 3rd-person loops) for output-local tau."""
        y = self.warp(tau - self.intro)
        loops = math.floor(y / self.theirs.period)
        return self.theirs.loop_start + (y - loops * self.theirs.period), loops

    def _root(self, tau):
        t, loops = self.their_time(tau)
        p = E.translation(self.theirs_kf.data('Bip01'), t)
        a, b = self.root_a, self.root_b
        return (p[0] + loops * (b[0] - a[0]), p[1] + loops * (b[1] - a[1]), p[2])

    def lower_pose(self, tau):
        t, _ = self.their_time(tau)
        pose = their_lower_pose(self.theirs_kf, t)
        p = self._root(tau)
        pose['Bip01'] = (pose['Bip01'][0], (p[0] - self.r0[0], p[1] - self.r0[1], p[2]))
        return pose

    def sample_times(self, extra_source_times=()):
        n = int(math.ceil(self.length * FPS))
        ts = {round(min(i / FPS, self.length), 6) for i in range(n + 1)}
        ts.add(round(self.length, 6))
        ts.add(round(self.intro, 6))
        for r in range(self.warp.our_loops + 1):
            ts.add(round(self.intro + r * self.ours.period, 6))
        for t in extra_source_times:
            for tau in self.local_times_of(t):
                if 0 <= tau <= self.length + EPS:
                    ts.add(round(min(tau, self.length), 6))
        return sorted(ts)

    def describe(self):
        w = self.warp
        return 'our loop %.3fs x%d, their loop %.3fs x%d, steps %d/%d' % (
            self.ours.period, w.our_loops, self.theirs.period, w.their_loops,
            len(self.ours.steps), len(self.theirs.steps))


# ---- everything else --------------------------------------------------------------------

class KeyWarp:
    """Piecewise-linear map from our time to theirs through shared key names of one section."""

    def __init__(self, points):
        self.points = points  # [(ours, theirs)] increasing in ours, non-decreasing in theirs
        self.start = points[0][0]
        self.end = points[-1][0]

    def __call__(self, t):
        pts = self.points
        if t <= pts[0][0]:
            return pts[0][1]
        for (a, ya), (b, yb) in zip(pts, pts[1:]):
            if t <= b:
                return ya if b == a else ya + (yb - ya) * (t - a) / (b - a)
        return pts[-1][1]


# Both feet higher than this at once, in an attack or equip section, means the 3rd-person pose does
# not stand on the floor there (jumps, hits and knockdowns are not sections, so never checked).
FEET_OFF_FLOOR = 8.0


def feet_leave_floor(theirs_kf, warp, samples=40):
    for i in range(samples + 1):
        t = warp(warp.start + (warp.end - warp.start) * i / samples)
        if min(E.world(theirs_kf, 'Bip01 L Foot', t)[1][2], E.world(theirs_kf, 'Bip01 R Foot', t)[1][2]) > FEET_OFF_FLOOR:
            return True
    return False


def key_section(key):
    first = key.split()[0]
    return first if first in SECTION_WORDS else ''


def key_warps(group, ours_keys, theirs_keys):
    sections = {}
    for k, t1 in ours_keys.items():
        if 'follow' in k and any(size in k.split() for size in FOLLOW_OTHERS):
            continue
        if k in theirs_keys:
            sections.setdefault(key_section(k), []).append((t1, theirs_keys[k], k))
    warps = []
    for section, pts in sections.items():
        pts.sort()
        kept = []
        for t1, t3, k in pts:
            if kept and abs(kept[-1][0] - t1) < EPS:
                kept[-1] = (kept[-1][0], max(kept[-1][1], t3))
            elif kept and t3 < kept[-1][1]:
                print('  %s: key %r runs backwards in the 3rd person, skipped' % (group, k))
            else:
                kept.append((t1, t3))
        if len(kept) < 2:
            # A lone key (e.g. the thrown attacks' "equip stop" at their start) cannot be warped;
            # its time is covered by the idle legs between spans.
            warn('%s: section %r shares a single key with the 3rd person, ignored' % (group, section or 'main'))
            continue
        warps.append((section, KeyWarp(kept)))
    return warps or None


class StillSegment:
    """One non-locomotion group copied as is; legs from the key-warped 3rd person, or for tails the
    attack's follow-through blending into the weapon's idle. A group none of that recognises keeps
    its own legs, with a warning."""
    sway = 0.0

    def __init__(self, name, keys, ours_kf, theirs_kf, their_groups, offset):
        self.name = name
        self.keys = keys
        self.ours_kf = ours_kf
        self.theirs_kf = theirs_kf
        self.offset = offset
        self.start = min(keys.values())
        self.stop = max(keys.values())
        self.length = self.stop - self.start
        idle_name = idle_group_for(name, their_groups)
        idle = their_groups[idle_name]
        self.idle_start = idle['start']
        self.idle_period = idle['stop'] - idle['start']
        self.spans = []  # (start, end, pose of our time)
        self.notes = []
        self.own = False
        target = their_group_for(name, their_groups)
        if target is not None:
            warps = key_warps(name, keys, their_groups[target])
            if warps is None:
                self._keep_own('shares too few text keys with the 3rd-person %s' % target)
                return
            for section, warp in warps:
                if section and feet_leave_floor(theirs_kf, warp):
                    # FBA's crossbow reload squats mid-air: its feet float 20-25 units up.
                    warn('%s: the 3rd-person %s %s lifts both feet off the floor, idle legs there'
                         % (name, target, section))
                    self.notes.append('%s %s -> %s (feet off floor)' % (target, section, idle_name))
                    continue
                # Attack and equip sections lunge like FBA: their hip travel, from where the section
                # starts, moves onto the pelvis (see lower_pose).
                lunge = None
                if section:
                    r0 = E.translation(theirs_kf.data('Bip01'), warp(warp.start))
                    lunge = (r0[0], r0[1])
                self.spans.append((warp.start, warp.end,
                                   lambda t, w=warp: their_lower_pose(theirs_kf, w(t)), lunge))
                self.notes.append('%s%s' % (target, (' ' + section) if section else ''))
        elif name.endswith('extra'):
            base = their_group_for(name[:-len('extra')], their_groups)
            for k, t0 in keys.items():
                if not k.endswith('tail start'):
                    continue
                attack = k[:-len('tail start')].strip()
                t1 = keys.get('%s tail stop' % attack)
                follow = None
                if base is not None:
                    base_keys = their_groups[base]
                    follow = base_keys.get('%s %s follow stop' % (attack, FOLLOW_KEPT),
                                           base_keys.get('%s follow stop' % attack))
                if t1 is None or follow is None:
                    self._keep_own('tail of %s has no 3rd-person follow-through to start from' % attack)
                    return
                follow_end = their_lower_pose(theirs_kf, follow)

                def tail(t, t0=t0, t1=t1, a=follow_end):
                    s = min(1.0, max(0.0, (t - t0) / (t1 - t0))) if t1 > t0 else 1.0
                    return blend_pose(a, self.idle_pose(t), s * s * (3 - 2 * s))
                self.spans.append((t0, t1, tail, None))
                self.notes.append('%s %s follow stop -> %s' % (base, attack, idle_name))
            if not self.spans:
                self._keep_own('tail group without tail keys')
        else:
            self._keep_own('no 3rd-person group matches its name')

    def _keep_own(self, reason):
        self.own = True
        self.spans = []
        self.notes = ['own legs (%s)' % reason]
        warn('%s: %s, keeps its own legs' % (self.name, reason))

    def idle_pose(self, t):
        return their_lower_pose(self.theirs_kf, self.idle_start + ((t - self.start) % self.idle_period))

    def group_key_time(self, key):
        return self.keys[key] - self.start

    def local_times_of(self, t):
        return [t - self.start] if self.start - EPS <= t <= self.stop + EPS else []

    def our_time(self, tau):
        return self.start + tau

    def lower_pose(self, tau):
        t = self.start + tau
        if self.own:
            return {b: (E.rotation(self.ours_kf.data(b), t), E.translation(self.ours_kf.data(b), t))
                    for b in LOWER_BONES}
        inside = [s for s in self.spans if s[0] - EPS <= t <= s[1] + EPS]
        # At a shared boundary the earlier span ends there; the later one starts just after.
        pose = inside[0][2](t) if inside else self.idle_pose(t)
        lunge = inside[0][3] if inside else None
        root_rot, (x, y, z) = pose['Bip01']
        if lunge is not None:
            # Bip01's horizontal translation would move the player (the engine accumulates it), so
            # the hip travel goes on the pelvis instead: body and camera lunge, the feet keep their
            # planted spots, the player stays put.
            travel = (x - lunge[0], y - lunge[1], 0.0)
            pelvis_rot, pelvis_trans = pose['Bip01 Pelvis']
            local = E.qrot(E.qconj(root_rot), travel)
            pose['Bip01 Pelvis'] = (pelvis_rot, tuple(a + b for a, b in zip(pelvis_trans, local)))
        pose['Bip01'] = (root_rot, (0.0, 0.0, z))
        return pose

    def sample_times(self, extra_source_times=()):
        n = int(math.ceil(self.length * FPS))
        ts = {round(min(i / FPS, self.length), 6) for i in range(n + 1)}
        ts.add(round(self.length, 6))
        for s in self.spans:
            for t in (s[0], s[1], s[1] + 1e-3):
                tau = t - self.start
                if 0 <= tau <= self.length:
                    ts.add(round(tau, 6))
        for t in extra_source_times:
            for tau in self.local_times_of(t):
                ts.add(round(min(max(tau, 0.0), self.length), 6))
        return sorted(ts)

    def describe(self):
        return ', '.join(self.notes)


# ---- build ---------------------------------------------------------------------------

def mean_sway(ours_kf, seg):
    """Average rotation from our Spine to theirs over the loop."""
    n = 120
    total = None
    for i in range(n):
        tau = seg.intro + i * seg.loop_len / n
        ours, _, theirs = spine_worlds(ours_kf, seg, tau, seg.lower_pose(tau))
        d = E.qmul(theirs, E.qconj(ours))
        if total is None:
            total = d
        else:
            if sum(a * b for a, b in zip(total, d)) < 0:
                d = tuple(-c for c in d)
            total = tuple(a + b for a, b in zip(total, d))
    return E.qnorm(total)


def spine_worlds(ours_kf, seg, tau, pose):
    """(our Spine world rotation, their Pelvis world rotation, their Spine world rotation)."""
    t_ours = seg.our_time(tau)
    ours = E.qmul(pelvis_world_rotation(ours_kf, t_ours), E.rotation(ours_kf.data(COMPENSATED_BONE), t_ours))
    their_pelvis = E.qmul(pose['Bip01'][0], pose['Bip01 Pelvis'][0])
    return ours, their_pelvis, E.qmul(their_pelvis, pose[COMPENSATED_BONE][0])


def add_rest_bones(ours_kf, reference):
    """Gives ours_kf constant tracks, in the reference kf's pose, for lower body bones it lacks (the
    bow set has no Bip01): the merge needs our pose there, and in game that pose comes from the rig."""
    times = [tm for tm, _ in ours_kf.text_keys()]
    first, last = min(times), max(times)
    for b in LOWER_BONES:
        if b in ours_kf.bone_data and ours_kf.data(b).trans['keys'] and ours_kf.data(b).quat_keys + (
                ours_kf.data(b).xyz or []):
            continue
        ref = reference.data(b)
        ref_t = ref.xyz[0]['keys'][0][0] if ref.rot_type == 4 else ref.quat_keys[0][0]
        rot = E.rotation(ref, ref_t)
        trans = tuple(E.translation(ref, ref_t))
        d = ours_kf.data(b) if b in ours_kf.bone_data else ours_kf.add_bone(b)
        d.rot_type = 1
        d.xyz = None
        d.quat_keys = [(first, rot, ()), (last, rot, ())]
        d.trans = {'itype': 1, 'keys': [(first, trans, ()), (last, trans, ())]}
        warn('%s not keyed, merged from the rig rest pose' % b)


def build(ours_path, theirs_path, out_path, reference=None):
    """Merges one kf. Returns its segments, or None when no group was recognised (nothing written)."""
    import os
    _current_file[0] = os.path.basename(ours_path)
    ours_kf = nifkf.KF.load(ours_path)
    theirs_kf = nifkf.KF.load(theirs_path)
    for b in LOWER_BONES:
        if b not in theirs_kf.bone_data:
            raise ValueError('3rd-person kf has no %s' % b)
    if not ours_kf.text_keys():
        warn('no text keys, not merged')
        return None
    if reference is not None:
        add_rest_bones(ours_kf, reference)
    else:
        for b in LOWER_BONES:
            if b not in ours_kf.bone_data:
                raise ValueError('1st-person kf has no %s' % b)

    our_lines = text_lines(ours_kf)
    their_lines = text_lines(theirs_kf)
    our_groups = all_group_keys(our_lines)
    their_groups = all_group_keys(their_lines)
    names = sorted(our_groups, key=lambda g: (min(our_groups[g].values()), g))

    segments = []
    offset = 0.0
    for name in names:
        keys = our_groups[name]
        target = their_group_for(name, their_groups)
        if LOCOMOTION.match(name) and 'start' in keys and 'stop' in keys and target is not None:
            ours = Group(our_lines, name)
            theirs = Group(their_lines, target)
            if theirs.steps_usable():
                labelled = list(theirs.steps)
                theirs.relabel_by_feet(theirs_kf)
                if not theirs.steps_usable():
                    # The foot heights are too close to call (runrighthh): trust the markers.
                    theirs.steps = labelled
            if not (ours.steps_usable() and theirs.steps_usable()):
                warn('%s: no usable step markers (ours %d, theirs %d), stretched loop to loop'
                     % (name, len(ours.steps), len(theirs.steps)))
                ours.steps = [(0.0, 'loop')]
                theirs.steps = [(0.0, 'loop')]
            seg = LocomotionSegment(ours, theirs, theirs_kf, offset)
            seg.mean_sway = mean_sway(ours_kf, seg)
        else:
            seg = StillSegment(name, keys, ours_kf, theirs_kf, their_groups, offset)
        segments.append(seg)
        offset += seg.length + SEGMENT_GAP
    if all(getattr(seg, 'own', False) for seg in segments):
        warn('no group recognised, file not merged')
        return None

    new_data = {b: nifkf.KeyframeData() for b in ours_kf.bone_data}
    for d in new_data.values():
        d.rot_type = 1
        d.trans = {'itype': 1, 'keys': []}
        d.scale = {'itype': 1, 'keys': []}

    spine_extra = set()
    for b in LOWER_BONES[:3]:
        spine_extra |= key_times(ours_kf.data(b))
    for seg in segments:
        seg.waist_twist = []
        seg.swing = []
        for tau in seg.sample_times(spine_extra):
            t_out = seg.offset + tau
            pose = seg.lower_pose(tau)
            ours_world, their_pelvis, theirs_world = spine_worlds(ours_kf, seg, tau, pose)
            target = ours_world
            if seg.sway:
                swing = E.qmul(E.qmul(theirs_world, E.qconj(ours_world)), E.qconj(seg.mean_sway))
                seg.swing.append(E.qangle(swing, IDENTITY))
                target = E.qmul(E.qslerp(IDENTITY, swing, seg.sway), ours_world)
            compensated = E.qmul(E.qconj(their_pelvis), target)
            seg.waist_twist.append(E.qangle(compensated, pose[COMPENSATED_BONE][0]))
            pose[COMPENSATED_BONE] = (compensated, pose[COMPENSATED_BONE][1])
            for bone in LOWER_BONES:
                rot, trans = pose[bone]
                new_data[bone].quat_keys.append((t_out, E.qnorm(rot), ()))
                new_data[bone].trans['keys'].append((t_out, tuple(trans), ()))
        for bone, dst in new_data.items():
            if bone in LOWER_BONES:
                continue
            src = ours_kf.data(bone)
            for tau in seg.sample_times(key_times(src)):
                t_ours = seg.our_time(tau)
                t_out = seg.offset + tau
                rot = E.rotation(src, t_ours)
                trans = E.translation(src, t_ours)
                scale = E._interp_group(src.scale['keys'], src.scale['itype'], t_ours, 1)
                if rot is not None:
                    dst.quat_keys.append((t_out, E.qnorm(rot), ()))
                if trans is not None:
                    dst.trans['keys'].append((t_out, tuple(trans), ()))
                if scale is not None:
                    dst.scale['keys'].append((t_out, scale, ()))

    # Keep quaternion signs continuous so slerp takes the short way between our samples.
    for d in new_data.values():
        fixed = []
        for t, q, extra in d.quat_keys:
            if fixed and sum(a * b for a, b in zip(fixed[-1][1], q)) < 0:
                q = tuple(-c for c in q)
            fixed.append((t, q, extra))
        d.quat_keys = fixed
        if not d.quat_keys:
            d.rot_type = 0
        for channel in ('trans', 'scale'):
            if not d.__dict__[channel]['keys']:
                d.__dict__[channel] = {'itype': 0, 'keys': []}

    for bone, di in ours_kf.bone_data.items():
        t, _ = ours_kf.blocks[di]
        ours_kf.blocks[di] = (t, new_data[bone])
    end = segments[-1].offset + segments[-1].length
    for t, p in ours_kf.blocks:
        if t == 'NiKeyframeController':
            p['start'] = 0.0
            p['stop'] = end

    # Text keys: each group's own keys, plus every key not naming one of our groups (footsteps,
    # sounds) from its range, per segment.
    sep = '\r\n' if any('\r\n' in s for _, s in ours_kf.text_keys()) else '\n'
    by_time = {}
    for seg in segments:
        for tm, line in our_lines:
            if ':' in line:
                name, key = split_line(line)
            else:
                name, key = None, None
            if name == seg.name:
                tau = seg.group_key_time(key)
                taus = [tau] if tau is not None else seg.local_times_of(tm)[:1]
            elif name not in our_groups:
                taus = seg.local_times_of(tm)
            else:
                continue
            for tau in taus:
                lines = by_time.setdefault(round(seg.offset + tau, 5), [])
                if line not in lines:
                    lines.append(line)
    tk = ours_kf.blocks[ours_kf.textkey_block][1]
    tk['keys'] = [(t, sep.join(lines)) for t, lines in sorted(by_time.items())]

    ours_kf.save(out_path)
    return segments


def report(segments):
    for seg in segments:
        extra = ''
        if seg.swing:
            extra = ', swing up to %.1f deg (%.1f kept)' % (max(seg.swing), max(seg.swing) * seg.sway)
        print('  %-24s %s%s, waist twist up to %.1f deg' % (seg.name, seg.describe(), extra, max(seg.waist_twist)))


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    report(build(*sys.argv[1:]))
