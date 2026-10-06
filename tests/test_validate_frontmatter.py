#!/usr/bin/env python3
"""Tests for hygiene/hooks/validate_frontmatter.py — run with: uv run pytest tests -q"""

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

HOOK = setup.CORE_HOOKS_DIR / "validate_frontmatter.py"

_spec = importlib.util.spec_from_file_location("validate_frontmatter", HOOK)
vf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vf)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _skill(name: str = "foo", description: str = "does foo when asked") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\nbody\n"


class TestValidateFrontmatter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_root = vf.REPO_ROOT
        vf.REPO_ROOT = self.root

    def tearDown(self):
        vf.REPO_ROOT = self._orig_root
        self._tmp.cleanup()

    def _validate(self, skill_dir: str = "foo", content: str | None = None):
        path = self.root / f"plugins/pc-x/skills/{skill_dir}/SKILL.md"
        _write(path, content if content is not None else _skill())
        return vf.validate_file(path, "skill")

    # ── Socle commun ────────────────────────────────────────────────────────

    def test_valid_skill_passes(self):
        report = self._validate()
        self.assertEqual(report, [])

    def test_valid_agent_passes(self):
        _write(
            self.root / "plugins/pc-x/agents/bar.md",
            "---\nname: bar\ndescription: does bar\n---\n\nbody\n",
        )
        report = vf.validate_file(self.root / "plugins/pc-x/agents/bar.md", "agent")
        self.assertEqual(report, [])

    def test_missing_description_fails(self):
        report = self._validate(content="---\nname: foo\n---\n\nbody\n")
        self.assertTrue(any("description" in p.message for p in report))

    def test_no_frontmatter_fails(self):
        report = self._validate(content="# just a heading\n")
        self.assertTrue(any("no YAML frontmatter" in p.message for p in report))

    def test_fork_without_agent_field_fails(self):
        report = self._validate(
            content="---\nname: foo\ndescription: does foo\ncontext: fork\n---\n\nbody\n"
        )
        self.assertTrue(any("agent" in p.message for p in report))

    def test_fork_with_agent_field_passes(self):
        report = self._validate(
            content=(
                "---\nname: foo\ndescription: does foo when asked\ncontext: fork\n"
                "agent: general-purpose\n---\n\nbody\n"
            )
        )
        self.assertEqual(report, [])

    def test_legacy_commands_dir_is_hard_failure(self):
        _write(
            self.root / "plugins/pc-x/commands/deploy.md",
            "---\nname: deploy\n---\nbody\n",
        )
        self.assertEqual(
            vf.find_legacy_commands_dirs(), [self.root / "plugins/pc-x/commands"]
        )

    def test_find_skill_and_agent_files(self):
        _write(
            self.root / "plugins/pc-x/skills/foo/SKILL.md",
            "---\nname: foo\ndescription: d when\n---\n",
        )
        _write(
            self.root / "plugins/pc-x/agents/bar.md",
            "---\nname: bar\ndescription: d\n---\n",
        )
        self.assertEqual(len(vf.find_skill_files()), 1)
        self.assertEqual(len(vf.find_agent_files()), 1)

    # ── Forme du `name` — kebab-case, égal au répertoire de la skill ────────────────

    def test_name_with_underscore_fails(self):
        report = self._validate(content=_skill(name="debug_brief"))
        self.assertTrue(any("kebab-case" in p.message for p in report))

    def test_name_with_uppercase_fails(self):
        report = self._validate(content=_skill(name="DebugBrief"))
        self.assertTrue(any("kebab-case" in p.message for p in report))

    def test_name_with_space_fails(self):
        report = self._validate(content=_skill(name="debug brief"))
        self.assertTrue(any("kebab-case" in p.message for p in report))

    def test_skill_dir_not_kebab_fails(self):
        report = self._validate(skill_dir="debug_brief")
        self.assertTrue(any("kebab-case" in p.message for p in report))

    def test_name_differs_from_dir_fails(self):
        report = self._validate(skill_dir="bar", content=_skill(name="foo"))
        self.assertTrue(any("must equal" in p.message for p in report))

    def test_name_over_64_chars_fails(self):
        long_name = "a" * 65
        report = self._validate(content=_skill(name=long_name))
        self.assertTrue(any("64" in p.message for p in report))

    def test_name_of_exactly_64_chars_passes(self):
        long_name = "a" * 64
        report = self._validate(skill_dir=long_name, content=_skill(name=long_name))
        self.assertEqual(report, [])

    # ── Forme de la `description` ──────────────────────────────────────────────────

    def test_description_over_1024_chars_fails(self):
        report = self._validate(content=_skill(description="x" * 1025 + " when"))
        self.assertTrue(any("1024" in p.message for p in report))

    def test_description_of_exactly_1024_chars_passes(self):
        report = self._validate(content=_skill(description="x" * 1019 + " when"))
        self.assertEqual(report, [])

    def test_description_with_xml_tag_fails(self):
        report = self._validate(
            content=_skill(description="summarizes <url> when asked")
        )
        self.assertTrue(any("XML" in p.message for p in report))

    def test_description_with_closing_tag_fails(self):
        report = self._validate(
            content=_skill(description="tracks </agent> when asked")
        )
        self.assertTrue(any("XML" in p.message for p in report))

    # ── Forme du corps ──────────────────────────────────────────────────────────

    def test_body_at_500_lines_fails(self):
        body = "\n".join(f"line {i}" for i in range(500))
        report = self._validate(
            content=f"---\nname: foo\ndescription: does foo when asked\n---\n\n{body}\n"
        )
        self.assertTrue(any("500" in p.message for p in report))

    def test_body_under_500_lines_passes(self):
        body = "\n".join(f"line {i}" for i in range(498))
        report = self._validate(
            content=f"---\nname: foo\ndescription: does foo when asked\n---\n\n{body}\n"
        )
        self.assertEqual(report, [])

    # ── Références .md locales liées ─────────────────────────────────────────

    def test_broken_md_link_fails(self):
        report = self._validate(
            content=_skill() + "see [notes](references/missing.md)\n"
        )
        self.assertTrue(any("missing.md" in p.message for p in report))

    def test_external_md_link_ignored(self):
        report = self._validate(
            content=_skill() + "see [spec](https://example.com/spec.md)\n"
        )
        self.assertEqual(report, [])

    def test_long_reference_without_toc_fails(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(ref, "\n".join(f"line {i}" for i in range(101)) + "\n")
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertTrue(
            any("Contents" in p.message or "Sommaire" in p.message for p in report)
        )

    def test_long_reference_with_toc_passes(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(
            ref,
            "# Notes\n\n## Contents\n\n"
            + "\n".join(f"line {i}" for i in range(101))
            + "\n",
        )
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertEqual(report, [])

    def test_short_reference_without_toc_passes(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(ref, "\n".join(f"line {i}" for i in range(50)) + "\n")
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertEqual(report, [])

    def test_sommaire_counts_as_toc(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(
            ref,
            "# Notes\n\n## Sommaire\n\n"
            + "\n".join(f"line {i}" for i in range(101))
            + "\n",
        )
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertEqual(report, [])

    def test_reference_of_exactly_100_lines_without_toc_passes(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(ref, "\n".join(f"line {i}" for i in range(100)) + "\n")
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertEqual(report, [])

    def test_toc_at_line_40_passes(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(
            ref,
            "\n".join(f"line {i}" for i in range(39))
            + "\n## Contents\n"
            + "\n".join(f"line {i}" for i in range(70))
            + "\n",
        )
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertEqual(report, [])

    def test_toc_at_line_41_fails(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(
            ref,
            "\n".join(f"line {i}" for i in range(40))
            + "\n## Contents\n"
            + "\n".join(f"line {i}" for i in range(70))
            + "\n",
        )
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertTrue(
            any("Contents" in p.message or "Sommaire" in p.message for p in report)
        )

    def test_double_space_toc_heading_passes(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        _write(
            ref,
            "# Notes\n\n##  Contents\n\n"
            + "\n".join(f"line {i}" for i in range(101))
            + "\n",
        )
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertEqual(report, [])

    def test_non_utf8_reference_reports_clean_problem(self):
        ref = self.root / "plugins/pc-x/skills/foo/references/notes.md"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_bytes(b"# \xff\xfe notes\n" + b"line\n" * 120)
        report = self._validate(content=_skill() + "see [notes](references/notes.md)\n")
        self.assertTrue(any("UTF-8" in p.message for p in report))

    def test_orphan_md_next_to_skill_fails(self):
        _write(self.root / "plugins/pc-x/skills/foo/notes.md", "orphan\n")
        report = self._validate()
        self.assertTrue(any(p.path.endswith("notes.md") for p in report))

    def test_md_in_skill_dir_mentioned_in_body_passes(self):
        _write(self.root / "plugins/pc-x/skills/foo/notes.md", "mentioned\n")
        report = self._validate(content=_skill() + "read `notes.md` first\n")
        self.assertEqual(report, [])

    def test_md_in_subdirectory_not_linked_is_not_an_orphan(self):
        _write(self.root / "plugins/pc-x/skills/foo/references/notes.md", "nested\n")
        self.assertEqual(self._validate(), [])

    # ── Arguments et déclencheur — bloquants comme le reste ────────────────────

    def test_args_without_argument_hint_fails(self):
        report = self._validate(content=_skill() + "use $ARGUMENTS as the input\n")
        self.assertTrue(any("argument-hint" in p.message for p in report))

    def test_dollar_one_without_argument_hint_fails(self):
        report = self._validate(content=_skill() + "take $1 as the card path\n")
        self.assertTrue(any("argument-hint" in p.message for p in report))

    def test_arguments_directive_without_argument_hint_fails(self):
        report = self._validate(content=_skill() + "arguments:\n  - card\n")
        self.assertTrue(any("argument-hint" in p.message for p in report))

    def test_indented_arguments_directive_without_argument_hint_fails(self):
        report = self._validate(
            content=_skill() + "options:\n  arguments:\n    - card\n"
        )
        self.assertTrue(any("argument-hint" in p.message for p in report))

    def test_args_with_argument_hint_passes(self):
        report = self._validate(
            content=(
                "---\nname: foo\ndescription: does foo when asked\n"
                'argument-hint: "[card]"\n---\n\nuse $ARGUMENTS as the input\n'
            )
        )
        self.assertEqual(report, [])

    def test_description_without_trigger_fails(self):
        report = self._validate(content=_skill(description="does foo"))
        self.assertTrue(any("trigger" in (p.help or "") for p in report))

    def test_description_with_use_for_passes(self):
        report = self._validate(content=_skill(description="Use for foo work"))
        self.assertEqual(report, [])

    def test_description_trigger_pattern_variants_passes(self):
        for trigger in ("whenever", "before", "after", "TRIGGER"):
            with self.subTest(trigger=trigger):
                report = self._validate(
                    content=_skill(description=f"does foo {trigger} a card lands")
                )
                self.assertEqual(report, [])

    # ── main() — chaque trouvaille bloque et s'affiche groupée par fichier ───────────

    def _run_main(self) -> tuple[int, str]:
        with unittest.mock.patch.object(sys, "argv", [sys.argv[0]]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = vf.main()
        return code, out.getvalue()

    def test_main_blocks_on_a_missing_trigger(self):
        path = self.root / "plugins/pc-x/skills/foo/SKILL.md"
        _write(path, _skill(description="does foo"))
        code, out = self._run_main()
        self.assertEqual(code, 1)
        self.assertEqual(out, _EXPECTED_MISSING_TRIGGER.format(path=path))

    def test_main_is_silent_when_everything_passes(self):
        _write(self.root / "plugins/pc-x/skills/foo/SKILL.md", _skill())
        self.assertEqual(self._run_main(), (0, ""))


_EXPECTED_MISSING_TRIGGER = """{path} (1)

  FRONTMATTER `description` says what the skill does but not when to use it
   --> {path}:3:14
    |
  3 | description: does foo
    |              ^^^^^^^^
    |
    = help: add a trigger: when / before / after / Use for / TRIGGER

Found 1 error in 1 file.
"""


if __name__ == "__main__":
    unittest.main()
