"""mkdocs build hooks for the live kanban site.

Card frontmatter (date/repos/model/sert/blocked_by, skill `kanban`'s schema) is consumed by MkDocs
as page metadata and never rendered. `on_page_markdown` re-renders it as a visible summary line at
the top of the page, before the body. A card has no `status:` field — its state is the column
folder it lives in (`0-ideas`…`4-done`); the summary derives the displayed state from that folder.

It also renders a Jira-style board on any CHANTIER index page that opts in with `board: true`
in its frontmatter — columns = the CHANTIER's status folders, cards = the .md files inside them.
"""

from pathlib import Path
from typing import Any

FIELDS = [
    "status",
    "name",
    "date",
    "repos",
    "model",
    "sert",
    "blocked_by",
    "requirements",
]
LABELS = {
    "status": "Status",
    "name": "Card",
    "date": "Date",
    "repos": "Repositories",
    "model": "Model",
    "sert": "Sert",
    "blocked_by": "Blocked by",
    "requirements": "Requirements",
}

# Ordre = ordre du flux Kanban. Ajuste si un chantier a des colonnes différentes.
COLUMN_DIRS = ["0-ideas", "1-todo", "2-selected-for-dev", "3-in-progress", "4-done"]
COLUMN_LABELS = {
    "0-ideas": "💡 Ideas",
    "1-todo": "☑️ To Do",
    "2-selected-for-dev": "📌 Selected",
    "3-in-progress": "⏳ In Progress",
    "4-done": "✅ Done",
}
# La colonne = l'état de la card (plus de champ `status:`). Mapping explicite dossier → état.
COLUMN_STATUS = {
    "0-ideas": "idea",
    "1-todo": "todo",
    "2-selected-for-dev": "selected",
    "3-in-progress": "in-progress",
    "4-done": "done",
}


def on_page_markdown(markdown, page, config, files):
    """MkDocs hook to inject status summary and kanban board into page markdown."""
    markdown = _inject_status_summary(markdown, page)
    if page.meta.get("board"):
        markdown = markdown + _inject_board(page)
    return markdown


def _inject_status_summary(markdown: str, page) -> str:
    """Prepend a summary of card metadata fields to the markdown content.

    Gate: the page is a card iff its parent folder is a column dir. `status` is not read from
    frontmatter — it is derived from that folder via `COLUMN_STATUS`.
    """
    src = Path(page.file.abs_src_path)
    status = COLUMN_STATUS.get(src.parent.name)
    if status is None:
        return markdown

    parts = []
    for field in FIELDS:
        if field == "status":
            value = status
        elif field == "name":
            value = src.stem
        else:
            value = page.meta.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(value)
        parts.append(f"**{LABELS[field]} :** `{value}`")

    summary = " · ".join(parts) + "\n\n---\n\n"
    return summary + markdown


def _read_frontmatter(path: Path) -> dict[str, Any]:
    """Parse a card's YAML frontmatter straight from disk, not via another page's `page.meta`
    (MkDocs does not guarantee page processing order, so a neighbouring card may not be read yet).

    `yaml` is imported at the point of use: only cards that actually carry frontmatter reach it,
    so the module stays importable — and testable — without the mkdocs-material toolchain."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    import yaml

    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _card_title(path: Path, meta: dict[str, Any]) -> str:
    """Derive a card title from metadata or path."""
    if meta.get("title"):
        return meta["title"]
    return path.stem.replace("-", " ").replace("_", " ").capitalize()


def _inject_board(page) -> str:
    """Generate and return an HTML kanban board for the chantier."""
    chantier_dir = Path(page.file.abs_src_path).parent

    # Index nom_de_card -> colonne, sur tout le chantier. Nécessaire car `sert`
    # ne donne que le nom de la card parente, pas sa colonne : le parent peut
    # être dans n'importe quelle colonne (pas forcément celle de l'enfant).
    card_locations = {}
    for col in COLUMN_DIRS:
        col_dir = chantier_dir / col
        if not col_dir.is_dir():
            continue
        for card_path in col_dir.glob("*.md"):
            card_locations[card_path.stem] = col

    columns_html = []
    for col in COLUMN_DIRS:
        col_dir = chantier_dir / col
        if not col_dir.is_dir():
            continue

        cards_html = []
        for card_path in sorted(col_dir.glob("*.md")):
            meta = _read_frontmatter(card_path)
            title = _card_title(card_path, meta)
            blocked = meta.get("blocked_by")
            sert = meta.get("sert")
            is_subtask = sert is not None

            if is_subtask:
                assert isinstance(sert, str)
                parent_col = card_locations.get(sert)
                if parent_col:
                    type_task = f'<a href="{parent_col}/{sert}" style="color: inherit;"><span class="tabler--subtasks" title="{sert}"></a></span> · '
                else:
                    # parent introuvable : renommée, supprimée, ou dans un autre chantier
                    type_task = f'<span class="tabler--subtasks" title="{sert} (parent unfindable)"></span> · '
            else:
                type_task = ""

            date = (
                f'<span class="board-card__badge">🕒 {meta.get("date")}</span><br/>'
                if meta.get("date")
                else ""
            )
            model = (
                f'<span class="board-card__badge">🤖 {meta.get("model")}</span>'
                if meta.get("model")
                else ""
            )
            badge = (
                f'<span class="board-card__badge_blocked">🛑 {blocked}</span>'
                if blocked
                else ""
            )
            link = col + "/" + card_path.stem
            class_suffix = "_blocked" if blocked else ""
            style_inline = "" if is_subtask else ' style="font-weight: 600;"'
            cards_html.append(
                f'<div class="board-card{class_suffix}">'
                f'<div class="board-card__title"{style_inline}>{type_task}<a href="{link}" style="color: inherit;">{title}</a></div>'
                f"{date}"
                f"{model}"
                f"{badge}"
                f"</div>"
            )

        columns_html.append(
            f'<div class="board-column">'
            f'<div class="board-column__header">'
            f"{COLUMN_LABELS.get(col, col)} "
            f'<span class="board-column__count">{len(cards_html)}</span>'
            f"</div>"
            f"{''.join(cards_html)}"
            f"</div>"
        )

    return f'<div class="kanban-board">{"".join(columns_html)}</div>\n\n'
