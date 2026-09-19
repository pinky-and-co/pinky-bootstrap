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


def test_the_diff_style_defaults_to_colored_text():
    assert style.diff_codes({}) == style.DiffCodes(style.RED_BOLD, style.GREEN)


def test_the_diff_style_can_be_a_background_from_the_terminals_own_palette():
    assert style.diff_codes({"PINKY_DIFF_STYLE": "bg16"}) == style.DiffCodes(
        "97;41", "30;42"
    )


def test_the_diff_style_can_mimic_github_in_light_or_dark():
    assert style.diff_codes({"PINKY_DIFF_STYLE": "github-light"}) == style.DiffCodes(
        "48;2;255;235;233", "48;2;218;251;225"
    )
    assert style.diff_codes({"PINKY_DIFF_STYLE": "github-dark"}) == style.DiffCodes(
        "48;2;61;22;26", "48;2;18;38;30"
    )


def test_an_unknown_diff_style_falls_back_to_colored_text():
    assert style.diff_codes({"PINKY_DIFF_STYLE": "nope"}) == style.DiffCodes(
        style.RED_BOLD, style.GREEN
    )
