# How to declare a secret resolved on demand

*Update date : 2026-10-01 13:50*

`pc-core`'s `load_secrets.py` reads the `keys` array of `settings.pinky.json`. A key is resolved
only when pc-core's own MCP-server process (behind `adversarial`, `panel`, `pool_check`) calls
`secret_env()`, right before starting a `pi` subprocess — the value then lives only in that
subprocess's own `env=`, never exported to a session env. A non-secret value (an account id, an endpoint) does not belong in
`keys`: put it in the `env` block of the user-level `settings.json`, which reaches hooks and MCP servers
too. That block is read when Claude Code starts, so a change applies to the next session. Never put a
credential there: it is plain text and every process of the session inherits it.
This is the general-purpose sibling of the `model_pool` key (`setup-model-pool.md`) —
`keys` covers any provider credential a `pi` call needs.

Scope note: `secret_env()` resolves every declared key in one call, not just the one a given `pi`
call needs — each subprocess still only receives that one dict in its own `env=`. Declaring a
`macos_keychain` entry here maps a keychain service name to the env var name pc-core expects; it
does not create the keychain item itself — `security add-generic-password` (below) does that.

## Where a key lives

Every key declared here is read from the **classic macOS keychain** (Trousseau d'accès,
`login.keychain-db`) — **never** the Passwords app. The Passwords app stores in a structurally
different, unreachable format (`keychain-2.db`, SQLite — `security show-keychain-info` refuses it
outright as "not a valid keychain file", verified, not assumed): no script, signed or not, can read
what it stores without a code-signing entitlement the Passwords app never grants to third parties.
This is a deliberate Apple boundary, not a gap to work around.

Protection is your macOS session only — no Touch ID prompt on read. Getting a biometric gate would
require a signed native helper (disproportionate for a dev API key); revisit only if a real need
shows up.

## Declaring a key

```json
{
  "keys": [
    { "reader": "macos_keychain", "service": "MISTRAL_API_KEY", "env": "MISTRAL_API_KEY" }
  ]
}
```

- `service` — the keychain item's service name (whatever you pick when you create it, below).
- `env` — the environment variable name pc-core hands to the `pi` subprocess that needs it — never
  exported into the session's own Bash environment.
- `reader` — `macos_keychain` is the wired reader: it resolves on demand, inside pc-core's own
  process, right before a pi call. An unwired reader (`aws_secretsmanager`, ...) fails loud on
  stderr wherever it is resolved, and leaves that variable unset — never a silent gap.

## Creating, updating, deleting a key

One command each — no wrapper script, this is a rare, manual gesture:

```bash
# create or update (same command for both, -U)
security add-generic-password -U -a "$USER" -s "MISTRAL_API_KEY" -w

# delete
security delete-generic-password -a "$USER" -s "MISTRAL_API_KEY"
```

`add-generic-password` prompts for the value when `-w` is given with no argument — avoid pasting
the secret directly on the command line where shell history or `ps` could catch it.

## Migrating a key already in the Passwords app

Not automatic — re-enter it once via the commands above. The Passwords app's own value is never
read programmatically (see "Where a key lives"), so this is a one-time manual gesture per key, not
a migration script.
