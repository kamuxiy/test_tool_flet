#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bump semantic version in core/config.py and print the new version."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "core" / "config.py"
_VERSION_RE = re.compile(
    r'^(__version__\s*=\s*")(\d+)\.(\d+)\.(\d+)(")',
    re.MULTILINE,
)


def read_version(text: str) -> tuple[int, int, int]:
    m = _VERSION_RE.search(text)
    if not m:
        raise SystemExit(f"__version__ not found in {CONFIG}")
    return int(m.group(2)), int(m.group(3)), int(m.group(4))


def bump(parts: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = parts
    if kind == "major":
        return major + 1, 0, 0
    if kind == "minor":
        return major, minor + 1, 0
    if kind == "patch":
        return major, minor, patch + 1
    raise SystemExit(f"unknown bump kind: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "kind",
        nargs="?",
        default="patch",
        choices=("patch", "minor", "major"),
        help="which semver component to increment (default: patch)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print next version without writing the file",
    )
    args = parser.parse_args()

    text = CONFIG.read_text(encoding="utf-8")
    old = read_version(text)
    new = bump(old, args.kind)
    old_s = ".".join(map(str, old))
    new_s = ".".join(map(str, new))

    if args.dry_run:
        print(new_s)
        return 0

    new_text, n = _VERSION_RE.subn(
        rf'\g<1>{new[0]}.{new[1]}.{new[2]}\g<5>',
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit("failed to rewrite __version__")
    CONFIG.write_text(new_text, encoding="utf-8")
    print(new_s, file=sys.stderr)
    print(new_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
