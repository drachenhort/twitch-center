"""Addon entry point, referenced by addon.xml's library="lib/main.py"."""
import sys


def run(argv):
    """Route to the appropriate window based on saved auth state. Stubbed - routing
    logic (login vs. home) lands in a follow-up implementation plan."""
    raise NotImplementedError


if __name__ == "__main__":
    run(sys.argv)
