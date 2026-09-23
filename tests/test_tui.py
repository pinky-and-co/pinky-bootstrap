"""`setup/tui.py` — the `questionary.checkbox` glue: choice building (tree indent, color,
disabled grouping nodes) and the index round-trip `run_checklist` does on top of it.

`questionary` itself is never driven here (no terminal in CI) — `questionary.checkbox` is
monkeypatched at the boundary, same discipline as `test_doctor.py` fakes `subprocess.run`.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import tui


def test_title_is_plain_text_indented_by_depth():
    item = tui.ChecklistItem("pinky-agentic-plugins", depth=2)
    assert tui._title(item) == "    pinky-agentic-plugins"


def test_title_marks_an_already_active_item_with_a_suffix():
    """Plain text, never a formatted-text list: `questionary` renders a list title verbatim and
    drops its own checked/pointer styling for that row."""
    item = tui.ChecklistItem("bootstrap", checked=True, depth=1)
    assert tui._title(item) == "  bootstrap ✓"


def test_title_leaves_a_non_selectable_grouping_node_unmarked():
    item = tui.ChecklistItem("pinky-lib", selectable=False, depth=1)
    assert tui._title(item) == "  pinky-lib"


def test_checklist_style_with_color_on_a_light_theme():
    assert tui._checklist_style(color=True, light=True).style_rules == [
        ("selected", "noreverse fg:ansigreen"),
        ("highlighted", "noreverse bold"),
        ("pointer", "noreverse bold fg:ansiblue"),
    ]


def test_checklist_style_with_color_on_a_dark_theme():
    assert tui._checklist_style(color=True, light=False).style_rules == [
        ("selected", "noreverse fg:ansigreen"),
        ("highlighted", "noreverse bold"),
        ("pointer", "noreverse bold fg:ansicyan"),
    ]


def test_checklist_style_with_color_off_still_drops_reverse_video():
    assert tui._checklist_style(color=False, light=True).style_rules == [
        ("selected", "noreverse"),
        ("highlighted", "noreverse bold"),
        ("pointer", "noreverse bold"),
    ]


def test_initial_choice_is_the_first_already_active_selectable_item():
    items = [
        tui.ChecklistItem("user"),
        tui.ChecklistItem("pinky-lib", checked=True, selectable=False),
        tui.ChecklistItem("bootstrap", checked=True),
        tui.ChecklistItem("ops", checked=True),
    ]
    assert tui._initial_choice(items) == 2


def test_initial_choice_is_none_when_nothing_is_active():
    assert tui._initial_choice([tui.ChecklistItem("user")]) is None


def test_choice_disables_a_non_selectable_item():
    choice = tui._choice(0, tui.ChecklistItem("pinky-lib", selectable=False))
    assert choice.disabled is True


def test_a_non_selectable_item_cannot_be_selected_in_questionary():
    from questionary.prompts.common import InquirerControl

    items = [
        tui.ChecklistItem("bootstrap", selectable=False),
        tui.ChecklistItem("user"),
    ]
    control = InquirerControl([tui._choice(i, item) for i, item in enumerate(items)])
    control.pointed_at = 0

    assert control.is_selection_valid() is False


def test_choice_leaves_a_selectable_item_enabled():
    choice = tui._choice(0, tui.ChecklistItem("user", selectable=True))
    assert choice.disabled is None


def test_choice_value_is_the_items_own_position():
    items = [
        tui.ChecklistItem("user"),
        tui.ChecklistItem("bootstrap", selectable=False),
        tui.ChecklistItem("pinky-agentic-plugins"),
    ]
    values = [tui._choice(i, item).value for i, item in enumerate(items)]
    assert values == [0, 1, 2]


def test_run_checklist_maps_the_answer_back_to_a_per_item_checked_list(monkeypatch):
    items = [
        tui.ChecklistItem("user", checked=False),
        tui.ChecklistItem("bootstrap", selectable=False),
        tui.ChecklistItem("pinky-agentic-plugins", checked=True),
    ]
    monkeypatch.setattr(
        tui.questionary,
        "checkbox",
        lambda title, choices, **kwargs: SimpleNamespace(unsafe_ask=lambda: [0]),
    )

    result = tui.run_checklist(items, title="enable", color=False)

    assert result == [True, False, False]


def test_run_checklist_passes_style_and_initial_choice(monkeypatch):
    seen = {}

    def checkbox(title, choices, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(unsafe_ask=lambda: [])

    monkeypatch.setattr(tui.questionary, "checkbox", checkbox)
    items = [tui.ChecklistItem("user"), tui.ChecklistItem("bootstrap", checked=True)]

    tui.run_checklist(items, title="enable", color=False)

    assert seen["initial_choice"] == 1
    assert seen["instruction"] == (
        "(arrows move · space toggles · a all · i invert · ✓ = enabled now, uncheck to disable)"
    )
    assert (
        seen["style"].style_rules
        == tui._checklist_style(color=False, light=False).style_rules
    )


def test_run_checklist_lets_ctrl_c_through(monkeypatch):
    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(
        tui.questionary,
        "checkbox",
        lambda title, choices, **kwargs: SimpleNamespace(unsafe_ask=interrupted),
    )

    with pytest.raises(KeyboardInterrupt):
        tui.run_checklist([tui.ChecklistItem("user")], title="enable", color=False)
