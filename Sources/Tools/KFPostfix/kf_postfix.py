"""Post-export fixes for ReAnimation .kf files: text keys, and where a file sits on the timeline.

Run after every Blender export of an animation, see README.md next to this file for why:

    python3 Sources/Tools/KFPostfix/kf_postfix.py check   # what changed since the last patch
    python3 Sources/Tools/KFPostfix/kf_postfix.py apply   # (re)patch listed files, record new hashes

kf_postfix.json is the list of files that get patched, with the hashes of the last export (source)
and of the patched result, so a re-exported .kf is detected by its hash.
"""
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'FBACompat'))
from nifkf import KF  # noqa: E402

MANIFEST = os.path.join(HERE, 'kf_postfix.json')
ANIM_DIRS = ['Animations/xbase_anim.1st']
SAME_TIME = 1e-5

HIT_KEY = re.compile(r'^(shoot) release$|^(chop|slash|thrust) hit$')
FOLLOW_KEY = re.compile(r'^(shoot) follow start$|^(chop|slash|thrust) (?:small|medium|large) follow start$')


def sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def split_line(line):
    if ':' not in line:
        return None, None
    g, k = line.split(':', 1)
    return g.strip().lower(), k.strip().lower()


# ---- operations --------------------------------------------------------------
# separate-follow-start: the engine starts the follow-through segment at "<attack> follow start"
# and fires every text key at that exact time (Animation::play, lowerBound(startTime)). A hit or
# release key on the same time is therefore fired a second time, and so is anything else sharing
# the frame (e.g. "Sound: CrossbowShoot"). Moving the follow start key `epsilon` later keeps it out
# of the release segment and makes the follow segment start past the release key.

def find_follow_starts(kf):
    """[(entry index, line index, line, time)] of follow start keys sharing their time with the
    hit/release key of the same group and attack."""
    hits = {}
    for tm, text in kf.text_keys():
        for line in text.replace('\r', '').split('\n'):
            g, k = split_line(line)
            m = k and HIT_KEY.match(k)
            if m:
                hits[(g, m.group(1) or m.group(2))] = tm
    out = []
    for ei, (tm, text) in enumerate(kf.text_keys()):
        for li, line in enumerate(text.replace('\r', '').split('\n')):
            g, k = split_line(line)
            m = k and FOLLOW_KEY.match(k)
            if not m:
                continue
            hit_time = hits.get((g, m.group(1) or m.group(2)))
            if hit_time is not None and abs(hit_time - tm) < SAME_TIME:
                out.append((ei, li, line.strip(), tm))
    return out


def separate_follow_start(kf, epsilon):
    """Moves the matching follow start lines into new entries at time + epsilon, right after the
    entry they came from. Returns [(line, old time, new time)]."""
    found = find_follow_starts(kf)
    if not found:
        return []
    moving = {}
    for ei, li, line, tm in found:
        moving.setdefault(ei, set()).add(li)
    keys = kf.text_keys()
    new_keys = []
    moved = []
    for ei, (tm, text) in enumerate(keys):
        sep = '\r\n' if '\r\n' in text else '\n'
        lines = text.replace('\r', '').split('\n')
        if ei not in moving:
            new_keys.append((tm, text))
            continue
        keep = [ln for li, ln in enumerate(lines) if li not in moving[ei]]
        move = [ln for li, ln in enumerate(lines) if li in moving[ei]]
        if keep:
            new_keys.append((tm, sep.join(keep)))
        new_keys.append((tm + epsilon, sep.join(move)))
        moved += [(ln.strip(), tm, tm + epsilon) for ln in move]
    new_keys.sort(key=lambda e: e[0])  # stable: equal times keep their order
    keys[:] = new_keys
    return moved


# align-time: moves the whole file - text keys, every track, and the controllers' start/stop - so
# one text key lands on a given time. The animation itself is untouched; only where it sits on the
# file's timeline changes. For thrown weapons that position is not neutral: OpenMW drives the held
# weapon mesh's own controllers with the absolute time of the "throwweapon" group
# (WeaponAnimationTime, character.cpp setWeaponGroup: relative time is for Ranged only). Meshes
# that bake a flight spin into the model (Improved Weapon Mesh Compilation, 0..4 s) expect the
# group where vanilla has it, 48.7 s on; at 0..1 s the knife jumps to its flight pose. Blender
# exports every action from 0, hence a post-export step.

def find_align_key(kf, key):
    """Time of the text key line equal to `key` (case-insensitive), or None."""
    want = key.strip().lower()
    for tm, text in kf.text_keys():
        for line in text.replace('\r', '').split('\n'):
            if line.strip().lower() == want:
                return tm
    return None


def shift_all(kf, offset):
    def shifted(keys):
        return [(k[0] + offset,) + tuple(k[1:]) for k in keys]
    for t, p in kf.blocks:
        if t == 'NiTextKeyExtraData':
            p['keys'] = [(tm + offset, s) for tm, s in p['keys']]
        elif t == 'NiKeyframeController':
            p['start'] += offset
            p['stop'] += offset
        elif t == 'NiKeyframeData':
            p.quat_keys = shifted(p.quat_keys)
            for g in p.xyz or ():
                g['keys'] = shifted(g['keys'])
            p.trans['keys'] = shifted(p.trans['keys'])
            p.scale['keys'] = shifted(p.scale['keys'])


def find_misaligned(kf, align):
    tm = find_align_key(kf, align['key'])
    if tm is None:
        raise ValueError(f'align-time: no text key "{align["key"]}"')
    return [] if abs(tm - align['time']) < SAME_TIME else [(align['key'], tm)]


def align_time(kf, align):
    """Returns [(description, old time, new time)] of the anchor key, or [] if already aligned."""
    found = find_misaligned(kf, align)
    if not found:
        return []
    tm = found[0][1]
    shift_all(kf, align['time'] - tm)
    return [(f'{align["key"]} (whole file)', tm, align['time'])]


# Each operation takes (kf, manifest entry, epsilon); detection takes (kf, manifest entry).
OPS = {'separate-follow-start': lambda kf, entry, eps: separate_follow_start(kf, eps),
       'align-time': lambda kf, entry, eps: align_time(kf, entry['align'])}
DETECT = {'separate-follow-start': lambda kf, entry: find_follow_starts(kf),
          'align-time': lambda kf, entry: find_misaligned(kf, entry['align'])}


def entry_ops(entry):
    """An entry names one operation ("op") or several ("ops"), applied in that order."""
    return entry['ops'] if 'ops' in entry else [entry['op']]


def pending_ops(kf, entry):
    return [op for op in entry_ops(entry) if DETECT[op](kf, entry)]


# ---- commands ----------------------------------------------------------------

def load_manifest():
    return json.load(open(MANIFEST))


def save_manifest(man):
    with open(MANIFEST, 'w') as f:
        json.dump(man, f, indent=2)
        f.write('\n')


def unlisted_candidates(man):
    """Animations that would need an operation but are not in the manifest."""
    out = []
    for d in ANIM_DIRS:
        for name in sorted(os.listdir(os.path.join(REPO, d))):
            rel = f'{d}/{name}'
            if not name.lower().endswith('.kf') or rel in man['files']:
                continue
            kf = KF.load(os.path.join(REPO, rel))
            if kf.textkey_block is None:
                continue
            # align-time needs a target per file, so only the follow start fix can be guessed at.
            found = find_follow_starts(kf)
            if found:
                out.append((rel, 'separate-follow-start', sorted({ln for _, _, ln, _ in found})))
    return out


def check(man):
    attention = False
    for rel, entry in man['files'].items():
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            print(f'MISSING   {rel}')
            attention = True
            continue
        h = sha256(path)
        pending = pending_ops(KF.load(path), entry)
        if h == entry.get('patched_sha256') and not pending:
            print(f'ok        {rel}  (patched {entry.get("patched_at")})')
        elif h == entry.get('source_sha256'):
            print(f'UNPATCHED {rel}  (same export as last time, patch not applied) -> run apply')
            attention = True
        elif pending:
            print(f'CHANGED   {rel}  (new export, needs {", ".join(pending)}) -> run apply')
            attention = True
        else:
            print(f'CHANGED   {rel}  (new export, nothing to fix any more) -> run apply to record it')
            attention = True
    extra = unlisted_candidates(man)
    for rel, op, lines in extra:
        print(f'UNLISTED  {rel}  would need {op}: {", ".join(lines)}')
    if extra:
        print('          (add to kf_postfix.json "files" if they should be patched)')
    return 1 if attention else 0


def apply(man):
    eps = man['epsilon']
    today = datetime.date.today().isoformat()
    for rel, entry in man['files'].items():
        path = os.path.join(REPO, rel)
        h = sha256(path)
        kf = KF.load(path)
        # The hash alone is not enough: an entry that gained an operation still matches the hash
        # recorded under the old list.
        if h == entry.get('patched_sha256') and not pending_ops(kf, entry):
            print(f'ok        {rel}  already patched')
            continue
        moved = []
        for op in entry_ops(entry):
            moved += OPS[op](kf, entry, eps)
        if moved:
            kf.save(path)
            entry['source_sha256'] = h
            entry['moved'] = [f'{ln}: {a:.4f} -> {b:.4f}' for ln, a, b in moved]
            print(f'patched   {rel}')
            for m in entry['moved']:
                print(f'            {m}')
        else:
            entry['source_sha256'] = h
            entry['moved'] = []
            print(f'no-op     {rel}  nothing to fix in this export, hash recorded')
        entry['patched_sha256'] = sha256(path)
        entry['patched_at'] = today
    save_manifest(man)
    return 0


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if cmd not in ('check', 'apply'):
        sys.exit(__doc__)
    manifest = load_manifest()
    sys.exit(check(manifest) if cmd == 'check' else apply(manifest))
