"""Parameters from the command line, or asked for in the console with the default pre-filled.

Without a console (stdin not a terminal), or with USE_DEFAULTS set (-y), the defaults are used, so
builds can run unattended.
"""
import atexit
import os
import re
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


def interactive():
    """A console to ask in (pythonw has no stdin at all)."""
    return sys.stdin is not None and sys.stdin.isatty()


def keep_console_open():
    """A double-clicked script on Windows gets a console that closes the moment it ends, with the
    summary, the warnings or a traceback in it. When questions are asked, wait for Enter at the end
    (atexit runs after a traceback is printed)."""
    if os.name == 'nt' and not USE_DEFAULTS and interactive():
        atexit.register(input, '\nPress Enter to close.')


def ask(given, label, explanation, default, cast):
    """given: the command-line value or None. default: a value, or a function finding it, called only
    when needed. Enter at the prompt keeps the default; a None default (nothing found) has to be
    typed in."""
    if given is not None:
        return cast(given)
    if callable(default):
        default = default()
    if USE_DEFAULTS or not interactive():
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


def _documents_folders():
    """Documents, where OpenMW keeps its settings on Windows: where Windows really has it (OneDrive
    can move it), then the usual place."""
    out = []
    if os.name == 'nt':
        import ctypes
        path = ctypes.create_unicode_buffer(260)
        # CSIDL_PERSONAL, SHGFP_TYPE_CURRENT: Documents, wherever it was redirected. 0 is S_OK.
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, path) == 0:
            out.append(path.value)
    out.append(os.path.join(os.path.expanduser('~'), 'Documents'))
    return out


def openmw_cfgs():
    """Every openmw.cfg found: Linux (XDG, Flatpak), Windows, macOS."""
    home = os.path.expanduser('~')
    folders = [os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.join(home, '.config'), 'openmw'),
               os.path.join(home, '.var', 'app', 'org.openmw.OpenMW', 'config', 'openmw'),
               os.path.join(home, 'Library', 'Preferences', 'openmw')]
    folders += [os.path.join(d, 'My Games', 'OpenMW') for d in _documents_folders()]
    out = []
    for folder in folders:
        cfg = os.path.join(folder, 'openmw.cfg')
        if os.path.isfile(cfg) and cfg not in out:
            out.append(cfg)
    return out


DATA_LINE = re.compile(r'data\s*=\s*(.*)$')


def _cfg_path(value):
    """A path as openmw.cfg writes it: in double quotes, & escaping the character after it (&& and &")."""
    value = value.strip()
    if not value.startswith('"'):
        return value
    out = []
    i = 1
    while i < len(value) and value[i] != '"':
        if value[i] == '&' and i + 1 < len(value):
            i += 1
        out.append(value[i])
        i += 1
    return ''.join(out)


def openmw_data_folders():
    """[(folder, enabled)] for the data= lines of every openmw.cfg, in file order. Commented-out ones
    come too, not enabled: a mod switched off is still there."""
    out = []
    for cfg in openmw_cfgs():
        for line in open(cfg, encoding='utf-8', errors='replace'):
            line = line.strip()
            m = DATA_LINE.match(line.lstrip('#').strip())
            if m:
                out.append((_cfg_path(m.group(1)), not line.startswith('#')))
    return out


def _by_preference(data_folders):
    """Enabled folders before switched-off ones, each from the last line up: of two folders with the
    same file, the game uses the later one."""
    return ([f for f, enabled in reversed(data_folders) if enabled] +
            [f for f, enabled in reversed(data_folders) if not enabled])


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
    for folder in _by_preference(openmw_data_folders()) + list(_mod_folders()):
        if folder not in found and is_fba(folder):
            found.append(folder)
    # Other mods can ship a 1st-person kf too; prefer the one named after FBA.
    named = [f for f in found if 'full body awareness' in f.lower()]
    return (named or found or [None])[0]


def find_data_files():
    """The folder with Morrowind.bsa, from openmw.cfg."""
    for folder in _by_preference(openmw_data_folders()):
        if child(folder, 'Morrowind.bsa'):
            return folder
    return None
