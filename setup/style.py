"""setup/style.py — terminal style for the CLI's own output.

What matters goes first and stands out: the report of a tool that says a lot must still let the
eye land on the one thing to act on. Color is a hint, never information: it is off when the output
is not a terminal (a pipe, a file, CI) and whenever `NO_COLOR` is set, so logs and tests stay plain.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
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
