"""
Identifier generation for session, message, part (ref: opencode id/id.ts).

Prefixes: ses (session), msg (message), prt (part).
Format: prefix_timestamp_hex + random_base62 for uniqueness and sortability.
"""

import os
import time
import secrets

PREFIXES = {"session": "ses", "message": "msg", "part": "prt", "permission": "per"}

# Monotonic state for ascending IDs
_last_ts = 0
_counter = 0


def _random_base62(length: int) -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(chars[secrets.randbelow(62)] for _ in range(length))


def _create(prefix_key: str, descending: bool, given: str | None = None) -> str:
    if given:
        p = PREFIXES.get(prefix_key, prefix_key[:3])
        if not given.startswith(p):
            raise ValueError(f"ID {given} does not start with {p}")
        return given
    return generate_id(prefix_key, descending=descending)


def generate_id(prefix_key: str, descending: bool = False, timestamp: float | None = None) -> str:
    """
    Generate a unique ID with prefix (ses_, msg_, prt_).
    Uses current time (ms) + counter for sortability, plus random suffix.
    """
    global _last_ts, _counter
    prefix = PREFIXES.get(prefix_key, "id")
    now_ms = int((timestamp or time.time()) * 1000)
    if now_ms != _last_ts:
        _last_ts = now_ms
        _counter = 0
    _counter += 1
    # Encode time + counter in 6 bytes hex (like opencode)
    combined = (now_ms << 4) + min(_counter, 15)
    if descending:
        combined = 0xFFFFFF - (combined & 0xFFFFFF)
    time_hex = f"{combined:012x}"[-12:]
    return f"{prefix}_{time_hex}{_random_base62(14)}"


def ascending(prefix_key: str, given: str | None = None) -> str:
    return _create(prefix_key, False, given)


def descending(prefix_key: str, given: str | None = None) -> str:
    return _create(prefix_key, True, given)


def validate_session_id(s: str) -> bool:
    return isinstance(s, str) and s.startswith("ses_")


def validate_message_id(s: str) -> bool:
    return isinstance(s, str) and s.startswith("msg_")


def validate_part_id(s: str) -> bool:
    return isinstance(s, str) and s.startswith("prt_")
