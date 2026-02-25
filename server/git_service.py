import subprocess
import logging
import os
from typing import List
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

        entries = self._parse_porcelain(status_out)
        files: List[Dict[str, Any]] = []
        aggregate_chunks: List[str] = []
        for entry in entries:
            path = entry.get("path", "")
            if not path:
                continue
            diff_text = self._diff_for_entry(entry)
            files.append(
                {
                    "path": path,
                    "status": entry.get("status", "").strip(),
                    "staged": bool(entry.get("staged")),
                    "unstaged": bool(entry.get("unstaged")),
                    "untracked": bool(entry.get("untracked")),
                    "renamed_from": entry.get("old_path"),
                    "diff": diff_text,
                }
            )
            if diff_text:
                aggregate_chunks.append(diff_text)

        # Backward-compatible aggregate diff string for existing callers.
        diff_out = "\n".join(chunk for chunk in aggregate_chunks if chunk).strip()
        if not diff_out:
            # Keep legacy behavior as fallback
            success_diff, fallback_diff = self._run_cmd(["git", "diff", "HEAD"])
            diff_out = fallback_diff if success_diff else ""

        return {
            "has_changes": len(status_out.strip()) > 0,
            "diff": diff_out,
            "status": status_out,
            "files": files,
            "error": None
        }

    def _parse_porcelain(self, status_out: str) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for raw_line in (status_out or "").splitlines():
            line = raw_line.rstrip("\n")
            if len(line) < 3:
                continue
            xy = line[:2]
            payload = line[3:]
            old_path = None
            path = payload
            if " -> " in payload:
                old_path, path = payload.split(" -> ", 1)
            path = path.strip()
            old_path = old_path.strip() if old_path else None
            entries.append(
                {
                    "raw": line,
                    "status": xy,
                    "staged": xy[0] != " ",
                    "unstaged": xy[1] != " ",
                    "untracked": xy == "??",
                    "old_path": old_path,
                    "path": path,
                }
            )
        return entries

    def _diff_for_entry(self, entry: Dict[str, Any]) -> str:
        path = entry.get("path", "")
        if not path:
            return ""
        if entry.get("untracked"):
            return self._untracked_file_diff(path)
        success, out = self._run_cmd(["git", "diff", "HEAD", "--", path], log_error=False)
        if success and out.strip():
            return out
        # Fallback for cases like new staged file in unborn/head edge cases.
        success_cached, out_cached = self._run_cmd(["git", "diff", "--cached", "--", path], log_error=False)
        if success_cached and out_cached.strip():
            return out_cached
        return ""

    def _untracked_file_diff(self, rel_path: str) -> str:
        file_path = self.workspace_root / rel_path
        if not file_path.exists() or not file_path.is_file():
            return f"diff --git a/{rel_path} b/{rel_path}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel_path}\n+<untracked file unavailable>\n"
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"diff --git a/{rel_path} b/{rel_path}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel_path}\n+<failed to read untracked file: {e}>\n"
        lines = content.splitlines()
        max_lines = 400
        truncated = len(lines) > max_lines
        lines = lines[:max_lines]
        plus_lines = "\n".join(f"+{ln}" for ln in lines)
        tail = "\n+... [truncated]" if truncated else ""
        return (
            f"diff --git a/{rel_path} b/{rel_path}\n"
            "new file mode 100644\n"
            f"--- /dev/null\n+++ b/{rel_path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n"
            f"{plus_lines}{tail}\n"
        )

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
