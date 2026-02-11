"""
Permission layer for tools: map tool name + args to permission/patterns, wrap tools to ask before run.

Ref: opencode tools call ctx.ask({ permission, patterns }) before executing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Lazy import to avoid circular dependency and optional permission module
def _get_permission_system():
    try:
        from server.permission import get_permission_system
        return get_permission_system()
    except ImportError:
        from permission import get_permission_system
        return get_permission_system()

def _permission_rule_from_dict(d: dict):
    try:
        from server.permission import PermissionRule
    except ImportError:
        from permission import PermissionRule
    return PermissionRule(
        permission=d.get("permission", "*"),
        pattern=d.get("pattern", "*"),
        action=d.get("action", "ask"),
    )


# Tool name -> permission name (opencode: read->read, edit/write/patch/multiedit->edit, bash->bash, etc.)
TOOL_PERMISSION: Dict[str, str] = {
    "read": "read",
    "write": "edit",
    "edit": "edit",
    "multiedit": "edit",
    "apply_patch": "edit",
    "grep": "grep",
    "glob": "glob",
    "list_files": "list",
    "ls": "list",
    "bash": "bash",
    "webfetch": "webfetch",
    "todowrite": "todowrite",
    "todoread": "todoread",
    "question": "question",
    "task": "task",
    "websearch": "websearch",
    "codesearch": "codesearch",
    "batch": "batch",  # batch delegates to other tools; we skip or use first sub-call
    "lsp": "lsp",
    "plan_exit": "plan",
    "plan_enter": "plan",
}


def _relative_path(path: str, workspace_root: str) -> str:
    """Return path relative to workspace for permission pattern."""
    p = Path(path).resolve()
    try:
        return str(p.relative_to(Path(workspace_root).resolve()))
    except ValueError:
        return path


def patterns_for_tool(tool_name: str, args: Dict[str, Any], workspace_root: str = "") -> List[str]:
    """
    Return permission patterns for a tool call (used for ask).
    Ref: opencode uses path.relative(worktree, filepath), command for bash, etc.
    """
    perm = TOOL_PERMISSION.get(tool_name, tool_name)
    if perm == "read":
        return [args.get("file_path", "*")]
    if perm == "edit":
        fp = args.get("file_path")
        if fp:
            return [_relative_path(fp, workspace_root)]
        # multiedit / apply_patch may have multiple paths
        if "edits" in args:
            return [_relative_path(e.get("file_path", "*"), workspace_root) for e in args["edits"] if e.get("file_path")]
        if "patch_text" in args:
            # Could parse patch for paths; default to *
            return ["*"]
        return ["*"]
    if perm == "write":
        return [_relative_path(args.get("file_path", "*"), workspace_root)]
    if perm == "grep":
        return [args.get("pattern", "*")]
    if perm == "glob":
        return [args.get("pattern", "*")]
    if perm == "list":
        return [args.get("path", ".") or "."]
    if perm == "bash":
        return [args.get("command", "*")]
    if perm == "webfetch":
        return [args.get("url", "*")]
    if perm in ("todowrite", "todoread", "question", "task", "plan_exit", "plan_enter"):
        return ["*"]
    if perm in ("websearch", "codesearch"):
        return [args.get("query", "*")]
    if perm == "batch":
        return ["*"]
    if perm == "lsp":
        return ["*"]
    return ["*"]


async def check_tool_permission(
    session_id: str,
    tool_name: str,
    args: Dict[str, Any],
    ruleset: List[Any],
    workspace_root: str = "",
    on_pending: Optional[Any] = None,
) -> None:
    """
    Run permission check for a tool. Raises if denied or rejected.
    When rule is "ask", calls on_pending(request_info) so the client can be notified, then awaits reply.
    No-op if permission module not available.
    """
    try:
        perm_system = _get_permission_system()
    except Exception:
        return
    permission = TOOL_PERMISSION.get(tool_name, tool_name)
    patterns = patterns_for_tool(tool_name, args, workspace_root)
    # Convert ruleset dicts to PermissionRule if needed
    rules = []
    for r in ruleset:
        if hasattr(r, "permission"):
            rules.append(r)
        elif isinstance(r, dict):
            rules.append(_permission_rule_from_dict(r))
    await perm_system.ask(
        session_id=session_id,
        permission=permission,
        patterns=patterns,
        metadata={"tool": tool_name, "args": {k: v for k, v in args.items()}},
        always=patterns,
        ruleset=rules,
        on_pending=on_pending,
    )


def wrap_tool_with_permission(tool: Any, workspace_root: str = "") -> Any:
    """
    Wrap a LangChain tool so it runs permission.ask() before invoking.
    Returns an async tool that: 1) gets context, 2) awaits permission.ask(), 3) runs original tool.
    """
    try:
        from server.tools.context import get_tool_context
    except ImportError:
        from tools.context import get_tool_context

    if not hasattr(tool, "invoke") or not hasattr(tool, "name"):
        return tool

    base_tool = tool
    name = getattr(base_tool, "name", None) or (getattr(base_tool, "func", None) and getattr(base_tool.func, "__name__", None)) or "unknown"

    async def _acall(*args: Any, **kwargs: Any) -> str:
        # LangChain may pass input as one dict or as kwargs
        if args and len(args) == 1 and isinstance(args[0], dict):
            input_dict = args[0]
        elif kwargs:
            input_dict = kwargs
        else:
            input_dict = {}
        ctx = get_tool_context()
        if ctx:
            session_id, workspace_root, ruleset = ctx[0], ctx[1], ctx[2]
            on_pending = ctx[3] if len(ctx) > 3 else None
            await check_tool_permission(
                session_id=session_id,
                tool_name=name,
                args=input_dict,
                ruleset=ruleset,
                workspace_root=workspace_root,
                on_pending=on_pending,
            )
        if asyncio.iscoroutinefunction(getattr(base_tool, "ainvoke", None)):
            return await base_tool.ainvoke(input_dict)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: base_tool.invoke(input_dict))

    from langchain_core.tools import StructuredTool

    new_tool = StructuredTool(
        name=name,
        description=base_tool.description or "",
        args_schema=getattr(base_tool, "args_schema", None),
        func=None,
        coroutine=_acall,
    )
    return new_tool
