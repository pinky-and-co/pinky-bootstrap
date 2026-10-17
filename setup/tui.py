"""setup/tui.py — the interactive checkbox screen `plugin_enable.py`'s scope table and plugin
picker share: `questionary.checkbox` (arrows, space, enter, its own inline rendering — the answer
stays in scrollback, same as `setup/doctor.py`'s report). One caller-built list of
`ChecklistItem`s in, the final checked flag per item back.

`questionary` is a real runtime dependency (`pyproject.toml`, next to `argcomplete`) — see
`docs/adr/0008-questionary-interactive-picker.md` for the reasoning: arrow/space/enter navigation,
pre-checked choices, and disabled (non-selectable) entries are exactly a checkbox library's own
job, cheaper to depend on than to hand-roll and maintain. The tree here is plain indentation in
each choice's own title — no separate tree widget.

Every caller checks `sys.stdin.isatty()` itself before ever reaching `run_checklist` — this module
never runs outside an interactive terminal, and is never exercised by the test suite (a test
replaces `run_checklist` itself with a fake — see `tests/test_plugin_enable.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import questionary

from . import style


@dataclass(frozen=True)
class DetailLine:
    """One secondary line under a checklist row, carrying its own style: the text, and an SGR
    code from `style.py` mapped to a prompt_toolkit style string at render time."""

    text: str
    code: str


@dataclass(frozen=True)
class ChecklistItem:
    """One line of a checklist screen.

    `depth` indents a tree node under its parent path segment (rendered as leading spaces in the
    choice's own title — questionary has no separate tree widget). `selectable=False` is a
    grouping label with nothing to check (a synthetic path segment with no row of its own, or a
    multi-plugin batch's plugin-name header) — `questionary` renders it disabled: visible, never
    focusable, never toggled. `key` is an opaque back-reference (a row's own index in the caller's
    own list) a caller reads off the result to map a final `checked` flag back to its row; `None`
    for a line with nothing to map back (every non-selectable line).

    `details` puts extra lines under the row's own line, each carrying its own style — a row's
    secondary prose (a description, a warning) instead of a single overlong line.
    """

    text: str
    checked: bool = False
    depth: int = 0
    selectable: bool = True
    key: int | None = None
    details: Sequence[DetailLine] = ()


# questionary (2.1.1) renders a title that is a list of (style, text) tuples verbatim — any
# other formatted-text object prints as its repr. prompt_toolkit's style grammar has no `dim`,
# so the dim look is bright black; the mapping covers the codes our callers pass.
_QUESTIONARY_STYLES = {
    style.DIM: "fg:ansibrightblack",
    style.YELLOW: "fg:ansiyellow",
}


def _choice_title(item: ChecklistItem, *, color: bool) -> "str | list[tuple[str, str]]":
    """The choice's whole title: the row's own line, plus one indented line per detail, styled
    when color is on — a plain multi-line string otherwise, the same shape every other title
    takes under `NO_COLOR`. A row with details loses questionary's own pointer styling (the
    checkbox glyph and the toggle are unaffected), which is why `details` stays opt-in."""
    title = _title(item)
    if not item.details:
        return title
    indent = "  " * (item.depth + 2)
    if not color:
        return title + "".join(f"\n{indent}{d.text}" for d in item.details)
    return [
        ("", title),
        *(
            (_QUESTIONARY_STYLES.get(d.code, ""), f"\n{indent}{d.text}")
            for d in item.details
        ),
    ]


ACTIVE_SUFFIX = " ✓"
# Replaces `questionary`'s own key hint, which has no room for what `ACTIVE_SUFFIX` means.
INSTRUCTION = "(arrows move · space toggles · a all · i invert · ✓ = enabled now, uncheck to disable)"


def _title(item: ChecklistItem) -> str:
    """The choice's own title: the item's text indented by depth, plus `ACTIVE_SUFFIX` on an item
    already checked when the screen opens (an existing target) — it stays visible after the user
    unchecks it, where the checkbox glyph alone would lose "was already there".

    Always plain text: `questionary` renders a formatted-text list title verbatim, dropping its own
    checked/pointer styling for that row.
    """
    text = f"{'  ' * item.depth}{item.text}"
    return text + ACTIVE_SUFFIX if item.checked and item.selectable else text


def _checklist_style(*, color: bool, light: bool) -> questionary.Style:
    """`noreverse` on every row class — `questionary`'s own `("selected", "")` leaves
    `prompt_toolkit`'s reverse video in place, a black block on a light background. The pointer
    color follows the theme (`style.is_light_theme`): blue on light, cyan on dark."""
    if not color:
        return questionary.Style(
            [
                ("selected", "noreverse"),
                ("highlighted", "noreverse bold"),
                ("pointer", "noreverse bold"),
            ]
        )
    pointer = "fg:ansiblue" if light else "fg:ansicyan"
    return questionary.Style(
        [
            ("selected", "noreverse fg:ansigreen"),
            ("highlighted", "noreverse bold"),
            ("pointer", f"noreverse bold {pointer}"),
        ]
    )


def _initial_choice(items: Sequence[ChecklistItem]) -> int | None:
    """The first already-active selectable item — where the cursor starts, since that is where
    the user is most likely to act; `None` (top of the list) when nothing is active."""
    return next(
        (i for i, item in enumerate(items) if item.checked and item.selectable), None
    )


def _choice(
    index: int, item: ChecklistItem, *, color: bool = False
) -> questionary.Choice:
    return questionary.Choice(
        title=_choice_title(item, color=color),
        value=index,
        checked=item.checked,
        # A bool disables without the " (reason)" suffix a string adds; the stub only says str.
        disabled=True if not item.selectable else None,  # type: ignore[arg-type]
    )


def run_checklist(
    items: Sequence[ChecklistItem],
    *,
    title: str,
    color: bool | None = None,
) -> list[bool]:
    """`questionary.checkbox` over `items` — the final checked flag per item (`items`' own order).
    Ctrl-C raises `KeyboardInterrupt` (`unsafe_ask`, where `.ask()` would swallow it into `None`),
    so it reaches `cli_pinky`'s handler: one-line message, exit 130, same as an `input()` prompt."""
    use_color = style.use_color() if color is None else color
    choices = [_choice(i, item, color=use_color) for i, item in enumerate(items)]
    start = _initial_choice(items)
    answer = questionary.checkbox(
        title,
        choices=choices,
        style=_checklist_style(
            color=use_color, light=use_color and style.is_light_theme()
        ),
        initial_choice=None if start is None else choices[start],
        instruction=INSTRUCTION,
    ).unsafe_ask()
    picked = set(answer)
    return [i in picked for i in range(len(items))]
