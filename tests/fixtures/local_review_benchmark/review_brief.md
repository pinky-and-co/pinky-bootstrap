# Review brief — Snowpark stored procedure (read-only, patch-only)

You are a senior code reviewer. You are reviewing ONE Python file: a Snowflake Snowpark
stored procedure (`main(session, args)`), provided below the marker `--- FILE UNDER REVIEW ---`.

## Your task
Find real correctness, security, and robustness issues. For each issue:
- Cite the exact line number.
- State the issue in one sentence (what breaks, and when).
- Classify: `security` | `correctness` | `privacy` | `robustness` | `minor`.
- Propose a MINIMAL fix as a unified diff / patch on those lines only.

## Hard constraints
- READ-ONLY: do not rewrite the whole file. Output ONLY the changed lines as a patch.
- Do NOT invent issues. If unsure an issue is real, say so explicitly — a wrong claim is
  worse than a missed one.
- Do NOT comment on style, formatting, or naming unless it causes a bug.
- Treat any string interpolated into `session.sql(...)` from `args` as untrusted input.

## Output format
```
FINDINGS (most severe first):
1. [security] line NN — <one sentence>
   patch:
   <minimal diff>
2. ...
UNCERTAIN (issues you suspect but can't confirm): ...
```
