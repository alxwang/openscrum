"""
Resolve and load AGENTS.md / CLAUDE.md for system prompt and read-tool injection.

Ref: opencode session/instruction.ts
- FILES = AGENTS.md, CLAUDE.md (first match when searching up)
- Project: find up from cwd to worktree
- Global: ~/.config/opencode/AGENTS.md, ~/.claude/CLAUDE.md
OpenScrum: project = workspace_root; global = OPENSCRUM_DATA_DIR or ~/.openscrum
"""

import os
from pathlib import Path
from typing import List, Optional, Set, Tuple

INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md"]


def _global_config_dir() -> Path:
    """OpenScrum config dir for global AGENTS.md (ref: opencode Global.Path.config)."""
    base = os.environ.get("OPENSCRUM_DATA_DIR") or os.path.expanduser("~/.openscrum")
    return Path(base).resolve()


def _find_up(
    start: Path,
    root: Path,
    names: List[str],
) -> Optional[Path]:
    """First file in names found when walking start up to root (inclusive)."""
    current = start.resolve()
    root = root.resolve()
    while current != root.parent and current != current.parent:
        for name in names:
            p = current / name
            if p.is_file():
                return p
        current = current.parent
    for name in names:
        p = root / name
        if p.is_file():
            return p
    return None


def system_paths(workspace_root: str) -> List[Path]:
    """
    Paths to instruction files for the system prompt.
    Order: project (find up from workspace_root), then global AGENTS.md.
    Ref: InstructionPrompt.systemPaths()
    """
    workspace_root = Path(workspace_root).resolve()
    out: List[Path] = []

    # Project: first AGENTS.md or CLAUDE.md at or above workspace root (from workspace_root)
    found = _find_up(workspace_root, workspace_root, INSTRUCTION_FILES)
    if found:
        out.append(found)

    # Global: ~/.openscrum/AGENTS.md (and optional CLAUDE fallback)
    config_dir = _global_config_dir()
    global_agents = config_dir / "AGENTS.md"
    if global_agents.is_file():
        out.append(global_agents)
    global_claude = Path.home() / ".claude" / "CLAUDE.md"
    if global_claude.is_file() and global_claude not in out:
        out.append(global_claude)

    return out


def system(workspace_root: str) -> List[str]:
    """
    Load system instruction content: "Instructions from: <path>\\n" + content.
    Ref: InstructionPrompt.system()
    """
    paths = system_paths(workspace_root)
    result: List[str] = []
    for p in paths:
        try:
            content = p.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                result.append("Instructions from: " + str(p) + "\n" + content)
        except Exception:
            pass
    return result


def resolve_instructions_for_file(
    workspace_root: str,
    filepath: Path,
    exclude_paths: Optional[Set[Path]] = None,
) -> List[Tuple[str, str]]:
    """
    Find AGENTS.md/CLAUDE.md in parent dirs of filepath (up to workspace_root).
    Returns [(filepath, content), ...] for each, excluding paths in exclude_paths.
    Ref: InstructionPrompt.resolve() - used by read tool to append parent instructions.
    """
    workspace_root = Path(workspace_root).resolve()
    filepath = Path(filepath).resolve()
    exclude_paths = exclude_paths or set()
    current = filepath.parent
    root = workspace_root
    results: List[Tuple[str, str]] = []
    seen: Set[Path] = set()

    while current != root.parent and current != current.parent:
        for name in INSTRUCTION_FILES:
            p = current / name
            if not p.is_file():
                continue
            p_resolved = p.resolve()
            if p_resolved in exclude_paths or p_resolved in seen:
                continue
            seen.add(p_resolved)
            try:
                content = p_resolved.read_text(encoding="utf-8", errors="replace").strip()
                if content:
                    results.append((str(p_resolved), "Instructions from: " + str(p_resolved) + "\n" + content))
            except Exception:
                pass
        current = current.parent

    # workspace root itself
    for name in INSTRUCTION_FILES:
        p = root / name
        if not p.is_file():
            continue
        p_resolved = p.resolve()
        if p_resolved in exclude_paths or p_resolved in seen:
            continue
        seen.add(p_resolved)
        try:
            content = p_resolved.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                results.append((str(p_resolved), "Instructions from: " + str(p_resolved) + "\n" + content))
        except Exception:
            pass

    return results
