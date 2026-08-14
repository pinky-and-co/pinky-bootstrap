#!/usr/bin/env python3
"""Reconcile Phase 1 — framing oracle. Score `PHASE1_TASK` against known-answer cases.

**Why this exists.** Twice (2026-07-16, 2026-07-17) a session retuned `PHASE1_TASK` by eye on two
repos with no ground truth, and the second attempt broke the tool: a "report only what breaks a
promise / when in doubt stay silent" framing made the model rubber-stamp a repo carrying 3 stubs
marked ✓ (`VERDICT: 0 diverge, 0 manquant`, no analysis). The rule that came out of it —
**no `PHASE1_TASK` change ships without this oracle passing** — needs the oracle to exist. This is it.

Two frozen cases, deliberately opposite (`tests/fixtures/reconcile_oracle/`):
- **recall_broken_promises** — 3 real provider stubs marked ✓, plus a complete resource as the
  contrast reference. A framing that misses any of them has rubber-stamped. This is the anti-silence
  guard; it is the hard one.
- **precision_clean_table** — the real, hand-verified-honest pinky-ai table + `ai.py`. The correct
  output is near-silence; the anchor is that `purge_expired` (a row that already exists) must NOT be
  demanded as missing — the known v2 false positive.

Scoring mirrors hand verification: is the object's name present in the report body? The framing is
told to emit only problem lines, so a mention = a flag. Crude, but it is exactly the check a human
does at triage, and it is stable across prose phrasings.

Usage:
    python3 reconcile_oracle.py                 # run every case against live Mistral, print scorecard
    python3 reconcile_oracle.py --model mistral-large-latest
    python3 reconcile_oracle.py --show <case>   # dump the model's full answer for one case

Costs Mistral tokens (small fixtures — a few K each). NOT a pytest: it calls a live model and scores
a probabilistic output. The scorer LOGIC is unit-tested in tests/test_reconcile_oracle.py with a fake.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES_DIR = HERE.parent / "tests" / "fixtures" / "reconcile_oracle"
sys.path.insert(0, str(HERE.parent / "core" / "harness-hooks"))
import pinky_reconcile as pr  # noqa: E402


@dataclass(frozen=True)
class Case:
    name: str
    table_md: str
    sources: dict[str, str]
    must_flag: list[str]
    must_not_flag: list[str]


def load_cases() -> list[Case]:
    cases: list[Case] = []
    for d in sorted(p for p in CASES_DIR.iterdir() if p.is_dir()):
        oracle = json.loads((d / "oracle.json").read_text(encoding="utf-8"))
        sources = {
            str(f.relative_to(d)): f.read_text(encoding="utf-8")
            for f in sorted((d / "src").rglob("*.py"))
        }
        cases.append(
            Case(
                name=d.name,
                table_md=(d / "features_table.md").read_text(encoding="utf-8"),
                sources=sources,
                must_flag=oracle.get("must_flag", []),
                must_not_flag=oracle.get("must_not_flag", []),
            )
        )
    return cases


def flagged(answer: str, obj: str) -> bool:
    """Did the report name this object as a finding? The framing emits only problem lines, so a
    mention = a flag.

    Whole-token match, not substring: ``database`` (the object) must not match inside
    ``database-scoped`` (a description word) — that false match made the recall case wrongly fail on
    2026-07-17. A token is bounded by anything other than a word char or hyphen, so neither a
    hyphenated compound (``database-scoped``) nor a longer identifier (``api_integration_v2``) counts.

    Scored on the body only — never the trailing ``VERDICT:`` line, which restates counts and could
    echo a name from the task instructions rather than a real finding.
    """
    body = answer.split("VERDICT:")[0].lower()
    return re.search(rf"(?<![\w-]){re.escape(obj.lower())}(?![\w-])", body) is not None


@dataclass(frozen=True)
class Score:
    name: str
    recall_hits: list[str]
    recall_misses: list[str]
    precision_violations: list[str]

    @property
    def passed(self) -> bool:
        return not self.recall_misses and not self.precision_violations


def score_case(case: Case, answer: str) -> Score:
    hits = [o for o in case.must_flag if flagged(answer, o)]
    misses = [o for o in case.must_flag if o not in hits]
    violations = [o for o in case.must_not_flag if flagged(answer, o)]
    return Score(case.name, hits, misses, violations)


# The two brief builders the oracle must guard: the all-source default AND the --selective path that
# is slated to become the default. A framing change has to stay green on BOTH, or the selective path
# (index + referenced modules) ships an unguarded regression — the gap that let the index double-count
# slip in unnoticed (card reconcile-scope-docs-et-oracle, blocage 2).
BRIEF_BUILDERS = {
    "all": lambda case: pr.build_phase1_brief(case.table_md, case.sources),
    "selective": lambda case: pr.build_selective_brief(
        "docs/explanation/2-features.md", case.table_md, case.sources
    ),
}


def run_case(case: Case, call, brief_mode: str = "all") -> str:
    brief = BRIEF_BUILDERS[brief_mode](case)
    return call(f"{pr.PHASE1_TASK}\n\n{brief}")


def _live_call(model: str | None):
    import pinky_mistral

    key = pinky_mistral.resolve_api_key()
    if not key:
        sys.exit("[oracle] no Mistral key (MISTRAL_API_KEY or ~/.mistral_api_key)")

    def call(prompt: str) -> str:
        r = pinky_mistral.call_mistral(key, pinky_mistral.resolve_model(model), prompt)
        return r["choices"][0]["message"]["content"]

    return call


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Score PHASE1_TASK against the oracle cases."
    )
    ap.add_argument("--model")
    ap.add_argument("--show", help="dump the full model answer for one case name")
    ap.add_argument(
        "--brief",
        choices=[*BRIEF_BUILDERS, "both"],
        default="both",
        help="which brief to score: all-source, selective, or both (default)",
    )
    args = ap.parse_args(argv)

    cases = load_cases()
    call = _live_call(args.model)
    modes = list(BRIEF_BUILDERS) if args.brief == "both" else [args.brief]

    if args.show:
        case = next((c for c in cases if c.name == args.show), None)
        if case is None:
            sys.exit(
                f"[oracle] no case named {args.show} (have: {[c.name for c in cases]})"
            )
        print(run_case(case, call, modes[0]))
        return 0

    all_pass = True
    for mode in modes:
        print(f"\n### brief = {mode}")
        for case in cases:
            s = score_case(case, run_case(case, call, mode))
            all_pass &= s.passed
            mark = "PASS" if s.passed else "FAIL"
            print(f"[{mark}] {case.name}")
            if case.must_flag:
                print(
                    f"    recall   : {len(s.recall_hits)}/{len(case.must_flag)} caught"
                    + (f" — MISSED {s.recall_misses}" if s.recall_misses else "")
                )
            if case.must_not_flag:
                v = s.precision_violations
                print(
                    f"    precision: {'clean' if not v else f'FLAGGED {v} (should not)'}"
                )
    print("\nOVERALL:", "PASS ✓" if all_pass else "FAIL ✗")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
