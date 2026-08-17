#!/usr/bin/env python3
"""Fail when Smallink's package and desktop version declarations drift."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package = json.loads((ROOT / "surfaces/gui/package.json").read_text())
    tauri = json.loads((ROOT / "surfaces/gui/src-tauri/tauri.conf.json").read_text())
    cargo = tomllib.loads((ROOT / "surfaces/gui/src-tauri/Cargo.toml").read_text())
    init_text = (ROOT / "smallink/__init__.py").read_text()
    license_text = (ROOT / "LICENSE").read_text()
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    license_match = re.search(r"Licensed Work:\s+Smallink\s+([^\s]+)", license_text)
    versions = {
        "pyproject": pyproject["project"]["version"],
        "python": match.group(1) if match else "",
        "npm": package["version"],
        "tauri": tauri["version"],
        "cargo": cargo["package"]["version"],
        "license": license_match.group(1) if license_match else "",
    }
    unique = set(versions.values())
    if len(unique) != 1 or "" in unique:
        print(json.dumps(versions, indent=2), file=sys.stderr)
        return 1
    print(next(iter(unique)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
