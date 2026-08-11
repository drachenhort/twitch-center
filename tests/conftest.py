"""Registers Kodi stub modules onto sys.path before any test imports lib.windows/lib.settings."""
import sys
from pathlib import Path

_KODI_STUBS_DIR = Path(__file__).resolve().parent / "kodi_stubs"
sys.path.insert(0, str(_KODI_STUBS_DIR))
