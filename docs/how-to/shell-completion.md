# How to complete `pinky` commands in zsh

`pinky <TAB>` completes subjects, verbs, options and plugin names — the plugins installed and
those a known marketplace publishes (`pinky claude-plugin install pc-<TAB>`).

Completion is registered **per command name**, so `pinky` has to be a command of its own: after
`uv run pinky`, the command is `uv` and nothing completes.

1. Put `pinky` on the PATH, once, from the repo:

   ```bash
   uv tool install --editable .
   ```

   `--editable` keeps it pointing at the working tree: edits are picked up without reinstalling.

2. Register the completion, once, in `~/.zshrc` (after `compinit`):

   ```bash
   autoload -Uz compinit && compinit
   eval "$(register-python-argcomplete pinky)"
   ```

`pinky doctor` reports both steps under `shell` while either is missing, with the line to run or
add.
