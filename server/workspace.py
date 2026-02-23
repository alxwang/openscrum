"""
Workspace management for OpenScrum sessions.

Provides functions to create and manage workspace directories for sessions.
All workspaces are stored under ~/openscrum/workspaces/ by default.
"""

import os
from pathlib import Path
from typing import List


def get_workspace_root() -> Path:
    """
    Get the root directory where all workspaces are stored.
    
    Returns:
        Path to ~/openscrum/workspaces/ (or OPENSCRUM_WORKSPACES_ROOT env var)
    """
    env_root = os.getenv("OPENSCRUM_WORKSPACES_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path.home() / "openscrum" / "workspaces"


def create_default_agent_rules(workspace_path: Path) -> None:
    """
    Create a default Agent.md file in the workspace if it doesn't exist.
    Copies content from the agent_rules.md template file.
    
    Args:
        workspace_path: Path to the workspace directory
    """
    agent_file = workspace_path / "Agent.md"
    if not agent_file.exists():
        # Try to read from agent_rules.md template file
        template_path = Path(__file__).parent.parent / "agent_rules.md"
        
        if template_path.exists():
            try:
                template_content = template_path.read_text(encoding="utf-8")
                agent_file.write_text(template_content, encoding="utf-8")
                return
            except Exception as e:
                # If reading template fails, fall back to basic content
                print(f"Warning: Could not read agent_rules.md template: {e}")
        
        # Fallback content if template doesn't exist or can't be read
        default_content = """# Agent Rules

## Project Information

This is a new OpenScrum workspace. The agent_rules.md template could not be loaded.
Please define your project-specific rules and guidelines here.

## Build Commands

- Build command: (to be determined)
- Test command: (to be determined)
- Lint command: (to be determined)
- Run command: (to be determined)

## Code Style Guidelines

- (to be determined)

## Testing Guidelines

- (to be determined)

## Additional Notes

- (to be determined)
"""
        agent_file.write_text(default_content, encoding="utf-8")


def create_workspace_for_session(session_id: str, workspace_name: str = None) -> Path:
    """
    Create a workspace directory for a session.
    
    The workspace is created at: ~/openscrum/workspaces/session_SESSIONID/
    
    Args:
        session_id: Session ID
        workspace_name: Optional workspace name (ignored - kept for compatibility)
    
    Returns:
        Path to the created workspace directory
    """
    workspace_root = get_workspace_root()
    workspace_root.mkdir(parents=True, exist_ok=True)
    
    # Use session_SESSIONID format for workspace folder name
    workspace_path = workspace_root / f"session_{session_id}"
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    # Create default Agent.md file
    create_default_agent_rules(workspace_path)
    
    return workspace_path


def resolve_workspace_path(session_id: str, directory: str = None) -> Path:
    """
    Resolve workspace path for a session.
    
    If directory is provided, use it. Otherwise, use the standard workspace location.
    
    Args:
        session_id: Session ID
        directory: Optional explicit directory path (for legacy mode)
    
    Returns:
        Path to the workspace directory
    """
    if directory:
        return Path(directory).expanduser().resolve()
    
    workspace_root = get_workspace_root()
    return workspace_root / f"session_{session_id}"


class WorkspaceManager:
    """Manager for workspace operations."""
    
    def __init__(self, workspace_root: Path = None):
        """
        Initialize workspace manager.
        
        Args:
            workspace_root: Root directory for workspaces (defaults to get_workspace_root())
        """
        self.workspace_root = workspace_root or get_workspace_root()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
    
    def list_workspaces(self) -> List[Path]:
        """
        List all workspace directories under ~/openscrum/workspaces/.
        Only returns directories that match the session_SESSIONID pattern.
        
        Returns:
            List of Path objects for workspace directories
        """
        if not self.workspace_root.exists():
            return []
        
        workspaces = []
        for item in self.workspace_root.iterdir():
            if item.is_dir() and item.name.startswith("session_"):
                workspaces.append(item)
        
        return sorted(workspaces, key=lambda p: p.name)
    
    def get_workspace_path(self, session_id: str) -> Path:
        """
        Get workspace path for a session.
        
        Args:
            session_id: Session ID
        
        Returns:
            Path to the workspace directory (may not exist)
        """
        return self.workspace_root / f"session_{session_id}"
    
    def workspace_exists(self, session_id: str) -> bool:
        """
        Check if workspace exists for a session.
        
        Args:
            session_id: Session ID
        
        Returns:
            True if workspace directory exists
        """
        workspace_path = self.get_workspace_path(session_id)
        return workspace_path.exists() and workspace_path.is_dir()
    
    def create_workspace(self, session_id: str, workspace_name: str = None) -> Path:
        """
        Create workspace directory for a session.
        
        Args:
            session_id: Session ID
            workspace_name: Optional workspace name (ignored)
        
        Returns:
            Path to the created workspace directory
        """
        return create_workspace_for_session(session_id, workspace_name)


# Global workspace manager instance
_workspace_manager = None


def get_workspace_manager() -> WorkspaceManager:
    """
    Get the global workspace manager instance.
    
    Returns:
        WorkspaceManager singleton instance
    """
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager


__all__ = [
    "get_workspace_root",
    "create_workspace_for_session",
    "create_default_agent_rules",
    "resolve_workspace_path",
    "WorkspaceManager",
    "get_workspace_manager",
]
