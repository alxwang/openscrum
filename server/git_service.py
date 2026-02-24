import subprocess
import logging
import os
from pathlib import Path
from typing import Dict, Any

_log = logging.getLogger(__name__)

class GitService:
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        
    def _run_cmd(self, cmd: list[str], *, log_error: bool = True) -> tuple[bool, str]:
        """Runs a command safely and returns (success, output)."""
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                check=True
            )
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            if log_error:
                _log.error(f"Git command failed: {' '.join(cmd)}\nError: {e.stderr}")
            return False, e.stderr
        except Exception as e:
            if log_error:
                _log.error(f"System error running git: {e}")
            return False, str(e)

    def is_git_repo(self) -> bool:
        """Return True if workspace is already a valid git worktree."""
        success, output = self._run_cmd(["git", "rev-parse", "--is-inside-work-tree"], log_error=False)
        return success and output.strip().lower() == "true"

    def init_repo(self) -> bool:
        """Initializes a git repository if one does not exist."""
        if self.is_git_repo():
            return True

        _log.info(f"Initializing Git repository in {self.workspace_root}")
        success, _ = self._run_cmd(["git", "init"])
        if success:
            # Add openscrum data to gitignore if it doesn't exist
            gitignore = self.workspace_root / ".gitignore"
            if not gitignore.exists() or ".openscrum" not in gitignore.read_text():
                with open(gitignore, "a") as f:
                    f.write("\n.openscrum/\nnode_modules/\n")
            
            # Make initial commit so we have a HEAD
            self._run_cmd(["git", "add", "."])
            self._run_cmd(["git", "commit", "-m", "Initial commit from OpenScrum"])
        return success

    def get_status(self) -> Dict[str, Any]:
        """Gets git status and diff without mutating repository state."""
        success_status, status_out = self._run_cmd(["git", "status", "--porcelain"])
        if not success_status:
            return {"has_changes": False, "diff": "", "error": status_out}

        # Compare working tree + index against HEAD when available.
        success_diff, diff_out = self._run_cmd(["git", "diff", "HEAD"])
        if not success_diff:
            # Fallback for repos without commits yet (unborn HEAD).
            diff_out = ""

        return {
            "has_changes": len(status_out.strip()) > 0,
            "diff": diff_out,
            "status": status_out,
            "error": None
        }

    def commit_changes(self, message: str) -> bool:
        """Commits all current changes with the provided message."""
        self._run_cmd(["git", "add", "."])
        success, _ = self._run_cmd(["git", "commit", "-m", message])
        return success

    def reset_hard(self) -> bool:
        """Discards all current changes and untracked files."""
        reset_success, _ = self._run_cmd(["git", "reset", "--hard", "HEAD"])
        clean_success, _ = self._run_cmd(["git", "clean", "-fd"])
        return reset_success and clean_success
