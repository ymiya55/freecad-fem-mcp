#!/usr/bin/env python3
"""Small, reviewable static security gate for the repository.

This is intentionally dependency-free so it can run before a virtual
environment is created.  It catches high-signal dangerous constructs and
accidental credential material; it is not a replacement for Bandit, CodeQL,
or a dedicated secret scanner.  The scanner never executes files it inspects.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str
    snippet: str


# Keep these patterns high signal.  The scanner itself is excluded below so
# the explanatory strings and regular expressions do not trigger themselves.
FORBIDDEN_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "python-eval-exec",
        re.compile(r"\b(?:eval|exec)\s*\("),
        "dynamic Python evaluation is forbidden",
    ),
    (
        "shell-true",
        re.compile(r"\bshell\s*=\s*True\b", re.IGNORECASE),
        "subprocess shell=True is forbidden",
    ),
    (
        "legacy-solver-import",
        re.compile(
            r"(?:\b(?:from|import)\s+femtools\.(?:ccxtools|solver)\b)"
            r"|\b(?:FemToolsCcx|CcxTools|makeSolverCalculiXCcxTools)\b"
            r"|\bFem::SolverCcxTools\b"
        ),
        "legacy CalculiX execution imports/symbols are forbidden; use the explicit solver adapter",
    ),
    (
        "non-loopback-bind",
        re.compile(
            r"(?:host|bind|address)\s*[:=]\s*[\"']\s*(?:0\.0\.0\.0|::|::0)\s*[\"']"
            r"|(?:listen|bind)\s*\(\s*(?:\(\s*)?[\"']\s*(?:0\.0\.0\.0|::|::0)",
            re.IGNORECASE,
        ),
        "network listeners must bind explicitly to loopback",
    ),
)

SECRET_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        "private key material must not be committed",
    ),
    (
        "aws-access-key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS access key material must not be committed",
    ),
    (
        "github-token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
        "GitHub token material must not be committed",
    ),
    (
        "slack-token",
        re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
        "Slack token material must not be committed",
    ),
    (
        "generic-secret-assignment",
        re.compile(
            r"\b(?:api[_-]?key|client[_-]?secret|password|secret|token)\s*"
            r"(?:=|:)\s*[\"'][^\"']{12,}[\"']",
            re.IGNORECASE,
        ),
        "credential-like literal must be supplied through environment/configuration",
    ),
)
SECRET_RULE_NAMES = frozenset(rule for rule, _, _ in SECRET_RULES)

TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".ps1",
    ".psm1",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".txt",
}
DEFAULT_IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def _normalise_line(line: str) -> str:
    # Full-line comments cannot execute a dangerous construct and are common
    # in security documentation.  Keep string literals and inline comments so
    # accidental command snippets still receive review.
    stripped = line.lstrip()
    return "" if stripped.startswith("#") else line


def iter_text_files(root: Path, ignored: Iterable[str] = ()) -> Iterable[Path]:
    ignored_parts = DEFAULT_IGNORED_PARTS | set(ignored)
    scanner = Path(__file__).resolve()
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.resolve() == scanner:
            continue
        if "tests" in path.parts and "security" in path.parts:
            # Adversarial tests intentionally contain forbidden examples.
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        yield path


def scan_file(path: Path, root: Path, max_bytes: int = 4 * 1024 * 1024) -> list[Finding]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [Finding(str(path.relative_to(root)), 0, "read-error", str(exc), "")]
    if len(raw) > max_bytes:
        return [Finding(str(path.relative_to(root)), 0, "file-too-large", f"file exceeds {max_bytes} bytes", "")]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []  # likely a binary asset with a text suffix; do not guess
    findings: list[Finding] = []
    relative = str(path.relative_to(root))
    for number, original in enumerate(text.splitlines(), start=1):
        line = _normalise_line(original)
        if not line:
            continue
        for rule, pattern, message in (*FORBIDDEN_RULES, *SECRET_RULES):
            if pattern.search(line):
                if rule == "generic-secret-assignment" and _is_placeholder_secret(line):
                    continue
                # Never echo a credential-shaped line into CI logs or JSON
                # artifacts.  Reviewers still get the file, line, and rule so
                # they can rotate/remove the material safely.
                snippet = "[redacted secret-like content]" if rule in SECRET_RULE_NAMES else original.strip()[:240]
                findings.append(Finding(relative, number, rule, message, snippet))
    return findings


def _is_placeholder_secret(line: str) -> bool:
    """Ignore unmistakable test/example values, never real credential shapes."""

    lowered = line.lower()
    return any(
        marker in lowered
        for marker in (
            "secret-token",
            "dummy-token",
            "example-token",
            "test-token",
            "changeme",
            "replace-me",
            "redacted",
        )
    )


def scan_repository(root: Path, ignored: Iterable[str] = ()) -> list[Finding]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"scan root does not exist or is not a directory: {root}")
    findings: list[Finding] = []
    for path in iter_text_files(root, ignored):
        findings.extend(scan_file(path, root))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="emit machine-readable findings")
    parser.add_argument("--ignore", action="append", default=[], help="directory name to ignore (repeatable)")
    parser.add_argument("--allow-findings", action="store_true", help="report findings but return success")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        findings = scan_repository(args.root, args.ignore)
    except ValueError as exc:
        print(f"security scan error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([asdict(item) for item in findings], indent=2))
    elif findings:
        for item in findings:
            print(f"{item.path}:{item.line}: [{item.rule}] {item.message}: {item.snippet}")
    else:
        print("security scan passed: no forbidden constructs or credential literals found")
    return 0 if not findings or args.allow_findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
