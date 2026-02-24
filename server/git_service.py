import subprocess
import logging
import os
from pathlib import Path
from typing import Dict, Any

_log = logging.getLogger(__name__)

class GitService:
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        
    def _run_cmd(self, cmd: list[str]) -> tuple[bool, str]:
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
            _log.error(f"Git command failed: {' '.join(cmd)}\nError: {e.stderr}")
            return False, e.stderr
        except Exception as e:
            _log.error(f"System error running git: {e}")
            return False, str(e)

    def init_repo(self) -> bool:
        """Initializes a git repository if one does not exist."""
        if not (self.workspace_root / ".git").exists():
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
        return True

    def get_status(self) -> Dict[str, Any]:
        """Gets the current git status diffs."""
        # Ensure all untracked files are staged (but not committed) so they appear in diff
        self._run_cmd(["git", "add", "."])
        
        success, diff_out = self._run_cmd(["git", "diff", "--staged"])
        if not success:
            return {"has_changes": False, "diff": "", "error": diff_out}
            
        return {
            "has_changes": len(diff_out.strip()) > 0,
            "diff": diff_out,
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
