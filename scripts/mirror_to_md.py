#!/usr/bin/env python3
"""
mirror_to_md.py — Convert offline wget HTML doc mirrors into lean Markdown.

The mirrors under ``docs/api/<topic>/<host>/...`` are ~90% boilerplate
(nav, scripts, CSS, fonts, footers). wget keeps the whole page; the agent only
needs the main content. This script extracts the ``<article>`` of each HTML page
and renders it to Markdown, so the converted tree becomes a reference the agent
*actually reads* (inverting the CLAUDE.md "generated/ = do not traverse" rule for
this curated output).

Why not trafilatura (the first candidate): on Sphinx-style API reference pages it
drops the method signature and the Parameters block (it favours article prose).
Selecting ``<article>`` + markdownify keeps signature + params + examples intact.

Layout:
    docs/api/<topic>/<host>/.../page.html   →   docs/api/<topic>/_md/.../page.md

The ``_md/`` sibling is NOT matched by the ``docs/api/*/*.com/`` .claudeignore
rule, so it stays readable; the heavy ``<host>/`` tree stays ignored.

Requires: beautifulsoup4, lxml, markdownify
    python3 -m pip install beautifulsoup4 lxml markdownify

Usage:
    # plan — list what would be converted, no writes
    python mirror_to_md.py --dry-run

    # apply — convert every mirror found under docs/api/
    python mirror_to_md.py

    # apply to specific topics only
    python mirror_to_md.py --topic snowpark --topic streamlit

    # custom roots
    python mirror_to_md.py --api-root path/to/docs/api
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    from markdownify import markdownify as html_to_md
except ImportError:  # pragma: no cover - dependency guard
    sys.exit(
        "Missing dependencies. Install with:\n"
        "    python3 -m pip install beautifulsoup4 lxml markdownify"
    )

# ── Configuration ──────────────────────────────────────────────────────────────

# The HTML host directory carries the wget mirror; the converted tree goes to _md/.
OUTPUT_DIRNAME = "_md"

# Tags that are never content — removed before extraction.
STRIP_TAGS = (
    "script",
    "style",
    "svg",
    "noscript",
    "button",
    "nav",
    "header",
    "footer",
    "form",
    "iframe",
    "link",
    "meta",
)

# Inline elements collapsed to their text (drops link/image URL noise → leaner).
MARKDOWNIFY_STRIP = ["a", "img"]

# A converted page below this many characters is treated as empty (asset/redirect).
MIN_CONTENT_CHARS = 40

# Asset path fragments: skip these HTML files entirely (not documentation).
SKIP_PATH_FRAGMENTS = ("/_next/", "/scripts/", "/fonts/", "/images/", "/static/")


def find_content(soup: BeautifulSoup):
    """Return the main-content node for a page, or None.

    Both docs.snowflake.com (Sphinx/Next.js) and docs.streamlit.io wrap the real
    content in <article>; Streamlit's first <article> is id="content-container".
    Falling back to <main> covers pages that lack <article>.
    """
    node = soup.find("article")
    if node is None:
        node = soup.find("main")
    return node


_PERMALINK_RE = re.compile(r"\[¶\]|\bPermalink to this (heading|definition)\b")
_BLANKLINES_RE = re.compile(r"\n{3,}")


def clean_markdown(md: str) -> str:
    """Strip permalink junk and collapse excessive blank lines."""
    md = _PERMALINK_RE.sub("", md)
    md = _BLANKLINES_RE.sub("\n\n", md)
    # Drop trailing whitespace per line.
    md = "\n".join(line.rstrip() for line in md.splitlines())
    return md.strip() + "\n"


def convert_html(html: str) -> str | None:
    """Convert one HTML document to lean Markdown, or None if no usable content."""
    soup = BeautifulSoup(html, "lxml")
    node = find_content(soup)
    if node is None:
        return None
    for tag in node.select(",".join(STRIP_TAGS)):
        tag.decompose()
    md = html_to_md(
        str(node),
        heading_style="ATX",
        code_language="python",
        strip=MARKDOWNIFY_STRIP,
    )
    md = clean_markdown(md)
    if len(md.strip()) < MIN_CONTENT_CHARS:
        return None
    return md


# ── Reporting (Talend-style per-object status) ─────────────────────────────────


@dataclass
class TopicReport:
    topic: str
    converted: int = 0
    skipped_empty: int = 0
    skipped_asset: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    bytes_in: int = 0
    bytes_out: int = 0


def human(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def convert_topic(topic_dir: Path, dry_run: bool) -> TopicReport:
    """Convert every HTML page of one topic mirror into <topic>/_md/."""
    report = TopicReport(topic=topic_dir.name)
    out_root = topic_dir / OUTPUT_DIRNAME

    # The host dir is the single subdir that is not _md (e.g. docs.snowflake.com).
    host_dirs = [
        d for d in topic_dir.iterdir() if d.is_dir() and d.name != OUTPUT_DIRNAME
    ]
    for host_dir in host_dirs:
        for html_path in sorted(host_dir.rglob("*.html")):
            rel = html_path.relative_to(host_dir)
            posix = "/" + html_path.as_posix()
            if any(frag in posix for frag in SKIP_PATH_FRAGMENTS):
                report.skipped_asset += 1
                continue
            try:
                raw = html_path.read_text(encoding="utf-8", errors="ignore")
                report.bytes_in += len(raw.encode("utf-8"))
                md = convert_html(raw)
            except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
                report.errors.append((str(rel), repr(exc)))
                continue
            if md is None:
                report.skipped_empty += 1
                continue
            out_path = (out_root / rel).with_suffix(".md")
            report.bytes_out += len(md.encode("utf-8"))
            report.converted += 1
            if not dry_run:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(md, encoding="utf-8")
    return report


def discover_topics(api_root: Path, only: list[str]) -> list[Path]:
    topics = [
        d
        for d in sorted(api_root.iterdir())
        if d.is_dir() and not d.name.startswith(".")
    ]
    if only:
        wanted = set(only)
        topics = [t for t in topics if t.name in wanted]
    return topics


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--api-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "api",
        help="Root holding the per-topic mirror dirs (default: pinky-workspace/docs/api)",
    )
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        help="Restrict to this topic (repeatable)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Plan only — report, no writes"
    )
    args = parser.parse_args()

    if not args.api_root.is_dir():
        sys.exit(f"api-root not found: {args.api_root}")

    topics = discover_topics(args.api_root, args.topic)
    if not topics:
        sys.exit("No topics to convert.")

    mode = "PLAN (dry-run)" if args.dry_run else "APPLY"
    print(f"mirror_to_md — {mode}\n  api-root: {args.api_root}\n")

    totals = TopicReport(topic="TOTAL")
    for topic_dir in topics:
        r = convert_topic(topic_dir, args.dry_run)
        verb = "would convert" if args.dry_run else "converted"
        print(
            f"  {r.topic:<22} {verb} {r.converted:>5}  "
            f"empty {r.skipped_empty:>4}  asset {r.skipped_asset:>5}  "
            f"err {len(r.errors):>3}  "
            f"{human(r.bytes_in)} → {human(r.bytes_out)}"
        )
        for rel, exc in r.errors[:5]:
            print(f"      ! {rel}: {exc}")
        totals.converted += r.converted
        totals.skipped_empty += r.skipped_empty
        totals.skipped_asset += r.skipped_asset
        totals.errors.extend(r.errors)
        totals.bytes_in += r.bytes_in
        totals.bytes_out += r.bytes_out

    print(
        f"\n  {'TOTAL':<22} {totals.converted:>5} pages  "
        f"empty {totals.skipped_empty}  asset {totals.skipped_asset}  err {len(totals.errors)}  "
        f"{human(totals.bytes_in)} → {human(totals.bytes_out)}"
    )
    if totals.bytes_in:
        ratio = 100 * (1 - totals.bytes_out / totals.bytes_in)
        print(f"  size reduction: {ratio:.1f}%")
    return 1 if totals.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
