---
paths:
  - "**/*.{docx,pptx,xlsx,pdf,html,htm}"
---
# Read convention — convert heavy documents to Markdown first

For **token economy** and readability: when you must read a document in a heavy or binary format,
convert it to Markdown with `markitdown` first, then read the lighter Markdown — rather than reading
(or failing to read) the original.

## When to convert

Run `markitdown <file>` via Bash, then `Read` its Markdown output, for:

- **`.docx` / `.pptx` / `.xlsx` / `.html`** — Claude Code cannot read these natively; markitdown is
  *enabling* here, not merely cheaper.
- **text-only `.pdf`** (no figures or scans that carry meaning) — native PDF read works, but markitdown
  is more compact; trade fidelity for tokens when the layout does not matter.

```bash
markitdown report.docx > /tmp/report.md   # then: Read /tmp/report.md
```

If `markitdown` is absent: `pip install 'markitdown[all]'` (the `[all]` extra pulls the docx/pptx/xlsx/
pdf handlers — the bare package omits them). `pipx` / `uv tool install` work too if you prefer an
isolated CLI. It is an **optional dependency** — MIT / Microsoft (honor provenance, see
`agent-knowledge-format.md`).

## Two carve-outs — do NOT convert

1. **A document to read ≠ a dataset to query.** An `.xlsx` of *specs / data-dictionary* → markitdown is
   fine (it is prose). An `.xlsx` / `.csv` / `.parquet` of *data* → never flatten it to Markdown prose:
   use a data-query path (DuckDB; on the pinky instance, `pinky dump`). It is data, not a document.
2. **Visual / scanned / layout-critical** → prefer native `Read`. markitdown mangles complex tables and
   OCRs scans; verify on a real sample before trusting it for content-critical work.

> **Local files only.** A remote URL is a different problem: `WebFetch` reads public HTML/JSON pages,
> so a URL pointing at a binary — PDF, archive, office file — is not fetchable at all. Ask for the
> file itself, or for the content pasted; downloading it first, then converting it locally, works too.
