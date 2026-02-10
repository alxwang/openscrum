"""
Todo list persistence per session.

Ref: opencode/packages/opencode/src/session/todo.ts
Storage key: ["todo", session_id] -> list of todo items.
"""

from typing import Any, List

try:
    from server.storage.storage import Storage, get_storage, NotFoundError
except ImportError:
    from storage.storage import Storage, get_storage, NotFoundError


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


def update_todos(session_id: str, todos: List[dict], storage: Storage = None) -> None:
    """
    Save todo list for a session.
    Each item should have: id, content, status (pending|in_progress|completed|cancelled), priority (high|medium|low).
    """
    s = storage or get_storage()
    s.write(["todo", session_id], todos)
