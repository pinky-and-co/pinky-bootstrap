"""Public-corpus leak guard (--check-public) — anti-regression gate for the public profile.

Scans every surface the designated public profile ships — each resolved knowledge agent and the
profile-independent agentic-harness/rules/* (etc., see PUBLIC_SCAN_SUBDIRS) — for product/private-doc leaks.
FAILS (exit 1, listing file:line) on the codenames AND the instance
identity (GitHub org / asset host) declared by the PRIVATE profiles, while letting the bare public
brand token `pinky` pass — the identity check catches the `pinky`-shaped strings the codename hunt
lets through (org `pinky-and-co`, asset host), the gap that let a render_docs.py leak pass in 2026-07.

This module carries NO instance literal. `--profile <name>` is mandatory (no configured default):
  - which profiles are refused as a target → any profile marked `visibility: private` (fail-safe);
  - what codenames to hunt → the UNION of every private profile's `leak_patterns` / `leak_patterns_file`
    (mirrors the pinky profile's forbidden_keywords / forbidden_keywords_file split).
A fork with only a public profile configures nothing and the guard no-ops cleanly — never crashes.

Scope guard: this NEVER scans the private profiles — scanning a corpus built to hold private content
would drown a real regression in false hits. The employer codenames stay out of git entirely (the
profile's forbidden_keywords_file / leak_patterns_file, never versioned here). This check is
workspace-local — it is NOT distributed to the consumer repos.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from .common import (
    AGENTIC_HARNESS_DIR,
    HYGIENE_DIR,
    _display_path,
    iter_profiles,
    load_profile,
    owning_corpus_root,
)
from .profile import _resolve_agent, validate_profile

# Every subdir shipped in the public moteur, and which root it lives under post-reorg (2026-08-20:
# core/ split into agentic-harness/ + hygiene/) — ALL are leak-scanned by --check-public. Keep in
# sync with what setup.py actually distributes.
PUBLIC_SCAN_ROOTS = {
    "rules": AGENTIC_HARNESS_DIR,
    "commands": AGENTIC_HARNESS_DIR,
    "agents": AGENTIC_HARNESS_DIR,
    "skills": AGENTIC_HARNESS_DIR,
    "status-lines": AGENTIC_HARNESS_DIR,
    "hooks": HYGIENE_DIR,
    "pre-commit": HYGIENE_DIR,
    "conventions": HYGIENE_DIR,
}
PUBLIC_SCAN_SUBDIRS = tuple(PUBLIC_SCAN_ROOTS)


def _load_patterns_file(path_str: str, base: Path) -> list[str]:
    """Read newline-separated leak patterns from an out-of-git file (mirror forbidden_keywords_file).

    `~`/`$VAR` expand; a relative path resolves against the profile's own directory. An absent file
    yields no patterns (a profile may reference one a given machine hasn't created), never a crash.
    """
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = (base / p).resolve()
    if not p.is_file():
        return []
    return [
        stripped.lower()
        for line in p.read_text(encoding="utf-8").splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def public_leak_patterns() -> tuple[str, ...]:
    """Codenames the public corpus must never contain — the UNION of every private profile's
    declared signature, sourced across the corpus roots. No profile name is hardcoded: a profile
    marked `visibility: private` owns its `leak_patterns` (inline, git-tracked in the private corpus)
    and optional `leak_patterns_file` (out-of-git, for employer-sensitive terms). Empty when no
    private profile declares any — the scan then no-ops instead of failing.
    """
    patterns: set[str] = set()
    for data, path in iter_profiles():
        if data.get("visibility") != "private":
            continue
        for pat in data.get("leak_patterns") or []:
            if isinstance(pat, str) and pat.strip():
                patterns.add(pat.strip().lower())
        pf = data.get("leak_patterns_file")
        if pf:
            patterns.update(_load_patterns_file(pf, path.parent))
    return tuple(sorted(patterns))


def public_identity_patterns() -> tuple[str, ...]:
    """Instance-identity tokens the public corpus must never hardcode — the GitHub org and the asset
    host declared in each private profile's `docs_identity.json` (sibling of its profile.yaml).

    Distinct from public_leak_patterns (product codenames): these are `pinky`-shaped strings the bare
    codename hunt lets through — e.g. the org ``pinky-and-co``, the asset host ``assets.pinky-suite.fr``
    — yet they are instance identity that must not be baked into the shippable engine. This is the gap
    that let a render_docs.py identity leak pass undetected (2026-07-10, ADR-0031). Sourced from the
    identity that already lives in docs_identity.json — no new config, no new literal in core.
    """
    patterns: set[str] = set()
    for data, path in iter_profiles():
        if data.get("visibility") != "private":
            continue
        id_file = path.parent / "docs_identity.json"
        if not id_file.is_file():
            continue  # a private profile need not ship generated docs (no identity to protect)
        try:
            identity = json.loads(id_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        org = identity.get("github_org")
        if isinstance(org, str) and org.strip():
            patterns.add(org.strip().lower())
        url = identity.get("header_image_url")
        if isinstance(url, str) and url.strip():
            host = urlparse(url).netloc.lower()
            if host:
                patterns.add(host)
    return tuple(sorted(patterns))


def _scan_text_for_leaks(label: str, text: str, patterns: tuple[str, ...]) -> list[str]:
    """Return ``label:line — match`` hits for every pattern found (case-insensitive) in ``text``."""
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        found = sorted({pat for pat in patterns if pat in low})
        if found:
            hits.append(f"{label}:{lineno}: {', '.join(found)}  | {line.strip()}")
    return hits


def check_public(profile_arg: str | None) -> int:
    """Scan the public profile's shipped surfaces for product/private-doc leaks.

    Loads the designated public profile and scans: every resolved knowledge agent file, and
    agentic-harness/rules/* (etc., PUBLIC_SCAN_SUBDIRS). Returns the total hit count (0 = clean).
    Refuses to run against a profile marked `visibility: private`. No target, or no private profile
    declaring patterns → clean no-op with a clear message (a fork that hasn't set anything up is
    not a failure).
    """
    if not profile_arg:
        print(
            "--check-public: no public profile to scan. Pass --profile <name>. Nothing scanned."
        )
        return 0
    target = profile_arg

    profile, profile_path = load_profile(target)
    name = profile.get("name", target)
    if profile.get("visibility") == "private":
        print(
            f"--check-public refuses private profile '{name}' (visibility: private). The guard "
            "only scans public profiles; private corpora are out of scope by design."
        )
        sys.exit(2)
    validate_profile(profile, profile_path)

    # Product codenames (leak_patterns) + instance identity (org / asset host from docs_identity):
    # both are things the public corpus must never carry, hunted in the same pass.
    patterns = tuple(
        sorted(set(public_leak_patterns()) | set(public_identity_patterns()))
    )

    print("Public-corpus leak guard — profile " + f"'{name}'")
    print("=" * 52)

    if not patterns:
        print(
            "\n⚠ Nothing to hunt — no `visibility: private` profile declares `leak_patterns` or a "
            "`docs_identity.json` identity. Scan is a no-op."
        )
        return 0

    hits: list[str] = []
    roots = profile.get("knowledge_roots") or []

    # The scan renders the shippable moteur's showcase, so it resolves agents against the corpus the
    # moteur SHIPS WITH — the root that owns the scanned profile — never every root this machine
    # mounts (ADR-0068). Otherwise the verdict is the machine's, not the artefact's: a private corpus
    # mounted here would surface its agents' H1s in the public routing index and fail a repo that has
    # not changed. Non-canonical profile path → no derivable bound: scan every root and SAY so, since
    # the reader would otherwise read a machine-dependent green as a portable one.
    corpus = owning_corpus_root(profile_path)
    if corpus is None:
        print(
            f"\n⚠ {_display_path(profile_path)} is outside <corpus root>/profiles/<name>/ — the "
            "scan falls back to every declared corpus root, so this verdict is specific to this "
            "machine."
        )
    bounded = None if corpus is None else [corpus]

    # 1. each resolved knowledge agent file
    for entry in profile.get("knowledge_agents") or []:
        resolved = _resolve_agent(entry, profile_path, roots, bounded)
        if resolved is None:
            continue  # validate_profile already failed on this; keep scanning is moot
        hits += _scan_text_for_leaks(
            _display_path(resolved), resolved.read_text(encoding="utf-8"), patterns
        )

    # 2. every profile-independent moteur surface shipped to consumers — not just rules/commands/
    # agents: a leak in a skill, a harness-hook docstring, a pre-commit fragment or a convention
    # file ships in the public moteur all the same (angle mort relevé par l'audit 2026-07-04).
    for sub in PUBLIC_SCAN_SUBDIRS:
        sub_dir = PUBLIC_SCAN_ROOTS[sub] / sub
        if sub_dir.is_dir():
            for f in sorted(sub_dir.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    hits += _scan_text_for_leaks(_display_path(f), text, patterns)

    if hits:
        print(
            f"\n✗ {len(hits)} leak(s) found (bare `pinky` is allowed; these are not):\n"
        )
        for hit in hits:
            print(f"  {hit}")
        print(
            "\nMove product docs to a private profile or scrub the example to a generic "
            "placeholder. See ADR-0009."
        )
        return len(hits)

    print("\n✓ No product/private-doc leak in the public corpus.")
    return 0
