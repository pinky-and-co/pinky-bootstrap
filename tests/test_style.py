"""Terminal style: color only on a terminal, and never against `NO_COLOR`."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import style


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_color_is_off_when_the_stream_is_not_a_terminal():
    assert style.use_color(io.StringIO(), {}) is False


def test_color_is_on_for_a_terminal():
    assert style.use_color(_Tty(), {"TERM": "xterm-256color"}) is True


def test_no_color_turns_it_off_even_on_a_terminal():
    assert style.use_color(_Tty(), {"NO_COLOR": "1"}) is False


def test_a_dumb_terminal_gets_no_color():
    assert style.use_color(_Tty(), {"TERM": "dumb"}) is False


def test_paint_wraps_the_text_when_color_is_on():
    assert style.paint("x", style.RED_BOLD, color=True) == "\x1b[1;31mx\x1b[0m"


def test_paint_leaves_the_text_alone_when_color_is_off():
    assert style.paint("x", style.RED_BOLD, color=False) == "x"
