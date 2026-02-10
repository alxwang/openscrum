"""
Command templates: init, etc. (ref: opencode command/index.ts, template/initialize.txt).

When the user runs /init, the server substitutes the message with this prompt
so the agent analyzes the codebase and creates/updates AGENTS.md.
"""

from pathlib import Path
from typing import Optional


def _default_template_path() -> Path:
    """Path to initialize.txt (server/command/ -> server/ -> repo root)."""
    return Path(__file__).resolve().parent.parent.parent / "prompts" / "command" / "template" / "initialize.txt"


def get_init_prompt(workspace_root: str, template_path: Optional[Path] = None) -> str:
    """
    Return the init command prompt with ${path} replaced by workspace_root.

    Ref: opencode Command.Default.INIT template (initialize.txt).
    """
    path = template_path or _default_template_path()
    if not path.exists():
        return (
            "Please analyze this codebase and create an AGENTS.md file containing:\n"
            "1. Build/lint/test commands - especially for running a single test\n"
            "2. Code style guidelines including imports, formatting, types, naming conventions, error handling, etc.\n"
            f"The file should be in the project root. If there's already an AGENTS.md in {workspace_root}, improve it.\n"
        )
    raw = path.read_text(encoding="utf-8")
    return raw.replace("${path}", workspace_root).replace("$ARGUMENTS", "").strip()
