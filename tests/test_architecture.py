"""Statically enforces the project's core architectural boundary: lib/twitch/*,
lib/kick/*, and lib/providers.py must never import xbmc-family modules, since
they're meant to run outside Kodi."""
import ast
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
PROVIDER_DIRS = [LIB_DIR / "twitch", LIB_DIR / "kick"]
PROVIDER_FILES = [LIB_DIR / "providers.py"]


def _imported_module_names(py_file):
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _is_xbmc_family(name):
    # Every Kodi-provided module name (xbmc, xbmcgui, xbmcaddon, xbmcvfs,
    # xbmcplugin, xbmcdrm, ...) starts with "xbmc" - checking only "xbmc" and
    # "xbmc." would miss "xbmcgui"/"xbmcaddon" etc, which have no dot after
    # the prefix.
    return name == "xbmc" or name.startswith("xbmc")


def test_provider_packages_have_no_xbmc_imports():
    offenders = []
    for provider_dir in PROVIDER_DIRS:
        for py_file in provider_dir.glob("*.py"):
            for name in _imported_module_names(py_file):
                if _is_xbmc_family(name):
                    offenders.append(f"{py_file.relative_to(LIB_DIR)}: imports {name!r}")
    for py_file in PROVIDER_FILES:
        for name in _imported_module_names(py_file):
            if _is_xbmc_family(name):
                offenders.append(f"{py_file.relative_to(LIB_DIR)}: imports {name!r}")
    assert not offenders, (
        "lib/twitch/*, lib/kick/*, and lib/providers.py must not import "
        "xbmc-family modules:\n" + "\n".join(offenders)
    )
