# How to provision the multi-provider model pool

*Update date : 2026-10-01 13:50*

`pc-core`'s `adversarial`, `panel` and `pool_check` MCP tools read a pool of non-Claude models from
the `model_pool` key of `settings.pinky.json` — the same file, and the same ascending resolution
(repo → parent directories → `~/.claude/`), that every other pinky setting uses. No `model_pool` key
anywhere in the chain → a single built-in `mistral-medium-3.5` entry. In practice the key lives at
the **account** tier (`~/.claude/settings.pinky.json`): a model pool is a machine/account fact, not
a per-repo one.

Every remote model is called through `pi`: `pi -p --model <provider>/<model>`. The pool says *which*
models to use; pi knows *where* they are (its built-in providers, or `~/.pi/agent/models.json`).
Keys stay in the keychain: the `keys` array of the same `settings.pinky.json` (see
`setup-declarative-secrets.md`) is resolved once per run and handed to each pi call as environment
variables, by `secret_env` inside the MCP server process — never exported to a session env. pi's
own `auth.json` is not needed.

## Files

| File | Contents | Committed? |
|---|---|---|
| `~/.claude/settings.pinky.json` | `{"model_pool": [...], "keys": [...]}` (schema below), alongside any other pinky setting | never |
| `~/.pi/agent/models.json` | custom providers pi does not ship (Cohere, a local MLX server, …) | never |

## Pool entry schema

```json
{
  "model_pool": [
    {
      "name": "mistral-medium-3.5",
      "kind": "cli",
      "provider": "mistral",
      "model": "mistral-medium-3.5",
      "capacity_tier": "opus",
      "free_tier": false,
      "concurrency": null
    }
  ]
}
```

- `kind` — `"cli"` (called through pi) or `"offline"` (routed to the separate zero-egress `offline`
  MCP tool, never through the pool). A leftover `"http"` entry is refused with a message saying to
  declare its provider in pi.
- `provider` + `model` — joined as pi's `--model <provider>/<model>`. The provider prefix is never
  optional: the same model id can exist under several providers, and pi would pick one on its own.
- `capacity_tier` — rough Claude-tier equivalence (`haiku`/`sonnet`/`opus`): `adversarial`'s floor,
  delegation's "cheapest that can still do it" filter, and `panel`'s eligibility (sonnet/opus by
  default).
- `free_tier` — no marginal cost; drives delegation's cost order (free before paid).
- `concurrency` — max simultaneous tasks, or `null` for no known limit. Recorded, not enforced.
- `local` — `true` for a model on this machine; sorts it before an equally ranked remote one.
- `timeout` — optional seconds to wait for this entry, overriding the caller's default (180s for
  `adversarial`/`panel`, 60s for `pool_check`). For a slow provider that still answers well —
  NVIDIA NIM models took 90–250s for a one-line reply.
- `thinking` — optional pi thinking level (`off`, `low`, `medium`, …). Absent → pi's own default.
  Set `off` for a small local model: a thinking pass drowns it into an empty answer.

Tools are never set in the pool. `adversarial` and `panel` take a `tools` argument per call
(`["read", "grep"]`); without it the model gets `--no-tools` and sees only its prompt.

## Adding a provider pi does not know

Declare it in `~/.pi/agent/models.json`, its key read from the environment that `keys` fills —
nothing in plaintext:

```json
{
  "providers": {
    "cohere": {
      "baseUrl": "https://api.cohere.com/compatibility/v1",
      "api": "openai-completions",
      "apiKey": "$COHERE_API_KEY",
      "compat": {
        "supportsDeveloperRole": false,
        "supportsReasoningEffort": false,
        "supportsStore": false,
        "supportsUsageInStreaming": false,
        "maxTokensField": "max_tokens"
      },
      "models": [
        { "id": "command-a-03-2025", "maxTokens": 8000 },
        { "id": "command-r7b-12-2024", "maxTokens": 4000 }
      ]
    }
  }
}
```

A bare `400 status code (no body)` from a new OpenAI-compatible provider usually means pi sent a
field it rejects: pi's default `maxTokens` (16384) above the model's own output cap, `store`,
`stream_options`, or `max_completion_tokens`. The `compat` block above turns those off.

Then store the key in the keychain under `COHERE_API_KEY` and declare it in `keys`
(`{"reader": "macos_keychain", "service": "COHERE_API_KEY", "env": "COHERE_API_KEY"}`).

The keychain item must list `apple-tool:` in its partition list — the hidden ACL entry that lets
`/usr/bin/security` read it without a password dialog. An item created with
`security add-generic-password` has it; one saved from the Keychain Access app gets `apple:` instead,
and Keychain Access never shows the difference. Fix an item with
`security set-generic-password-partition-list -S apple-tool:,apple: -a <user> -s <SERVICE>`.

Then add the pool entry with `"kind": "cli"` and `"provider"` set to the name used in `models.json`.

## Checking the pool

```bash
python3 <pinky-agentic-plugins>/plugins/pc-core/mcp/model_adversarial.py --check-pool
python3 <pinky-agentic-plugins>/plugins/pc-core/mcp/model_adversarial.py --check-pool --provider nvidia
python3 <pinky-agentic-plugins>/plugins/pc-core/mcp/model_adversarial.py --check-pool --name codestral-latest
```

or the `pool_check` MCP tool (`provider=`, `names=[…]`). Each entry gets a one-line prompt with no
tools, four at a time; the report gives the latency, or the provider's own error (bad key, rate
limit, unknown model, timeout, out of memory for a local server). `offline` entries are skipped —
`pinky doctor` checks them.

Each entry checked is one real call against that provider's quota, so validate a provider you just
added with `--provider` (or one entry with `--name`, repeatable) rather than the whole pool — an
evaluation key can be capped at a few dozen calls a day. A filter that matches nothing says so and
exits 2, so a misspelled provider is not read as "nothing to check".

## Direct vs aggregator

For a model reachable both directly at its own provider and through an aggregator (OpenRouter), list
the **direct** entry — the aggregator is API-usage-only, never the plan you hold with the provider
itself, so direct is at least as good and has one fewer party in the egress path. Use an aggregator
entry only for models unreachable any other way.

## Verifying a model id before adding it

```bash
pi --list-models <search>
```

lists the models pi can reach, with their provider — only for providers whose key it resolves, so
run it with the provider key it must resolve exported in that shell (for example
`export GROQ_API_KEY=$(security find-generic-password -s GROQ_API_KEY -w)`). An
aggregator's `:free` suffix is not predictable from the model's own naming — check it there rather
than guessing.

A `429` with `x-ratelimit-limit-req-minute: 0` is not congestion but a closed model: some providers
set the quota per model, and a free plan can leave most of them at zero while the key itself is
valid (a free Mistral plan opens `codestral-*` and `ministral-*`, not `mistral-medium-*`). Probe the
model directly before blaming pi. A free-tier model can also return `429` under shared-pool
congestion: the pool falls through to its next entry on a rate limit, an out-of-memory, an
insufficient credit or a timeout, never on a wrong answer.
