# How to provision the multi-provider model pool

*Update date : 2026-08-27 09:47*

`pc-core`'s `adversarial` MCP tool (and, in the future, a task-delegation consumer) reads a pool of
non-Claude models from a **user-level** config file — not a repo, not a shared kanban board. This is
account setup, not something `pinky` generates or distributes automatically: no file → the tool falls
back to a single built-in Mistral entry, so an unconfigured account keeps working.

## Files

| File | Contents | Committed? |
|---|---|---|
| `~/.claude/pinky_model_pool.json` | the pool list (see schema below) | never |
| `~/.mistral_api_key` | Mistral API key, one line | never |
| `~/.openrouter_api_key` | OpenRouter API key, one line | never |

Each key file also accepts the matching env var instead (`MISTRAL_API_KEY`, `OPENROUTER_API_KEY`) —
env wins when both are set. The file matters for an unattended/scheduled caller with no shell env
(a cron job, a scheduled agent).

## Pool entry schema

```json
{
  "pool": [
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
