""".claude/ scaffolding install — profile resolution, behavior/language rendering, settings.json.

CLAUDE.md rendering itself (render_claude_md, install_from_profile, install_into_repo,
install_provider) was removed 2026-08-17: pinky-bootstrap's scope is hygiene tooling only, and its
CLAUDE.md.tpl/CLAUDE-base.md.tpl inputs were already deleted when that scope reduction landed
(827edaf/3c79927). See CHANTIER0023 card `cli-setup-repo-lot1` for what replaces it.
"""

import re
import sys
from pathlib import Path

from .common import (
    CORE_DIR,
    MACHINE_CAPABILITIES,
    corpus_roots,
)

# One-way edge: precommit imports common + product_scaffold, neither of which imports this module,
# so there is no cycle. The capability DETECTOR lives next to the hook extras it was written for —
# duplicating it here to avoid the import would give the two axes two answers.
from .precommit import resolve_scope_capabilities

REQUIRED_PROFILE_KEYS = ("name", "knowledge_agents", "knowledge_roots", "model_routing")


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
