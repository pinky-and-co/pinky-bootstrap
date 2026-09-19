"""setup/style.py — terminal style for the CLI's own output.

What matters goes first and stands out: the report of a tool that says a lot must still let the
eye land on the one thing to act on. Color is a hint, never information: it is off when the output
is not a terminal (a pipe, a file, CI) and whenever `NO_COLOR` is set, so logs and tests stay plain.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TextIO

RESET = "\x1b[0m"
GREEN = "32"
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


# Chosen by `PINKY_DIFF_STYLE`. The 16-color codes (`bg16`) are cases of the terminal's own palette
# and follow its theme; the truecolor ones are fixed values, one set per light or dark background.
_DIFF_STYLES = {
    "text": DiffCodes(RED_BOLD, GREEN),
    "bg16": DiffCodes("97;41", "30;42"),
    "github-light": DiffCodes("48;2;255;235;233", "48;2;218;251;225"),
    "github-dark": DiffCodes("48;2;61;22;26", "48;2;18;38;30"),
}


def diff_codes(environ: Mapping[str, str] | None = None) -> DiffCodes:
    """The codes for the diff style named by `PINKY_DIFF_STYLE` (colored text when unset or unknown)."""
    env = os.environ if environ is None else environ
    return _DIFF_STYLES.get(env.get("PINKY_DIFF_STYLE", "text"), _DIFF_STYLES["text"])
