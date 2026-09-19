# How to complete `pinky` commands in zsh

`pinky <TAB>` completes subjects, verbs, options and plugin names — the plugins installed and
those a known marketplace publishes (`pinky claude-plugin install pc-<TAB>`).

Three things to do, once. Nothing to look up: `pinky doctor` tells you which one is missing.

## 1. Make `pinky` a command of your own

From the `pinky-bootstrap` folder:

```bash
uv tool install --editable .
```

After `uv run pinky`, the command your shell sees is `uv`, and nothing completes.
`--editable` keeps `pinky` pointing at this folder: edits are picked up without reinstalling.

## 2. Add two lines to `~/.zshrc`

Easiest — let `pinky` do it, it shows the lines and asks before writing:

```bash
pinky doctor --fix
```

Answer `y`.

Or do it yourself, by pasting this in the terminal (it appends to the end of `~/.zshrc`):

```bash
cat >> ~/.zshrc <<'EOF'

# pinky: shell completion
autoload -Uz compinit && compinit
eval "$(pinky completion zsh)"
EOF
```

The first line starts zsh's completion system (skip it if your `~/.zshrc` already has `compinit`,
as oh-my-zsh does). The second one asks `pinky` for the script that registers its completion.

## 3. Open a new terminal

Then type `pinky ` and press TAB: the subjects appear.

`pinky doctor` reports both steps under `shell` while either is missing.
