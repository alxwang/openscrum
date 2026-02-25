"""
Todo list persistence per session.

Ref: opencode/packages/opencode/src/session/todo.ts
Storage key: ["todo", session_id] -> list of todo items.
"""

import logging
import re
from typing import Any, List

try:
    from server.storage.storage import Storage, get_storage, NotFoundError
    from server.workspace_log import append_workspace_log
except ImportError:
    from storage.storage import Storage, get_storage, NotFoundError
    try:
        from workspace_log import append_workspace_log
    except ImportError:
        def append_workspace_log(*args, **kwargs):
            return None


def get_todos(session_id: str, storage: Storage = None) -> List[dict]:
    """
    Load todo list for a session. Returns list of todo items (dicts with id, content, status, priority).
    """
    s = storage or get_storage()
    try:
        raw = s.read(["todo", session_id])
        return raw if isinstance(raw, list) else []
    except NotFoundError:
        return []


VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
VALID_PRIORITIES = {"high", "medium", "low"}

# Keep todo scope focused on implementation work. These patterns intentionally
# target design-document maintenance tasks rather than coding tasks.
NON_IMPLEMENTATION_PATTERNS = [
    re.compile(r"\b(update|edit|write|rewrite|sync|synchronize)\b.*\bdesign doc", re.IGNORECASE),
    re.compile(r"\b(update|edit|write|rewrite)\b.*\b(architecture|requirements|tech stack|user flow|api design|database design|functionalities)\b", re.IGNORECASE),
    re.compile(r"\b(architecture|requirements|tech_stack|user_flow|api_design|database_design|functionalities)\.md\b", re.IGNORECASE),
    re.compile(r"\bgap analysis\b", re.IGNORECASE),
    # Bootstrap/repo-init tasks should not appear as execution todos.
    re.compile(r"\bgit init\b", re.IGNORECASE),
    re.compile(r"\binitialize (the )?repository\b", re.IGNORECASE),
    re.compile(r"\bset up (the )?repository\b", re.IGNORECASE),
    re.compile(r"\bproject-wide configuration\b", re.IGNORECASE),
    re.compile(r"\b(readme|\.gitignore|license|ci skeleton)\b", re.IGNORECASE),
]

_log = logging.getLogger(__name__)


def _workspace_root_for_session(storage: Storage, session_id: str) -> str | None:
    """
    Resolve workspace root for a session so storage-layer todo filtering can
    emit detailed workspace log entries.
    """
    # Fast path: default project id currently used by session storage.
    try:
        raw = storage.read(["session", "default", session_id])
        workspace = str(raw.get("directory", "")).strip() if isinstance(raw, dict) else ""
        if workspace:
            return workspace
    except Exception:
        pass

    # Fallback: scan all projects for this session id.
    try:
        for key in storage.list(["session"]):
            if len(key) == 3 and key[2] == session_id:
                raw = storage.read(key)
                workspace = str(raw.get("directory", "")).strip() if isinstance(raw, dict) else ""
                if workspace:
                    return workspace
    except Exception:
        pass
    return None


def is_implementation_todo_content(content: str) -> bool:
    """Return True when todo content appears to be implementation-focused."""
    if not content or not content.strip():
        return False
    normalized = content.strip()
    for pattern in NON_IMPLEMENTATION_PATTERNS:
        if pattern.search(normalized):
            return False
    return True


def todo_rejection_reason(content: str) -> str | None:
    """Return a stable rejection reason for non-implementation todo content."""
    if not content or not content.strip():
        return "empty_content"
    normalized = content.strip()
    for pattern in NON_IMPLEMENTATION_PATTERNS:
        if pattern.search(normalized):
            return f"non_implementation_pattern:{pattern.pattern}"
    return None


def _normalize_todo_item(raw: dict, fallback_id: int) -> dict | None:
    """Normalize one todo item; return None when invalid or non-implementation."""
    if not isinstance(raw, dict):
        return None

    content = str(raw.get("content", "")).strip()
    if not is_implementation_todo_content(content):
        return None

    item_id = raw.get("id")
    if item_id is None or str(item_id).strip() == "":
        item_id = str(fallback_id)
    else:
        item_id = str(item_id).strip()

    status = str(raw.get("status", "pending")).strip().lower()
    if status not in VALID_STATUSES:
        status = "pending"

    priority = str(raw.get("priority", "medium")).strip().lower()
    if priority not in VALID_PRIORITIES:
        priority = "medium"

    return {
        "id": item_id,
        "content": content,
        "status": status,
        "priority": priority,
    }


def sanitize_todos(todos: List[dict], session_id: str | None = None) -> List[dict]:
    """Normalize todos and drop non-implementation entries."""
    if not isinstance(todos, list):
        return []

    sanitized: List[dict] = []
    next_id = 1
    for raw in todos:
        if not isinstance(raw, dict):
            _log.warning(
                "Filtered todo item for session %s: reason=invalid_item_type type=%s item=%r",
                session_id or "-",
                type(raw).__name__,
                raw,
            )
            continue
        content = str(raw.get("content", "")).strip()
        rejection_reason = todo_rejection_reason(content)
        if rejection_reason is not None:
            _log.warning(
                "Filtered todo item for session %s: reason=%s content=%r",
                session_id or "-",
                rejection_reason,
                content,
            )
            continue

        item = _normalize_todo_item(raw, fallback_id=next_id)
        if item is None:
            _log.warning(
                "Filtered todo item for session %s: reason=normalization_failed item=%r",
                session_id or "-",
                raw,
            )
            continue
        sanitized.append(item)
        # Keep fallback id monotonic for new items
        try:
            next_id = max(next_id + 1, int(item["id"]) + 1)
        except ValueError:
            next_id += 1
    return sanitized


def sanitize_todos_with_report(todos: List[dict], session_id: str | None = None) -> tuple[List[dict], List[dict]]:
    """Normalize todos, returning (sanitized, filtered_report)."""
    if not isinstance(todos, list):
        return [], [{
            "reason": "invalid_payload_type",
            "item_type": type(todos).__name__,
            "item": todos,
        }]

    sanitized: List[dict] = []
    filtered: List[dict] = []
    next_id = 1
    for raw in todos:
        if not isinstance(raw, dict):
            reason = "invalid_item_type"
            _log.warning(
                "Filtered todo item for session %s: reason=%s type=%s item=%r",
                session_id or "-",
                reason,
                type(raw).__name__,
                raw,
            )
            filtered.append({"reason": reason, "item_type": type(raw).__name__, "item": raw})
            continue

        content = str(raw.get("content", "")).strip()
        rejection_reason = todo_rejection_reason(content)
        if rejection_reason is not None:
            _log.warning(
                "Filtered todo item for session %s: reason=%s content=%r",
                session_id or "-",
                rejection_reason,
                content,
            )
            filtered.append({"reason": rejection_reason, "content": content, "item": raw})
            continue

        item = _normalize_todo_item(raw, fallback_id=next_id)
        if item is None:
            reason = "normalization_failed"
            _log.warning(
                "Filtered todo item for session %s: reason=%s item=%r",
                session_id or "-",
                reason,
                raw,
            )
            filtered.append({"reason": reason, "item": raw})
            continue

        sanitized.append(item)
        try:
            next_id = max(next_id + 1, int(item["id"]) + 1)
        except ValueError:
            next_id += 1
    return sanitized, filtered


def update_todos(session_id: str, todos: List[dict], storage: Storage = None) -> List[dict]:
    """
    Save todo list for a session.
    Each item should have: id, content, status (pending|in_progress|completed|cancelled), priority (high|medium|low).
    """
    s = storage or get_storage()
    sanitized, filtered = sanitize_todos_with_report(todos, session_id=session_id)
    s.write(["todo", session_id], sanitized)
    if filtered:
        workspace_root = _workspace_root_for_session(s, session_id)
        if workspace_root:
            for entry in filtered:
                append_workspace_log(
                    workspace_root,
                    "todo_filtered",
                    {
                        "session_id": session_id,
                        **entry,
                    },
                )
    return sanitized
