"""
Permission system: ruleset evaluation, tool authorization, user approval workflow.

Ref: opencode/packages/opencode/src/permission/index.ts, next.ts
- Rules: permission + pattern + action (allow | deny | ask)
- evaluate(permission, pattern, ruleset) -> allow/deny/ask
- ask(request) -> async: returns when allow, raises when deny, awaits user reply when ask
- reply(request_id, reply) -> resolve/reject pending, optionally add "always allow"
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Literal, Optional

from server.permission.wildcard import match as wildcard_match

try:
    from server.session.id_util import ascending
except ImportError:
    from session.id_util import ascending

Action = Literal["allow", "deny", "ask"]
Reply = Literal["once", "always", "reject"]


def _expand_pattern(pattern: str) -> str:
    """Expand ~ and $HOME in pattern (ref: PermissionNext.expand)."""
    if pattern.startswith("~/"):
        return os.path.expanduser("~") + pattern[1:]
    if pattern == "~":
        return os.path.expanduser("~")
    if pattern.startswith("$HOME/"):
        return os.path.expanduser("~") + pattern[5:]
    if pattern == "$HOME" or pattern.startswith("$HOME"):
        return os.path.expanduser("~") + pattern[5:]
    return pattern


class PermissionRule:
    """Single rule: permission name, pattern, action. Ref: PermissionNext.Rule."""

    def __init__(self, permission: str, pattern: str, action: Action):
        self.permission = permission
        self.pattern = pattern
        self.action = action

    def __repr__(self) -> str:
        return f"Rule({self.permission!r}, {self.pattern!r}, {self.action!r})"


class PermissionRequest:
    """Pending permission request. Ref: PermissionNext.Request."""

    def __init__(
        self,
        id: str,
        session_id: str,
        permission: str,
        patterns: list[str],
        metadata: dict[str, Any],
        always: list[str],
        tool: Optional[dict[str, str]] = None,
    ):
        self.id = id
        self.session_id = session_id
        self.permission = permission
        self.patterns = patterns
        self.metadata = metadata
        self.always = always
        self.tool = tool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "sessionID": self.session_id,
            "permission": self.permission,
            "patterns": self.patterns,
            "metadata": self.metadata,
            "always": self.always,
            "tool": self.tool,
        }


# --- Exceptions ---


class RejectedError(Exception):
    """User rejected without message - halts execution. Ref: PermissionNext.RejectedError."""

    def __init__(self, message: str = "The user rejected permission to use this specific tool call."):
        self.message = message
        super().__init__(message)


class CorrectedError(Exception):
    """User rejected with message - continues with guidance. Ref: PermissionNext.CorrectedError."""

    def __init__(self, message: str):
        self.feedback = message
        super().__init__(f"The user rejected with feedback: {message}")


class DeniedError(Exception):
    """Auto-rejected by config rule. Ref: PermissionNext.DeniedError."""

    def __init__(self, ruleset: list[PermissionRule], message: Optional[str] = None):
        self.ruleset = ruleset
        self._message = message or (
            f"Rule prevents this tool call. Relevant rules: {[r.__repr__() for r in ruleset]}"
        )
        super().__init__(self._message)


# --- Permission system ---


def merge_rulesets(*rulesets: list[PermissionRule]) -> list[PermissionRule]:
    """Merge multiple rulesets (ref: PermissionNext.merge)."""
    result: list[PermissionRule] = []
    for rs in rulesets:
        result.extend(rs)
    return result


def evaluate(
    permission: str,
    pattern: str,
    *rulesets: list[PermissionRule],
) -> PermissionRule:
    """
    Evaluate permission + pattern against merged rules.
    Last matching rule wins. Default: ask. Ref: PermissionNext.evaluate.
    """
    merged = merge_rulesets(*rulesets)
    pattern = _expand_pattern(pattern)
    match_rule: Optional[PermissionRule] = None
    for rule in merged:
        if wildcard_match(permission, rule.permission) and wildcard_match(pattern, rule.pattern):
            match_rule = rule
    if match_rule is not None:
        return match_rule
    return PermissionRule(permission=permission, pattern="*", action="ask")


def from_config(config: dict[str, Any]) -> list[PermissionRule]:
    """
    Build ruleset from config dict (ref: PermissionNext.fromConfig).
    Config: { "permission_name": "allow"|"deny"|"ask" } or
            { "permission_name": { "pattern": "allow"|"deny"|"ask", ... } }
    """
    rules: list[PermissionRule] = []
    for key, value in config.items():
        if isinstance(value, str):
            rules.append(PermissionRule(permission=key, pattern="*", action=value))
            continue
        if isinstance(value, dict):
            for pat, action in value.items():
                rules.append(
                    PermissionRule(permission=key, pattern=_expand_pattern(pat), action=action)
                )
    return rules


# Edit tools map to "edit" permission (ref: PermissionNext.EDIT_TOOLS)
EDIT_TOOLS = {"edit", "write", "patch", "multiedit", "apply_patch"}


def disabled_tools(tool_names: list[str], ruleset: list[PermissionRule]) -> set[str]:
    """Return set of tool names disabled by rules (ref: PermissionNext.disabled)."""
    result: set[str] = set()
    for tool in tool_names:
        permission = "edit" if tool in EDIT_TOOLS else tool
        for rule in reversed(ruleset):
            if wildcard_match(permission, rule.permission):
                if rule.pattern == "*" and rule.action == "deny":
                    result.add(tool)
                break
    return result


class PermissionSystem:
    """
    In-memory permission state: pending requests, approved rules.
    ask() awaits until user reply; reply() resolves/rejects.
    Approved rules can be persisted to storage. Ref: opencode Permission + PermissionNext.
    """

    PROJECT_ID = "default"

    def __init__(self, storage=None):
        self._pending: dict[str, dict] = {}  # request_id -> { info, resolve, reject }
        self._approved: list[PermissionRule] = []
        self._storage = storage
        self._project_id = self.PROJECT_ID
        self._load_approved()

    def _load_approved(self) -> None:
        """Load approved rules from storage if available."""
        if not self._storage:
            return
        try:
            raw = self._storage.read(["permission", self._project_id])
            if isinstance(raw, list):
                self._approved = [
                    PermissionRule(p["permission"], p["pattern"], p["action"])
                    for p in raw
                ]
        except Exception:
            pass

    def _save_approved(self) -> None:
        """Persist approved rules to storage."""
        if not self._storage:
            return
        try:
            self._storage.write(
                ["permission", self._project_id],
                [
                    {"permission": r.permission, "pattern": r.pattern, "action": r.action}
                    for r in self._approved
                ],
            )
        except Exception:
            pass

    def list_pending(self) -> list[dict]:
        """Return all pending permission requests (for API)."""
        return [v["info"].to_dict() for v in self._pending.values()]

    async def ask(
        self,
        session_id: str,
        permission: str,
        patterns: list[str],
        metadata: Optional[dict] = None,
        always: Optional[list[str]] = None,
        tool: Optional[dict[str, str]] = None,
        ruleset: Optional[list[PermissionRule]] = None,
        request_id: Optional[str] = None,
        on_pending: Optional[Callable[[dict], None]] = None,
    ) -> None:
        """
        Check permission. If rule says deny -> raise DeniedError.
        If rule says ask -> add to pending, call on_pending(request_info), then await until reply() is called.
        If rule says allow -> return.
        """
        import logging
        _log = logging.getLogger(__name__)
        ruleset = ruleset or []
        merged = merge_rulesets(ruleset, self._approved)
        metadata = metadata or {}
        always = always or []

        for pattern in patterns:
            rule = evaluate(permission, pattern, merged)
            if rule.action == "deny":
                raise DeniedError(
                    [r for r in ruleset if wildcard_match(permission, r.permission)]
                )
            if rule.action == "ask":
                rid = request_id or ascending("permission")
                req = PermissionRequest(
                    id=rid,
                    session_id=session_id,
                    permission=permission,
                    patterns=patterns,
                    metadata=metadata,
                    always=always,
                    tool=tool,
                )
                loop = asyncio.get_running_loop()
                future: asyncio.Future = loop.create_future()
                _log.info("permission future created: request_id=%s future_id=%s loop=%s", 
                         rid, id(future), id(loop))

                def resolve():
                    _log.info("permission resolve() called: request_id=%s future_done=%s", rid, future.done())
                    if not future.done():
                        try:
                            # Always use call_soon_threadsafe to ensure proper event loop scheduling
                            # This is critical because reply() is sync but called from async endpoint
                            loop.call_soon_threadsafe(future.set_result, None)
                            _log.info("permission future.set_result scheduled: request_id=%s", rid)
                        except Exception as e:
                            _log.exception("permission resolve() failed to schedule future: request_id=%s error=%s", rid, e)
                    else:
                        _log.warning("permission resolve() called but future already done: request_id=%s", rid)

                def reject(ex: BaseException):
                    _log.info("permission reject() called: request_id=%s exception=%s", rid, type(ex).__name__)
                    if not future.done():
                        try:
                            # Always use call_soon_threadsafe for proper event loop scheduling
                            loop.call_soon_threadsafe(future.set_exception, ex)
                            _log.info("permission future.set_exception scheduled: request_id=%s", rid)
                        except Exception as e:
                            _log.exception("permission reject() failed to schedule future: request_id=%s error=%s", rid, e)
                    else:
                        _log.warning("permission reject() called but future already done: request_id=%s", rid)

                self._pending[rid] = {"info": req, "resolve": resolve, "reject": reject}
                _log.info("permission request created: request_id=%s session_id=%s permission=%s patterns=%s pending_count=%d", 
                           rid, session_id, permission, patterns, len(self._pending))
                if on_pending is not None:
                    try:
                        on_pending(req.to_dict())
                        _log.info("permission on_pending callback invoked: request_id=%s", rid)
                    except Exception as e:
                        _log.exception("permission on_pending callback failed: %s", e)
                
                # Await the future - this will block until resolve() or reject() is called
                _log.info("permission awaiting future: request_id=%s future=%s done=%s", 
                         rid, id(future), future.done())
                try:
                    await future  # Simpler: just await the future directly
                    _log.info("permission future resolved successfully: request_id=%s", rid)
                except Exception as e:
                    _log.error("permission future raised exception: request_id=%s error=%s", rid, e)
                    self._pending.pop(rid, None)
                    raise
                
                # Clean up after successful resolution
                self._pending.pop(rid, None)
                _log.info("permission approved and cleaned up: request_id=%s remaining_pending=%d", 
                         rid, len(self._pending))
                return
        return

    def reply(
        self,
        request_id: str,
        reply: Reply,
        message: Optional[str] = None,
    ) -> None:
        """
        Handle user response to a pending request.
        once -> resolve and remove. always -> add to approved, resolve, auto-resolve matching.
        reject -> reject this (and optionally all for session).
        """
        import logging
        _log = logging.getLogger(__name__)
        pending = self._pending.get(request_id)
        if not pending:
            _log.warning(
                "permission reply for unknown request_id=%r (pending=%s). "
                "If using multiple server workers, run with one worker so the stream and reply share the same process.",
                request_id,
                list(self._pending.keys()),
            )
            return
        req = pending["info"]
        resolve_fn = pending["resolve"]
        reject_fn = pending["reject"]
        del self._pending[request_id]
        _log.info("permission reply received: request_id=%r reply=%s permission=%s patterns=%s session=%s", 
                   request_id, reply, req.permission, req.patterns, req.session_id)

        if reply == "reject":
            _log.info("permission rejecting: request_id=%s", request_id)
            reject_fn(
                CorrectedError(message) if message else RejectedError()
            )
            # Reject all other pending for same session
            rejected_count = 0
            for rid, p in list(self._pending.items()):
                if p["info"].session_id == req.session_id:
                    del self._pending[rid]
                    p["reject"](RejectedError())
                    rejected_count += 1
            if rejected_count > 0:
                _log.info("permission rejected %d other pending requests for session %s", 
                         rejected_count, req.session_id)
            return

        if reply == "once":
            _log.info("permission resolving future for request_id=%s", request_id)
            resolve_fn()
            _log.info("permission resolved once for request_id=%s", request_id)
            return

        if reply == "always":
            for pattern in req.always:
                self._approved.append(
                    PermissionRule(permission=req.permission, pattern=pattern, action="allow")
                )
            self._save_approved()
            _log.info("permission resolving future and saving rule for request_id=%s", request_id)
            resolve_fn()
            _log.info("permission resolved always for request_id=%s, checking other pending", request_id)
            # Auto-resolve other pending for same session that are now covered
            for rid, p in list(self._pending.items()):
                if p["info"].session_id != req.session_id:
                    continue
                ok = all(
                    evaluate(p["info"].permission, pat, self._approved).action == "allow"
                    for pat in p["info"].patterns
                )
                if not ok:
                    continue
                del self._pending[rid]
                p["resolve"]()
            return


# Module-level singleton for API
_system: Optional[PermissionSystem] = None


def get_permission_system(storage=None) -> PermissionSystem:
    global _system
    if _system is None:
        _system = PermissionSystem(storage=storage)
    return _system
