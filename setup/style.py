"""setup/style.py — terminal style for the CLI's own output.

What matters goes first and stands out: the report of a tool that says a lot must still let the
eye land on the one thing to act on. Color is a hint, never information: it is off when the output
is not a terminal (a pipe, a file, CI) and whenever `NO_COLOR` is set, so logs and tests stay plain.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 — `defaults`, fixed argv, never shell=True
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TextIO

RESET = "\x1b[0m"
GREEN = "32"
YELLOW = "33"
RED_BOLD = "1;31"
BOLD = "1"
DIM = "2"


def use_color(
    stream: TextIO | None = None, environ: Mapping[str, str] | None = None
) -> bool:
    """Whether to emit ANSI codes on `stream` (stdout by default): a real terminal, `NO_COLOR`
    unset or empty, and not a `dumb` terminal."""
    out = stream if stream is not None else sys.stdout
    env = os.environ if environ is None else environ
    return out.isatty() and not env.get("NO_COLOR") and env.get("TERM") != "dumb"


def paint(text: str, code: str, *, color: bool) -> str:
    """`text` wrapped in the SGR `code` when `color` is on, untouched otherwise."""
    return f"\x1b[{code}m{text}{RESET}" if color else text


@dataclass(frozen=True)
class DiffCodes:
    """The SGR codes a removed and an added diff line are painted with."""

    removed: str
    added: str


_DIFF_ON_DARK = DiffCodes(RED_BOLD, GREEN)
# Pastel backgrounds like GitHub's light diff: fixed truecolor values, legible only on a light
# background — which is why they are used on a light theme alone.
_DIFF_ON_LIGHT = DiffCodes("48;2;255;235;233", "48;2;218;251;225")


def is_light_theme(
    environ: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    """Whether the terminal has a light background, best effort.

    `PINKY_THEME=light|dark` decides when set. Otherwise macOS says so: `AppleInterfaceStyle` reads
    `Dark` in dark mode and nothing in light mode. Elsewhere `COLORFGBG` (`fg;bg`, set by some
    terminals) is read. Anything undecided counts as dark, where colored text is legible.
    """
    env = os.environ if environ is None else environ
    forced = env.get("PINKY_THEME", "").lower()
    if forced in ("light", "dark"):
        return forced == "light"
    if (platform or sys.platform) == "darwin":
        result = run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],  # nosec B603, B607
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return "dark" not in result.stdout.lower()
    background = env.get("COLORFGBG", "").rsplit(";", 1)[-1]
    return background.isdigit() and int(background) in (7, 9, 10, 11, 12, 13, 14, 15)


def diff_codes(
    environ: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DiffCodes:
    """How a removed and an added diff line are painted: a pastel background on a light theme,
    colored text (the terminal's own red and green) otherwise."""
    if is_light_theme(environ, platform=platform, run=run):
        return _DIFF_ON_LIGHT
    return _DIFF_ON_DARK
