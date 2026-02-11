"""
Tool execution context: session_id, workspace_root, permission ruleset, and optional callback for permission requests.

Set before running the agent (e.g. in session message handler); tools read it
to call permission.ask() when the permission layer is enabled.
When a permission is pending, the optional on_permission_request callback is
invoked so the stream can emit a permission_request chunk to the client.
"""

from contextvars import ContextVar
from typing import Any, Callable, List, Optional, Tuple

# (session_id, workspace_root, ruleset, optional on_permission_request callback)
_tool_context: ContextVar[Optional[Tuple[str, str, List[Any], Optional[Callable[[dict], None]]]]] = ContextVar(
    "tool_context", default=None
)


def set_tool_context(
    session_id: str,
    workspace_root: str,
    ruleset: Optional[List[Any]] = None,
    on_permission_request: Optional[Callable[[dict], None]] = None,
) -> None:
    """Set current tool context (session_id, workspace_root, ruleset, optional callback). Call before invoking the agent."""
    _tool_context.set((session_id, workspace_root, ruleset or [], on_permission_request))


def get_tool_context() -> Optional[Tuple[str, str, List[Any], Optional[Callable[[dict], None]]]]:
    """Return (session_id, workspace_root, ruleset, on_permission_request) if set, else None."""
    return _tool_context.get()


def get_workspace_root_from_context() -> Optional[str]:
    """Return workspace_root from current tool context, or None if not set."""
    context = _tool_context.get()
    if context and len(context) >= 2:
        return context[1]
    return None


def clear_tool_context() -> None:
    """Clear tool context (e.g. after request)."""
    try:
        _tool_context.set(None)
    except LookupError:
        pass
