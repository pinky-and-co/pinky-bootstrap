"""Tests comportementaux du hook `run-tests` — exécution réelle, pas invariant statique.

Ce hook est le portier de qualité de TOUS les repos distribués, et il n'avait aucun test
(constaté 2026-07-31). Un portier ne se prouve pas en lisant son code : la seule preuve qu'il
bloque, c'est de le faire bloquer. Chaque cas ci-dessous lance le script dans un dossier temporaire
et n'assertionne que sur son code de sortie — le contrat du hook, rien d'autre.

Le cas qui porte la valeur est `test_js_suite_failing_blocks` : retirer la branche JS du hook doit
le faire repasser au vert (preuve par mutation, `core/rules/base/tests.md`). Avant le 2026-07-31 le
hook ne savait faire que du pytest, donc une suite JS rouge produisait « Passed ».
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "hygiene" / "hooks" / "run-tests"

PASSING_JS = "import {test} from 'node:test';\ntest('ok', () => {});\n"
FAILING_JS = (
    "import {test} from 'node:test';\ntest('boom', () => { throw new Error('x'); });\n"
)


def _resolve_bash() -> str:
    """The bash to invoke `run-tests` with.

    On Windows, a bare `"bash"` resolved via PATH can land on `C:\\Windows\\System32\\bash.exe` —
    the WSL launcher stub, not Git's bash — when it precedes Git's own `bin\\` on PATH. Confirmed
    on GitHub's `windows-latest` runner (CHANTIER0001 `run-tests-hook-cassé-sous-git-bash`,
    `bash -x` trace): it exits 1 printing "Windows Subsystem for Linux has no installed
    distributions", never reaching the script. Git for Windows ships its own `bash.exe` next to
    `git.exe`'s install root — prefer it explicitly rather than trusting PATH order.
    """
    if sys.platform != "win32":
        return "bash"
    git = shutil.which("git")
    if git:
        candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base and (candidate := Path(base) / "Git" / "bin" / "bash.exe").exists():
            return str(candidate)
    return "bash"


def run_hook(cwd: Path) -> int:
    """Le hook, lancé comme pre-commit le lance : bash, depuis la racine du repo."""
    return subprocess.run(
        [_resolve_bash(), str(HOOK)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).returncode


def with_python(repo: Path) -> None:
    """Pose `.venv/bin/python` → l'interpréteur courant, via un script d'enveloppe.

    Sans ça le hook retombe sur le `python3` du PATH, qui n'a pas forcément pytest : il
    avertirait et sauterait, et un test « suite Python rouge » passerait au vert pour la mauvaise
    raison. Exerce au passage le premier barreau de l'échelle de résolution.

    Enveloppe et NON symlink : un lien symbolique vers l'interpréteur d'un venv (ou d'un
    environnement uv) fait remonter Python jusqu'à l'interpréteur de base pour calculer `sys.prefix`,
    qui perd alors les site-packages de l'environnement — pytest redevient introuvable et le test
    passerait au vert pour exactement la raison qu'il est censé exclure (mesuré 2026-07-31 :
    prefix retombé sur le framework système). L'enveloppe invoque le binaire par son vrai chemin.
    """
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    wrapper = venv_bin / "python"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)


def write_py_suite(repo: Path, *, passing: bool) -> None:
    tests = repo / "tests"
    tests.mkdir()
    body = "def test_x():\n    assert %s\n" % ("True" if passing else "False")
    (tests / "test_x.py").write_text(body, encoding="utf-8")
    with_python(repo)


needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node absent de cette machine"
)


def test_no_suite_at_all_passes(tmp_path):
    assert run_hook(tmp_path) == 0


def test_package_json_without_test_script_is_a_noop(tmp_path):
    """La forme de pinky-studio : un package.json, mais aucun script `test` et aucun *.test.js.

    Garde anti-régression du rollout : ce repo ne doit pas se mettre à voir ses commits bloqués
    parce qu'il possède un package.json (le sien ne déclare qu'un script `build`).
    """
    (tmp_path / "package.json").write_text(
        '{"name":"x","scripts":{"build":"echo build"}}', encoding="utf-8"
    )
    assert run_hook(tmp_path) == 0


def test_python_suite_passing_passes(tmp_path):
    write_py_suite(tmp_path, passing=True)
    assert run_hook(tmp_path) == 0


def test_python_suite_failing_blocks(tmp_path):
    write_py_suite(tmp_path, passing=False)
    assert run_hook(tmp_path) == 1


@needs_node
def test_js_suite_passing_passes(tmp_path):
    (tmp_path / "engine.test.js").write_text(PASSING_JS, encoding="utf-8")
    assert run_hook(tmp_path) == 0


@needs_node
def test_js_suite_failing_blocks(tmp_path):
    """LE test de ce changement. Sans la branche JS du hook, il repasse au vert."""
    (tmp_path / "engine.test.js").write_text(FAILING_JS, encoding="utf-8")
    assert run_hook(tmp_path) == 1


@needs_node
def test_js_tests_in_a_subdirectory_are_found(tmp_path):
    """PILOT met son JS sous src/web/scripts/ — la découverte ne doit pas être limitée à la racine."""
    nested = tmp_path / "src" / "web" / "scripts"
    nested.mkdir(parents=True)
    (nested / "engine.test.js").write_text(FAILING_JS, encoding="utf-8")
    assert run_hook(tmp_path) == 1


@needs_node
def test_node_modules_is_not_scanned(tmp_path):
    """Un test rouge d'une dépendance ne doit jamais bloquer le commit du repo."""
    vendored = tmp_path / "node_modules" / "some-dep"
    vendored.mkdir(parents=True)
    (vendored / "broken.test.js").write_text(FAILING_JS, encoding="utf-8")
    assert run_hook(tmp_path) == 0


@needs_node
@pytest.mark.skipif(shutil.which("npm") is None, reason="npm absent de cette machine")
def test_package_json_test_script_wins_over_file_discovery(tmp_path):
    """Le script déclaré l'emporte : ici il échoue alors que le fichier *.test.js, lui, passerait."""
    (tmp_path / "package.json").write_text(
        '{"name":"x","scripts":{"test":"exit 3"}}', encoding="utf-8"
    )
    (tmp_path / "engine.test.js").write_text(PASSING_JS, encoding="utf-8")
    assert run_hook(tmp_path) == 1


@needs_node
def test_tests_dir_holding_only_js_does_not_block(tmp_path):
    """Un dossier tests/ sans test Python ne doit pas bloquer sur « aucun test collecté ».

    Régression introduite puis corrigée le 2026-07-31 : sortir les tests JS de la racine statique
    de PILOT vers tests/ a suffi à déclencher la branche Python, et pytest renvoie 5 quand il ne
    collecte rien — code non nul, donc traité comme un échec. Les 22 tests JS passaient, le commit
    était bloqué quand même. Le code 5 est « rien à exécuter », pas « la suite échoue ».
    """
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "engine.test.js").write_text(PASSING_JS, encoding="utf-8")
    with_python(tmp_path)
    assert run_hook(tmp_path) == 0


@needs_node
def test_tests_dir_holding_only_js_still_reports_a_js_failure(tmp_path):
    """Le pardon du code 5 ne doit pas avaler le verdict de l'autre suite."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "engine.test.js").write_text(FAILING_JS, encoding="utf-8")
    with_python(tmp_path)
    assert run_hook(tmp_path) == 1


@needs_node
def test_js_failure_blocks_even_when_python_passes(tmp_path):
    """Le verdict est l'union des suites : une seule rouge suffit à bloquer."""
    write_py_suite(tmp_path, passing=True)
    (tmp_path / "engine.test.js").write_text(FAILING_JS, encoding="utf-8")
    assert run_hook(tmp_path) == 1


@needs_node
def test_python_failure_blocks_even_when_js_passes(tmp_path):
    write_py_suite(tmp_path, passing=False)
    (tmp_path / "engine.test.js").write_text(PASSING_JS, encoding="utf-8")
    assert run_hook(tmp_path) == 1


def test_missing_node_warns_but_does_not_block(tmp_path):
    """Un outil de dev absent est une machine mal équipée, pas un test qui échoue.

    PATH vidé de node : le hook doit détecter la suite JS, le dire sur stderr, et sortir en 0.
    """
    (tmp_path / "engine.test.js").write_text(FAILING_JS, encoding="utf-8")
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    if shutil.which("node", path=env["PATH"]):
        pytest.skip("node est dans /usr/bin — impossible de simuler son absence ici")
    proc = subprocess.run(
        [_resolve_bash(), str(HOOK)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        encoding="utf-8",
    )
    assert proc.returncode == 0
    assert "node absent" in proc.stderr


def test_test_gate_declares_no_files_pattern():
    """Le portier de tests ne doit filtrer sur AUCUN motif de chemin (2026-08-07).

    Il valait `^(src|tests)/`, soit une **allowlist de layouts** : fausse par défaut pour toute
    arborescence non énumérée. Le moteur lui-même en était la preuve — son code vit dans `setup/`,
    jamais matché, donc jamais testé au commit. Même trou pour `resources/` (repos data) et pour tout
    paquet Python en flat layout, qui est un layout valide.

    Élargir le motif aurait déplacé le défaut d'une arborescence. L'absence de motif rend le portier
    correct par construction : `run-tests` détecte les suites lui-même et sort en 0 quand il n'y en a
    pas. Ce test échoue si quelqu'un réintroduit un filtre — y compris un filtre « plus complet ».
    """
    yaml = pytest.importorskip("yaml")

    base = yaml.safe_load(
        (
            Path(__file__).parent.parent / "hygiene" / "pre-commit" / "base.yaml"
        ).read_text(encoding="utf-8")
    )
    gate = [
        h
        for r in base["repos"]
        for h in r.get("hooks", [])
        if h.get("id") == "run-tests"
    ]
    assert len(gate) == 1, "run-tests doit être le seul hook de son bloc repo"
    assert "files" not in gate[0], (
        "run-tests a retrouvé un `files:` — c'est une allowlist de layouts, elle sera fausse "
        "pour la prochaine arborescence non prévue (cf. `setup/` sur le moteur lui-même)"
    )
    assert "exclude" not in gate[0], (
        "une exclusion serait plus défendable qu'un `files:`, mais elle n'a pas été retenue : "
        "à rediscuter explicitement, pas à réintroduire en passant"
    )


def test_darglint_config_written_when_absent(tmp_path):
    """Un repo python sans `.darglint` en reçoit un — sinon darglint retombe sur son défaut.

    Son défaut est **full**, pas `long` : mesuré le 2026-08-07 sur un docstring d'une ligne avec un
    paramètre — short 0 · long 0 · full 2 · ni flag ni fichier 2. Le commit a7250ce a retiré le flag
    CLI `--strictness=short` en affirmant que « chaque repo porte déjà un .darglint » ; c'était faux
    pour cinq d'entre eux, qui sont donc passés de `short` à `full` en silence. CI de
    pluto-poc-pilot cassée, quatre autres repos en panne latente.
    """
    import setup

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    setup._write_darglint_config(tmp_path, ["python"])
    cfg = tmp_path / ".darglint"
    assert cfg.exists(), "un repo python sans .darglint doit en recevoir un"
    assert "strictness = long" in cfg.read_text(encoding="utf-8")


def test_darglint_config_converges_a_diverging_repo(tmp_path):
    """Un repo qui diverge est RAMENÉ à la valeur du socle — uniformité voulue (user, 2026-08-07).

    La première version gardait le fichier existant, en supposant qu'un repo sur `short` avait
    décidé. Vérifié : les quatre `.darglint` du parc datent tous du 2026-06-11, trois d'entre eux
    posés en effet de bord de commits sans rapport. `short` ici et `long` là était une divergence
    accidentelle, pas une position. Ce test remplace `..._never_overwrites_a_repo_decision`, qui
    protégeait une décision fantôme.
    """
    import setup

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / ".darglint").write_text(
        "[darglint]\nstrictness = short\n", encoding="utf-8"
    )
    setup._write_darglint_config(tmp_path, ["python"])
    assert "strictness = long" in (tmp_path / ".darglint").read_text(encoding="utf-8")


def test_darglint_config_skipped_without_the_python_extra(tmp_path):
    """Pas d'extra python → pas de hook darglint → pas de fichier à poser."""
    import setup

    setup._write_darglint_config(tmp_path, ["python-lint"])
    assert not (tmp_path / ".darglint").exists()
