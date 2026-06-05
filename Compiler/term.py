"""Tiny ANSI color helpers — dependency-free, and a no-op when output is not a
TTY or NO_COLOR is set, so piped/redirected build logs stay clean."""

import os
import sys


def _supported() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        # Enable ANSI escape processing on Windows 10+ consoles.
        os.system("")
    return True


ENABLED = _supported()

_CODES = {
    "reset": "0", "bold": "1", "dim": "2",
    "red": "31", "green": "32", "yellow": "33",
    "blue": "34", "magenta": "35", "cyan": "36", "grey": "90",
}


def style(text: str, *names: str) -> str:
    """Wrap text in the given style codes (e.g. style('hi', 'bold', 'green'))."""
    if not ENABLED or not names:
        return text
    prefix = "".join(f"\033[{_CODES[n]}m" for n in names)
    return f"{prefix}{text}\033[0m"


def red(t):    return style(t, "red")
def green(t):  return style(t, "green")
def yellow(t): return style(t, "yellow")
def cyan(t):   return style(t, "cyan")
def bold(t):   return style(t, "bold")
def dim(t):    return style(t, "dim")
