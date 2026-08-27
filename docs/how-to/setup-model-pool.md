# How to provision the multi-provider model pool

*Update date : 2026-08-27 13:55*

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

**Recommended**: declare each provider's key in `settings.pinky.json`'s `keys` array, stored in the
classic macOS keychain — never a plaintext file. See `setup-declarative-secrets.md` for the schema
and the `security add-generic-password` commands. `load_secrets.py` (a `SessionStart` hook) exports
it as `MISTRAL_API_KEY`/`OPENROUTER_API_KEY` before `resolve_api_key_for` ever looks anywhere else.

Each pool entry's `api_key_file` (`~/.mistral_api_key`, `~/.openrouter_api_key`, ...) is a **legacy
fallback only**, checked after the env var — it exists for `model_adversarial.py` invoked as a bare
CLI outside any Claude Code session (no `SessionStart` hook ever ran, so no env var was exported).
Plaintext files are exactly what the `keys`/keychain mechanism was built to stop needing — don't
create one for a new setup.

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
      "api_key_file": "~/.mistral_api_key",
      "capacity_tier": "opus",
      "free_tier": false,
      "concurrency": null
    }
  ]
}
```

- `api_key_env`/`api_key_file` — resolution order for this entry's key: env var first (populated by
  `load_secrets.py` from the keychain when a matching `keys` entry exists), the file only as a
  legacy fallback — see "Files" above.
- `kind` — `"http"` (called directly, OpenAI-compatible `/v1/chat/completions`) or `"offline"`
  (routed to the separate zero-egress `offline` MCP tool instead — never called through this pool's
  HTTP path, so its answer body never crosses into the cloud tool's return value).
- `capacity_tier` — rough Claude-tier equivalence (`haiku`/`sonnet`/`opus`), used both as
  `adversarial`'s capacity floor and delegation's "cheapest that can still do it" filter.
- `free_tier` — no marginal cost; drives delegation's cost order (free before paid).
- `concurrency` — max simultaneous tasks, or `null` for no known limit. Set to `1` for a local/offline
  entry (one machine) — recorded for a future concurrent dispatcher, not enforced by the pool
  selectors themselves today.

Adding a provider is a config-only change — no `pc-core` code references a provider name.

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
