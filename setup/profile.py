"""Profile-driven CLAUDE.md renderer + .claude/ scaffolding install (Phase 3, ADR-0014)."""

import copy
import json
import platform
import re
import shutil
import sys
from pathlib import Path

from .common import (
    CORE_DIR,
    CORE_HARNESS_HOOKS_DIR,
    DEFAULT_PROFILE,
    MACHINE_CAPABILITIES,
    PROVIDERS,
    WORKSPACE_ROOT,
    _WORKSPACE_DEFAULTS,
    _display_path,
    corpus_roots,
    load_profile,
)

# One-way edge: precommit imports common + product_scaffold, neither of which imports this module,
# so there is no cycle. The capability DETECTOR lives next to the hook extras it was written for —
# duplicating it here to avoid the import would give the two axes two answers.
from .precommit import resolve_scope_capabilities, warn_on_drift

# =============================================================================
# Profile-driven CLAUDE.md renderer (Phase 3)
# =============================================================================
# The runner resolves each profile.knowledge_agents entry to a file, builds a static
# routing index (H1 = name, first prose line = summary — no MCP, ADR-0006), and injects
# it plus the model/override/extras slots into core/CLAUDE.md.tpl.

REQUIRED_PROFILE_KEYS = ("name", "knowledge_agents", "knowledge_roots", "model_routing")


# ── Scaffolding corpus refs ({{agent:…}} placeholders) — ADR-0013 ────────────
# Distinct from the renderer's knowledge index: the installed agents/commands/rules and the
# CLAUDE.md.tpl carry DIRECT pointers to corpus docs (e.g. "Read @…/AGENT_GITMOJI.md"). Hardcoding
# the corpus subdir there would re-couple the moteur and break again at corpus extraction
# (ADR-0010 §Consequences). Instead the sources carry a profile-agnostic token `{{agent:NAME.md}}`,
# rewritten through corpus_roots() at install/render time — the SINGLE rewrite point. The token
# resolves to a `_display_path` (workspace-relative when in-repo, absolute once the corpus is
# external), so it survives the future split with no source edit. Surrounding syntax (`@`, backticks)
# stays literal in the source — the token is the path only.
AGENT_REF_TOKEN = re.compile(r"\{\{agent(\?)?:([A-Za-z0-9_./-]+)\}\}")

# Marqueur interne posé à la place d'un {{agent?:…}} non résolu : la ligne entière est retirée
# ensuite. \x00 est impossible dans un .md, donc aucune collision avec du contenu réel.
_DROP_LINE = "\x00pinky-drop-line\x00"


def resolve_agent_ref(
    filename: str,
    *,
    local_dir: Path | None = None,
    link_base: str | None = None,
    roots: list[Path] | None = None,
) -> str | None:
    """Resolve a bare AGENT_*.md filename to a display path via corpus_roots() (profile-independent).

    Searches each corpus root's ``knowledge/`` first (the generic/public corpus the scaffolding
    points at), then ``profiles/*/knowledge/`` (a profile-scoped agent such as the private
    AGENT_PINKY_SUITE). Returns the ``_display_path`` of the first hit, or None if unresolved.

    ``roots`` restricts the search to a given corpus subset (default: every declared root). Only a
    *control* passes it — see ``_discover_capability_agents``.

    ``--into`` self-sufficiency: when ``local_dir`` holds a copy of the agent (the agents bundled
    into a standalone POC repo), the ref resolves to ``<link_base>/<basename>`` (repo-relative)
    instead of the author-machine corpus path — so links survive ``git clone`` on another machine.
    """
    base = Path(filename).name
    if local_dir is not None and link_base is not None and (local_dir / base).exists():
        return f"{link_base}/{base}"
    roots = corpus_roots() if roots is None else roots
    for cr in roots:
        candidate = cr / "knowledge" / base
        if candidate.exists():
            return _display_path(candidate)
    for cr in roots:
        for kdir in sorted(cr.glob("profiles/*/knowledge")):
            candidate = kdir / base
            if candidate.exists():
                return _display_path(candidate)
    return None


def _expand_agent_refs(
    text: str,
    *,
    context: str,
    local_dir: Path | None = None,
    link_base: str | None = None,
    roots: list[Path] | None = None,
) -> str:
    """Rewrite every ``{{agent:NAME.md}}`` token to its corpus-resolved path (single point).

    Two flavours, because a scaffolding file cites two different kinds of agent:

    - ``{{agent:NAME.md}}`` — **framework guarantee**: the agent ships with every corpus. Unresolved
      would ship the token verbatim into the output (CLAUDE.md / scaffolding), a silent defect, so it
      fails the build rather than warning-and-continuing.
    - ``{{agent?:NAME.md}}`` — **profile capability**: the agent may legitimately be absent (e.g. the
      private-only ``AGENT_NAMING.md``, missing from the public corpus). Unresolved drops the whole
      **line** — the mention only makes sense with the agent, and blanking just the token would leave
      a dangling ``(e.g. ``)``. Corollary for authors: keep such a mention on a single line.

    Shared by the scaffolding installer and the CLAUDE.md renderer. ``local_dir``/``link_base``
    switch refs to repo-relative paths for ``--into`` (see ``resolve_agent_ref``); ``roots``
    restricts which corpus roots the refs resolve against.
    """
    unresolved: list[str] = []
    search_roots = corpus_roots() if roots is None else roots

    def _replace(match: "re.Match[str]") -> str:
        optional, name = match.group(1), match.group(2)
        ref = resolve_agent_ref(
            name, local_dir=local_dir, link_base=link_base, roots=search_roots
        )
        if ref is not None:
            return ref
        if optional:
            return _DROP_LINE
        unresolved.append(name)
        return match.group(0)

    result = AGENT_REF_TOKEN.sub(_replace, text)
    if unresolved:
        searched = ", ".join(str(r) for r in search_roots)
        sys.exit(
            f"✗ unresolved agent ref(s) in {context}: {', '.join(unresolved)}\n"
            f"  → Add the corpus root to `corpus_roots_local` in .pinky/config.txt "
            f"(searched: {searched})"
        )
    if _DROP_LINE in result:
        result = "\n".join(ln for ln in result.split("\n") if _DROP_LINE not in ln)
    return result


def _resolve_agent(
    entry: str,
    profile_path: Path,
    knowledge_roots: list[str],
    roots: list[Path] | None = None,
) -> Path | None:
    """Resolve a knowledge_agents entry to an existing file (first hit wins).

    1. profile-relative — handles instance entries like ``knowledge/AGENT_PINKY_SUITE.md``
       (the profile's own corpus subdir; self-contained, travels with the profile).
    2. each declared knowledge_root + basename. An ABSOLUTE knowledge_root is used as-is
       (an external corpus repo); a relative one is searched under every corpus root.
    3. ``<corpus root>/knowledge/`` + basename (framework-corpus fallback), per corpus root.

    ``roots`` restricts steps 2 and 3 to a corpus subset (default: every declared root).
    """
    base = Path(entry).name
    roots = corpus_roots() if roots is None else roots
    candidates = [profile_path.parent / entry]
    for kr in knowledge_roots:
        kr_path = Path(kr).expanduser()
        if kr_path.is_absolute():
            candidates.append(kr_path / base)
        else:
            candidates += [cr / kr / base for cr in roots]
    candidates += [cr / "knowledge" / base for cr in roots]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _discover_capability_agents(
    scope_caps: frozenset[str], roots: list[Path] | None = None
) -> dict[str, Path]:
    """Knowledge agents this scope is entitled to across every declared corpus root, by filename.

    Two levels per root, and the level is a precedence, not a filter (ADR-0068):

    1. ``<root>/knowledge/`` — the PUBLIC corpus, agents describing a technology.
    2. ``<root>/profiles/*/knowledge/`` — a profile's own corpus, agents describing an instance's
       products and doctrine.

    An agent is kept when its ``capability:`` is absent (socle) or present in ``scope_caps`` — the
    same filter at both levels, so being private never buys an exemption from routing. On a filename
    collision the public agent wins: the alternative is a mounted private corpus silently eclipsing a
    socle agent for everyone. The active profile's own ``knowledge_agents:`` still overrides both,
    applied afterwards by ``resolve_profile_agents``.

    **Declaring a corpus root subscribes to its knowledge** (ADR-0068). Level 2 used to be excluded
    on the grounds that auto-serving another profile's private corpus would be a leak — measured
    false on 2026-08-08: nothing travels between repos, and the surface that could leak is the
    *rendered* index of the public profile, which the leak guard now bounds at the source
    (``owning_corpus_root``). What the exclusion actually produced was a declaration with no effect:
    a root whose knowledge all lives under ``profiles/`` was mounted, visited, and left empty-handed —
    silently, because nothing fails when doctrine is merely absent.

    Level 1 is also what lets a profile stop hand-listing agents: the 13 ``AGENT_SNOWFLAKE_*`` were
    enumerated in every profile that wanted Snowflake, so adding one to the corpus meant editing N
    profiles (ADR-0058).

    Args:
        scope_caps: Capabilities this scope has — the routing filter.
        roots: Corpus roots to scan. Default (None) is every declared root; a **control** that must
            render the same verdict on any machine passes a bounded list instead.

    Returns:
        The entitled agents by filename, public level first, then profile corpora.
    """
    search_roots = corpus_roots() if roots is None else roots
    found: dict[str, Path] = {}
    for level in ("knowledge", "profiles/*/knowledge"):
        for cr in search_roots:
            for kdir in sorted(cr.glob(level)):
                if not kdir.is_dir():
                    continue
                for f in sorted(kdir.glob("AGENT_*.md")):
                    cap = _frontmatter_field(f, "capability")
                    if cap is None or cap in scope_caps:
                        found.setdefault(f.name, f)
    return found


def _agent_name_and_summary(path: Path) -> tuple[str, str]:
    """Tolerant header parse: H1 → display name, first prose line → summary.

    Survives the real corpus shape (no blockquote summary; line 2 is usually
    ``*Update date : …*``). Skips optional YAML frontmatter, the H1 itself, the
    update-date tag, separators and headings. Falls back to the filename / empty
    summary — never raises (reconciliation #5: no corpus retrofit required).
    """
    name = path.stem
    summary = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return name, summary

    i = 0
    if i < len(lines) and lines[i].strip() == "---":  # optional YAML frontmatter
        i += 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1  # past the closing ---

    while i < len(lines):  # H1 → display name
        stripped = lines[i].strip()
        if stripped.startswith("# "):
            name = stripped[2:].strip()
            i += 1
            break
        if stripped:  # non-empty, non-H1 line before any H1 → keep the filename
            break
        i += 1

    while i < len(lines):  # first real prose line → summary
        stripped = lines[i].strip()
        i += 1
        if not stripped or stripped == "---" or stripped.startswith("#"):
            continue
        if stripped.startswith("*Update date"):
            continue
        summary = stripped.lstrip("> ").strip()
        break
    return name, summary


def resolve_profile_agents(
    profile: dict,
    profile_path: Path,
    scope_caps: frozenset[str],
    roots: list[Path] | None = None,
) -> tuple[dict[str, Path], list[str]]:
    """The agents this scope actually gets, plus the profile entries that would not resolve.

    Two sources, both filtered by capability (ADR-0058):

    1. **auto-discovered** — every agent of every declared corpus root (public level then profile
       corpora, ADR-0068) whose capability this scope has, or that declares none. Nothing to list.
    2. **the profile's own** ``knowledge_agents:`` — an explicit declaration, which still wins over a
       discovered agent of the same name (same precedence as the commands/agents scaffolding
       layering). Since ADR-0068 an entry pointing at an agent discovery already found is a no-op
       kept for readability, not a requirement.

    ``roots`` restricts both sources to a corpus subset (default: every declared root).

    Returns ``(by_filename, unresolved_entries)``; ``validate_profile`` is what fails on the second,
    this only carries it so the index can leave a visible marker.
    """
    agents = _discover_capability_agents(scope_caps, roots)
    knowledge_roots = profile.get("knowledge_roots") or []
    unresolved: list[str] = []
    for entry in profile.get("knowledge_agents") or []:
        resolved = _resolve_agent(entry, profile_path, knowledge_roots, roots)
        if resolved is None:
            unresolved.append(entry)
            continue
        cap = _frontmatter_field(resolved, "capability")
        if cap is not None and cap not in scope_caps:
            continue
        agents[resolved.name] = resolved
    return agents, unresolved


def _command_description(path: Path) -> str:
    """Read the `description:` frontmatter field from a command file — empty if absent."""
    in_frontmatter = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            m = re.match(r"^description:\s*(.+)$", line)
            if m:
                return m.group(1).strip()
    return ""


def _command_requirements(path: Path) -> tuple[str | None, str | None]:
    """A command's ``(capability, machine)`` frontmatter — ``(None, None)`` when both are absent.

    Two axes because there are two subjects. ``capability:`` is what the REPO must be (snowflake,
    python, web — derived from its layout by ``resolve_extras``); ``machine:`` is what the OPERATOR
    must run (cortex, local-model — declared in ``.pinky/config.txt``, undetectable). A command
    may require one, the other, both, or neither.

    Both absent = **socle**, installed everywhere. That default is deliberate in this direction:
    forgetting a key can only make a command more available, never silently narrower — a command
    that vanishes without explanation is far harder to diagnose than one that shows up unused.
    """
    return (
        _frontmatter_field(path, "capability"),
        _frontmatter_field(path, "machine"),
    )


def _frontmatter_field(path: Path, key: str) -> str | None:
    """A single YAML-frontmatter scalar, or None when the block or the key is absent.

    Regex, never ``pyyaml``: the default distribution path is dependency-free (see
    ``setup/common.py``). Only a ``---`` on the FIRST line opens a frontmatter — a file without one
    would otherwise have its BODY scanned, and `---` is ordinary markdown (a horizontal rule, a
    section break). Knowledge agents are full of them, so this is not a theoretical concern.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.+)$")
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if m := pattern.match(line):
            return m.group(1).strip()
    return None


def _meets_requirements(path: Path, scope_caps: frozenset[str]) -> bool:
    """Whether an artefact's declared requirements are met by this scope and this machine.

    Serves commands AND rules (ADR-0060): both carry the same two frontmatter keys, so one predicate
    rather than one per artefact type — a second copy would drift the day only one of them is fixed.
    """
    capability, machine = _command_requirements(path)
    if capability is not None and capability not in scope_caps:
        return False
    if machine is not None and machine not in MACHINE_CAPABILITIES:
        return False
    return True


# Canonical language axes (ordered) — the override vocabulary for a profile's `languages:` block.
# Mentally grouped in two registers: REASONING (authored in the working language, where
# comprehension is load-bearing) and INTERFACE (lingua franca, outward-facing). The split is a
# CONVENTION rendered into CLAUDE.md — never hook-enforced (natural language is not regex-verifiable).
# See ADR-0011. The list is extensible; an unknown override axis fails the build (validate_profile).
DEFAULT_LANGUAGE = "en"
LANGUAGE_AXES: list[tuple[str, str]] = [
    # reasoning register (typically the author's working language)
    ("comments", "inline comments (intent)"),
    ("explanation", "explanation (ADR, docs/explanation)"),
    ("doc_private", "private docs (brainstorm, pitch)"),
    ("chat", "agent → you (chat output)"),
    # interface register (typically the lingua franca)
    ("code", "code identifiers"),
    ("docstrings", "docstrings (→ autodoc)"),
    ("doc_public", "public docs (reference/how-to/tutorial)"),
    ("commit", "commit messages"),
    ("pr", "PR/MR titles + bodies"),
]


def _resolve_language_axis(profile: dict, axis: str) -> str:
    """Resolve one language axis to its effective value: ``overrides[axis] or default or
    DEFAULT_LANGUAGE``.

    Single source of truth for this formula — ``render_languages`` (the {{languages}} slot in
    CLAUDE.md) and ``_inject_agent_language`` (a forked agent's chat-output directive) both call
    this rather than each carrying their own copy, so the two can never disagree on what a
    profile's language for a given axis actually is.
    """
    languages = profile.get("languages") or {}
    default = str(languages.get("default") or DEFAULT_LANGUAGE)
    overrides = languages.get("overrides") or {}
    return str(overrides.get(axis, default))


def render_languages(profile: dict) -> str:
    """Render the {{languages}} slot — the per-axis authoring-language policy (ADR-0011).

    Flat model: ``languages: {default, overrides}``. Each axis resolves to
    ``overrides[axis] or default or DEFAULT_LANGUAGE``. Grouped by language for a lean render.
    A convention only — never hook-enforced (natural language is not regex-verifiable).
    """
    languages = profile.get("languages") or {}
    default = str(languages.get("default") or DEFAULT_LANGUAGE)
    overrides = languages.get("overrides") or {}
    by_lang: dict[str, list[str]] = {}
    for axis, label in LANGUAGE_AXES:
        by_lang.setdefault(str(overrides.get(axis, default)), []).append(label)

    lines = [
        "Authoring language per artefact, set by the active profile (`languages:`), by cognitive "
        "function — reasoning artefacts in your working language, interface/contract artefacts in "
        "the lingua franca. Convention only (not hook-enforced):",
        "",
    ]
    # default language first, then the rest alphabetically — stable and readable.
    seen: set[str] = set()
    for lang in [default, *sorted(by_lang)]:
        if lang in seen or lang not in by_lang:
            continue
        seen.add(lang)
        lines.append(f"- **`{lang}`** → {', '.join(by_lang[lang])}")

    # The `chat` axis governs every message the user reads, yet grouped-by-language it lands as one
    # comma-item among the reasoning artefacts — the least visible line for the most-used axis. It is
    # observed to drift toward the lingua franca after a run of interface-register outputs (commit
    # messages, docstrings). Surface it on its own imperative line. Convention only, still no hook
    # (ADR-0011) — this is prominence, not enforcement.
    chat_lang = _resolve_language_axis(profile, "chat")
    lines += [
        "",
        f"**Chat output to you is `{chat_lang}`.** Re-read this axis before composing any long "
        "synthesis: a run of interface-register artefacts (commit messages, docstrings, filenames) "
        f"does not change the chat register — it stays `{chat_lang}`.",
    ]
    return "\n".join(lines)


# Interaction-style knobs (profile `behavior:` block) — dials core-rule baselines the same way
# `languages:` dials the language policy (ADR-0011 pattern, extended from *language* to
# *interaction style*; see ADR-0021). Each knob is flat `name: value` (not default+overrides —
# unlike language axes, knobs don't share a value space, so there's nothing to group by).
# Convention only — never hook-enforced. YAGNI: only knobs with a real per-target variation
# (see the chantier-0001 card `configurable-behavior-layer`) — resist adding cosmetic ones.
BEHAVIOR_KNOBS: dict[str, dict] = {
    "challenge": {
        "default": "on",
        "render": {
            "on": "**Challenge decisions** — push back before executing; no rubber-stamping, "
            "zero confirmation bias.",
            "off": "**Challenge decisions** — off; proceed on the user's call without pushback.",
        },
    },
    # Three postures, one axis (ADR-0070). They exclude each other by construction: you assume the
    # vocabulary, you teach it, or you avoid it. A second `vulgarise` knob next to a `teaching_mode`
    # one would have produced combinations nobody can read (`on` + `on` = ?).
    #
    # Named `vocabulary` and not `teaching_mode`, because the third posture is exactly the one where
    # you do NOT teach — the old name described one of its own values, a defect invisible while
    # there were only two of them, one of which was negative.
    "vocabulary": {
        "default": "assume",
        "render": {
            "assume": "**Vocabulary** — assume; the reader knows the trade's vocabulary. Use it "
            "plainly, without glossing.",
            "teach": "**Vocabulary** — teach; use the real technical term AND explain it as you go, "
            "so the reader acquires it.",
            "explain": "**Vocabulary** — explain; the reader is not a developer. Say what a thing "
            "DOES before naming it, and gloss any term of the trade (CI, hook, back vs front) the "
            "first time it appears. Neither assume the vocabulary nor drill it — the goal is that "
            "the decision is understood, not that the words are learned.",
        },
    },
    "derail_handling": {
        "default": "park",
        "render": {
            "park": "**Derailment handling** — park side-quests (kanban `0-ideas`, see `kanban.md`) "
            "and keep the current thread going.",
            "stop": "**Derailment handling** — stop and ask before following a side-quest.",
        },
    },
}


def _normalize_knob_value(raw) -> str:
    """Coerce a raw YAML value to the knob's string vocabulary.

    PyYAML (1.1 spec) parses bare ``on``/``off`` as booleans, so ``teaching_mode: on`` loads as
    Python ``True``, not the string ``"on"`` — a footgun for anyone hand-editing profile.yaml
    without quoting it. Booleans normalize to ``on``/``off``; everything else is just stringified.
    """
    if isinstance(raw, bool):
        return "on" if raw else "off"
    return str(raw)


def render_behavior(profile: dict) -> str:
    """Render the {{behavior}} slot — interaction-style knobs dialed by the profile (ADR-0021).

    Same pattern as ``render_languages`` (ADR-0011): core rules set the baseline, the profile's
    ``behavior:`` block dials it per knob, per target. Convention only — never hook-enforced. This
    renderer keeps a defensive per-knob default fallback, but an unknown knob or out-of-range value
    is already rejected upstream: validate_profile fails the build on it (strict).
    """
    behavior = profile.get("behavior") or {}
    lines = [
        "Interaction-style knobs, set by the active profile (`behavior:`) — core rules set the "
        "baseline, the profile dials it per target. Convention only (not hook-enforced):",
        "",
    ]
    for knob, spec in BEHAVIOR_KNOBS.items():
        value = _normalize_knob_value(behavior.get(knob, spec["default"]))
        lines.append(f"- {spec['render'].get(value, spec['render'][spec['default']])}")
    return "\n".join(lines)


# ── Multi-agent dispatch (profile `multi_agent:` block) ───────────────────────────────────────
# Le troisième knob de profil, et le seul qui n'avait PAS de renderer jusqu'au 2026-08-09 : sa valeur
# ne quittait jamais `profile.yaml`, tandis que `apply-convention.md` réécrivait les défauts en dur
# dans sa prose. Un profil qui dialait 8 lisait donc une rule annonçant 4 — et une faute de frappe
# (`multi_agents:`) était ignorée sans un mot, faute de validation.
#
# ADR-0069 a décrit cette clé comme « morte » (§ Not for) sur la foi d'un grep : aucun code ne la lit,
# c'est exact — mais son consommateur est l'AGENT, via une rule distribuée qu'il a en contexte à
# chaque session. Non lue par le code ≠ sans consommateur. Voir l'amendement d'ADR-0069.
MULTI_AGENT_KNOBS: dict[str, dict] = {
    "max_parallel_tasks": {
        "default": 4,
        "render": "**Max concurrent Tasks:** {value} — the ceiling when `--parallel` dispatches one "
        "Task per target.",
    },
    "task_timeout_minutes": {
        "default": 15,
        "render": "**Per-Task timeout:** {value} min — past it the orchestrator marks the Task "
        "failed and reports it, without retrying.",
    },
}


def _multi_agent_value(raw, default: int) -> int | None:
    """Coerce a knob value to a positive int; None when it is not one.

    Accepts the string form on purpose: an instance override comes from `key = value` text, and it
    must clear the SAME gate as the int a profile.yaml yields — one validation path, never two
    (ADR-0069).
    """
    if isinstance(raw, bool):  # `True` is an int in Python; never a task count
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str) and raw.strip().isdigit() and int(raw) > 0:
        return int(raw)
    return None


def render_multi_agent(profile: dict) -> str:
    """Render the {{multi_agent}} slot — the `--parallel` dispatch limits, with their real values.

    Same shape as ``render_behavior``/``render_languages``: the engine holds the baseline, the
    profile dials it, the rendered text carries the RESOLVED number. Convention only — no hook
    enforces a task count.
    """
    block = profile.get("multi_agent") or {}
    lines = []
    for knob, spec in MULTI_AGENT_KNOBS.items():
        value = _multi_agent_value(block.get(knob, spec["default"]), spec["default"])
        if (
            value is None
        ):  # rejected upstream by validate_profile; stay renderable anyway
            value = spec["default"]
        lines.append("- " + spec["render"].format(value=value))
    return "\n".join(lines)


# ── Instance overrides — this machine's knobs, over the loaded profile (ADR-0069) ─────────────
# A versioned profile mixed two natures. What produces a SHARED ARTEFACT (code, doc, commit — read
# by someone else, some day) stays in profile.yaml; what tunes the tool FOR THIS SESSION, ON THIS
# MACHINE, belongs to the instance. `pluto` is what makes this necessary rather than tidy: the
# profile is shared with a second developer, so flipping `chat: fr` to `de` for oneself changes what
# HE receives, or costs a commit/revert per experiment.
#
# The key IS the dotted path inside the profile — no second vocabulary to keep in sync with the
# structure it describes. The allowlist is derived from the existing knob vocabularies for the same
# reason: adding a behavior knob makes it overridable without touching this line.
#
# `languages` contributes exactly ONE axis. The other eight all end up written into a committed file
# — including `explanation` and `doc_private`, whose reasoning register still lands in an ADR or a
# versioned doc. `chat` is the only one that produces no file at all.
INSTANCE_OVERRIDABLE: frozenset[str] = frozenset(
    {"languages.overrides.chat"}
    | {f"behavior.{knob}" for knob in BEHAVIOR_KNOBS}
    | {f"model_routing.{key}" for key in ("provider", "fast", "default", "thorough")}
    # Capacité de la machine et quota du compte, jamais un artefact partagé : le critère d'ADR-0069
    # range ces deux-là côté instance sans hésitation.
    | {f"multi_agent.{knob}" for knob in MULTI_AGENT_KNOBS}
)


def apply_instance_overrides(profile: dict, config: dict[str, str]) -> dict:
    """Return `profile` with this machine's allowed knobs applied on top.

    Args:
        profile: The loaded profile, left untouched (a copy is returned).
        config: The parsed instance config — `common._WORKSPACE_DEFAULTS` in practice. Flat keys
            (``default_profile``, ``repo_globs``…) are not profile paths and are ignored here; a
            DOTTED key is read as an intent to override, and must be in ``INSTANCE_OVERRIDABLE``.

    Returns:
        A new dict. Precedence is instance > profile > engine default, and nothing else changes:
        a profile key absent from the config is never touched.

    Call it BEFORE ``validate_profile``, never after — an instance value must clear the same gate as
    the same value written in a profile.yaml. A second validation path would drift from the first,
    and the knobs' vocabularies (``BEHAVIOR_KNOBS``, ``LANGUAGE_AXES``, the model tiers) already live
    there. Rejecting an out-of-allowlist key rather than ignoring it is the same posture: a silently
    inert override is exactly the failure the strict profile validation exists to refuse.
    """
    merged = copy.deepcopy(profile)
    refused: list[str] = []
    for key, value in config.items():
        if "." not in key:
            continue  # a plain instance key, not a profile path
        if key not in INSTANCE_OVERRIDABLE:
            refused.append(key)
            continue
        *parents, leaf = key.split(".")
        node = merged
        for part in parents:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[leaf] = value
    if refused:
        print("Instance config: key(s) that cannot be overridden per machine:")
        for key in sorted(refused):
            print(f"  ✗ {key}")
        print(
            "\n  → Only what tunes the tool for this session is overridable; anything that "
            "produces a shared artefact (code, doc, commit) stays in profile.yaml (ADR-0069)."
        )
        print(f"  → Overridable: {', '.join(sorted(INSTANCE_OVERRIDABLE))}")
        sys.exit(1)
    return merged


def _render_overrides(profile: dict) -> str:
    """Render the {{rules_overrides}} slot from the profile."""
    overrides = profile.get("rules_overrides") or []
    if not overrides:
        return "No overrides — all core rules apply as-is."
    return "Overrides (replace the matching core rule):\n" + "\n".join(
        f"- `{item}`" for item in overrides
    )


def render_claude_md(
    profile: dict,
    profile_path: Path,
    *,
    template_name: str = "CLAUDE.md.tpl",
    local_dir: Path | None = None,
    link_base: str | None = None,
    scope_caps: frozenset[str] | None = None,
    roots: list[Path] | None = None,
) -> str:
    """Render a CLAUDE.md template from the active profile.

    ``template_name`` selects the template (ADR-0014 Phase 1):
    - ``CLAUDE.md.tpl``      — domain layer (knowledge index + domain header)
    - ``CLAUDE-base.md.tpl`` — neutral root (base rules only, no knowledge agents)

    ``local_dir``/``link_base`` (``--into``) rewrite both the knowledge index and the inline
    ``{{agent:…}}`` refs to repo-relative paths, so a standalone POC repo's CLAUDE.md resolves
    after ``git clone``.

    ``roots`` restricts every corpus lookup this render performs — the index and the ``{{agent:…}}``
    refs alike — to a subset of the declared roots. The real render leaves it None (a machine's
    workspace gets everything it declares, ADR-0068); ``--check-public`` passes the corpus root that
    owns the profile, so its verdict is the artefact's, not the machine's.
    """
    content = (CORE_DIR / template_name).read_text(encoding="utf-8")
    routing = profile.get("model_routing") or {}
    slots = {
        "profile_name": str(profile.get("name", "unknown")),
        "knowledge_index": build_knowledge_index(
            profile,
            profile_path,
            link_base=link_base,
            scope_caps=scope_caps,
            roots=roots,
        ),
        "commands_index": build_commands_index(profile_path, scope_caps),
        "languages": render_languages(profile),
        "behavior": render_behavior(profile),
        "multi_agent": render_multi_agent(profile),
        "rules_overrides": _render_overrides(profile),
        "extras": (profile.get("claude_md_extras") or "").rstrip("\n"),
        "model_fast": str(routing.get("fast", "")),
        "model_default": str(routing.get("default", "")),
        "model_thorough": str(routing.get("thorough", "")),
    }
    for token, value in slots.items():
        content = content.replace("{{" + token + "}}", value)

    # Direct corpus pointers in the .tpl ({{agent:…}}) — resolved through corpus_roots() (ADR-0013).
    content = _expand_agent_refs(
        content,
        context="CLAUDE.md.tpl",
        local_dir=local_dir,
        link_base=link_base,
        roots=roots,
    )

    leftover = sorted(set(re.findall(r"\{\{[A-Za-z_]+\}\}", content)))
    if leftover:
        # A literal {{slot}} in the output means the .tpl carries a token the slots dict doesn't
        # cover — a framework bug that would ship verbatim into CLAUDE.md. Fail, never warn-and-ship.
        sys.exit(
            f"✗ unresolved template slot(s) in {template_name}: {', '.join(leftover)}"
        )
    return content.rstrip("\n") + "\n"


def validate_profile(profile: dict, profile_path: Path) -> None:
    """Fail fast on a malformed profile: required keys, model tiers, resolvable agents."""
    errors: list[str] = []
    for key in REQUIRED_PROFILE_KEYS:
        if key not in profile or profile[key] in (None, ""):
            errors.append(f"missing required key: {key}")

    routing = profile.get("model_routing") or {}
    for tier in ("fast", "default", "thorough"):
        if not routing.get(tier):
            errors.append(f"model_routing.{tier} is required")

    roots = profile.get("knowledge_roots") or []
    corpus = corpus_roots()
    for root in roots:
        root_path = Path(root).expanduser()
        ok = (
            root_path.is_dir()
            if root_path.is_absolute()
            else any((cr / root).is_dir() for cr in corpus)
        )
        if not ok:
            errors.append(f"knowledge_root is not a directory: {root}")
    unresolved_agents: list[str] = []
    for entry in profile.get("knowledge_agents") or []:
        if _resolve_agent(entry, profile_path, roots) is None:
            errors.append(f"knowledge agent not found: {entry}")
            unresolved_agents.append(entry)

    # `domain_layer_subdir:` was REMOVED (ADR-0060) — it rendered a CLAUDE.md + rules into
    # WORKSPACE_ROOT/<subdir>/, expecting repos to be cloned inside it. They never were:
    # discover_repos() globs the workspace ROOT. Fail rather than ignore, same reasoning as below.
    if profile.get("domain_layer_subdir") is not None:
        errors.append(
            "domain_layer_subdir: key removed (ADR-0060) — domain rules now declare "
            "`capability:` and land in the workspace .claude/rules/ like every other rule. "
            "Delete the key."
        )

    # `commands:` was REMOVED (2026-08-05) — a command's requirements now travel in its own
    # frontmatter (`capability:` / `machine:`) and are answered by the repo's layout and the
    # machine's declared tooling. Fail rather than ignore: a profile still carrying the key would
    # otherwise keep looking authoritative while having no effect at all, and the author would only
    # find out by noticing an unexpected command months later.
    if profile.get("commands") is not None:
        errors.append(
            "commands: key removed (2026-08-05) — a command now declares its own "
            "`capability:` / `machine:` requirement. Delete the key; commands whose "
            "requirement this machine cannot meet are dropped automatically."
        )

    # Language policy (ADR-0011) — strict: an unknown override axis is a profile typo the renderer
    # would silently drop. Fail the build rather than warn-and-continue (a dropped config the author
    # believes is active is exactly the silent failure this guard exists to catch).
    languages = profile.get("languages") or {}
    unknown_axes = set((languages.get("overrides") or {})) - {
        axis for axis, _ in LANGUAGE_AXES
    }
    if unknown_axes:
        errors.append(
            f"unknown language axis override(s): {', '.join(sorted(unknown_axes))}"
        )

    # Behavior knobs (ADR-0021) — same strict posture: an unknown knob, or an out-of-range value for
    # a known knob, is a typo — not a graceful degradation. Fail rather than fall back silently.
    behavior = profile.get("behavior") or {}
    # `teaching_mode:` was RENAMED to `vocabulary:` (ADR-0070). It would otherwise be caught by the
    # generic unknown-knob check below, whose message ("unknown behavior knob") says nothing about
    # where the value went — and a renamed knob is the one case where the author DID configure
    # something and deserves to be told what it became, not just that it is wrong.
    if "teaching_mode" in behavior:
        errors.append(
            "behavior.teaching_mode: knob renamed to `vocabulary` (ADR-0070) — `on` → `teach`, "
            "`off` → `assume`, plus a third posture `explain` for a reader who is not a developer."
        )
    unknown_knobs = set(behavior) - set(BEHAVIOR_KNOBS) - {"teaching_mode"}
    if unknown_knobs:
        errors.append(f"unknown behavior knob(s): {', '.join(sorted(unknown_knobs))}")
    for knob, value in behavior.items():
        spec = BEHAVIOR_KNOBS.get(knob)
        if spec and _normalize_knob_value(value) not in spec["render"]:
            errors.append(f"behavior.{knob}={value!r} not in {sorted(spec['render'])}")

    # Multi-agent dispatch — même posture stricte. Sans elle, `multi_agents:` (typo) ou
    # `max_parallel_tasks: 0` passaient sans un mot : rien ne lisait la clé, donc rien ne s'en
    # plaignait, et l'auteur du profil croyait sa limite active.
    multi_agent = profile.get("multi_agent") or {}
    unknown_ma = set(multi_agent) - set(MULTI_AGENT_KNOBS)
    if unknown_ma:
        errors.append(f"unknown multi_agent knob(s): {', '.join(sorted(unknown_ma))}")
    for knob, value in multi_agent.items():
        if knob in MULTI_AGENT_KNOBS and _multi_agent_value(value, 0) is None:
            errors.append(f"multi_agent.{knob}={value!r} is not a positive integer")

    if errors:
        print(f"Profile validation failed ({profile_path}):")
        for error in errors:
            print(f"  ✗ {error}")
        if unresolved_agents:
            searched = ", ".join(str(r) for r in corpus_roots())
            print(f"\n  → Corpus roots searched: {searched}")
            print(
                "  → Add the missing root to `corpus_roots_local` in .pinky/config.txt, "
                "or set the CORPUS_ROOT env var."
            )
        sys.exit(1)


def _scaffolding_sources(
    subfolder: str,
    profile_path: Path | None,
    *,
    filtered: bool = True,
    scope_caps: frozenset[str] | None = None,
) -> dict[str, Path]:
    """Resolve the source files for a scaffolding subfolder, by filename (last writer wins).

    Commands and agents layer the PUBLIC moteur set (``core/<subfolder>/``) with the active
    profile's PRIVATE set (``<profile dir>/<subfolder>/``) — same public/private split as the
    knowledge agents. A profile file overrides a core file of the same name. ``rules`` layers the
    PUBLIC base set (``core/rules/base/``) with the profile's PRIVATE ``<profile dir>/rules/`` —
    instance-specific, leaky rules (e.g. "reuse the pinky libs", which names product libraries)
    live in the private corpus, never in the public base. They land in the workspace-root base
    layer so they load under every sibling repo. Domain rules (``core/rules/domain-<x>/``) land in
    the SAME set, gated by the capability each declares (ADR-0060, superseding ADR-0014's subtree).
    """
    if subfolder == "rules":
        # base = always; domain-<x>/ = gated by the capability each rule declares (ADR-0060).
        # They land in the SAME .claude/rules/ as the base ones: the workspace has one rule
        # surface, not one per subtree. The `paths:` frontmatter is what keeps a domain rule from
        # costing context on unrelated work — capability decides PRESENCE, paths decides LOADING.
        src_dirs = [CORE_DIR / "rules" / "base"]
        src_dirs += sorted(
            d for d in (CORE_DIR / "rules").glob("domain-*") if d.is_dir()
        )
        if profile_path is not None:
            src_dirs.append(profile_path.parent / "rules")
    else:
        src_dirs = [CORE_DIR / subfolder]
        if profile_path is not None:
            src_dirs.append(profile_path.parent / subfolder)
    sources: dict[str, Path] = {}
    for sd in src_dirs:
        if sd.is_dir():
            for f in sorted(sd.rglob("*")):
                if f.is_file():
                    sources[f.name] = f
    # Commands only: keep those whose frontmatter requirements this scope satisfies. Applied HERE
    # rather than at each call site so the two consumers stay in sync by construction — the files
    # copied into `.claude/commands/` and the `{{commands_index}}` table rendered into CLAUDE.md. A
    # table that advertises a command the machine does not have is the same class of drift
    # build_commands_index was written to kill. `filtered=False` is for validate_profile, which
    # needs the full set.
    #
    # Replaced the profile's `commands:` allowlist (2026-07-31 → 2026-08-05). That key made the
    # answer depend on which PROFILE the machine had selected, so the same repo was governed
    # differently depending on the laptop it sat on. The requirement now travels with the command
    # itself and is answered by the repo's layout + the machine's declared tooling — nobody declares
    # anything per profile, and a command added to core/ later cannot silently land on a machine
    # that cannot run it.
    if filtered and subfolder in ("commands", "rules"):
        if scope_caps is None:
            scope_caps = resolve_scope_capabilities()
        sources = {
            n: f for n, f in sources.items() if _meets_requirements(f, scope_caps)
        }
    return sources


def _install_claude_scaffolding(
    profile_path: Path | None = None,
    target_root: Path = WORKSPACE_ROOT,
    *,
    local_dir: Path | None = None,
    link_base: str | None = None,
    scope_caps: frozenset[str] | None = None,
    model_routing: dict[str, str] | None = None,
    chat_language: str | None = None,
) -> None:
    """Copy the provider scaffolding from core/ (+ the active profile's private set) to ``target_root``.

    ADR-0014 Phase 1: only ``core/rules/base/`` rules are written to ``target_root``'s
    ``.claude/rules/`` receives the base rules PLUS the domain rules whose capability is in scope
    (ADR-0060). Commands and agents layer the public ``core/`` set with the
    active profile's private ``<profile dir>/{commands,agents}/`` (the public/private layering —
    leaky/instance-specific commands like ``review_brief`` live in the private corpus, not core/).

    ``target_root`` defaults to the workspace; ``--into`` points it at a standalone POC repo.
    ``local_dir``/``link_base`` rewrite ``{{agent:…}}`` refs to repo-relative paths in that case.
    ``model_routing`` (the profile's ``model_routing`` dict) derives each agent's ``model:`` from
    its ``tier:`` at copy time — see ``_inject_agent_model``. ``None`` (e.g. no profile resolved)
    skips injection: the distributed agent then carries no ``model:``, same as an agent with no
    ``tier:`` at all. ``chat_language`` (the profile's resolved `chat` axis) is injected into every
    agent's body the same way — see ``_inject_agent_language``.
    """
    src = CORE_DIR / ".claudeignore"
    if src.exists():
        shutil.copy(src, target_root / ".claudeignore")
        print("  ✓ .claudeignore")
    for subfolder in ("commands", "agents", "rules"):
        sources = _scaffolding_sources(subfolder, profile_path, scope_caps=scope_caps)
        if not sources:
            continue
        dst_dir = target_root / ".claude" / subfolder
        dst_dir.mkdir(parents=True, exist_ok=True)
        # Expected = the union of core + profile filenames. Remove stale files no longer in any
        # source (e.g. a command relocated to the private corpus, or a previous profile's privates).
        expected = set(sources)
        for existing in list(dst_dir.iterdir()):
            if existing.is_file() and existing.name not in expected:
                existing.unlink()
        for name, f in sorted(sources.items()):
            # Rewrite {{agent:…}} corpus pointers through corpus_roots() at copy time
            # (ADR-0013) — keeps the sources profil-agnostic, one rewrite point.
            context = f".claude/{subfolder}/{name}"
            text = _expand_agent_refs(
                f.read_text(encoding="utf-8"),
                context=context,
                local_dir=local_dir,
                link_base=link_base,
            )
            if subfolder == "agents" and model_routing is not None:
                text = _inject_agent_model(text, model_routing, context=context)
            if subfolder == "agents" and chat_language is not None:
                text = _inject_agent_language(text, chat_language, context=context)
            (dst_dir / name).write_text(text, encoding="utf-8")
        print(f"  ✓ .claude/{subfolder}/")
    # Skills: each skill is a directory tree — copy the whole dir, stale cleanup by dir name.
    skill_srcs = _skill_sources(profile_path)
    if skill_srcs:
        skills_dst = target_root / ".claude" / "skills"
        skills_dst.mkdir(parents=True, exist_ok=True)
        for existing in list(skills_dst.iterdir()):
            if existing.is_dir() and existing.name not in skill_srcs:
                shutil.rmtree(existing)
        for name, src_dir in sorted(skill_srcs.items()):
            dst = skills_dst / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src_dir, dst)
            skill_md = dst / "SKILL.md"
            if model_routing is not None and skill_md.exists():
                text = _inject_agent_model(
                    skill_md.read_text(encoding="utf-8"),
                    model_routing,
                    context=f".claude/skills/{name}/SKILL.md",
                )
                skill_md.write_text(text, encoding="utf-8")
        print("  ✓ .claude/skills/")


def _dedup_rules(raw: object) -> list[str]:
    """De-duplicate a list of permission-rule strings, order kept, dropping non-str/empty."""
    seen: dict[str, None] = {}
    for rule in raw or []:
        if isinstance(rule, str) and rule and rule not in seen:
            seen[rule] = None
    return list(seen)


def render_settings_deny(profile: dict) -> list[str]:
    """Return the profile's least-agency `permissions_deny` list, de-duplicated, order kept.

    The MOTEUR is policy-agnostic: it renders whatever the profile (the CONSUMER layer)
    declares — it never hardcodes a deny baseline. Absent/empty key → no deny rules.
    """
    return _dedup_rules(profile.get("permissions_deny"))


def render_settings_allow(profile: dict) -> list[str]:
    """Return the profile's `permissions_allow` baseline, de-duplicated, order kept.

    Symmetric to `render_settings_deny`: a fewer-prompts productivity baseline (safe read-only
    bash the framework's own rules/agents trigger repeatedly — `stat` after .md edits, read-only
    `git`, `find`/`grep` in the audit agents). Still policy-agnostic: the list lives in the profile
    (consumer layer), never hardcoded here. Absent/empty key → no allow rules (existing allow kept).

    Per-machine discovery (the `/fewer-permission-prompts` skill) stays out of this baseline — it
    writes to ``settings.local.json``, which setup.py never touches.
    """
    return _dedup_rules(profile.get("permissions_allow"))


def _write_settings_json(profile: dict, claude_dir: Path) -> Path | None:
    """Render `permissions_deny` + `permissions_allow` into ``<claude_dir>/settings.json``.

    `permissions_deny` = least-agency baseline (mandatory on non-author machines — SPEC § Agentic
    security baseline). `permissions_allow` = fewer-prompts baseline (safe read-only bash). Merges
    into an existing project ``settings.json``: each list is (re)written ONLY when the profile
    declares it, so a profile that omits `permissions_allow` leaves any existing allow untouched.
    Every other key (model, hooks, …) is preserved. The user-local ``settings.local.json`` is NEVER
    touched — it carries the developer's own machine-specific allow-list (the skill writes there).

    Returns the written path, or None when the profile declares neither list (nothing to write).
    """
    deny = render_settings_deny(profile)
    allow = render_settings_allow(profile)
    if not deny and not allow:
        return None

    target = claude_dir / "settings.json"
    data: dict = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            print(f"  ⚠️  {target} is not valid JSON — rewriting permissions only")
            data = {}
    if not isinstance(data, dict):
        data = {}

    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    if deny:
        permissions["deny"] = deny
    if allow:
        permissions["allow"] = allow
    data["permissions"] = permissions

    claude_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = []
    if deny:
        summary.append(f"deny — {len(deny)} least-agency")
    if allow:
        summary.append(f"allow — {len(allow)} fewer-prompts")
    print(f"  ✓ .claude/settings.json  (permissions.{' · '.join(summary)} rule(s))")
    return target




def _install_status_lines(claude_dir: Path, target_os: str | None = None) -> None:
    """Copy the status-line scripts into ``<claude_dir>/scripts/`` and wire them in ``settings.json``.

    Only the status lines: every lifecycle hook (Stop, PreToolUse, PostToolUse) now ships with a
    plugin, which the plugin mechanism registers on its own. A status line cannot — ``statusLine``
    is a settings key with no plugin equivalent, and a plugin's own ``settings.json`` supports
    ``subagentStatusLine`` only. Shipping half a feature through each channel would mean two places
    to keep in sync, so both stay here.

    The commands carry an ABSOLUTE path. A relative one resolves against the session's working
    directory, which is not the directory holding the scripts — the status line then renders
    nothing, silently, with no error anywhere (found live 2026-08-14).

    ``target_os`` (``"Windows"`` or anything else, mirrors ``platform.system()``) picks the launcher
    for the machine that will RUN the config, not the one generating it. Self-install leaves it
    unset — target == author machine by construction. ``--into`` (rendering for a non-author
    machine, e.g. le frère) must pass it explicitly: ``platform.system()`` there reads the author's
    OS, which silently committed the wrong launcher (loup, CHANTIER0001, 2026-07-04).

    Every other key in ``settings.json`` is preserved; ``settings.local.json`` is never touched.
    """
    if not CORE_HARNESS_HOOKS_DIR.is_dir():
        return
    scripts = [f for f in sorted(CORE_HARNESS_HOOKS_DIR.iterdir()) if f.suffix == ".py"]
    if not scripts:
        return

    scripts_dst = claude_dir / "scripts"
    scripts_dst.mkdir(parents=True, exist_ok=True)
    for src in scripts:
        dst = scripts_dst / src.name
        shutil.copy(src, dst)
        dst.chmod(0o755)

    target = claude_dir / "settings.json"
    data: dict = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}

    launcher = "py -3" if (target_os or platform.system()) == "Windows" else "python3"
    for key, script in (
        ("statusLine", "statusline.py"),
        ("subagentStatusLine", "subagent_statusline.py"),
    ):
        path = scripts_dst / script
        if path.exists():
            data[key] = {
                "type": "command",
                "command": f'{launcher} "{path}"',
            }

    claude_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  \u2713 .claude/scripts/  ({len(scripts)} status line(s)) + settings.json")


def install_from_profile(profile_arg: str, output: Path | None = None) -> None:
    """Render CLAUDE.md from a profile and (when installing for real) the .claude/ scaffolding.

    Single render since ADR-0060: ``WORKSPACE_ROOT/CLAUDE.md`` (CLAUDE-base.md.tpl). The former
    per-subtree domain layer is gone — it rendered into a directory no repo lived under, so its
    rules never reached a session.

    When ``output`` is given, only that CLAUDE.md is written (the .claude/ scaffolding is left
    untouched — safe for temp/validation renders).
    """
    profile, profile_path = load_profile(profile_arg)
    # This render is FOR THIS MACHINE, so it is the one place instance knobs apply (ADR-0069).
    # `install_into_repo` deliberately does not: it produces a CLAUDE.md the author commits and
    # someone else clones, so applying her chat language or model tiers there would ship personal
    # settings as if they were the repo's policy. `--check-public` does not either — its verdict is
    # the artefact's, never the machine's (same reasoning as ADR-0068's bounded roots).
    profile = apply_instance_overrides(profile, _WORKSPACE_DEFAULTS)
    validate_profile(profile, profile_path)

    # Install scope = the whole machine: ONE .claude/ at the workspace root serves every sibling
    # repo, so the routing key is the union of their capabilities (see resolve_scope_capabilities).
    # Resolved once here and threaded to both consumers — the rendered {{commands_index}} and the
    # copied files must agree.
    scope_caps = resolve_scope_capabilities()

    # Root render: neutral base template (no knowledge agents, no domain header).
    content = render_claude_md(
        profile,
        profile_path,
        template_name="CLAUDE-base.md.tpl",
        scope_caps=scope_caps,
    )
    target = output or (WORKSPACE_ROOT / "CLAUDE.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"  ✓ CLAUDE.md  (neutral base, rendered from profile '{profile['name']}')")

    if output is None:
        # Base rules + public core commands/agents + the active profile's private commands/agents.
        _install_claude_scaffolding(
            profile_path,
            scope_caps=scope_caps,
            model_routing=profile.get("model_routing"),
            chat_language=_resolve_language_axis(profile, "chat"),
        )
        # Least-agency baseline: render the profile's permissions_deny into .claude/settings.json.
        _write_settings_json(profile, WORKSPACE_ROOT / ".claude")
        # Harness hooks (Stop → kanban handoff auto-maintainer) + settings.json wiring.
        _install_status_lines(WORKSPACE_ROOT / ".claude")

    _print_profile_summary(profile, profile_path, target)
    # Rendering is not distributing — ADR-0055's drift check only fires on the distribution flags,
    # so this path used to leave stale repos completely unsignalled (card
    # `render-path-ne-verifie-aucune-derive`). Advisory and last: never costs the caller its render.
    warn_on_drift()


def install_into_repo(
    profile_arg: str, repo: Path, target_os: str | None = None
) -> None:
    """Render a profile's FULL agent layer INTO a standalone repo, committed config and all.

    For a POC repo that lives on its own (cloned on a non-author machine — frère's flow): the
    workspace-root install (``install_from_profile``) renders the agent layer only at
    WORKSPACE_ROOT, so a cloned-alone repo has nothing. ``--into`` makes the repo self-sufficient:

    1. bundle the profile's knowledge agents into ``<repo>/.claude/knowledge/``
    2. render the full-profile ``CLAUDE.md`` at the repo root with repo-relative links (no domain
       split — the repo IS the working context)
    3. install the scaffolding (commands/agents/rules + the profile's private set) with the same
       repo-relative ``{{agent:…}}`` rewrite
    4. write the least-agency ``.claude/settings.json`` (permissions_deny)

    ``target_os`` (``"Windows"`` or ``"posix"``): the OS of the machine that will RUN this repo,
    not the one generating it — pass it whenever the two differ (the frère's flow, almost always).
    Unset falls back to the generating machine's OS, correct only when target == author.

    The author runs it once and commits the result; ``git clone`` then carries the whole config.
    """
    profile, profile_path = load_profile(profile_arg)
    validate_profile(profile, profile_path)
    repo = repo.expanduser().resolve()
    if not repo.is_dir():
        print(f"--into target is not a directory: {repo}")
        sys.exit(1)

    link_base = ".claude/knowledge"
    knowledge_dir = repo / ".claude" / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # Install scope = THIS repo alone, so the capability routing is exact (same reasoning as the
    # commands, ADR-0058 + lot 1). Resolved ONCE and reused by every consumer below: the bundled
    # files, the rendered index and the scaffolding must agree — two resolutions are two chances to
    # disagree, which is the drift class this whole chantier exists to remove.
    scope_caps = resolve_scope_capabilities(repo)

    # 1. Bundle the agents this scope gets (prune stale copies from a previous run — including one
    #    dropped because its capability is no longer in scope).
    resolved_agents, _ = resolve_profile_agents(profile, profile_path, scope_caps)
    bundled = set(resolved_agents)
    for existing in list(knowledge_dir.iterdir()):
        if existing.is_file() and existing.name not in bundled:
            existing.unlink()
    for resolved in sorted(resolved_agents.values()):
        text = _expand_agent_refs(
            resolved.read_text(encoding="utf-8"),
            context=f"{link_base}/{resolved.name}",
            local_dir=knowledge_dir,
            link_base=link_base,
        )
        (knowledge_dir / resolved.name).write_text(text, encoding="utf-8")
    print(f"  ✓ .claude/knowledge/  ({len(bundled)} agent(s) bundled)")

    # 2. Full-profile CLAUDE.md at the repo root, repo-relative links.
    content = render_claude_md(
        profile,
        profile_path,
        local_dir=knowledge_dir,
        link_base=link_base,
        scope_caps=scope_caps,
    )
    (repo / "CLAUDE.md").write_text(content, encoding="utf-8")
    print(f"  ✓ CLAUDE.md  (full profile '{profile['name']}', repo-relative)")

    # 3. Scaffolding (commands/agents/rules) into the repo, same rewrite.
    _install_claude_scaffolding(
        profile_path,
        repo,
        model_routing=profile.get("model_routing"),
        chat_language=_resolve_language_axis(profile, "chat"),
        local_dir=knowledge_dir,
        link_base=link_base,
        scope_caps=scope_caps,
    )
    # 4. Least-agency baseline.
    _write_settings_json(profile, repo / ".claude")
    # 5. Harness hooks (Stop → kanban handoff auto-maintainer). No-op at runtime when the cloned
    #    repo has no _KANBAN/, so it degrades cleanly on a POC machine.
    _install_status_lines(repo / ".claude", target_os=target_os)

    _print_profile_summary(profile, profile_path, repo / "CLAUDE.md")
    warn_on_drift()  # same blind spot as install_from_profile — advisory, never blocking


def _print_profile_summary(profile: dict, profile_path: Path, target: Path) -> None:
    """Print the active profile, the agents loaded, and the CLAUDE.md path."""
    agents = profile.get("knowledge_agents") or []
    print("\nSummary")
    print("-" * 52)
    print(f"  Active profile        : {profile['name']}  ({profile_path})")
    print(f"  Knowledge agents      : {len(agents)} loaded")
    for entry in agents:
        print(f"      - {Path(entry).name}")
    print(f"  CLAUDE.md written to  : {target}")


def install_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        print(f"Unknown provider: {provider}")
        print(f"Available: {', '.join(PROVIDERS)}")
        sys.exit(1)

    print(f"\nInstalling {provider} configuration...")

    if provider == "claude":
        # `claude` is an alias for this instance's default profile (single rendering path).
        if DEFAULT_PROFILE is None:
            print(
                "--provider claude has no default profile to alias — set default_profile in "
                ".pinky/config.txt (or the DEFAULT_PROFILE env var), or pass --profile "
                "<name> directly."
            )
            sys.exit(1)
        install_from_profile(DEFAULT_PROFILE)
    elif provider == "mistral":
        print(
            "  Mistral provider not yet implemented — see providers/mistral/README.md"
        )
