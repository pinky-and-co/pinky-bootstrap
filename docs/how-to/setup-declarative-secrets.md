# How to declare a secret loaded at session start

*Update date : 2026-08-27 18:00*

`pc-core`'s `load_secrets.py` (a `SessionStart` hook) reads the `keys` array of
`settings.pinky.json` and exports each resolved value as an environment variable before the first
Bash command of the session runs. This is the general-purpose sibling of the `model_pool` key
(`setup-model-pool.md`) — `keys` covers any secret a session's **Bash commands** need.

Scope note: the export reaches Bash-invoked processes only. An MCP server process does not receive
`$CLAUDE_ENV_FILE`, so an MCP tool that needs a provider key reads the keychain directly at the
point of use (see `setup-model-pool.md`) — declaring the key here still matters, because that is
what puts the item in the keychain.

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
- `env` — the environment variable name exported for the session.
- `reader` — `macos_keychain` is the only one wired today. An unwired reader (`aws_secretsmanager`,
  ...) fails loud on stderr at session start and leaves that variable unset — never a silent gap.

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
