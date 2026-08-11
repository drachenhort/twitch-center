"""Statically enforces the project's core architectural boundary: lib/twitch/*
must never import xbmc-family modules, since it's meant to run outside Kodi."""
import ast
from pathlib import Path

TWITCH_DIR = Path(__file__).resolve().parent.parent / "lib" / "twitch"


def _imported_module_names(py_file):
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_lib_twitch_has_no_xbmc_imports():
    offenders = []
    for py_file in TWITCH_DIR.glob("*.py"):
        for name in _imported_module_names(py_file):
            if name == "xbmc" or name.startswith("xbmc."):
                offenders.append(f"{py_file.name}: imports {name!r}")
    assert not offenders, "lib/twitch/* must not import xbmc-family modules:\n" + "\n".join(offenders)
