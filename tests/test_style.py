"""Terminal style: color only on a terminal, and never against `NO_COLOR`."""

import io
import subprocess
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


def _defaults(stdout: str):
    """A stand-in for `defaults read -g AppleInterfaceStyle`, the OS boundary."""

    def run(cmd, **kwargs):
        assert cmd == ["defaults", "read", "-g", "AppleInterfaceStyle"]
        return subprocess.CompletedProcess(cmd, 0 if stdout else 1, stdout, "")

    return run


def test_pinky_theme_decides_before_anything_is_asked_of_the_system():
    def run(*_a, **_k):
        raise AssertionError("must not ask the system")

    assert style.is_light_theme({"PINKY_THEME": "light"}, platform="darwin", run=run)
    assert not style.is_light_theme({"PINKY_THEME": "dark"}, platform="darwin", run=run)


def test_macos_dark_mode_is_a_dark_theme():
    assert not style.is_light_theme({}, platform="darwin", run=_defaults("Dark\n"))


def test_macos_light_mode_is_a_light_theme():
    assert style.is_light_theme({}, platform="darwin", run=_defaults(""))


def test_elsewhere_colorfgbg_names_the_background():
    assert style.is_light_theme({"COLORFGBG": "0;15"}, platform="linux")
    assert not style.is_light_theme({"COLORFGBG": "15;0"}, platform="linux")


def test_an_undecided_theme_counts_as_dark():
    assert not style.is_light_theme({}, platform="linux")
    assert not style.is_light_theme({"COLORFGBG": "garbage"}, platform="linux")


def test_a_dark_theme_paints_the_diff_as_colored_text():
    assert style.diff_codes({"PINKY_THEME": "dark"}) == style.DiffCodes(
        style.RED_BOLD, style.GREEN
    )


def test_a_light_theme_paints_the_diff_as_pastel_backgrounds():
    assert style.diff_codes({"PINKY_THEME": "light"}) == style.DiffCodes(
        "48;2;255;235;233", "48;2;218;251;225"
    )
