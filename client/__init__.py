"""
OpenScrum Client Package

Provides TUI client for interacting with the OpenScrum agent.
Lazy imports avoid RuntimeWarning when run as python -m client.tui.
"""

__all__ = ["OpenScrumApp", "main"]


def __getattr__(name: str):
    if name in ("OpenScrumApp", "main"):
        from .tui import OpenScrumApp, main
        return main if name == "main" else OpenScrumApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
