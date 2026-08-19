# Kanban — maintain the board proactively

A file-based kanban may carry the live state of the work (chantiers, cards moving between columns).
It replaces a ticketing tool and only works because **the agent maintains it reliably** — the user
stays the decider, the clerical layer is automated. See the `kanban` skill for the mechanics
(columns, dating, tier, filiation, cross-agent log).

Do not wait for "create a card" or "move it to done". Surface the board update as part of the work:

- **Capture → card.** When the user surfaces a new task, idea, or request, write a card for it —
  without being asked.
- **Select → commit.** The commitment column is a user decision by default; the agent may *propose*
  a selection, never select unasked.
- **Progress → move.** Taking a card in means moving it to in-progress; finished and verified means
  moving it to done.
- **End of session → handoff.** Before context runs out or the session ends, update the in-progress
  card's handoff so the next session resumes cleanly — narrative first, mechanical state second.
