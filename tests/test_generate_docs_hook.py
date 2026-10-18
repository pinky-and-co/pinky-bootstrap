"""Behavioral tests of the `generate-docs` hook — coverage measured in a complete env only.

The coverage badge has been written wrong three times (~59% instead of ~84%): the suite ran
in an env stripped of its optional extras, the affected tests skipped, and a skip makes
nothing red. The contract proven here: on a uv machine BOTH coverage invocations (run and
xml) go through `uv run --frozen --all-extras`, and a skip whose reason is a missing import
makes the hook refuse the badge (exit 1) instead of writing a measurement made in a
degraded env.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "hygiene" / "hooks" / "generate-docs"

NO_SKIP_LOG = "1 passed in 0.01s\n"
IMPORT_SKIP_LOG = (
    "1 passed, 1 skipped in 0.01s\n"
    "\n"
    "======================== short test summary info ========================\n"
    "SKIPPED [1] tests/test_validate.py:60: python-stdnum not installed\n"
)
UNRELATED_SKIP_LOG = (
    "1 passed, 1 skipped in 0.01s\n"
    "\n"
    "======================== short test summary info ========================\n"
    "SKIPPED [1] tests/test_platform.py:5: windows only\n"
)

BADGE = Path("docs/reference/generated/coverage_badge.svg")


def _resolve_bash() -> str:
    """The bash to invoke the hook with — Git for Windows' own bash, never the WSL stub."""
    if sys.platform != "win32":
        return "bash"
    git = shutil.which("git")
    if git:
        candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    return "bash"


def _fake_venv(repo: Path, log: str) -> None:
    """A fake `.venv`: `coverage run` prints the given pytest log, anything else (scripts/,
    -c probes) goes to the real interpreter — but `coverage xml` FAILS, the way it does on a
    stale interpreter resolved before uv created the venv. `genbadge` writes its `-o` target
    only when the xml output exists, so the badge-written verdict is real, not unconditional."""
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    cov_log = repo / "cov_out.txt"
    cov_log.write_text(log, encoding="utf-8")
    wrapper = venv_bin / "python"
    wrapper.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "coverage" ] && [ "$3" = "run" ]; then\n'
        f'  cat "{cov_log}"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "-m" ] && [ "$2" = "coverage" ] && [ "$3" = "xml" ]; then\n'
        '  echo "No module named coverage" >&2\n'
        "  exit 1\n"
        "fi\n"
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    genbadge = venv_bin / "genbadge"
    genbadge.write_text(
        "#!/bin/sh\n"
        'out=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
        '[ -n "$out" ] && [ -f .cache/coverage/coverage.xml ] && printf "badge\\n" > "$out"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    genbadge.chmod(0o755)


def _staged_src_repo(tmp_path: Path, log: str, *, with_uv: bool) -> tuple[Path, Path]:
    """A git repo with a staged src/ file (the badge branch's trigger), a fake venv, and a
    PATH bin dir holding git (symlink) and — optionally — a fake `uv` that records each of its
    invocations' argv and replays the pytest log."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    pkg = repo / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/pkg/mod.py"], cwd=repo, check=True)
    # Stub : l'étape 1 du hook exécute le renderer de docs local ; neutre, il évite le sys.exit
    # (identité distribuée absente du repo factice) dans le stderr de chaque run.
    stub = repo / "scripts" / "hooks" / "render_docs.py"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "# stub - doc rendering is covered by test_render_docs_repo_name.py\n",
        encoding="utf-8",
    )
    # Le badge en place porte une valeur datée : « réécrit ou pas » s'observe par le contenu.
    (repo / BADGE).parent.mkdir(parents=True)
    (repo / BADGE).write_text("stale", encoding="utf-8")
    _fake_venv(repo, log)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if git := shutil.which("git"):
        os.symlink(git, bin_dir / "git")
    if with_uv:
        uv = bin_dir / "uv"
        uv.write_text(
            "#!/bin/sh\n"
            f'printf \'%s\\n\' "$@" >> "{repo / "uv_args.txt"}"\n'
            'out=""; prev=""\n'
            'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
            '[ -n "$out" ] && printf "xml\\n" > "$out"\n'
            f'cat "{repo / "cov_out.txt"}"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        uv.chmod(0o755)
    return repo, bin_dir


def _run_hook(repo: Path, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    # PATH réduit à nos faux + le socle système : `uv` n'y est que si le test le pose.
    return subprocess.run(
        [_resolve_bash(), str(HOOK)],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
    )


def _has_argv_sequence(argv: list[str], expected: list[str]) -> bool:
    """Whether ``expected`` appears as one contiguous run of arguments — isolated flags prove
    nothing, they could belong to another invocation recorded in the same argv log."""
    return any(argv[i : i + len(expected)] == expected for i in range(len(argv)))


@pytest.mark.skipif(sys.platform == "win32", reason="enveloppe sh POSIX")
def test_suite_runs_through_uv_all_extras(tmp_path):
    """The coverage run resyncs the env with every extra installed, and reports skip
    reasons (-rs) — the input of the degraded-env guard below."""
    repo, bin_dir = _staged_src_repo(tmp_path, NO_SKIP_LOG, with_uv=True)
    run = _run_hook(repo, bin_dir)
    assert run.returncode == 0
    argv = (repo / "uv_args.txt").read_text(encoding="utf-8").splitlines()
    # Séquences contiguës, pas des flags isolés : les extras doivent habiter LE run de coverage,
    # pas un autre appel uv du hook.
    assert _has_argv_sequence(
        argv, ["run", "--frozen", "--all-extras", "coverage", "run"]
    )
    assert "-rs" in argv
    assert (repo / BADGE).read_text(encoding="utf-8") == "badge\n"


@pytest.mark.skipif(sys.platform == "win32", reason="enveloppe sh POSIX")
def test_coverage_xml_goes_through_uv_too(tmp_path):
    """The xml export rides the same uv env: PY was resolved before uv created the venv, so a
    stale system interpreter has no coverage module — the badge written below is the proof the
    xml step did NOT run under it (the fake genbadge refuses a missing xml output)."""
    repo, bin_dir = _staged_src_repo(tmp_path, NO_SKIP_LOG, with_uv=True)
    run = _run_hook(repo, bin_dir)
    assert run.returncode == 0
    argv = (repo / "uv_args.txt").read_text(encoding="utf-8").splitlines()
    assert _has_argv_sequence(
        argv, ["run", "--frozen", "--all-extras", "coverage", "xml"]
    )
    assert (repo / BADGE).read_text(encoding="utf-8") == "badge\n"


@pytest.mark.skipif(sys.platform == "win32", reason="enveloppe sh POSIX")
def test_import_skip_refuses_the_badge_and_blocks(tmp_path):
    """THE test of this change: a skip whose reason is a missing import means the
    measurement was made in a stripped env — no badge, the offending skip named, exit 1."""
    repo, bin_dir = _staged_src_repo(tmp_path, IMPORT_SKIP_LOG, with_uv=True)
    run = _run_hook(repo, bin_dir)
    assert run.returncode == 1
    assert "python-stdnum not installed" in run.stderr
    assert "uv sync --all-extras" in run.stderr
    assert (repo / BADGE).read_text(encoding="utf-8") == "stale"


@pytest.mark.skipif(sys.platform == "win32", reason="enveloppe sh POSIX")
def test_import_skip_still_blocks_without_uv(tmp_path):
    """The fallback interpreter path (no uv on the machine) carries the same guard."""
    repo, bin_dir = _staged_src_repo(tmp_path, IMPORT_SKIP_LOG, with_uv=False)
    run = _run_hook(repo, bin_dir)
    assert run.returncode == 1
    # Pas d'uv sur la machine : le remède pointe le venv, pas une commande uv introuvable.
    assert "uv sync --all-extras" not in run.stderr
    assert ".venv" in run.stderr
    assert (repo / BADGE).read_text(encoding="utf-8") == "stale"


@pytest.mark.skipif(sys.platform == "win32", reason="enveloppe sh POSIX")
def test_skip_for_another_reason_does_not_block(tmp_path):
    """The guard bites import-missing skips only — a deliberate platform skip is a normal
    suite outcome, the badge must still be written."""
    repo, bin_dir = _staged_src_repo(tmp_path, UNRELATED_SKIP_LOG, with_uv=True)
    run = _run_hook(repo, bin_dir)
    assert run.returncode == 0
    assert (repo / BADGE).read_text(encoding="utf-8") == "badge\n"
