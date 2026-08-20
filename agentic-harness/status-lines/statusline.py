#!/usr/bin/env python3
"""
Claude Code status line — 3 lines + 1 conditional warning line (rate limits).
Reads the JSON sent via stdin by Claude Code with every update.

Layout: each line is either a simple concatenation of segments (with a separator
between them) or a "flex" layout where a left group and a right group are
pushed to opposite ends of the line (like `ccstatusline` flex separators),
with a guaranteed minimum gap between them if the terminal is too narrow
to separate them fully.
"""

import json
import os
import sys
import unicodedata
from datetime import datetime, timedelta


def _enable_ansi_on_windows():
    """On Windows, enables ANSI rendering (Windows Terminal already has it, but
    classic cmd.exe/PowerShell require this flag). A no-op on Mac/Linux."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(
                handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
    except Exception:
        # If this fails (old cmd.exe, permissions...), continue without crashing:
        # the text remains readable, just without colors.
        pass


_enable_ansi_on_windows()

# Force UTF-8 output (Windows consoles sometimes default to cp1252,
# which breaks emojis). reconfigure() has existed since Python 3.7.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- ANSI colors ---

WHITE = "\033[37m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREY = "\033[90m"
YELLOW_BG = "\033[43;30m"  # yellow background, black text ->  "warning" effect
RED_BG = "\033[41;30m"  # red background, white text ->  "alert" effect

SEP = f"  {GREY}·{RESET}  "
SEP_LINE = f"{DIM}-{RESET}"


def _safe_get(d, path, default=None):
    """Secure access to a nested path like 'a.b.c'."""
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur if cur is not None else default


def _get_columns(default=100):
    """Terminal width. Claude Code sets the COLUMNS environment variable
    before launching the script (v2.1.153+); otherwise, it fallback to a reasonable default."""
    try:
        return int(os.environ.get("COLUMNS", default))
    except (TypeError, ValueError):
        return default


def _visible_len(s: str):
    """Text length excluding ANSI codes, for flex alignment."""
    WIDE_RANGES = (
        (0x1100, 0x115F),
        (0x2300, 0x23FF),
        (0x2600, 0x27BF),
        (0x2E80, 0xA4CF),
        (0xAC00, 0xD7A3),
        (0xF900, 0xFAFF),
        (0xFF00, 0xFF60),
        (0xFFE0, 0xFFE6),
        (0x1F1E6, 0x1F1FF),  # drapeaux
        (0x1F300, 0x1FAFF),  # emoji principaux
    )
    ZERO_WIDTH_CODEPOINTS = {0x200D, 0xFE0E, 0xFE0F}  # ZWJ, VS15, VS16

    out, in_escape = 0, False
    for ch in s:
        if ch == "\033":
            in_escape = True
            continue
        if in_escape:
            if ch == "m":
                in_escape = False
            continue

        cp = ord(ch)
        if cp in ZERO_WIDTH_CODEPOINTS or unicodedata.combining(ch):
            continue  # largeur 0 : se colle au caractère précédent
        if any(lo <= cp <= hi for lo, hi in WIDE_RANGES):
            out += 2
        else:
            out += 1
    return out


def _render_flex(
    left_parts: list[str], right_parts: list[str], left_column_width, min_gap=10
):
    """Joins `left_parts` with `SEP` and `right_parts` with `SEP`, and pushes the right-hand group to the edge of
    the terminal—with a guaranteed minimum spacing if the terminal is too narrow to separate them completely
    (the flex behavior then degrades to simple fixed spacing rather than overlapping)."""
    left = SEP.join(left_parts)
    if not right_parts:
        return left
    right = SEP.join(right_parts)
    pad = max(min_gap, (left_column_width - _visible_len(left)) + min_gap)
    return f"{left}{' ' * pad}{right}"


def _compute_content_width(flex_specs):
    """Calculates column widths to align multiple flex rows with each other,
    table-style: using max(left) and max(right) separately.

    The distinction matters: with a maximum width based on the full row,
    two rows of the same total width might have different left/right
    split points (e.g., 20+43 vs. 50+13—same total of 63, but the right
    column starts at a different screen position). By using separate
    max(left) and max(right) values, the right column consistently
    starts at the same position across all rows—creating true grid alignment."""
    left_widths, right_widths = [], []
    for left_parts, right_parts in flex_specs:
        left_widths.append(_visible_len(SEP.join(left_parts)))
        if right_parts:
            right_widths.append(_visible_len(SEP.join(right_parts)))
    max_left = max(left_widths) if left_widths else 0
    max_right = max(right_widths) if right_widths else 0
    return max_left, max_right


def _color_for_pct(pct):
    if pct >= 75:
        return RED
    if pct >= 50:
        return YELLOW
    return GREEN


def _color_for_hit_rate(pct, warmed_up: bool):
    "Inverted logic: here, a LOW rate is the problem (more fresh tokens = higher cost), unlike with the context window."
    if warmed_up:
        if pct < 30:
            return "🔴 " + RED
        if pct < 60:
            return "🟡 " + YELLOW
        return "🟢 " + GREEN
    else:
        return "⚪️ " + DIM


def _build_bar(pct, width=10, filled_char="█", empty_char="░"):
    pct = max(0, min(100, pct))
    filled = round(pct * width / 100)
    color = _color_for_pct(pct)
    return f"{color}{filled_char * filled}{RESET}{DIM}{empty_char * (width - filled)}{RESET}"


def _fmt_epoch(epoch_seconds):
    """Displays only the time if the reset is today; otherwise, displays date + time
    (useful for the '7-day' reset, which often falls on a different day)."""
    try:
        dt = datetime.fromtimestamp(epoch_seconds)
        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return "?"


def _count_subagents(transcript_path, session_id):
    """The sub-agents (Task tool / context:fork) each write their own
    file to <transcript-folder>/<session_id>/subagents/agent-*.jsonl
    — a sibling folder to the main .jsonl file, not inside it. We simply
    count the existing files without parsing them (negligible cost,
    called on every refresh)."""
    if not transcript_path or not session_id:
        return None
    try:
        parent_dir = os.path.dirname(transcript_path)
        subagents_dir = os.path.join(parent_dir, session_id, "subagents")
        if not os.path.isdir(subagents_dir):
            return 0
        return len(
            [
                f
                for f in os.listdir(subagents_dir)
                if f.startswith("agent-") and f.endswith(".jsonl")
            ]
        )
    except Exception:
        return None


def _get_advisor_model(transcript_path, tail_bytes=16384):
    """advisorModel is not exposed in the status line's stdin JSON (it is not in the documented schema),
    but it appears in every assistant entry in the .jsonl file when --advisor is active.
    Only the end of the file (tail_bytes) is read to avoid re-parsing a potentially huge transcript on every refresh.."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            chunk = f.read().decode("utf-8", errors="ignore")

        # Coupe la première ligne, probablement partielle (le seek tombe
        # souvent au milieu d'une ligne JSON).
        lines = chunk.split("\n")[1:]

        for raw_line in reversed(lines):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "assistant" and "advisorModel" in entry:
                return entry["advisorModel"]
        return None
    except Exception:
        return None


def _short_model(model_id):
    """claude-opus-4-8 -> Opus 4.8, claude-sonnet-5 -> Sonnet 5, etc."""
    if not model_id:
        return None
    name = model_id.replace("claude-", "")
    parts = name.split("-")
    if not parts:
        return model_id
    label = parts[0].capitalize()
    version_parts = [p for p in parts[1:] if not (p.isdigit() and len(p) >= 6)]
    version = ".".join(version_parts)
    return f"{label} {version}".strip()


def build_lines(data: dict) -> list[str]:
    """Render the status line as a list of lines from the harness payload.

    Pure + total in intent: `main()` wraps this call in a try/except so a malformed payload
    degrades to a bare fallback line instead of blanking the whole bar — but this function itself
    stays the single, testable entry point (tests.md § generator oracle)."""
    transcript_path = _safe_get(data, "transcript_path")
    columns: int = _get_columns()
    lines: list[str] = []

    version = _safe_get(data, "version", "?")
    line0_left_parts = ["⚪️"]
    line0_right_parts = [f"{DIM}v{version}{RESET}"]
    # ---------- Ligne 1 : version, modèle, effort, thinking, fast mode, output style ----------
    model = _safe_get(data, "model.display_name", "?")
    effort = _safe_get(data, "effort.level")
    thinking_on = _safe_get(data, "thinking.enabled", False)
    fast_on = _safe_get(data, "fast_mode", False)
    style = _safe_get(data, "output_style.name", "default")

    effort_txt = f"💪 {effort}" if effort else f"{DIM}💪 —{RESET}"
    thinking_txt = "🧠 ON" if thinking_on else f"{DIM}🧠 off{RESET}"
    fast_txt = "⚡ fast" if fast_on else f"{DIM}🐢 normal{RESET}"

    advisor_model = _short_model(_get_advisor_model(transcript_path))

    line1_left_parts: list[str] = [
        f"{CYAN}{BOLD}🤖 {model}{RESET}",
        f"{effort_txt}",
        f"{fast_txt}",
    ]

    if advisor_model:
        line1_left_parts.append(f"{YELLOW}🧐 {advisor_model}{RESET}")

    line1_right_parts: list[str] = [
        f"{thinking_txt}",
        f"🎨 {style}{RESET}",
    ]

    # ---------- Ligne 2 : session id (courte), session name, heure de début ----------
    session_id = _safe_get(data, "session_id", "?")

    duration_ms = _safe_get(data, "cost.total_duration_ms", 0) or 0
    start_dt = datetime.now() - timedelta(milliseconds=duration_ms)
    start_txt = start_dt.strftime("%d/%m %H:%M")
    subagent_count = _count_subagents(transcript_path, session_id)

    line2_left_parts: list[str] = [
        f"{MAGENTA}Session 🆔 {session_id}{RESET}",
        f"🕐 Started at {start_txt}{RESET}",
    ]
    line2_right_parts: list[str] = (
        [
            f"{CYAN}🧬 {subagent_count} subagent{'s' if subagent_count > 1 else ''}{RESET}"
        ]
        if subagent_count
        else []
    )

    # ---------- Line 3 : context bar + hit cache performance ----------
    pct = _safe_get(data, "context_window.used_percentage", 0) or 0
    pct = int(pct)
    bar = _build_bar(pct)
    cost = _safe_get(data, "cost.total_cost_usd", 0) or 0
    total_input_tokens = _safe_get(data, "context_window.total_input_tokens", 0) or 0

    usage = _safe_get(data, "context_window.current_usage")
    if usage:
        cache_c = usage.get("cache_creation_input_tokens", 0) or 0
        cache_r = usage.get("cache_read_input_tokens", 0) or 0
        hit_rate = (cache_r / total_input_tokens * 100) if total_input_tokens > 0 else 0
        # At the very beginning of a session (nothing to reuse yet, cache not
        # yet primed), a low rate is normal: no alert.
        # The cache only becomes a meaningful signal once data has been
        # written to the cache (cache_c > 0) for reuse.
        warmed_up = cache_c > 0 or cache_r > 0
        color = _color_for_hit_rate(hit_rate, warmed_up)
        cache_txt = f"{color}{hit_rate:.0f}%{RESET}"
    else:
        cache_txt = f"{DIM}—{RESET}"

    line3_left_parts: list[str] = [
        f"Context window {bar} {_color_for_pct(pct)}{pct}%{RESET}",
        f"Cache hit {cache_txt}{RESET}",
    ]
    line3_right_parts: list[str] = [f"💲 {cost:.2f} (equi API)"]

    # ---------- Optional line : rate limits > 90% ----------
    warnings = []
    bg = YELLOW_BG
    for label, key in (("Session", "five_hour"), ("Hebdo", "seven_day")):
        used = _safe_get(data, f"rate_limits.{key}.used_percentage")
        resets_at = _safe_get(data, f"rate_limits.{key}.resets_at")
        if used is not None and used > 90:
            reset_txt = _fmt_epoch(resets_at) if resets_at else "?"
            warnings.append(f"{label}: {used:.0f}% (reset {reset_txt})")
            if used >= 100:
                bg = RED_BG

    if warnings:
        line0_left_parts = [f"{bg} ⚠ RATE LIMIT — {' | '.join(warnings)} {RESET}"]

    max_left, max_right = _compute_content_width(
        [
            (line1_left_parts, line1_right_parts),
            (line2_left_parts, line2_right_parts),
            (line3_left_parts, line3_right_parts),
        ]
    )
    natural_total = max_left + 3 + max_right
    if columns and columns < natural_total:
        overflow = natural_total - columns
        max_left = max(10, max_left - overflow)

    lines.append(
        _render_flex(line0_left_parts, line0_right_parts, left_column_width=max_left)
    )
    lines.append(SEP_LINE)
    lines.append(
        _render_flex(line1_left_parts, line1_right_parts, left_column_width=max_left)
    )
    lines.append(SEP_LINE)
    lines.append(
        _render_flex(line2_left_parts, line2_right_parts, left_column_width=max_left)
    )
    lines.append(SEP_LINE)
    lines.append(
        _render_flex(line3_left_parts, line3_right_parts, left_column_width=max_left)
    )
    lines.append(SEP_LINE)

    return lines


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("[status line: JSON invalide]")
        return
    try:
        print("\n".join(build_lines(data)))
    except Exception:
        # A statusline must never crash — a bare fallback is better than an error blanking the bar.
        print("⬡")


if __name__ == "__main__":
    main()
