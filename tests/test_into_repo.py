"""--into <repo> — render a profile's full agent layer into a standalone POC repo.

Defines "done" for the chantier-0001 card `render-profile-into-repo`: a repo that lives on its
own carries its agent layer committed, with repo-relative links that survive `git clone` on a
non-author machine (no workspace/corpus paths baked in).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402


# ── repo-relative link resolution (the self-sufficiency primitive) ───────────


def test_resolve_agent_ref_local_when_bundled(tmp_path):
    (tmp_path / "AGENT_GITMOJI.md").write_text("# x", encoding="utf-8")
    ref = setup.resolve_agent_ref(
        "AGENT_GITMOJI.md", local_dir=tmp_path, link_base=".claude/knowledge"
    )
    assert ref == ".claude/knowledge/AGENT_GITMOJI.md"


def test_resolve_agent_ref_falls_back_to_corpus_when_not_bundled(tmp_path):
    # not present in local_dir → normal corpus resolution (workspace-relative). AGENT_BRANCH.md,
    # not AGENT_GITMOJI.md (relocated 2026-08-09 into core/skills/commit/ — no longer in the
    # corpus this falls back to, see tier-commande-non-mecanise).
    ref = setup.resolve_agent_ref(
        "AGENT_BRANCH.md", local_dir=tmp_path, link_base=".claude/knowledge"
    )
    assert ref is not None and not ref.startswith(".claude/knowledge")


def test_build_knowledge_index_link_base_is_repo_relative():
    # Profil incident (on teste la résolution de liens repo-relative, pas une valeur du profil) →
    # `example`, le seul profil public, pour tourner en CI sans le corpus privé.
    profile, ppath = setup.load_profile("example")
    idx = setup.build_knowledge_index(profile, ppath, link_base=".claude/knowledge")
    assert "(.claude/knowledge/AGENT_BRANCH.md)" in idx
    assert "pinky-workspace/" not in idx and "_corpus-pinky/" not in idx


# ── optional agent refs — profile capability vs framework guarantee ──────────


def test_optional_agent_ref_drops_its_line_when_unresolved():
    # Le bug 2026-07-20 : `commit.md` citait le privé-seul AGENT_NAMING.md via un token dur,
    # donc `--into` avec le seul profil public sortait en erreur. Un `{{agent?:…}}` absent
    # retire la mention entière, pas seulement le token (sinon « (e.g. ``) » reste).
    text = "garde-moi\nsi un agent de nommage existe (`{{agent?:AGENT_NOPE.md}}`), lis-le\nmoi aussi\n"
    assert setup._expand_agent_refs(text, context="t.md") == "garde-moi\nmoi aussi\n"


def test_optional_agent_ref_expands_like_a_required_one_when_resolved():
    out = setup._expand_agent_refs(
        "voir `{{agent?:AGENT_BRANCH.md}}`\n", context="t.md"
    )
    assert "AGENT_BRANCH.md" in out and "{{agent" not in out


def test_required_agent_ref_still_fails_the_build_when_unresolved():
    # Le garde-fou qui a attrapé le bug ci-dessus — l'optionnel ne doit pas l'affaiblir.
    with pytest.raises(SystemExit):
        setup._expand_agent_refs("`{{agent:AGENT_NOPE.md}}`\n", context="t.md")


# ── full install_into_repo integration ───────────────────────────────────────


def test_into_repo_is_self_sufficient(tmp_path):
    # La self-suffisance (liens repo-relative, zéro chemin corpus fuité, scaffolding présent) est
    # générique → `example` la couvre en CI. Seul l'agent asserté ci-dessous change :
    # un public (`AGENT_BRANCH.md`) au lieu du pluto-spécifique `AGENT_PLUTO_TARGET_ARCHITECTURE.md`.
    setup.install_into_repo("example", tmp_path)

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    # index links are repo-relative; no author-machine corpus paths leak into the index lines
    assert "(.claude/knowledge/AGENT_BRANCH.md)" in claude_md
    index_lines = [ln for ln in claude_md.splitlines() if ln.startswith("- [")]
    assert index_lines and all("_corpus-pinky/" not in ln for ln in index_lines)

    # knowledge agents are bundled in the repo
    bundled = {p.name for p in (tmp_path / ".claude" / "knowledge").glob("*.md")}
    assert {"AGENT_BRANCH.md"} <= bundled

    # scaffolding + permissions baseline are wired into the into-repo render. `example` carries
    # both permissions_allow AND permissions_deny (ADR-0063 — the reference demonstrates the full
    # enforcement preset, matching what the `pluto` org profile already ships in production for its
    # own non-author machine); the render mechanism itself is exhaustively covered, corpus-free, by
    # test_settings_render.py — this only proves the real profile file declares the baseline.
    assert (tmp_path / ".claude" / "skills" / "llm-council" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "rules" / "branch.md").exists()
    permissions = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )["permissions"]
    assert "Bash(git status:*)" in permissions["allow"]
    assert "Bash(ssh *)" in permissions["deny"]
    assert "Read(~/.ssh/**)" in permissions["deny"]


def test_into_repo_target_os_overrides_launcher(tmp_path, monkeypatch):
    # Loup audit 2026-07-04 : auteur Mac rendant --into pour une machine cible Windows (le
    # frère) — sans target_os, platform.system() lit la machine auteur et commet le mauvais
    # launcher. target_os doit se propager jusqu'à la commande de hook générée.
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    # Mécanisme launcher (générique) → profil public `example`.
    setup.install_into_repo("example", tmp_path, target_os="Windows")
    cmd = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert cmd.startswith("py -3 ")


def test_into_repo_reinstall_prunes_stale_agent(tmp_path):
    # Mécanisme de prune (générique) → profil public `example`.
    setup.install_into_repo("example", tmp_path)
    stale = tmp_path / ".claude" / "knowledge" / "AGENT_STALE.md"
    stale.write_text("# leftover from a previous profile", encoding="utf-8")
    setup.install_into_repo("example", tmp_path)
    assert not stale.exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
