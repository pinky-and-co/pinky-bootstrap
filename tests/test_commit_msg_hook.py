"""Tests comportementaux du hook `commit-msg` — exécution réelle, pas invariant statique.

Ce hook garde le format des messages de commit sur TOUS les repos distribués. Le parsing des
breaking changes conformes à la spec Conventional Commits (`<type>!:` sur le header, et/ou un
footer `BREAKING CHANGE:`) a été ajouté sans aucun test — or un portier ne se prouve pas en
lisant son code, seulement en le faisant accepter puis bloquer. Chaque cas écrit le message dans
un fichier temporaire, lance le hook comme git le lance (`bash commit-msg <file>`) et n'assertionne
que sur le code de sortie ; un cas de rejet fige aussi la sortie complète du hook (oracle, `core/rules/base/tests.md`).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent / "hygiene" / "hooks" / "commit-msg"


def _resolve_bash() -> str:
    """Le bash avec lequel invoquer `commit-msg`.

    Sur Windows, un `"bash"` nu résolu par le PATH peut tomber sur le stub WSL de System32 au lieu
    du bash de Git — même piège que `test_run_tests_hook.py`, même parade : préférer explicitement
    le `bash.exe` livré à côté de `git.exe`.
    """
    if sys.platform != "win32":
        return "bash"
    git = shutil.which("git")
    if git:
        candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if candidate.exists():
            return str(candidate)
    return "bash"


def run_hook(tmp_path: Path, message: str) -> subprocess.CompletedProcess[str]:
    """Le hook, lancé comme pre-commit le lance : bash, avec le chemin du fichier de message en `$1`."""
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(message, encoding="utf-8")
    return subprocess.run(
        [_resolve_bash(), str(HOOK), str(msg_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ── Accepté ─────────────────────────────────────────────────────────────────

ACCEPTED = [
    pytest.param("✨ feat: add manifest variable resolution", id="plain-feat"),
    pytest.param("♻️ refactor: extract stage upload logic", id="plain-refactor"),
    pytest.param("💾 save: core/manifest.py in progress [skip ci]", id="save"),
    pytest.param("Merge branch 'main' into feature/x", id="merge"),
    pytest.param("♻️ refactor!: rename upload_packages signature", id="bang-refactor"),
    pytest.param("🔧 chore!: drop the legacy config key", id="bang-chore"),
    pytest.param(
        "♻️ refactor!: rename upload_packages signature\n"
        "\n"
        "BREAKING CHANGE: upload_packages now takes (bucket, key) instead of (path).",
        id="bang-and-footer",
    ),
    pytest.param(
        "🐛 fix: handle missing region\n"
        "\n"
        "BREAKING CHANGE: the region field is now required in every profile.",
        id="footer-without-bang",
    ),
    pytest.param("✨ feat: ééé", id="three-codepoint-description"),
]


@pytest.mark.parametrize("message", ACCEPTED)
def test_accepted(tmp_path, message):
    """Un message conforme sort avec le code 0."""
    result = run_hook(tmp_path, message)
    assert result.returncode == 0, result.stdout + result.stderr


# ── Rejeté ──────────────────────────────────────────────────────────────────

# (message, fragment attendu dans la sortie) — le fragment prouve QUE le rejet vient du bon check.
REJECTED = [
    pytest.param("♻️ refactor!:", "invalid commit format", id="bang-empty-description"),
    pytest.param(
        "♻️ refactor !: rename x", "invalid commit format", id="space-before-bang"
    ),
    pytest.param(
        "💥 breaking: rename upload_packages signature",
        "not in mapping",
        id="dropped-breaking-type",
    ),
    pytest.param(
        "🐛 fix: handle missing region\n\nBREAKING CHANGE: ab",
        "malformed BREAKING CHANGE footer",
        id="footer-too-short",
    ),
    pytest.param(
        "🐛 fix: handle missing region\n\nBreaking change: the region field is now required.",
        "malformed BREAKING CHANGE footer",
        id="footer-wrong-case",
    ),
    pytest.param(
        "🐛 fix: handle missing region\n\nBREAKING-CHANGE: the region field is now required.",
        "malformed BREAKING CHANGE footer",
        id="footer-hyphen-form",
    ),
    pytest.param(
        "✨ feat: éé", "invalid commit format", id="two-codepoint-description"
    ),
]


@pytest.mark.parametrize("message, fragment", REJECTED)
def test_rejected(tmp_path, message, fragment):
    """Un message non conforme sort non nul, et le message d'erreur cible le bon check."""
    result = run_hook(tmp_path, message)
    assert result.returncode != 0, result.stdout + result.stderr
    assert fragment in result.stdout, result.stdout + result.stderr


def test_malformed_footer_full_output(tmp_path):
    """Oracle : le rejet d'un footer mal casé pine la sortie entière du hook, pas un fragment."""
    result = run_hook(
        tmp_path,
        "🐛 fix: handle missing region\n\nBreaking change: the region field is now required.",
    )
    assert result.returncode == 1
    msg_file = tmp_path / "COMMIT_EDITMSG"
    assert result.stdout == (
        f"{msg_file} (1)\n"
        "\n"
        "  COMMIT-MSG malformed BREAKING CHANGE footer\n"
        f"   --> {msg_file}:3:1\n"
        "    |\n"
        "  3 | Breaking change: the region field is now required.\n"
        "    | ^^^^^^^^^^^^^^^^\n"
        "    |\n"
        "    = help: must be exactly: BREAKING CHANGE: <description>  (one space, both words uppercase)\n"
        "            BREAKING-CHANGE: and other casings are rejected on purpose — use the space form\n"
        "\n"
        "Found 1 error in 1 file.\n"
    )


def test_wrong_type_underlines_the_type_and_suggests_the_right_one(tmp_path):
    """Oracle : sortie entière d'un emoji associé au mauvais type."""
    result = run_hook(tmp_path, "✨ fixx: bad")
    msg_file = tmp_path / "COMMIT_EDITMSG"
    assert result.returncode == 1
    assert result.stdout == (
        f"{msg_file} (1)\n"
        "\n"
        "  COMMIT-MSG emoji '✨' requires type 'feat', got 'fixx'\n"
        f"   --> {msg_file}:1:3\n"
        "    |\n"
        "  1 | ✨ fixx: bad\n"
        "    |   ^^^^\n"
        "    |\n"
        "    = help: use: ✨ feat: <description>\n"
        "\n"
        "Found 1 error in 1 file.\n"
    )


def test_force_color_paints_the_report(tmp_path):
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text("hello world", encoding="utf-8")
    env = {**os.environ, "FORCE_COLOR": "1", "TERM": "dumb"}
    env.pop("NO_COLOR", None)
    result = subprocess.run(
        [_resolve_bash(), str(HOOK), str(msg_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert "\x1b[1;31mCOMMIT-MSG\x1b[0m" in result.stdout


def test_no_color_wins_over_force_color(tmp_path):
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text("hello world", encoding="utf-8")
    result = subprocess.run(
        [_resolve_bash(), str(HOOK), str(msg_file)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "FORCE_COLOR": "1", "NO_COLOR": "1"},
    )
    assert "\x1b" not in result.stdout


def test_unknown_emoji_lists_the_emojis_of_the_typed_type(tmp_path):
    """Oracle : un emoji inconnu devant un type valide renvoie les emojis de CE type, sans renvoi externe."""
    result = run_hook(tmp_path, "🙂 docs: tidy the readme")
    msg_file = tmp_path / "COMMIT_EDITMSG"
    assert result.returncode == 1
    assert result.stdout == (
        f"{msg_file} (1)\n"
        "\n"
        "  COMMIT-MSG emoji '🙂' not in mapping\n"
        f"   --> {msg_file}:1:1\n"
        "    |\n"
        "  1 | 🙂 docs: tidy the readme\n"
        "    | ^\n"
        "    |\n"
        "    = help: emojis for 'docs': 📝 💡 💬 📄 👥\n"
        "\n"
        "Found 1 error in 1 file.\n"
    )


def test_unknown_emoji_and_unknown_type_lists_the_types(tmp_path):
    result = run_hook(tmp_path, "🙂 nope: x thing")
    assert result.returncode == 1
    assert (
        "= help: types: feat fix docs style refactor move perf test revert build chore release"
        in result.stdout
    )


def test_crlf_message_file_is_read_without_the_carriage_returns(tmp_path):
    """Oracle : un COMMIT_EDITMSG CRLF (éditeur Windows) sort exactement comme un LF — le ``\r``
    n'est ni compté dans le soulignement ni recraché dans la ligne source."""
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_bytes("✨ feat ab\r\n".encode("utf-8"))
    result = subprocess.run(
        [_resolve_bash(), str(HOOK), str(msg_file)],
        capture_output=True,
    )
    assert result.returncode == 1
    assert result.stdout.decode("utf-8") == (
        f"{msg_file} (1)\n"
        "\n"
        "  COMMIT-MSG invalid commit format\n"
        f"   --> {msg_file}:1:1\n"
        "    |\n"
        "  1 | ✨ feat ab\n"
        "    | ^^^^^^^^^\n"
        "    |\n"
        "    = help: format: <emoji> <type>[!]: <description>\n"
        "            examples:\n"
        "              ✨ feat: add manifest variable resolution\n"
        "              🐛 fix: handle missing warehouse field\n"
        "              🔧 chore: add release workflow\n"
        "              📝 docs: add plan command usage\n"
        "              ♻️ refactor!: rename upload_packages signature\n"
        "              💾 save: core/manifest.py in progress [skip ci]\n"
        "\n"
        "Found 1 error in 1 file.\n"
    )
