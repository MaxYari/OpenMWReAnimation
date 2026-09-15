"""Parameters from the command line, or asked for in the console with the default pre-filled.

Without a console (stdin not a terminal), or with USE_DEFAULTS set (-y), the defaults are used, so
builds can run unattended.
"""
import os
import sys
import textwrap

USE_DEFAULTS = False
HERE = os.path.dirname(os.path.abspath(__file__))
# The folder the animation mod sits in, next to FBA and the output folders.
MODS = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..'))


def yes_no(value):
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ('y', 'yes', 'true', '1', 'on'):
        return True
    if s in ('n', 'no', 'false', '0', 'off'):
        return False
    raise ValueError('expected y or n, got %r' % value)


def ask(given, label, explanation, default, cast):
    """given: the command-line value or None. Enter at the prompt keeps the default; a None default
    (nothing found) has to be typed in."""
    if given is not None:
        return cast(given)
    if USE_DEFAULTS or not sys.stdin.isatty():
        if default is None:
            sys.exit('%s: not found, give it on the command line (see --help)' % label)
        return default
    shown = ('y' if default else 'n') if isinstance(default, bool) else ('' if default is None else default)
    print('\n' + label)
    for line in textwrap.wrap(explanation, 92):
        print('  ' + line)
    while True:
        answer = input('  [%s] > ' % shown).strip().strip('"')
        if not answer:
            if default is None:
                continue
            return default
        try:
            return cast(answer)
        except ValueError as e:  # a typo re-asks instead of ending the build
            print('  %s, try again' % e)


# ---- finding folders ---------------------------------------------------------------------

def child(folder, name):
    """folder/name, matched case-insensitively, or None."""
    try:
        for n in os.listdir(folder):
            if n.lower() == name.lower():
                return os.path.join(folder, n)
    except OSError:
        pass
    return None


def openmw_data_folders():
    """data= folders from openmw.cfg (commented-out ones too: a mod switched off is still there)."""
    cfgs = [os.path.expanduser('~/.config/openmw/openmw.cfg'),
            os.path.expanduser('~/Documents/My Games/OpenMW/openmw.cfg'),
            os.path.expanduser('~/Library/Preferences/openmw/openmw.cfg')]
    out = []
    for cfg in cfgs:
        if not os.path.isfile(cfg):
            continue
        for line in open(cfg, encoding='utf-8', errors='replace'):
            line = line.strip().lstrip('#').strip()
            if line.startswith('data='):
                out.append(line[5:].strip().strip('"').replace('&&', '&'))
    return out


def _mod_folders(depth=3):
    """Folders under MODS, down to depth levels."""
    for root, dirs, _ in os.walk(MODS):
        dirs.sort()
        if os.path.relpath(root, MODS).count(os.sep) >= depth - 1:
            dirs[:] = []
        yield root


def find_fba():
    """FBA's folder (the one with meshes/xbase_anim.1st.kf), from openmw.cfg or the mods folder."""
    def is_fba(folder):
        meshes = child(folder, 'meshes')
        return meshes is not None and child(meshes, 'xbase_anim.1st.kf') is not None
    found = []
    for folder in openmw_data_folders() + list(_mod_folders()):
        if folder not in found and is_fba(folder):
            found.append(folder)
    # Other mods can ship a 1st-person kf too; prefer the one named after FBA.
    named = [f for f in found if 'full body awareness' in f.lower()]
    return (named or found or [None])[0]


def find_data_files():
    """The folder with Morrowind.bsa, from openmw.cfg."""
    for folder in openmw_data_folders():
        if child(folder, 'Morrowind.bsa'):
            return folder
    return None
