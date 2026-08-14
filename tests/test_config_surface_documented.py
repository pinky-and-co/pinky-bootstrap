"""Cliquet — toute surface de configuration lue par le code est documentée.

`docs/reference/configuration.md` est la seule page qui énumère les variables d'environnement : rien
d'autre ne les liste, donc rien d'autre ne signale qu'il en manque une. Les clés de
`.pinky/config.txt`, elles, sont documentées deux fois par construction (le template livré commenté,
et la page) — et c'est exactement là que la dérive s'est produite : le how-to d'install en listait 6
sur 8 le jour où les deux dernières ont été ajoutées, dans la même session.

D'où un cliquet et pas une relecture : une doc exhaustive ne le reste pas parce que quelqu'un y
pense. La liste attendue est **dérivée du code** (le template pour les clés, l'AST pour les variables
d'env), jamais recopiée ici — une liste en dur dans le test serait une troisième copie à maintenir,
et le test passerait au vert en ratant précisément ce qu'il surveille.

L'AST plutôt qu'un grep, parce que le grep a échoué pour de vrai en écrivant cette page :
`ruff format` coupe `os.environ.get(\\n    "DEFAULT_PROFILE"\\n)` sur trois lignes, et un motif
`environ\\.get\\("[A-Z_]+"` en rate cinq sur dix-neuf sans rien dire.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import common  # noqa: E402

ROOT = Path(__file__).parent.parent
DOC = ROOT / "docs" / "reference" / "configuration.md"

# Les fichiers dont la config est celle du MOTEUR. `tests/` est exclu : une variable posée par un
# monkeypatch de test n'est pas une surface offerte à l'utilisateur.
SOURCES = [
    *(ROOT / "setup").rglob("*.py"),
    *(ROOT / "core").rglob("*.py"),
    ROOT / "cli_pinky.py",
]


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, so `environ.get(CORPUS_ROOT_ENV)` resolves."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            out[node.targets[0].id] = node.value.value
    return out


def env_vars_read_by_the_engine() -> set[str]:
    """Every env var name reaching `os.environ.get` / `os.getenv`, literal or via a constant."""
    found: set[str] = set()
    for path in SOURCES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        consts = _string_constants(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                continue
            target = node.func.value
            is_environ = (
                isinstance(target, ast.Attribute)
                and target.attr == "environ"
                and node.func.attr in ("get", "setdefault")
            )
            is_getenv = (
                isinstance(target, ast.Name)
                and target.id == "os"
                and node.func.attr == "getenv"
            )
            if not (is_environ or is_getenv) or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in consts:
                found.add(consts[arg.id])
    return found


def config_keys_in_the_template() -> set[str]:
    """The keys `pinky init-workspace` ships, read off the shipped template itself."""
    return set(re.findall(r"^# ([a-z_]+) =\s*$", common._CONFIG_TEMPLATE, re.M))


def test_the_reference_page_exists():
    assert DOC.is_file(), f"{DOC} — la page de reference est la cible de ce cliquet"


def test_every_env_var_read_by_the_engine_is_documented():
    """Une variable lue et non documentée est une surface invisible : personne ne peut la trouver."""
    text = DOC.read_text(encoding="utf-8")
    missing = sorted(v for v in env_vars_read_by_the_engine() if f"`{v}`" not in text)

    assert not missing, (
        f"variable(s) d'environnement lues par le code et absentes de {DOC.name} : "
        f"{', '.join(missing)}.\n"
        "→ Ajouter une ligne dans la section « Environment variables », y compris pour une variable "
        "que l'utilisateur ne doit PAS poser lui-même (elle a sa propre sous-section) : ce cliquet "
        "documente la surface, il n'arbitre pas qui l'écrit."
    )


def test_every_shipped_config_key_is_documented():
    """Le défaut réellement constaté : 2 clés ajoutées, la doc en listait 6 sur 8 le même jour."""
    text = DOC.read_text(encoding="utf-8")
    keys = config_keys_in_the_template()
    assert keys, "extraction cassée — le template ne rend aucune clé"
    missing = sorted(k for k in keys if f"`{k}`" not in text)

    assert not missing, (
        f"clé(s) de .pinky/config.txt absentes de {DOC.name} : {', '.join(missing)}"
    )


def test_the_install_how_to_lists_the_same_keys():
    """La seconde copie, celle qui a dérivé. Le how-to garde un tableau court par choix Diátaxis —
    court ne veut pas dire incomplet, et rien ne le disait avant ce test.
    """
    how_to = ROOT / "docs" / "how-to" / "installer-le-moteur.md"
    text = how_to.read_text(encoding="utf-8")
    missing = sorted(k for k in config_keys_in_the_template() if f"`{k}`" not in text)

    assert not missing, f"clé(s) absentes de {how_to.name} : {', '.join(missing)}"


def test_the_extraction_itself_is_not_silently_empty():
    """Un cliquet dont la source se tarit passe au vert en ne surveillant plus rien.

    Les deux extracteurs sont dérivés du code, donc un refactor peut les faire rendre l'ensemble
    vide — et les tests ci-dessus deviendraient des tautologies sans que rien n'échoue. Deux
    sentinelles connues suffisent à le détecter.
    """
    env = env_vars_read_by_the_engine()
    assert "CORPUS_ROOT" in env, "résolution par constante cassée (CORPUS_ROOT_ENV)"
    assert "MACHINE_CAPABILITIES" in env, "résolution par littéral cassée"
    assert len(env) >= 15, (
        f"seulement {len(env)} variables trouvées — extraction suspecte"
    )
    assert len(config_keys_in_the_template()) >= 8


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
