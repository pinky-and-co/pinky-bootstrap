#!/usr/bin/env python3
"""Run the local code-review benchmark against an Ollama model.

Usage:
    python3 run.py <model> [base|knowledge] [num_ctx]

Examples:
    python3 run.py devstral base
    python3 run.py devstral knowledge
    python3 run.py gemma4:12b base

Prints the model's FINDINGS to stdout (copy them to score against the oracle in
docs/reference/local-models-review-benchmark.md). Requires only the stdlib + a
running Ollama daemon on localhost:11434. See README.md for setup.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

FIX = Path(__file__).resolve().parent
REPO = FIX.parents[2]
KNOW_PATH = REPO / "corpus-public" / "knowledge" / "AGENT_SNOWFLAKE_SNOWPARK.md"

model = sys.argv[1] if len(sys.argv) > 1 else "devstral"
cond = sys.argv[2] if len(sys.argv) > 2 else "base"
num_ctx = (
    int(sys.argv[3]) if len(sys.argv) > 3 else (16384 if cond == "knowledge" else 8192)
)

brief = (FIX / "review_brief.md").read_text(encoding="utf-8")
code = (FIX / "notify_proc.py").read_text(encoding="utf-8")

parts = [brief]
if cond == "knowledge":
    if not KNOW_PATH.exists():
        sys.exit(f"knowledge file not found: {KNOW_PATH}")
    parts.append(
        "--- SNOWFLAKE / SNOWPARK REFERENCE (apply when relevant) ---\n"
        + KNOW_PATH.read_text(encoding="utf-8")
    )
parts.append("--- FILE UNDER REVIEW (notify_proc.py) ---\n" + code)
prompt = "\n\n".join(parts)

payload = {
    "model": model,
    "prompt": prompt,
    "stream": False,
    "think": False,  # harmless for non-thinking models; mandatory for gemma4 (it drowns otherwise)
    "options": {"num_ctx": num_ctx, "num_predict": 3000, "temperature": 0.2},
}
req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
t = time.time()
r = json.load(urllib.request.urlopen(req, timeout=900))
dur = time.time() - t

sys.stderr.write(
    f"[{model} · {cond}] {dur:.0f}s · ctx={num_ctx} · in={r.get('prompt_eval_count')} "
    f"· out={r.get('eval_count')} · done={r.get('done_reason')}\n"
)
print(
    r.get("response")
    or "(empty response — if a thinking model, it may have drowned; see README)"
)
