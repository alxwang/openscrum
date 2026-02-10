"""Storage layer for session, message, todo, permission, and project persistence (ref: opencode storage)."""

from server.storage.storage import Storage, get_storage, NotFoundError
from server.storage.todo import get_todos, update_todos
from server.storage.project import get_project, write_project, update_project, list_projects, set_initialized

__all__ = [
    "Storage",
    "get_storage",
    "NotFoundError",
    "get_todos",
    "update_todos",
    "get_project",
    "write_project",
    "update_project",
    "list_projects",
    "set_initialized",
]
