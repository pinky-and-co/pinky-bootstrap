#!/usr/bin/env python3
"""
PR Analyzer - Analyze PR complexity and suggest review approach.

Source: https://github.com/awesome-skills/code-review-skill/blob/main/scripts/pr-analyzer.py
Adapted for pinky workspace: YAML/resources files treated as pipeline config.

Usage:
    python pr-analyzer.py [--diff-file FILE] [--stats]

    Or pipe diff directly:
    git diff develop...HEAD | python tools/pr-analyzer.py --stats
"""

import os
import sys
import re
import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict

RISK_NO_TESTS = "NO_TEST_CHANGES"


@dataclass
class FileStats:
    filename: str
    additions: int = 0
    deletions: int = 0
    is_test: bool = False
    is_config: bool = False
    language: str = "unknown"


@dataclass
class PRAnalysis:
    total_files: int
    total_additions: int
    total_deletions: int
    files: List[FileStats]
    complexity_score: float
    size_category: str
    estimated_review_time: int
    risk_factors: List[str]
    suggestions: List[str]


def detect_language(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    extensions = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript/React",
        ".jsx": "JavaScript/React",
        ".rs": "Rust",
        ".go": "Go",
        ".java": "Java",
        ".kt": "Kotlin",
        ".swift": "Swift",
        ".rb": "Ruby",
        ".php": "PHP",
        ".cs": "C#",
        ".sql": "SQL",
        ".md": "Markdown",
        ".json": "JSON",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".toml": "TOML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".html": "HTML",
    }
    return extensions.get(ext.lower(), "unknown")


def is_test_file(filename: str) -> bool:
    test_patterns = [
        r"test_.*\.py$",
        r".*_test\.py$",
        r".*\.test\.(js|ts|tsx)$",
        r".*\.spec\.(js|ts|tsx)$",
        r"tests?/",
        r"__tests__/",
    ]
    return any(re.search(p, filename) for p in test_patterns)


def is_config_file(filename: str) -> bool:
    config_patterns = [
        r"\.env",
        r"config\.",
        r"\.json$",
        r"\.yaml$",
        r"\.yml$",
        r"\.toml$",
        r"package\.json$",
        r"tsconfig\.json$",
        r"resources/",
        r"manifest\.yml$",  # pinky: pipeline config
    ]
    return any(re.search(p, filename) for p in config_patterns)


def parse_diff(diff_content: str) -> List[FileStats]:
    files = []
    current_file = None

    for line in diff_content.split("\n"):
        if line.startswith("diff --git"):
            if current_file:
                files.append(current_file)
            match = re.match(r"diff --git a/(.+?) b/\1", line)
            if not match:
                match = re.search(r" b/(.+)$", line)
            if match:
                filename = match.group(1)
                current_file = FileStats(
                    filename=filename,
                    language=detect_language(filename),
                    is_test=is_test_file(filename),
                    is_config=is_config_file(filename),
                )
            else:
                current_file = None
        elif current_file:
            if line.startswith("+") and not line.startswith("+++"):
                current_file.additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                current_file.deletions += 1

    if current_file:
        files.append(current_file)

    return files


def calculate_complexity(files: List[FileStats]) -> float:
    if not files:
        return 0.0

    total_changes = sum(f.additions + f.deletions for f in files)
    size_factor = min(total_changes / 1000, 1.0)
    file_factor = min(len(files) / 20, 1.0)
    test_lines = sum(f.additions + f.deletions for f in files if f.is_test)
    non_test_ratio = 1 - (test_lines / max(total_changes, 1))
    languages = set(f.language for f in files if f.language != "unknown")
    lang_factor = min(len(languages) / 5, 1.0)

    complexity = (
        size_factor * 0.4 + file_factor * 0.2 + non_test_ratio * 0.2 + lang_factor * 0.2
    )
    return round(complexity, 2)


def categorize_size(total_changes: int) -> str:
    if total_changes < 50:
        return "XS (Extra Small)"
    elif total_changes < 200:
        return "S (Small)"
    elif total_changes < 400:
        return "M (Medium)"
    elif total_changes < 800:
        return "L (Large)"
    else:
        return "XL (Extra Large) - Consider splitting"


def estimate_review_time(files: List[FileStats], complexity: float) -> int:
    total_changes = sum(f.additions + f.deletions for f in files)
    base_time = total_changes / 20
    adjusted_time = base_time * (1 + complexity)
    return max(5, min(120, int(adjusted_time)))


def identify_risk_factors(files: List[FileStats]) -> List[str]:
    risks = []
    total_changes = sum(f.additions + f.deletions for f in files)
    test_changes = sum(f.additions + f.deletions for f in files if f.is_test)

    if total_changes > 400:
        risks.append("Large PR (>400 lines) - harder to review thoroughly")

    if test_changes == 0 and total_changes > 50:
        risks.append(f"{RISK_NO_TESTS}: No test changes - verify test coverage")

    if total_changes > 100 and test_changes / max(total_changes, 1) < 0.2:
        risks.append("Low test ratio (<20%) - consider adding more tests")

    security_patterns = [".env", "auth", "security", "password", "token", "secret"]
    for f in files:
        if any(p in f.filename.lower() for p in security_patterns):
            risks.append(f"Security-sensitive file: {f.filename}")
            break

    for f in files:
        if "migration" in f.filename.lower() or f.language == "SQL":
            risks.append("Database/migration changes detected - review carefully")
            break

    # pinky-specific: resources/ changes = pipeline config
    resource_files = [f for f in files if "resources/" in f.filename]
    if resource_files:
        risks.append(
            f"Pipeline config changes in {len(resource_files)} resource file(s) - verify manifest"
        )

    config_files = [f for f in files if f.is_config and "resources/" not in f.filename]
    if config_files:
        risks.append(f"Configuration changes in {len(config_files)} file(s)")

    return risks


def generate_suggestions(
    files: List[FileStats], complexity: float, risks: List[str]
) -> List[str]:
    suggestions = []
    total_changes = sum(f.additions + f.deletions for f in files)

    if total_changes > 800:
        suggestions.append("Consider splitting this PR into smaller, focused changes")

    if complexity > 0.7:
        suggestions.append("High complexity - allocate extra review time")

    if any(RISK_NO_TESTS in r for r in risks):
        suggestions.append("Request test additions before approval")

    if any("resource" in r.lower() for r in risks):
        suggestions.append("Run /yml_audit on changed resource files")

    if not suggestions:
        suggestions.append("Standard review process should suffice")

    return suggestions


def analyze_pr(diff_content: str) -> PRAnalysis:
    files = parse_diff(diff_content)
    total_additions = sum(f.additions for f in files)
    total_deletions = sum(f.deletions for f in files)
    total_changes = total_additions + total_deletions
    complexity = calculate_complexity(files)
    risks = identify_risk_factors(files)
    suggestions = generate_suggestions(files, complexity, risks)

    return PRAnalysis(
        total_files=len(files),
        total_additions=total_additions,
        total_deletions=total_deletions,
        files=files,
        complexity_score=complexity,
        size_category=categorize_size(total_changes),
        estimated_review_time=estimate_review_time(files, complexity),
        risk_factors=risks,
        suggestions=suggestions,
    )


def print_analysis(analysis: PRAnalysis, show_files: bool = False):
    print("\n" + "=" * 60)
    print("PR ANALYSIS REPORT")
    print("=" * 60)

    print("\n📊 SUMMARY")
    print(f"   Files changed: {analysis.total_files}")
    print(f"   Additions: +{analysis.total_additions}")
    print(f"   Deletions: -{analysis.total_deletions}")
    print(f"   Total changes: {analysis.total_additions + analysis.total_deletions}")

    print(f"\n📏 SIZE: {analysis.size_category}")
    print(f"   Complexity score: {analysis.complexity_score}/1.0")
    print(f"   Estimated review time: ~{analysis.estimated_review_time} minutes")

    if analysis.risk_factors:
        print("\n⚠️  RISK FACTORS:")
        for risk in analysis.risk_factors:
            print(f"   • {risk}")

    print("\n💡 SUGGESTIONS:")
    for suggestion in analysis.suggestions:
        print(f"   • {suggestion}")

    if show_files:
        print("\n📁 FILES:")
        by_lang: Dict[str, List[FileStats]] = defaultdict(list)
        for f in analysis.files:
            by_lang[f.language].append(f)

        for lang, lang_files in sorted(by_lang.items()):
            print(f"\n   [{lang}]")
            for f in lang_files:
                prefix = "🧪" if f.is_test else "⚙️" if f.is_config else "📄"
                print(f"   {prefix} {f.filename} (+{f.additions}/-{f.deletions})")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Analyze PR complexity")
    parser.add_argument("--diff-file", "-f", help="Path to diff file")
    parser.add_argument("--stats", "-s", action="store_true", help="Show file details")
    args = parser.parse_args()

    try:
        if args.diff_file:
            with open(args.diff_file, "r", encoding="utf-8", errors="replace") as f:
                diff_content = f.read()
        elif not sys.stdin.isatty():
            diff_content = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        else:
            print("Usage: git diff develop...HEAD | python tools/pr-analyzer.py")
            print("       python tools/pr-analyzer.py -f diff.txt")
            sys.exit(1)
    except OSError as e:
        print(f"Error reading diff input: {e}", file=sys.stderr)
        sys.exit(1)

    if not diff_content.strip():
        print("No diff content provided")
        sys.exit(1)

    analysis = analyze_pr(diff_content)
    print_analysis(analysis, show_files=args.stats)


if __name__ == "__main__":
    main()
