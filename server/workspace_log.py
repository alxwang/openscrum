import json
import logging
import os
import time
from pathlib import Path
from typing import Any

WORKSPACE_LOG_FILENAME = "openscrum-detailed-log.jsonl"


def _env_truthy(name: str, default: str = "0") -> bool:
    value = str(os.getenv(name, default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def append_workspace_log(workspace_root: str, event: str, payload: dict[str, Any]) -> None:
    if not _env_truthy("OPENSCRUM_DETAILED_LOG", "0"):
        return
    if not workspace_root:
        return
    try:
        path = Path(workspace_root) / WORKSPACE_LOG_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp_ms": int(time.time() * 1000),
            "event": event,
            **payload,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to write workspace log: %s", e)
