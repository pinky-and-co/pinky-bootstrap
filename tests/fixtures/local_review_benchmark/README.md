# Local code-review benchmark — fixture + runner

Reproducible harness for [docs/reference/local-models-review-benchmark.md](../../../docs/reference/local-models-review-benchmark.md)
(local Ollama models) and its cloud sibling
[docs/reference/nvidia-models-review-benchmark.md](../../../docs/reference/nvidia-models-review-benchmark.md)
(NVIDIA NIM free tier). Scores how well a model reviews Snowpark data code, on a public-safe fixture
(`notify_proc.py`) carrying 7 known defect classes (the *oracle*) — same fixture, same brief, same
oracle for both backends.

## What's here
| File | Role |
|------|------|
| `notify_proc.py` | the fixture under review (~170 lines, 7 seeded defects) |
| `review_brief.md` | the read-only/patch-only review brief fed to the model |
| `run.py` | runner — calls Ollama (local), prints the model's FINDINGS |
| `run_nvidia.py` | runner — calls NVIDIA NIM `/v1/chat/completions` (cloud, free tier), prints the model's FINDINGS. Reads the API key from `~/.nvidia_api_key` (never a CLI arg) |

## Install (one-time, per machine)
Tested on macOS (Apple Silicon). **Devstral 24B needs ≥ 32 GB RAM** (it swaps/OOMs on 18 GB).

```bash
# 1. Ollama (model runtime)
brew install ollama
brew services start ollama          # persistent daemon on localhost:11434
ollama --version                    # sanity

# 2. The model(s) to benchmark
ollama pull devstral                # Devstral Small 2, 24B, ~14.3 GB
# (gemma4:12b ~7.6 GB and qwen2.5-coder:14b ~9 GB already benchmarked on the 18 GB machine)

# 3. This repo (if not already synced/cloned on the machine)
#    git pull / clone pinky-workspace — the fixture + runner travel with it.
#    Python 3 (stdlib only — no pip install needed).
```

## Run — local (Ollama)
From anywhere (the runner locates the fixture + knowledge file by its own path):

```bash
python3 run.py devstral base        # condition A: brief + file only
python3 run.py devstral knowledge   # condition B: + AGENT_SNOWFLAKE_SNOWPARK.md injected
```

Each prints the model's FINDINGS to stdout (timing/token stats go to stderr).

## Run — NVIDIA NIM (cloud, free tier)
Needs a working key at `~/.nvidia_api_key` — **generate it from a model's own "Generate API Key"
quickstart button on build.nvidia.com, not the account settings page** (an account-page key
authenticates `GET /v1/models` but is rejected with `403` on actual inference calls — see the doc's
auth gotcha). `chmod 600` it once created.

```bash
echo "nvapi-..." > ~/.nvidia_api_key && chmod 600 ~/.nvidia_api_key
python3 run_nvidia.py minimaxai/minimax-m3 base
python3 run_nvidia.py mistralai/mistral-nemotron base
```

Stick to small/mid models (~≤14B) — every model ≥49B tested timed out or drowned in unbounded
chain-of-thought on the free tier (see the doc's Results table). Also watch for `404 Function not
found`: some catalog entries are legacy versions with a decommissioned backend — use the latest
generation in a model family.

## Score
Compare the FINDINGS against the **oracle** (the 7 defects + bonuses) in the reference doc's
*Method* section. The decisive question for Devstral: does the 24B local model catch the
**intent defects #3 (misleading status) + #4 (PII telemetry)** that gemma4:12b / qwen14b miss?
- Catches #3/#4 → capacity closes the blind spot → Devstral is a viable *thorough-ish* local backend.
- Misses #3/#4 → the blind spot is structural to local models → thorough stays cloud-only.

Paste the output back into the working session to have it scored and the doc's results table updated.

## Notes
- `run.py` sends `think:false` — harmless for Devstral/Qwen, **mandatory for gemma4** (a thinking
  model that otherwise fills the context with reasoning and returns an empty response).
- `num_ctx` defaults: 8192 (base) / 16384 (knowledge, the injected reference is ~7k tokens).
- No OpenCode needed — the raw Ollama API call is enough for a single-file review.
