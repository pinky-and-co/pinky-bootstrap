#!/usr/bin/env python3
"""Run the code-review benchmark against a Mistral La Plateforme model (cloud, OpenAI-compatible API).

Sibling of run_nvidia.py — same brief, same oracle, same assembly, so results are directly comparable
(score against the oracle in docs/reference/local-models-review-benchmark.md). The point of testing a
Mistral *reasoning* model (magistral-*) is whether it catches the INTENT defects (#2/#3/#4) that every
local model missed.

Usage:
    python3 run_mistral.py <model> [base|knowledge]

Examples:
    python3 run_mistral.py magistral-medium-latest base
    python3 run_mistral.py mistral-medium-3.5 base

Key from ~/.mistral_api_key, read in-process (never a CLI arg or subprocess env → never in `ps`).
Deviation from the local protocol, flagged: max_tokens 8000 (not 3000) — a reasoning model spends
budget thinking before the findings; 3000 truncates them (finish_reason=length). finish_reason is
printed so truncation is visible. temperature stays 0.2 for comparability with the rest of the bench.
Stdlib only.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FIX = Path(__file__).resolve().parent
REPO = FIX.parents[2]
KNOW_PATH = REPO / "corpus-public" / "knowledge" / "AGENT_SNOWFLAKE_SNOWPARK.md"
KEY_PATH = Path.home() / ".mistral_api_key"
API_URL = "https://api.mistral.ai/v1/chat/completions"

model = sys.argv[1] if len(sys.argv) > 1 else "magistral-medium-latest"
cond = sys.argv[2] if len(sys.argv) > 2 else "base"
# temp: 0.2 keeps generalists comparable to the rest of the bench; pass 0.7 for magistral-* (Mistral's
# recommended reasoning setting) so a reasoning model isn't judged on a throttled sampler.
temp = float(sys.argv[3]) if len(sys.argv) > 3 else 0.2

if not KEY_PATH.exists():
    sys.exit(f"API key not found at {KEY_PATH} — see README.md")
api_key = KEY_PATH.read_text(encoding="utf-8").strip()

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
    "messages": [{"role": "user", "content": prompt}],
    "temperature": temp,
    "max_tokens": 8000,
    "stream": False,
}
req = urllib.request.Request(
    API_URL,
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
)

t = time.time()
try:
    r = json.load(urllib.request.urlopen(req, timeout=300))
except urllib.error.HTTPError as e:
    sys.exit(f"[{model}] HTTP {e.code} — {e.read().decode(errors='ignore')}")
dur = time.time() - t

usage = r.get("usage", {})
choice = r.get("choices", [{}])[0]
message = choice.get("message", {})
finish = choice.get("finish_reason")
content = (
    message.get("content") or message.get("reasoning_content") or "(empty response)"
)
# Reasoning models (magistral-*) return content as a list of typed blocks
# [{"type":"thinking",...}, {"type":"text","text":...}] — keep only the final answer text.
if isinstance(content, list):
    texts = [
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    content = "\n".join(t for t in texts if t) or "(no text block — reasoning only)"

sys.stderr.write(
    f"[{model} · {cond} · t={temp}] {dur:.0f}s · in={usage.get('prompt_tokens')} "
    f"· out={usage.get('completion_tokens')} · finish={finish}\n"
)
print(content)
