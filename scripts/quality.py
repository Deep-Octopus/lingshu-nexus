#!/usr/bin/env python3
"""Repository quality checks that can run before dependencies are installed."""

from __future__ import annotations

import argparse
import ast
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIRS = [
    ROOT / "backend" / "src",
    ROOT / "packages" / "lingshu-domain" / "src",
    ROOT / "scripts",
    ROOT / "tests",
]
SCAN_DIRS = [
    ROOT / "backend",
    ROOT / "packages",
    ROOT / "frontend",
    ROOT / "config",
    ROOT / "docs",
    ROOT / "scripts",
    ROOT / "tests",
]
SCAN_FILES = [
    ROOT / ".env.example",
    ROOT / ".gitignore",
    ROOT / "docker-compose.yml",
    ROOT / "Makefile",
    ROOT / "pyproject.toml",
    ROOT / "README.md",
]
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".ts",
    ".vue",
    ".css",
    ".html",
    ".sql",
}
SECRET_PATTERN = re.compile(r"(api[_-]?key|token|secret|password)", re.IGNORECASE)
PLACEHOLDER_PATTERN = re.compile(
    r"(replace-with|change-me|example\.invalid|localhost)",
    re.IGNORECASE,
)


def iter_files() -> Iterable[Path]:
    ignored_parts = {".venv", "node_modules", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
    for file_path in SCAN_FILES:
        if file_path.exists():
            yield file_path
    for directory in SCAN_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignored_parts for part in path.parts):
                continue
            yield path


def python_files() -> list[Path]:
    files: list[Path] = []
    for directory in PYTHON_DIRS:
        if directory.exists():
            files.extend(sorted(directory.rglob("*.py")))
    return files


def run_external(command: list[str]) -> bool:
    executable = command[0]
    if shutil.which(executable) is None:
        return False
    subprocess.run(command, cwd=ROOT, check=True)
    return True


def check_python_syntax() -> None:
    for path in python_files():
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))


def check_text_format() -> None:
    for path in iter_files():
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"Makefile"}:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                raise SystemExit(f"Trailing whitespace: {path.relative_to(ROOT)}:{line_number}")
        if text and not text.endswith("\n"):
            raise SystemExit(f"Missing final newline: {path.relative_to(ROOT)}")


def check_env_template() -> None:
    env_path = ROOT / ".env.example"
    if not env_path.exists():
        raise SystemExit(".env.example is missing")
    for line_number, line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if SECRET_PATTERN.search(key) and value and not PLACEHOLDER_PATTERN.search(value):
            raise SystemExit(f"Secret-like value must be a placeholder: .env.example:{line_number}")


def check_frontend_manifest() -> None:
    manifest_path = ROOT / "frontend" / "package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_scripts = {"dev", "build", "typecheck", "lint"}
    missing = required_scripts.difference(manifest.get("scripts", {}))
    if missing:
        raise SystemExit(f"frontend/package.json missing scripts: {sorted(missing)}")


def lint() -> None:
    targets = [str(path.relative_to(ROOT)) for path in PYTHON_DIRS if path.exists()]
    if not run_external(["ruff", "check", *targets]):
        check_python_syntax()
        check_text_format()
    check_env_template()
    check_frontend_manifest()


def format_check() -> None:
    targets = [str(path.relative_to(ROOT)) for path in PYTHON_DIRS if path.exists()]
    if not run_external(["ruff", "format", "--check", *targets]):
        check_text_format()


def typecheck() -> None:
    targets = [str(path.relative_to(ROOT)) for path in PYTHON_DIRS if path.exists()]
    if run_external(["mypy", *targets]):
        return
    for path in python_files():
        py_compile.compile(str(path), doraise=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["lint", "format-check", "typecheck"])
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    if args.command == "lint":
        lint()
    elif args.command == "format-check":
        format_check()
    elif args.command == "typecheck":
        typecheck()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
