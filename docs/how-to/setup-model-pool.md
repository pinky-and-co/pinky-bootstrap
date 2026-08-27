# How to provision the multi-provider model pool

*Update date : 2026-08-27 18:00*

`pc-core`'s `adversarial` MCP tool (and, in the future, a task-delegation consumer) reads a pool of
non-Claude models from the `model_pool` key of `settings.pinky.json` — the same file, and the same
ascending resolution (repo → parent directories → `~/.claude/`), that every other pinky setting uses
(see `.claude/settings.pinky.json` conventions elsewhere in this doc set). No `model_pool` key
anywhere in the chain → the tool falls back to a single built-in Mistral entry, so an unconfigured
account keeps working. In practice this key almost always lives at the **account** tier
(`~/.claude/settings.pinky.json`) — a repo-level override is legal (same mechanism, no special
case) but rarely useful, since a model pool is a machine/account fact, not a per-repo one.

## Files

| File | Contents | Committed? |
|---|---|---|
| `~/.claude/settings.pinky.json` | `{"model_pool": [...], "keys": [...]}` (see schema below), alongside any other pinky setting | never |

Store each provider's key in the **classic macOS keychain**, under a service name equal to the
entry's `api_key_env` (`MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, ...). Declaring it in the `keys`
array too is recommended but not required by the pool — see `setup-declarative-secrets.md` for the
schema and the `security add-generic-password` commands.

`resolve_api_key_for` reads, in order: the `api_key_env` variable from the process environment,
then a keychain item of that same name. **No plaintext file anywhere** — a keychain item is the
only supported store.

The env-var branch matters less than it looks: the `adversarial` MCP tool runs in a server process
that never receives `$CLAUDE_ENV_FILE` (Claude Code sources that for Bash commands only), so
`load_secrets.py` exporting the key does **not** reach it — the keychain read is the real path. The
env branch only catches a key exported into the session by hand, or a bare-CLI
`model_adversarial.py --task ...` run with the var already set.

Keychain reads need the `login` keychain unlocked (it unlocks with your macOS GUI session). A
headless/SSH caller with the keychain locked gets no key and that pool entry is skipped — acceptable
for a live-review tool, revisit only if a scheduled local caller needs it.

## Pool entry schema

```json
{
  "model_pool": [
    {
      "name": "mistral-medium-3.5",
      "kind": "http",
      "provider": "mistral",
      "model": "mistral-medium-3.5",
      "base_url": "https://api.mistral.ai/v1/chat/completions",
      "api_key_env": "MISTRAL_API_KEY",
      "capacity_tier": "opus",
      "free_tier": false,
      "concurrency": null
    }
  ]
}
```

- `api_key_env` — the env var checked first for this entry's key, and the macOS keychain service
  name checked next. No file fallback — see "Files" above.
- `kind` — `"http"` (called directly, OpenAI-compatible `/v1/chat/completions`) or `"offline"`
  (routed to the separate zero-egress `offline` MCP tool instead — never called through this pool's
  HTTP path, so its answer body never crosses into the cloud tool's return value).
- `capacity_tier` — rough Claude-tier equivalence (`haiku`/`sonnet`/`opus`), used both as
  `adversarial`'s capacity floor and delegation's "cheapest that can still do it" filter.
- `free_tier` — no marginal cost; drives delegation's cost order (free before paid).
- `concurrency` — max simultaneous tasks, or `null` for no known limit. Set to `1` for a local/offline
  entry (one machine) — recorded for a future concurrent dispatcher, not enforced by the pool
  selectors themselves today.
- `max_tokens` — optional, overrides the module's global response-token budget for this entry only.
  Needed when a free tier's tokens-per-minute quota is tighter than the default (confirmed on Groq:
  `openai/gpt-oss-120b`'s free tier caps at 8000 TPM, below the default budget alone — a real `413`,
  not assumed). Omit for providers with a generous enough quota.

Adding a provider is a config-only change — no `pc-core` code references a provider name.

## A plain `urllib` request gets blocked by some providers' WAF

Confirmed on Groq: the default `urllib` User-Agent trips a Cloudflare rule (error code 1010, a bare
`403`, easy to misread as an auth problem). `call_provider` already sends a fixed `User-Agent`
header for every request — nothing to configure per entry, but worth knowing if you're debugging a
`403` from a new provider that looks unrelated to the API key.

## Direct vs aggregator

For a model reachable both directly at its own provider and through an aggregator (OpenRouter), list
the **direct** entry — the aggregator is API-usage-only, never the plan you hold with the provider
itself, so direct is at least as good and has one fewer party in the egress path. Use an aggregator
entry only for models unreachable any other way.

## Verifying a model id before adding it

An aggregator's `:free` suffix is not predictable from the model's own naming — check the live
catalog rather than guessing:

```bash
curl -s https://openrouter.ai/api/v1/models | python3 -c \
  "import json,sys; [print(m['id']) for m in json.load(sys.stdin)['data'] if 'free' in m['id']]"
```

A wrong id fails with `404`, not a clean fallback to the next pool entry — verify before shipping a
new entry. A free-tier model can also return `429` (`limit_source: upstream_provider_shared_pool`) —
that is normal shared-pool congestion, not a broken id; the pool's fallback-on-error is what absorbs
it, not a fix on your end.
