"""
Session lifecycle and message history (ref: opencode session/index.ts).

- SessionInfo: id, slug, project_id, directory (workspace_root), parent_id, title, version, time
- create, get, update, fork, touch, list, children, remove
- messages, update_message, remove_message, update_part, remove_part
"""

import os
import time
from typing import Any, Callable, Iterator, List, Optional

from server.storage.storage import Storage, get_storage, NotFoundError
from server.session.id_util import descending, ascending, validate_session_id, validate_message_id
from server.session.status import SessionStatus
from server.session.message import MessageInfo, MessagePart, message_from_dict, message_to_dict

# Default project when no project/instance is set (opencode uses Instance.project.id)
DEFAULT_PROJECT_ID = "default"
VERSION = "0.1.0"

# Slug for human-readable session ref (opencode: Slug.create())
def _make_slug() -> str:
    import secrets
    return secrets.token_urlsafe(8)


class SessionInfo(dict):
    """Session metadata (ref: Session.Info in opencode). Mutable dict for update() editor."""

    @property
    def id(self) -> str:
        return self["id"]

    @property
    def slug(self) -> str:
        return self["slug"]

    @property
    def project_id(self) -> str:
        return self["project_id"]

    @property
    def directory(self) -> str:
        return self["directory"]

    @property
    def workspace_root(self) -> str:
        return self["directory"]

    @property
    def parent_id(self) -> Optional[str]:
        return self.get("parent_id")

    @property
    def title(self) -> str:
        return self["title"]

    @property
    def version(self) -> str:
        return self.get("version", VERSION)

    @property
    def time(self) -> dict:
        return self["time"]

    @property
    def created_at(self) -> int:
        return self["time"]["created"]

    @property
    def updated_at(self) -> int:
        return self["time"]["updated"]


def _session_info(raw: dict) -> SessionInfo:
    return SessionInfo(raw)


class BusyError(Exception):
    """Raised when an operation requires the session to be idle but it is busy."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session {session_id} is busy")


class Session:
    """Session CRUD and message history. Ref: opencode Session namespace."""

    def __init__(self, storage: Optional[Storage] = None):
        self._storage = storage or get_storage()

    @staticmethod
    def _default_title(is_child: bool = False) -> str:
        prefix = "Child session - " if is_child else "New session - "
        return prefix + time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

    @staticmethod
    def _forked_title(title: str) -> str:
        if title.endswith(")"):
            import re
            m = re.match(r"^(.+) \(fork #(\d+)\)$", title)
            if m:
                base, num = m.group(1), int(m.group(2))
                return f"{base} (fork #{num + 1})"
        return f"{title} (fork #1)"

    def create(
        self,
        *,
        directory: str,
        parent_id: Optional[str] = None,
        title: Optional[str] = None,
        permission: Optional[dict] = None,
        id: Optional[str] = None,
    ) -> SessionInfo:
        """Create a new session. Ref: Session.createNext."""
        now = int(time.time() * 1000)
        sid = id or descending("session")
        info = {
            "id": sid,
            "slug": _make_slug(),
            "version": VERSION,
            "project_id": DEFAULT_PROJECT_ID,
            "directory": directory,
            "parent_id": parent_id,
            "title": title or self._default_title(bool(parent_id)),
            "permission": permission,
            "time": {"created": now, "updated": now},
        }
        key = ["session", DEFAULT_PROJECT_ID, sid]
        self._storage.write(key, info)
        return _session_info(info)

    def get(self, session_id: str) -> SessionInfo:
        """Load session by id. Raises NotFoundError if missing."""
        if not validate_session_id(session_id):
            raise ValueError(f"Invalid session id: {session_id}")
        key = ["session", DEFAULT_PROJECT_ID, session_id]
        raw = self._storage.read(key)
        return _session_info(raw)

    def update(
        self,
        session_id: str,
        editor: Callable[[dict], None],
        *,
        touch: bool = True,
    ) -> SessionInfo:
        """Update session with editor(draft). Optionally skip touching updated_at."""
        session = self.get(session_id)
        draft = dict(session)
        editor(draft)
        if touch:
            draft["time"] = dict(draft["time"])
            draft["time"]["updated"] = int(time.time() * 1000)
        key = ["session", DEFAULT_PROJECT_ID, session_id]
        self._storage.write(key, draft)
        return _session_info(draft)

    def touch(self, session_id: str) -> None:
        """Update session's updated_at timestamp."""
        self.update(session_id, lambda d: None)

    def list(
        self,
        *,
        directory: Optional[str] = None,
        roots_only: bool = False,
        start: Optional[int] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[SessionInfo]:
        """List sessions (ref: Session.list)."""
        prefix = ["session", DEFAULT_PROJECT_ID]
        keys = self._storage.list(prefix)
        sessions: List[SessionInfo] = []
        for k in keys:
            if len(k) != 3:
                continue
            try:
                raw = self._storage.read(k)
            except NotFoundError:
                continue
            if directory is not None and raw.get("directory") != directory:
                continue
            if roots_only and raw.get("parent_id"):
                continue
            if start is not None and raw.get("time", {}).get("updated", 0) < start:
                continue
            if search is not None and search.lower() not in (raw.get("title") or "").lower():
                continue
            sessions.append(_session_info(raw))
        sessions.sort(key=lambda s: s["time"]["updated"], reverse=True)
        if limit is not None:
            sessions = sessions[:limit]
        for s in sessions:
            yield s

    def children(self, parent_id: str) -> List[SessionInfo]:
        """Return child sessions of parent. Ref: Session.children."""
        result = []
        for s in self.list():
            if s.get("parent_id") == parent_id:
                result.append(s)
        return result

    def remove(self, session_id: str) -> None:
        """Delete session and all its messages/parts. Ref: Session.remove."""
        session = self.get(session_id)
        for child in self.children(session_id):
            self.remove(child["id"])
        msg_prefix = ["message", session_id]
        for key in self._storage.list(msg_prefix):
            # key = ["message", session_id, message_id]
            if len(key) >= 3:
                msg_id = key[-1]
                for part_key in self._storage.list(["part", msg_id]):
                    self._storage.remove(part_key)
            self._storage.remove(key)
        self._storage.remove(["session", DEFAULT_PROJECT_ID, session_id])
        SessionStatus.set(session_id, {"type": "idle"})

    def fork(
        self,
        session_id: str,
        message_id: Optional[str] = None,
    ) -> SessionInfo:
        """Fork session at optional message; copy messages (and parts) into new session. Ref: Session.fork."""
        original = self.get(session_id)
        title = self._forked_title(original["title"])
        new_session = self.create(directory=original["directory"], title=title)
        id_map: dict[str, str] = {}
        for msg_with_parts in self.messages(session_id=session_id):
            msg_info = msg_with_parts["info"]
            mid = msg_info["id"] if isinstance(msg_info, dict) else msg_info.id
            if message_id and mid >= message_id:
                break
            new_mid = ascending("message")
            id_map[mid] = new_mid
            new_info = dict(msg_info) if isinstance(msg_info, dict) else msg_info.model_dump()
            new_info["session_id"] = new_session["id"]
            new_info["id"] = new_mid
            if new_info.get("role") == "assistant" and new_info.get("parent_id"):
                new_info["parent_id"] = id_map.get(new_info["parent_id"], new_info["parent_id"])
            self.update_message(new_info)
            for part in msg_with_parts["parts"]:
                p = dict(part) if isinstance(part, dict) else part.model_dump()
                p["id"] = ascending("part")
                p["message_id"] = new_mid
                p["session_id"] = new_session["id"]
                self.update_part(p)
        return new_session

    def messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Return messages with parts, newest first. Ref: Session.messages."""
        result = []
        prefix = ["message", session_id]
        keys = self._storage.list(prefix)
        msg_ids = [k[-1] for k in keys if len(k) == 3]
        msg_ids.sort(reverse=True)
        if limit:
            msg_ids = msg_ids[:limit]
        for mid in msg_ids:
            try:
                raw = self._storage.read(["message", session_id, mid])
            except NotFoundError:
                continue
            info = message_from_dict(raw) if isinstance(raw, dict) and raw else raw
            info_dict = info if isinstance(info, dict) else info.model_dump()
            parts = []
            for pk in self._storage.list(["part", mid]):
                if len(pk) == 3:
                    try:
                        parts.append(self._storage.read(pk))
                    except NotFoundError:
                        pass
            parts.sort(key=lambda p: p.get("id", ""))
            result.append({"info": info_dict, "parts": parts})
        return result

    def update_message(self, msg: dict | MessageInfo) -> dict:
        """Write message to storage. Ref: Session.updateMessage."""
        if isinstance(msg, MessageInfo):
            msg = message_to_dict(msg)
        key = ["message", msg["session_id"], msg["id"]]
        self._storage.write(key, msg)
        return msg

    def remove_message(self, session_id: str, message_id: str) -> str:
        """Delete message and its parts. Ref: Session.removeMessage."""
        for pk in self._storage.list(["part", message_id]):
            self._storage.remove(pk)
        self._storage.remove(["message", session_id, message_id])
        return message_id

    def update_part(self, part: dict | MessagePart) -> dict:
        """Write part to storage. Ref: Session.updatePart."""
        if hasattr(part, "model_dump"):
            part = part.model_dump()
        key = ["part", part["message_id"], part["id"]]
        self._storage.write(key, part)
        return part

    def remove_part(self, session_id: str, message_id: str, part_id: str) -> str:
        """Delete a part. Ref: Session.removePart."""
        self._storage.remove(["part", message_id, part_id])
        return part_id


# Module-level default for API use
_session: Optional[Session] = None


def get_session(storage: Optional[Storage] = None) -> Session:
    global _session
    if _session is None:
        _session = Session(storage=storage)
    return _session
