"""
Session status tracking: idle, busy, retry (ref: opencode session/status.ts).

In-memory state per session; used to block concurrent prompts and show retry state.
"""

from typing import Literal, TypedDict

# SessionStatus types matching opencode SessionStatus.Info
IdleStatus = TypedDict("IdleStatus", {"type": Literal["idle"]})


class RetryStatus(TypedDict):
    type: Literal["retry"]
    attempt: int
    message: str
    next: int


BusyStatus = TypedDict("BusyStatus", {"type": Literal["busy"]})

SessionStatusInfo = IdleStatus | RetryStatus | BusyStatus

# In-memory state: session_id -> status (idle is implied when missing)
_state: dict[str, SessionStatusInfo] = {}


class SessionStatus:
    """Get/set session status (idle, busy, retry). Ref: opencode SessionStatus namespace."""

    @staticmethod
    def get(session_id: str) -> SessionStatusInfo:
        """Return current status for session; default idle."""
        return _state.get(session_id, {"type": "idle"})

    @staticmethod
    def list_all() -> dict[str, SessionStatusInfo]:
        """Return all non-idle session statuses."""
        return dict(_state)

    @staticmethod
    def set(session_id: str, status: SessionStatusInfo) -> None:
        """Set status. Idle clears the entry."""
        if status["type"] == "idle":
            _state.pop(session_id, None)
            return
        _state[session_id] = status
