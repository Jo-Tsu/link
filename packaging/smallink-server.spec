# PyInstaller spec for the Smallink server sidecar (onedir).
#
# Built by packaging/build_dmg.sh: it freezes smallink-server into a standalone
# dist/smallink-server/ folder (executable + _internal/) that ships in the Tauri app's
# `resources` slot, so the desktop app needs no Python/venv at runtime.
#
# Design notes:
#   - Entry is packaging/entry_smallink_server.py (an absolute-import shim; run.py itself uses
#     relative imports and can't be a frozen __main__).
#   - collect_all() is used for third-party packages that carry data files, dynamic imports, or
#     importlib metadata that PyInstaller's static analysis misses (providers, mcp, ddgs, …).
#   - Built-in persona manifests (smallink/personas/builtin/*.md) are bundled as package data;
#     build_dmg.sh hard-checks ops.md is present in the frozen tree.
#   - Experimental connectors are excluded unless LINK_EXPERIMENTAL=1 (matches the release
#     builds, which must not ship use-at-your-own-risk connectors).

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Absolute repo root, independent of the cwd PyInstaller is invoked from. The `smallink`
# package is installed EDITABLE via a custom MetaPathFinder (__editable___…_finder.py), which
# PyInstaller's static analysis cannot follow — so we must point the graph at the real source
# tree here (SRC_ROOT on pathex), and also ship it as data (below) so no submodule can be
# silently dropped. SPECPATH is packaging/; the repo root is its parent.
SRC_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = []
binaries = []
hiddenimports = []

# Third-party packages that need their data/metadata/dynamic submodules collected wholesale.
for pkg in (
    "openai",
    "anthropic",
    "google",           # google-genai namespace package
    "mcp",
    "ddgs",
    "aisuite",
    "fake_useragent",   # ships a data/ json payload loaded at runtime
    "certifi",
    "croniter",
    "keyring",
    "pypdfium2",        # bundles the native libpdfium binary
    "pypdf",
    "docstring_parser",
    "uvicorn",          # dynamic protocol/loader imports
    "fastapi",
    "starlette",
    "pydantic",
    "tzdata",           # IANA tz DB (Windows has no system copy)
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        # A package that isn't installed in this environment simply contributes nothing.
        pass

# Our own package: pull in every submodule so lazily/dynamically imported ones
# (providers, tools, connectors) are frozen. collect_submodules needs the real source dir on
# sys.path (the editable finder hides it), so temporarily prepend SRC_ROOT.
import sys as _sys

_sys.path.insert(0, SRC_ROOT)
hiddenimports += collect_submodules("smallink")

# Belt-and-suspenders: ship the ENTIRE smallink (and link compat) source tree as data, so every
# .py module is physically present in the frozen app even if the graph missed one. This is what
# makes `import smallink.server` work at runtime despite the editable-install finder.
def _tree(pkg_dir):
    out = []
    root = os.path.join(SRC_ROOT, pkg_dir)
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for fn in files:
            if fn.endswith((".py", ".md")):
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(dirpath, SRC_ROOT)
                out.append((src, rel))
    return out

datas += _tree("smallink")
datas += _tree("link")

# uvicorn/websockets protocol implementations are selected by string at runtime.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
]

# Release builds must not ship experimental connectors; opt in with LINK_EXPERIMENTAL=1.
excludes = []
if not os.environ.get("LINK_EXPERIMENTAL"):
    excludes.append("smallink.connectors.experimental")

a = Analysis(
    ["entry_smallink_server.py"],
    pathex=[SRC_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="smallink-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="smallink-server",
)
