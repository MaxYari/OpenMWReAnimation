"""Parameters from the command line, or asked for in the console with the default pre-filled.

Without a console (stdin not a terminal) the defaults are used, so builds can run unattended.
"""
import sys
import textwrap


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
    """given: the command-line value or None. Enter at the prompt keeps the default."""
    if given is not None:
        return cast(given)
    if not sys.stdin.isatty():
        return default
    shown = ('y' if default else 'n') if isinstance(default, bool) else default
    print('\n' + label)
    for line in textwrap.wrap(explanation, 92):
        print('  ' + line)
    while True:
        answer = input('  [%s] > ' % shown).strip().strip('"')
        if not answer:
            return default
        try:
            return cast(answer)
        except ValueError as e:  # a typo re-asks instead of ending the build
            print('  %s, try again' % e)
