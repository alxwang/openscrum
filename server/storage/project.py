"""
Project metadata persistence.

Ref: opencode/packages/opencode/src/project/project.ts
Storage key: ["project", project_id] -> project info (id, worktree, vcs, time, ...).
"""

from typing import Any, Callable, List, Optional

try:
    from server.storage.storage import Storage, get_storage, NotFoundError
except ImportError:
    from storage.storage import Storage, get_storage, NotFoundError


def get_project(project_id: str, storage: Storage = None) -> Optional[dict]:
    """Load project metadata by id. Returns None if not found."""
    s = storage or get_storage()
    try:
        return s.read(["project", project_id])
    except NotFoundError:
        return None


def write_project(project_id: str, info: dict, storage: Storage = None) -> None:
    """Save project metadata. Info should include at least id, worktree, and optionally vcs, time."""
    s = storage or get_storage()
    s.write(["project", project_id], info)


def update_project(project_id: str, editor: Callable[[dict], None], storage: Storage = None) -> dict:
    """Update project with editor(draft). Creates empty dict if missing. Returns updated value."""
    s = storage or get_storage()
    try:
        content = s.read(["project", project_id])
    except NotFoundError:
        content = {}
    editor(content)
    s.write(["project", project_id], content)
    return content


def set_initialized(project_id: str, storage: Storage = None) -> None:
    """Mark project as initialized (e.g. after /init command). Ref: opencode Project.setInitialized."""
    import time
    def _set(d: dict) -> None:
        d.setdefault("time", {})["initialized"] = int(time.time() * 1000)
    update_project(project_id, _set, storage=storage)


def list_projects(storage: Storage = None) -> List[dict]:
    """List all stored projects."""
    s = storage or get_storage()
    result = []
    for key in s.list(["project"]):
        if len(key) >= 2:
            try:
                result.append(s.read(key))
            except NotFoundError:
                pass
    return result
