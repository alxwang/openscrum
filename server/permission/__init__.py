"""Permission system for tool execution authorization (ref: opencode permission/)."""

from server.permission.permission import (
    PermissionSystem,
    PermissionRule,
    PermissionRequest,
    Reply,
    RejectedError,
    DeniedError,
    CorrectedError,
    get_permission_system,
    evaluate,
    from_config,
    merge_rulesets,
    disabled_tools,
)

__all__ = [
    "PermissionSystem",
    "PermissionRule",
    "PermissionRequest",
    "Reply",
    "RejectedError",
    "DeniedError",
    "CorrectedError",
    "get_permission_system",
    "evaluate",
    "from_config",
    "merge_rulesets",
    "disabled_tools",
]
