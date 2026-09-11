#!/usr/bin/env python3
"""
check_snowpark_api.py — Enforce Snowpark/Core API usage conventions.

Three checks run on every Python file under src/:

1. session.sql() — Flag any .sql() method call.
   Use the Core API (snowflake.core) for DDL; session.table() or the
   DataFrame API for queries. Raw SQL belongs in stored procedures only.

2. SQL injection risk — Flag .sql() calls using string interpolation
   (f-strings, .format(), concatenation, % operator).
   Prefer params=[...] with ? placeholders for bindable values.
   For identifiers/fragments (table names, column names, SQL fragments)
   that cannot use ? binding, use the dedicated suppression comment.

3. Banned method aliases — Flag camelCase and non-canonical Snowpark names.
   Snowpark's camelCase aliases are deprecated in favour of snake_case.
   A few snake_case pairs also have a pinky-preferred canonical.

   Canonical choices that diverge from Snowflake's own "recommendation":
     sort / order_by  → sort    (Python-idiomatic for DataFrames)
                                 order_by NOT banned — used in Window specs
     except_ / minus  → minus  (no trailing underscore)

   Note: `sort` also matches Python list.sort() — acceptable false-positive
   rate in a Snowpark src/ context where sorted() is the idiomatic alternative.

Suppression comments (two independent levels):

  The marker is `# pinky:`, not `# noqa:` — `# noqa:` is owned by ruff/flake8
  (and `-- noqa:` by sqlfluff), which would parse SNOWPARK-* as an unknown code
  and warn. `# pinky:` is in no linter's namespace, so there is no collision.

  # pinky: SNOWPARK-API
    Suppresses: check 1 (generic .sql() usage)
    Does NOT suppress: check 2 (SQL injection)
    Use when: .sql() is required but the query is static (no interpolation).

  # pinky: SNOWPARK-SQL-INLINE
    Suppresses: check 2 (SQL injection risk)
    Does NOT suppress: check 1 (generic .sql() usage)
    Use when: string interpolation is unavoidable (identifiers, fragments
    that params= cannot bind). Always pair with a justification comment.

  Both on the same line:
    # pinky: SNOWPARK-API  # pinky: SNOWPARK-SQL-INLINE
    Suppresses both checks. Use sparingly — this is the maximum risk level.

Usage (pre-commit local hook):
  entry: python scripts/hooks/check_snowpark_api.py
  language: system
  types: [python]
  files: ^src/
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Receivers whose .sql() call is NOT a Snowpark session.sql() — skip them.
ALLOW_SQL_RECEIVERS: set[str] = {
    "pd",
    "pandas",
    "sqlalchemy",
    "sa",
    "text",
    "engine",
    "conn",
    "connection",
    "cursor",
    "metadata",
}

BANNED_METHODS: dict[str, str] = {
    # ── Column ───────────────────────────────────────────────────────────────
    "as_": "alias",
    "astype": "cast",  # SQL-native term
    "bitwiseAnd": "bitand",
    "bitwiseOR": "bitor",
    "bitwiseXOR": "bitxor",
    "eqNullSafe": "equal_null",
    "getField": "col[field] operator",  # deprecated getter → subscript
    "getItem": "col[field] operator",  # deprecated getter → subscript
    "getName": "get_name",
    # ── DataFrame ────────────────────────────────────────────────────────────
    "approxQuantile": "approx_quantile",
    "createOrReplaceView": "create_or_replace_view",
    "createOrReplaceTempView": "create_or_replace_temp_view",
    "createTempView": "create_temp_view",
    "crossJoin": "cross_join",
    "dropDuplicates": "drop_duplicates",
    "except_": "minus",
    "groupBy": "group_by",
    "orderBy": "sort",
    "printSchema": "print_schema",
    "randomSplit": "random_split",
    "sampleBy": "sample_by",
    "selectExpr": "select_expr",
    "subtract": "minus",
    "toDF": "to_df",
    "toLocalIterator": "to_local_iterator",
    "toPandas": "to_pandas",
    "unionAll": "union_all",
    "unionAllByName": "union_all_by_name",
    "unionByName": "union_by_name",
    "where": "filter",
    "withColumn": "with_column",
    "withColumnRenamed": "with_column_renamed",
}


def _receiver_repr(node: ast.expr) -> str:
    """Best-effort readable name for the receiver of a method call."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_receiver_repr(node.value)}.{node.attr}"
    return "<expr>"


def _receiver_root(node: ast.expr) -> str:
    """Extract the leftmost Name in a chained attribute access (a.b.c → a)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _receiver_root(node.value)
    return ""


def _canonical_msg(attr: str, canonical: str) -> str:
    """Suggestion line: ".astype() — use .cast() instead"; a canonical containing a space (an operator form) is shown verbatim."""
    if " " in canonical:
        return f".{attr}() — use the {canonical} instead"
    return f".{attr}() — use .{canonical}() instead"


def _has_params_kwarg(node: ast.Call) -> bool:
    """Check if the call has a `params=` keyword argument."""
    return any(kw.arg == "params" for kw in node.keywords)


def _is_dynamic_string(node: ast.expr) -> bool:
    """Detect f-strings, .format() calls, and string concatenation with variables."""
    # f-string (JoinedStr in AST)
    if isinstance(node, ast.JoinedStr):
        return True
    # "...".format(...)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        return True
    # "..." + variable  or  variable + "..."
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return True
    # "..." % (...)
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr

            if attr == "sql":
                root = _receiver_root(node.func.value)
                if root not in ALLOW_SQL_RECEIVERS:
                    receiver = _receiver_repr(node.func.value)
                    first_arg = node.args[0] if node.args else None
                    if first_arg and _is_dynamic_string(first_arg):
                        if _has_params_kwarg(node):
                            self.violations.append(
                                (
                                    node.lineno,
                                    f"{receiver}.sql() — SQL injection risk: "
                                    "uses string interpolation alongside params=. "
                                    "Use ? placeholders for all values",
                                )
                            )
                        else:
                            self.violations.append(
                                (
                                    node.lineno,
                                    f"{receiver}.sql() — SQL injection risk: "
                                    "use params=[...] with ? placeholders for values. "
                                    "For identifiers/fragments: "
                                    "# pinky: SNOWPARK-SQL-INLINE",
                                )
                            )
                    else:
                        self.violations.append(
                            (
                                node.lineno,
                                f"{receiver}.sql() — use Core API (snowflake.core) "
                                "for DDL or session.table() / DataFrame API for queries",
                            )
                        )

            elif attr in BANNED_METHODS:
                canonical = BANNED_METHODS[attr]
                self.violations.append(
                    (
                        node.lineno,
                        _canonical_msg(attr, canonical),
                    )
                )

        self.generic_visit(node)


def check_file(path: Path) -> list[tuple[int, str]]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return []
    lines = source.splitlines()

    def _suppressed(lineno: int, code: str = "") -> bool:
        line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if code == "SQL-INLINE":
            return "# pinky: SNOWPARK-SQL-INLINE" in line
        return "# pinky: SNOWPARK-API" in line

    visitor = _Visitor()
    visitor.visit(tree)
    results: list[tuple[int, str]] = []
    for ln, msg in visitor.violations:
        code = "SQL-INLINE" if "SQL injection" in msg else ""
        if not _suppressed(ln, code):
            results.append((ln, msg))
    return results


def _is_disabled() -> bool:
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    if _is_disabled():
        return 0
    failed = False
    for filepath in sys.argv[1:]:
        for line, reason in check_file(Path(filepath)):
            print(f"❌ [SNOWPARK-API] {filepath}:{line}: {reason}")
            failed = True
    if failed:
        print(
            "   💡 Prefer Core API over raw SQL. "
            "Canonical names: bitand/bitor/bitxor, alias, cast, "
            "equal_null, get_name, filter, sort, minus, "
            "group_by, drop_duplicates, with_column, to_pandas, "
            "union_all, union_by_name, union_all_by_name, …"
        )
        print("   🤖 Agents: AGENT_SNOWFLAKE_CORE_API.md · AGENT_SNOWFLAKE_SNOWPARK.md")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
