"""Storage layer for session, message, todo, permission, and project persistence (ref: opencode storage)."""

from server.storage.storage import Storage, get_storage, NotFoundError
from server.storage.todo import get_todos, update_todos
from server.storage.project import get_project, write_project, update_project, list_projects, set_initialized

# Memsearch integration (optional)
try:
    from server.storage.memsearch_adapter import MemSearchAdapter, get_memsearch_storage
    MEMSEARCH_ADAPTER_AVAILABLE = True
except ImportError:
    MEMSEARCH_ADAPTER_AVAILABLE = False
    MemSearchAdapter = None
    get_memsearch_storage = None

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
    "MemSearchAdapter",
    "get_memsearch_storage",
    "MEMSEARCH_ADAPTER_AVAILABLE",
]
