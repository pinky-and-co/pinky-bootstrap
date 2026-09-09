"""mkdocs build hooks for the live kanban site.

Card frontmatter (status/date/repos/model/sert/blocked_by, skill `kanban`'s schema) is consumed
by MkDocs as page metadata and never rendered — mkdocs-material even reads `status:` for its own
nav badge, which makes the disappearance easy to miss. `on_page_markdown` re-renders it as a
visible summary line at the top of the page, before the body.

It also renders a Jira-style board on any CHANTIER index page that opts in with `board: true`
in its frontmatter — columns = the CHANTIER's status folders, cards = the .md files inside them.
"""

from pathlib import Path
from typing import Any

import yaml

FIELDS = ["status", "name", "date", "repos", "model", "sert", "blocked_by", "exigences"]
LABELS = {
    "status": "Status",
    "name": "Card",
    "date": "Date",
    "repos": "Repositories",
    "model": "Model",
    "sert": "Sert",
    "blocked_by": "Blocked by",
    "exigences": "Exigences",
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


def on_page_markdown(markdown, page, config, files):
    """MkDocs hook to inject status summary and kanban board into page markdown."""
    markdown = _inject_status_summary(markdown, page)
    if page.meta.get("board"):
        markdown = markdown + _inject_board(page)
    return markdown


def _inject_status_summary(markdown: str, page) -> str:
    """Prepend a summary of card metadata fields to the markdown content."""
    if "status" not in page.meta:
        return markdown

    parts = []
    for field in FIELDS:
        value = (
            Path(page.file.abs_src_path).stem
            if field == "name"
            else page.meta.get(field)
        )
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(value)
        parts.append(f"**{LABELS[field]} :** `{value}`")

    summary = " · ".join(parts) + "\n\n---\n\n"
    return summary + markdown


def _read_frontmatter(path: Path) -> dict[str, Any]:
    """Parse le frontmatter YAML directement sur disque, sans dépendre de page.meta
    d'autres pages (l'ordre de traitement des pages par MkDocs n'est pas garanti,
    donc on ne suppose pas que les cards voisines ont déjà été lues par MkDocs)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
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
