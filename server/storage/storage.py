"""
File-based storage layer.

Ref: opencode/packages/opencode/src/storage/storage.ts
- write(key, value), read(key), update(key, fn), list(prefix), remove(key)
- Keys are path segments; stored under data_dir as key[0]/key[1]/.../key[-1].json
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, List
from filelock import FileLock

# Default storage root: $OPENSCRUM_DATA/storage or ~/.openscrum/storage
_DATA_DIR = os.environ.get(
    "OPENSCRUM_DATA_DIR",
    os.path.join(os.path.expanduser("~"), ".openscrum"),
)
_STORAGE_DIR = os.path.join(_DATA_DIR, "storage")


class NotFoundError(Exception):
    """Raised when a storage key is not found."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _key_path(key: List[str], base_dir: str) -> str:
    """Return filesystem path for a key. Key segments joined with os.sep + .json."""
    return os.path.join(base_dir, *key) + ".json"


def _ensure_dir(path: str) -> None:
    """Ensure parent directory exists."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)


class Storage:
    """
    File-based storage with key = list of strings, value = JSON-serializable.
    Mirrors opencode Storage namespace.
    """

    def __init__(self, base_dir: str | None = None):
        self._dir = base_dir or _STORAGE_DIR
        _ensure_dir(self._dir)

    def _path(self, key: List[str]) -> str:
        return _key_path(key, self._dir)

    def write(self, key: List[str], value: Any) -> None:
        """Write value at key. Overwrites if exists. Uses file locking."""
        path = self._path(key)
        _ensure_dir(path)
        lock_path = path + ".lock"
        with FileLock(lock_path):
            with open(path, "w") as f:
                json.dump(value, f, indent=2)

    def read(self, key: List[str]) -> Any:
        """Read value at key. Raises NotFoundError if missing."""
        path = self._path(key)
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            raise NotFoundError(f"Resource not found: {path}")

    def update(self, key: List[str], editor: Callable[[Any], None]) -> Any:
        """Read, apply editor(draft), write back. Returns updated value. Atomic with lock."""
        path = self._path(key)
        _ensure_dir(path)
        lock_path = path + ".lock"
        
        with FileLock(lock_path):
            try:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        content = json.load(f)
                else:
                    content = {}
            except (FileNotFoundError, json.JSONDecodeError):
                 content = {}
            
            editor(content)
            
            with open(path, "w") as f:
                json.dump(content, f, indent=2)
                
        return content

    def remove(self, key: List[str]) -> None:
        """Remove key. No-op if not found. Atomic with lock."""
        path = self._path(key)
        lock_path = path + ".lock"
        with FileLock(lock_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def list(self, prefix: List[str]) -> List[List[str]]:
        """
        List keys under prefix. Returns list of full keys (path segments to each .json file).
        E.g. list(["message", "ses_1"]) -> [["message", "ses_1", "msg_1"], ...]
        """
        dir_path = os.path.join(self._dir, *prefix)
        if not os.path.isdir(dir_path):
            return []
        result: List[List[str]] = []
        for root, _dirs, files in os.walk(dir_path):
            rel = os.path.relpath(root, self._dir)
            if rel == ".":
                segments = []
            else:
                segments = rel.split(os.sep)
            for f in files:
                if f.endswith(".json"):
                    name = f[:-5]  # strip .json
                    # Full key = path from storage root to this file (segments + filename)
                    result.append(segments + [name])
        result.sort()
        return result


# Module-level default instance for session/message code
_default_storage: Storage | None = None


def get_storage(base_dir: str | None = None) -> Storage:
    """
    Return default storage instance; create with optional base_dir if not set.
    
    If OPENSCRUM_STORAGE_BACKEND=memsearch, returns MemSearchAdapter for semantic search.
    Otherwise returns standard file-based Storage.
    """
    global _default_storage
    if _default_storage is None:
        # Check if memsearch backend is requested
        backend = os.environ.get("OPENSCRUM_STORAGE_BACKEND", "file")
        
        if backend == "memsearch":
            try:
                from server.storage.memsearch_adapter import MemSearchAdapter
                _default_storage = MemSearchAdapter(base_dir=base_dir)
            except ImportError:
                import logging
                logging.warning(
                    "OPENSCRUM_STORAGE_BACKEND=memsearch but memsearch_adapter not available. "
                    "Using standard file storage. Install: pip install memsearch"
                )
                _default_storage = Storage(base_dir=base_dir)
        else:
            _default_storage = Storage(base_dir=base_dir)
    
    return _default_storage
