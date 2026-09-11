#!/usr/bin/env python3
"""Run the local code-review benchmark against an NVIDIA NIM model (cloud, OpenAI-compatible API).

Usage:
    python3 run_nvidia.py <model> [base|knowledge]

Examples:
    python3 run_nvidia.py minimaxai/minimax-m3 base
    python3 run_nvidia.py nvidia/llama-3.3-nemotron-super-49b-v1.5 knowledge

Prints the model's FINDINGS to stdout (score against the oracle in
docs/reference/nvidia-models-review-benchmark.md). Reads the API key from
~/.nvidia_api_key, never as a CLI arg or subprocess env var — urllib makes the
call in-process so the key never appears in `ps` output (unlike a curl -H
invocation). Requires only the stdlib.
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
KEY_PATH = Path.home() / ".nvidia_api_key"
API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

model = sys.argv[1] if len(sys.argv) > 1 else "minimaxai/minimax-m3"
cond = sys.argv[2] if len(sys.argv) > 2 else "base"

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
    "temperature": 0.2,
    "max_tokens": 3000,
    "stream": False,
}
req = urllib.request.Request(
    API_URL,
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
)

t = time.time()
try:
    r = json.load(urllib.request.urlopen(req, timeout=180))
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

sys.stderr.write(
    f"[{model} · {cond}] {dur:.0f}s · in={usage.get('prompt_tokens')} "
    f"· out={usage.get('completion_tokens')} · finish={finish}\n"
)
print(content)
