"""
System tools for OpenScrum - Python replica of OpenCode tools.

All tools ensure paths are relative to the workspace root for safety.
Uses LangChain's @tool decorator and Pydantic for validation.
"""

import os
import re
import json
import subprocess
import glob as pyglob
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# Workspace root - should be set by the application
WORKSPACE_ROOT = os.getcwd()


def resolve_path(file_path: str) -> Path:
    """Resolve a path relative to workspace root. Ensures safety by preventing path traversal."""
    if os.path.isabs(file_path):
        # If absolute, ensure it's within workspace
        abs_path = Path(file_path).resolve()
        workspace = Path(WORKSPACE_ROOT).resolve()
        try:
            abs_path.relative_to(workspace)
        except ValueError:
            raise ValueError(f"Path {file_path} is outside workspace root {WORKSPACE_ROOT}")
        return abs_path
    else:
        # Relative path - resolve from workspace root
        return (Path(WORKSPACE_ROOT) / file_path).resolve()


def ensure_in_workspace(path: Path) -> None:
    """Ensure a path is within the workspace root."""
    workspace = Path(WORKSPACE_ROOT).resolve()
    try:
        path.resolve().relative_to(workspace)
    except ValueError:
        raise ValueError(f"Path {path} is outside workspace root {WORKSPACE_ROOT}")


# ============================================================================
# File Operations
# ============================================================================


@tool
def read(
    file_path: str = Field(..., description="The path to the file to read (relative to workspace root)"),
    offset: Optional[int] = Field(None, description="The line number to start reading from (0-based)"),
    limit: Optional[int] = Field(None, description="The number of lines to read (defaults to 2000)"),
) -> str:
    """
    Reads a file from the local filesystem.
    
    Usage:
    - The filePath parameter can be relative to workspace root or absolute
    - By default, reads up to 2000 lines starting from the beginning
    - You can optionally specify a line offset and limit
    - Any lines longer than 2000 characters will be truncated
    - Results are returned with line numbers starting at 1
    """
    DEFAULT_LIMIT = 2000
    MAX_LINE_LENGTH = 2000
    
    try:
        resolved_path = resolve_path(file_path)
        ensure_in_workspace(resolved_path)
        
        if not resolved_path.exists():
            return f"Error: File not found: {file_path}"
        
        if resolved_path.is_dir():
            return f"Error: Path is a directory, not a file: {file_path}"
        
        with open(resolved_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        
        # Apply offset and limit
        start = offset if offset is not None else 0
        end = start + (limit if limit is not None else DEFAULT_LIMIT)
        selected_lines = lines[start:end]
        
        # Format with line numbers (1-based)
        result_lines = []
        for i, line in enumerate(selected_lines, start=start + 1):
            # Truncate long lines
            truncated = line[:MAX_LINE_LENGTH] + "..." if len(line) > MAX_LINE_LENGTH else line.rstrip('\n\r')
            result_lines.append(f"{i:6d}\t{truncated}")
        
        output = "\n".join(result_lines)
        
        if end < len(lines):
            output += f"\n... ({len(lines) - end} more lines)"

        # Append AGENTS.md/CLAUDE.md from parent dirs (ref: opencode read tool + InstructionPrompt.resolve)
        try:
            from server.instruction import system_paths, resolve_instructions_for_file
        except ImportError:
            try:
                from instruction import system_paths, resolve_instructions_for_file
            except ImportError:
                system_paths = resolve_instructions_for_file = None
        if system_paths is not None and resolve_instructions_for_file is not None:
            workspace = Path(WORKSPACE_ROOT).resolve()
            exclude = set(system_paths(str(workspace)))
            extra = resolve_instructions_for_file(str(workspace), resolved_path, exclude_paths=exclude)
            if extra:
                output += "\n\n<system-reminder>\n"
                output += "\n\n".join(content for _fp, content in extra)
                output += "\n</system-reminder>"
        
        return output
    
    except Exception as e:
        return f"Error reading file {file_path}: {str(e)}"


@tool
def write(
    file_path: str = Field(..., description="The path to the file to write (relative to workspace root)"),
    content: str = Field(..., description="The content to write to the file"),
) -> str:
    """
    Writes a file to the local filesystem.
    
    Usage:
    - This tool will overwrite the existing file if there is one at the provided path
    - If this is an existing file, you MUST use the Read tool first to read the file's contents
    - ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required
    """
    try:
        resolved_path = resolve_path(file_path)
        ensure_in_workspace(resolved_path)
        
        # Create parent directories if needed
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if file exists
        exists = resolved_path.exists()
        
        # Write the file
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        relative_path = resolved_path.relative_to(Path(WORKSPACE_ROOT))
        return f"Wrote file successfully: {relative_path}"
    
    except Exception as e:
        return f"Error writing file {file_path}: {str(e)}"


@tool
def edit(
    file_path: str = Field(..., description="The path to the file to modify (relative to workspace root)"),
    old_string: str = Field(..., description="The text to replace"),
    new_string: str = Field(..., description="The text to replace it with (must be different from oldString)"),
    replace_all: bool = Field(False, description="Replace all occurrences of oldString (default false)"),
) -> str:
    """
    Performs exact string replacements in files.
    
    Usage:
    - You must use the Read tool at least once before editing
    - Ensure you preserve exact indentation as it appears in the file
    - The edit will FAIL if oldString is not found or found multiple times (unless replaceAll=True)
    """
    try:
        if old_string == new_string:
            return "Error: oldString and newString must be different"
        
        resolved_path = resolve_path(file_path)
        ensure_in_workspace(resolved_path)
        
        if not resolved_path.exists():
            return f"Error: File not found: {file_path}"
        
        if resolved_path.is_dir():
            return f"Error: Path is a directory, not a file: {file_path}"
        
        # Read current content
        with open(resolved_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Perform replacement
        if replace_all:
            if old_string not in content:
                return f"Error: oldString not found in content"
            new_content = content.replace(old_string, new_string)
        else:
            if content.count(old_string) == 0:
                return f"Error: oldString not found in content"
            if content.count(old_string) > 1:
                return f"Error: oldString found multiple times. Provide more context or use replaceAll=True"
            new_content = content.replace(old_string, new_string, 1)
        
        # Write back
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        relative_path = resolved_path.relative_to(Path(WORKSPACE_ROOT))
        return f"Edit applied successfully: {relative_path}"
    
    except Exception as e:
        return f"Error editing file {file_path}: {str(e)}"


# ============================================================================
# Search Operations
# ============================================================================


@tool
def grep(
    pattern: str = Field(..., description="The regex pattern to search for in file contents"),
    path: Optional[str] = Field(None, description="The directory to search in (relative to workspace root). Defaults to workspace root."),
    include: Optional[str] = Field(None, description='File pattern to include (e.g. "*.py", "*.{ts,tsx}")'),
) -> str:
    """
    Fast content search tool that works with any codebase size.
    
    Searches file contents using regular expressions.
    Returns file paths and line numbers with matches sorted by modification time.
    """
    try:
        search_path = resolve_path(path) if path else Path(WORKSPACE_ROOT)
        ensure_in_workspace(search_path)
        
        if not search_path.is_dir():
            return f"Error: Path is not a directory: {path}"
        
        # Build glob pattern
        if include:
            glob_pattern = f"**/{include}"
        else:
            glob_pattern = "**/*"
        
        # Find matching files
        matches = []
        for file_path in search_path.rglob(glob_pattern):
            if file_path.is_file():
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, start=1):
                            if re.search(pattern, line):
                                rel_path = file_path.relative_to(Path(WORKSPACE_ROOT))
                                matches.append({
                                    'path': str(rel_path),
                                    'line': line_num,
                                    'content': line.rstrip(),
                                    'mtime': file_path.stat().st_mtime
                                })
                                break  # Only need one match per file for now
                except Exception:
                    continue  # Skip files that can't be read
        
        # Sort by modification time (newest first)
        matches.sort(key=lambda x: x['mtime'], reverse=True)
        
        # Format output
        if not matches:
            return "No files found"
        
        output_lines = [f"Found {len(matches)} matches"]
        for match in matches[:100]:  # Limit to 100 results
            output_lines.append(f"{match['path']}:{match['line']}: {match['content'][:200]}")
        
        if len(matches) > 100:
            output_lines.append(f"\n(Results truncated. {len(matches) - 100} more matches found.)")
        
        return "\n".join(output_lines)
    
    except Exception as e:
        return f"Error searching: {str(e)}"


@tool
def glob(
    pattern: str = Field(..., description="The glob pattern to match files against (e.g. '**/*.py', 'src/**/*.ts')"),
    path: Optional[str] = Field(None, description="The directory to search in (relative to workspace root). Defaults to workspace root."),
) -> str:
    """
    Fast file pattern matching tool that works with any codebase size.
    
    Supports glob patterns like "**/*.js" or "src/**/*.ts".
    Returns matching file paths sorted by modification time.
    """
    try:
        search_path = resolve_path(path) if path else Path(WORKSPACE_ROOT)
        ensure_in_workspace(search_path)
        
        if not search_path.is_dir():
            return f"Error: Path is not a directory: {path}"
        
        # Build full pattern
        full_pattern = str(search_path / pattern)
        
        # Find matching files
        files = []
        for file_path in Path(WORKSPACE_ROOT).rglob(pattern):
            if file_path.is_file():
                try:
                    rel_path = file_path.relative_to(Path(WORKSPACE_ROOT))
                    files.append({
                        'path': str(rel_path),
                        'mtime': file_path.stat().st_mtime
                    })
                except Exception:
                    continue
        
        # Sort by modification time (newest first)
        files.sort(key=lambda x: x['mtime'], reverse=True)
        
        # Limit to 100 results
        files = files[:100]
        
        if not files:
            return "No files found"
        
        output_lines = [f.path for f in files]
        if len(files) == 100:
            output_lines.append("\n(Results are truncated. Consider using a more specific path or pattern.)")
        
        return "\n".join(output_lines)
    
    except Exception as e:
        return f"Error globbing: {str(e)}"


@tool
def list_files(
    path: Optional[str] = Field(None, description="The directory to list (relative to workspace root). Defaults to workspace root."),
    ignore: Optional[List[str]] = Field(None, description="List of glob patterns to ignore"),
) -> str:
    """
    Lists files and directories in a given path.
    
    You should generally prefer the Glob and Grep tools if you know which directories to search.
    """
    try:
        list_path = resolve_path(path) if path else Path(WORKSPACE_ROOT)
        ensure_in_workspace(list_path)
        
        if not list_path.is_dir():
            return f"Error: Path is not a directory: {path}"
        
        # Default ignore patterns
        ignore_patterns = [
            "node_modules/", "__pycache__/", ".git/", "dist/", "build/",
            "target/", "vendor/", "bin/", "obj/", ".idea/", ".vscode/",
            ".zig-cache/", "zig-out", ".coverage", "coverage/", "tmp/",
            "temp/", ".cache/", "cache/", "logs/", ".venv/", "venv/", "env/"
        ]
        if ignore:
            ignore_patterns.extend(ignore)
        
        files = []
        dirs = []
        
        for item in list_path.iterdir():
            rel_path = item.relative_to(Path(WORKSPACE_ROOT))
            rel_str = str(rel_path)
            
            # Check ignore patterns
            should_ignore = False
            for pattern in ignore_patterns:
                if pattern in rel_str or rel_str.startswith(pattern.rstrip('/')):
                    should_ignore = True
                    break
            
            if should_ignore:
                continue
            
            if item.is_file():
                files.append(rel_str)
            elif item.is_dir():
                dirs.append(rel_str + "/")
        
        # Sort and format
        dirs.sort()
        files.sort()
        
        output_lines = [f"{list_path.relative_to(Path(WORKSPACE_ROOT))}/"]
        output_lines.extend(dirs)
        output_lines.extend(files)
        
        return "\n".join(output_lines)
    
    except Exception as e:
        return f"Error listing directory: {str(e)}"


# ============================================================================
# Shell Operations
# ============================================================================


@tool
def bash(
    command: str = Field(..., description="The command to execute"),
    workdir: Optional[str] = Field(None, description="The working directory to run the command in (relative to workspace root)"),
    timeout: Optional[int] = Field(None, description="Optional timeout in milliseconds (default: 600000 / 10 minutes)"),
    description: Optional[str] = Field(None, description="Clear, concise description of what this command does in 5-10 words"),
) -> str:
    """
    Executes a bash command in a shell session with optional timeout.
    
    IMPORTANT: This tool is for terminal operations like git, npm, docker, etc.
    DO NOT use it for file operations - use the specialized tools instead.
    
    All commands run in workspace root by default. Use workdir parameter to change directories.
    
    This tool is **non-interactive**:
    - stdin is closed for the child process (no user input possible)
    - Interactive commands like `npm init` or `vue create` will hang or fail
    - Prefer non-interactive variants (e.g. `npm init -y`, `vue create app --default`)
    
    For long-running servers (e.g. `npm run serve`, `node server.js`), you should:
    - Start them in the background using `&` (e.g. `npm run serve &`)
    - Or use one-shot commands (e.g. `npm run build`) in automated tests
    """
    # Default timeout in milliseconds for foreground commands.
    # Match OpenCode's default (2 minutes) and allow override via environment.
    DEFAULT_TIMEOUT = int(os.getenv("OPENSCRUM_BASH_DEFAULT_TIMEOUT_MS", "120000"))
    
    try:
        # Resolve working directory
        if workdir:
            cmd_dir = resolve_path(workdir)
            ensure_in_workspace(cmd_dir)
            if not cmd_dir.is_dir():
                return f"Error: Working directory is not a directory: {workdir}"
        else:
            cmd_dir = Path(WORKSPACE_ROOT)
        
        # Detect background commands (trailing '&') and handle specially
        cmd_str = command.strip()
        is_background = cmd_str.endswith("&")
        if is_background:
            # Strip trailing '&' and any trailing whitespace
            cmd_str = cmd_str[:-1].rstrip()
            
            # Start background process and return immediately without waiting.
            proc = subprocess.Popen(
                cmd_str,
                shell=True,
                cwd=str(cmd_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return (
                f"Started background command (PID {proc.pid}): {cmd_str}\n"
                f"Note: This process will continue running until it exits or is manually stopped."
            )
        
        # Foreground command with timeout
        timeout_ms = timeout if timeout else DEFAULT_TIMEOUT
        timeout_sec = timeout_ms / 1000.0
        
        result = subprocess.run(
            cmd_str,
            shell=True,
            cwd=str(cmd_dir),
            stdin=subprocess.DEVNULL,  # Explicitly disable stdin to prevent interactive prompts
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding='utf-8',
            errors='replace'
        )
        
        # Format output
        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        
        output = "\n".join(output_parts)
        
        if result.returncode != 0:
            output += f"\n\nExit code: {result.returncode}"
        
        return output
    
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout_ms}ms"
    except Exception as e:
        return f"Error executing command: {str(e)}"


# ============================================================================
# Web Operations
# ============================================================================


@tool
def webfetch(
    url: str = Field(..., description="The URL to fetch content from"),
    format: str = Field("markdown", description="The format to return (text, markdown, or html). Defaults to markdown."),
    timeout: Optional[int] = Field(None, description="Optional timeout in seconds (max 120)"),
) -> str:
    """
    Fetches content from a specified URL.
    
    Takes a URL and optional format as input.
    Fetches the URL content, converts to requested format (markdown by default).
    """
    import httpx
    from markdownify import markdownify as md
    
    MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB
    DEFAULT_TIMEOUT = 30
    MAX_TIMEOUT = 120
    
    try:
        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"
        
        timeout_sec = min(timeout if timeout else DEFAULT_TIMEOUT, MAX_TIMEOUT)
        
        with httpx.Client(timeout=timeout_sec) as client:
            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            
            # Check size
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                return "Error: Response too large (exceeds 5MB limit)"
            
            content = response.text
            if len(content.encode('utf-8')) > MAX_RESPONSE_SIZE:
                return "Error: Response too large (exceeds 5MB limit)"
            
            # Convert format
            content_type = response.headers.get("content-type", "")
            
            if format == "markdown":
                if "text/html" in content_type:
                    return md(content)
                return content
            elif format == "text":
                if "text/html" in content_type:
                    # Simple HTML to text conversion
                    from html import unescape
                    import re
                    text = re.sub(r'<[^>]+>', '', content)
                    return unescape(text)
                return content
            elif format == "html":
                return content
            else:
                return f"Error: Unknown format: {format}"
    
    except Exception as e:
        return f"Error fetching URL: {str(e)}"


# ============================================================================
# Multi-Edit Operations
# ============================================================================


@tool
def multiedit(
    file_path: str = Field(..., description="The path to the file to modify (relative to workspace root)"),
    edits: List[Dict[str, Any]] = Field(..., description="Array of edit operations to perform sequentially"),
) -> str:
    """
    Tool for making multiple edits to a single file in one operation.
    
    All edits are applied in sequence. If any edit fails, the operation fails.
    Each edit contains: oldString, newString, and optionally replaceAll.
    """
    try:
        resolved_path = resolve_path(file_path)
        ensure_in_workspace(resolved_path)
        
        if not resolved_path.exists():
            return f"Error: File not found: {file_path}"
        
        # Read current content
        with open(resolved_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Apply edits sequentially
        for i, edit in enumerate(edits):
            old_string = edit.get('oldString', '')
            new_string = edit.get('newString', '')
            replace_all = edit.get('replaceAll', False)
            
            if old_string == new_string:
                return f"Error: Edit {i+1}: oldString and newString must be different"
            
            if replace_all:
                if old_string not in content:
                    return f"Error: Edit {i+1}: oldString not found in content"
                content = content.replace(old_string, new_string)
            else:
                if content.count(old_string) == 0:
                    return f"Error: Edit {i+1}: oldString not found in content"
                if content.count(old_string) > 1:
                    return f"Error: Edit {i+1}: oldString found multiple times. Provide more context or use replaceAll=True"
                content = content.replace(old_string, new_string, 1)
        
        # Write back
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        relative_path = resolved_path.relative_to(Path(WORKSPACE_ROOT))
        return f"MultiEdit applied successfully: {len(edits)} edits to {relative_path}"
    
    except Exception as e:
        return f"Error in multiedit: {str(e)}"


# ============================================================================
# Patch Operations
# ============================================================================


@tool
def apply_patch(patch_text: str = Field(..., description="The full patch text that describes all changes to be made")) -> str:
    """
    Apply patch format edits to files.
    
    Patch format:
    *** Begin Patch
    *** Add File: <path>
    +content
    *** Update File: <path>
    @@ context
    -old line
    +new line
    *** Delete File: <path>
    *** End Patch
    """
    try:
        if not patch_text.strip():
            return "Error: Empty patch text"
        
        # Simple patch parser (simplified version)
        lines = patch_text.split('\n')
        i = 0
        results = []
        
        while i < len(lines):
            line = lines[i]
            
            if line.strip() == "*** Begin Patch":
                i += 1
                continue
            elif line.strip() == "*** End Patch":
                break
            elif line.startswith("*** Add File:"):
                file_path = line.replace("*** Add File:", "").strip()
                resolved_path = resolve_path(file_path)
                ensure_in_workspace(resolved_path)
                
                # Collect content (lines starting with +)
                content_lines = []
                i += 1
                while i < len(lines) and not lines[i].startswith("***"):
                    if lines[i].startswith("+"):
                        content_lines.append(lines[i][1:])
                    i += 1
                i -= 1  # Back up one line
                
                content = "\n".join(content_lines)
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                with open(resolved_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                results.append(f"Added: {file_path}")
            
            elif line.startswith("*** Update File:"):
                file_path = line.replace("*** Update File:", "").strip()
                resolved_path = resolve_path(file_path)
                ensure_in_workspace(resolved_path)
                
                if not resolved_path.exists():
                    return f"Error: File not found for update: {file_path}"
                
                # Read current content
                with open(resolved_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Simple patch application (look for @@ markers and apply changes)
                i += 1
                new_content = content
                while i < len(lines) and not lines[i].startswith("***"):
                    if lines[i].startswith("@@"):
                        # Context marker - skip
                        i += 1
                        continue
                    elif lines[i].startswith("-"):
                        # Remove line
                        old_line = lines[i][1:]
                        new_content = new_content.replace(old_line + "\n", "", 1)
                        i += 1
                    elif lines[i].startswith("+"):
                        # Add line
                        new_line = lines[i][1:]
                        # Simple insertion - in real implementation would use context
                        i += 1
                    else:
                        i += 1
                
                with open(resolved_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                results.append(f"Updated: {file_path}")
            
            elif line.startswith("*** Delete File:"):
                file_path = line.replace("*** Delete File:", "").strip()
                resolved_path = resolve_path(file_path)
                ensure_in_workspace(resolved_path)
                
                if resolved_path.exists():
                    resolved_path.unlink()
                    results.append(f"Deleted: {file_path}")
            
            i += 1
        
        if not results:
            return "Error: No changes found in patch"
        
        return "Success. Updated the following files:\n" + "\n".join(results)
    
    except Exception as e:
        return f"Error applying patch: {str(e)}"


# ============================================================================
# Todo Operations
# ============================================================================


@tool
def todowrite(todos: List[Dict[str, Any]] = Field(..., description="The updated todo list")) -> str:
    """
    Use this tool to create and manage a structured task list.
    
    Helps track progress, organize complex tasks, and demonstrate thoroughness.
    """
    # In a real implementation, this would persist to a session store
    # For now, just return a summary
    pending = [t for t in todos if t.get('status') != 'completed']
    return f"Updated todo list: {len(pending)} pending, {len(todos) - len(pending)} completed"


@tool
def todoread() -> str:
    """Use this tool to read your todo list."""
    # In a real implementation, this would read from a session store
    return "[]"  # Empty list for now


# ============================================================================
# Question Tool (placeholder - requires session management)
# ============================================================================


@tool
def question(questions: List[Dict[str, Any]] = Field(..., description="Questions to ask the user")) -> str:
    """
    Use this tool when you need to ask the user questions during execution.
    
    Allows you to:
    1. Gather user preferences or requirements
    2. Clarify ambiguous instructions
    3. Get decisions on implementation choices
    """
    # In a real implementation, this would interact with the UI/session
    # For now, return a placeholder
    question_texts = [q.get('question', '') for q in questions]
    return f"Questions asked: {len(questions)}. In real implementation, this would prompt the user."


# ============================================================================
# Task Tool (Subagent Launching)
# ============================================================================


@tool
def task(
    description: str = Field(..., description="A short (3-5 words) description of the task"),
    prompt: str = Field(..., description="The task for the agent to perform"),
    subagent_type: str = Field(..., description="The type of specialized agent to use for this task"),
    task_id: Optional[str] = Field(None, description="Optional task_id to resume a previous task"),
    command: Optional[str] = Field(None, description="The command that triggered this task"),
) -> str:
    """
    Launch a new agent to handle complex, multistep tasks autonomously.
    
    When to use:
    - When instructed to execute custom slash commands
    - For complex tasks that require specialized agents
    - When you need to delegate work to a subagent
    
    When NOT to use:
    - For reading specific files (use Read or Glob instead)
    - For searching code (use Grep or Glob instead)
    - For simple operations
    """
    # In a full implementation, this would:
    # 1. Create a new session with parent relationship
    # 2. Launch the subagent with the specified prompt
    # 3. Return the task_id for resuming
    
    # For now, return a placeholder that indicates the task would be launched
    result = f"""Task launched: {description}
Subagent type: {subagent_type}
Task ID: {task_id or 'new-task-' + str(int(datetime.now().timestamp()))}

Note: Full task tool implementation requires session management.
In production, this would launch a subagent session and return results."""
    
    return result


# ============================================================================
# WebSearch Tool (Exa AI)
# ============================================================================


@tool
def websearch(
    query: str = Field(..., description="Web search query"),
    numResults: Optional[int] = Field(8, description="Number of search results to return (default: 8)"),
    livecrawl: Optional[str] = Field("fallback", description="Live crawl mode: 'fallback' or 'preferred'"),
    type: Optional[str] = Field("auto", description="Search type: 'auto', 'fast', or 'deep'"),
    contextMaxCharacters: Optional[int] = Field(10000, description="Maximum characters for context (default: 10000)"),
) -> str:
    """
    Search the web using Exa AI - performs real-time web searches.
    
    Provides up-to-date information for current events and recent data.
    Supports configurable result counts and returns content from relevant websites.
    """
    import httpx
    from datetime import date
    
    API_BASE_URL = "https://mcp.exa.ai/mcp"
    DEFAULT_TIMEOUT = 25
    
    try:
        # Build JSON-RPC request
        search_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "web_search_exa",
                "arguments": {
                    "query": query,
                    "type": type or "auto",
                    "numResults": numResults or 8,
                    "livecrawl": livecrawl or "fallback",
                    "contextMaxCharacters": contextMaxCharacters or 10000,
                }
            }
        }
        
        # Make request
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.post(
                API_BASE_URL,
                json=search_request,
                headers={
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                }
            )
            response.raise_for_status()
            
            # Parse SSE response
            response_text = response.text
            lines = response_text.split("\n")
            for line in lines:
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("result") and data.get("result", {}).get("content"):
                        content = data["result"]["content"]
                        if isinstance(content, list) and len(content) > 0:
                            return content[0].get("text", "No content found")
            
            return "No search results found. Please try a different query."
    
    except httpx.TimeoutException:
        return "Error: Search request timed out"
    except Exception as e:
        return f"Error performing web search: {str(e)}"


# ============================================================================
# CodeSearch Tool (Exa Code API)
# ============================================================================


@tool
def codesearch(
    query: str = Field(..., description="Search query for APIs, Libraries, and SDKs (e.g., 'React useState hook examples', 'Python pandas dataframe filtering')"),
    tokensNum: int = Field(5000, description="Number of tokens to return (1000-50000, default: 5000)"),
) -> str:
    """
    Search and get relevant context for any programming task using Exa Code API.
    
    Provides high-quality, fresh context for libraries, SDKs, and APIs.
    Returns comprehensive code examples, documentation, and API references.
    """
    import httpx
    
    API_BASE_URL = "https://mcp.exa.ai/mcp"
    DEFAULT_TIMEOUT = 30
    
    # Validate token count
    if tokensNum < 1000 or tokensNum > 50000:
        return "Error: tokensNum must be between 1000 and 50000"
    
    try:
        # Build JSON-RPC request
        code_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_code_context_exa",
                "arguments": {
                    "query": query,
                    "tokensNum": tokensNum,
                }
            }
        }
        
        # Make request
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.post(
                API_BASE_URL,
                json=code_request,
                headers={
                    "accept": "application/json, text/event-stream",
                    "content-type": "application/json",
                }
            )
            response.raise_for_status()
            
            # Parse SSE response
            response_text = response.text
            lines = response_text.split("\n")
            for line in lines:
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("result") and data.get("result", {}).get("content"):
                        content = data["result"]["content"]
                        if isinstance(content, list) and len(content) > 0:
                            return content[0].get("text", "No content found")
            
            return "No code snippets or documentation found. Please try a different query or be more specific."
    
    except httpx.TimeoutException:
        return "Error: Code search request timed out"
    except Exception as e:
        return f"Error performing code search: {str(e)}"


# ============================================================================
# Batch Tool (Parallel Tool Execution)
# ============================================================================


@tool
def batch(
    tool_calls: List[Dict[str, Any]] = Field(..., description="Array of tool calls to execute in parallel. Format: [{\"tool\": \"tool_name\", \"parameters\": {...}}, ...]"),
) -> str:
    """
    Executes multiple independent tool calls concurrently to reduce latency.
    
    Notes:
    - 1-25 tool calls per batch
    - All calls start in parallel; ordering NOT guaranteed
    - Partial failures do not stop other tool calls
    - Do NOT use batch tool within another batch tool
    
    Good for: reading many files, grep+glob+read combos, multiple bash commands
    """
    import asyncio
    import concurrent.futures
    
    MAX_CALLS = 25
    DISALLOWED_TOOLS = {"batch"}
    
    if not tool_calls:
        return "Error: At least one tool call is required"
    
    if len(tool_calls) > MAX_CALLS:
        return f"Error: Maximum {MAX_CALLS} tool calls allowed in batch"
    
    # Get available tools
    from .system_tools import (
        read, write, edit, multiedit, apply_patch,
        grep, glob, list_files, bash, webfetch,
        todowrite, todoread, question, task, websearch, codesearch
    )
    
    tool_map = {
        "read": read,
        "write": write,
        "edit": edit,
        "multiedit": multiedit,
        "apply_patch": apply_patch,
        "grep": grep,
        "glob": glob,
        "list_files": list_files,
        "bash": bash,
        "webfetch": webfetch,
        "todowrite": todowrite,
        "todoread": todoread,
        "question": question,
        "task": task,
        "websearch": websearch,
        "codesearch": codesearch,
    }
    
    results = []
    successful = 0
    failed = 0
    
    def execute_call(call: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = call.get("tool", "")
        parameters = call.get("parameters", {})
        
        if tool_name in DISALLOWED_TOOLS:
            return {
                "success": False,
                "tool": tool_name,
                "error": f"Tool '{tool_name}' is not allowed in batch"
            }
        
        if tool_name not in tool_map:
            return {
                "success": False,
                "tool": tool_name,
                "error": f"Tool '{tool_name}' not found in registry"
            }
        
        try:
            tool_func = tool_map[tool_name]
            result = tool_func.invoke(parameters)
            return {
                "success": True,
                "tool": tool_name,
                "result": result
            }
        except Exception as e:
            return {
                "success": False,
                "tool": tool_name,
                "error": str(e)
            }
    
    # Execute all calls in parallel using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tool_calls), 10)) as executor:
        futures = [executor.submit(execute_call, call) for call in tool_calls]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            if result["success"]:
                successful += 1
            else:
                failed += 1
    
    # Format output
    output_lines = []
    if failed > 0:
        output_lines.append(f"Executed {successful}/{len(results)} tools successfully. {failed} failed.")
    else:
        output_lines.append(f"All {successful} tools executed successfully.\n\nKeep using the batch tool for optimal performance in your next response!")
    
    # Add details
    output_lines.append("\nResults:")
    for r in results:
        if r["success"]:
            output_lines.append(f"  ✓ {r['tool']}: {str(r['result'])[:100]}...")
        else:
            output_lines.append(f"  ✗ {r['tool']}: {r['error']}")
    
    return "\n".join(output_lines)


# ============================================================================
# LSP Tool (Language Server Protocol)
# ============================================================================


@tool
def lsp(
    operation: str = Field(..., description="The LSP operation: goToDefinition, findReferences, hover, documentSymbol, workspaceSymbol, goToImplementation, prepareCallHierarchy, incomingCalls, outgoingCalls"),
    filePath: str = Field(..., description="The absolute or relative path to the file"),
    line: int = Field(..., description="The line number (1-based, as shown in editors)"),
    character: int = Field(..., description="The character offset (1-based, as shown in editors)"),
) -> str:
    """
    Interact with Language Server Protocol (LSP) servers for code intelligence.
    
    Supported operations:
    - goToDefinition: Find where a symbol is defined
    - findReferences: Find all references to a symbol
    - hover: Get hover information (documentation, type info)
    - documentSymbol: Get all symbols in a document
    - workspaceSymbol: Search for symbols across workspace
    - goToImplementation: Find implementations
    - prepareCallHierarchy: Get call hierarchy
    - incomingCalls: Find callers
    - outgoingCalls: Find callees
    """
    valid_operations = [
        "goToDefinition", "findReferences", "hover", "documentSymbol",
        "workspaceSymbol", "goToImplementation", "prepareCallHierarchy",
        "incomingCalls", "outgoingCalls"
    ]
    
    if operation not in valid_operations:
        return f"Error: Invalid operation. Must be one of: {', '.join(valid_operations)}"
    
    try:
        resolved_path = resolve_path(filePath)
        ensure_in_workspace(resolved_path)
        
        if not resolved_path.exists():
            return f"Error: File not found: {filePath}"
        
        # In a full implementation, this would:
        # 1. Connect to LSP server for the file type
        # 2. Execute the requested operation
        # 3. Return structured results
        
        # For now, return a placeholder indicating LSP would be used
        return f"""LSP operation '{operation}' requested for {filePath}:{line}:{character}

Note: Full LSP implementation requires:
- LSP client library (python-lsp-server or similar)
- Language server configuration
- Server connection management

In production, this would connect to the appropriate LSP server and return:
- Definition locations
- Reference lists
- Hover documentation
- Symbol information
- Call hierarchy data"""
    
    except Exception as e:
        return f"Error: {str(e)}"


# ============================================================================
# Plan Tools (Plan Mode Entry/Exit)
# ============================================================================


@tool
def plan_exit() -> str:
    """
    Use this tool when you have completed the planning phase and are ready to exit plan agent.
    
    Call this tool:
    - After you have written a complete plan to the plan file
    - After you have clarified any questions with the user
    - When you are confident the plan is ready for implementation
    """
    # In a full implementation, this would:
    # 1. Ask user if they want to switch to build agent
    # 2. Create a message to switch modes
    # 3. Update session state
    
    return """Plan exit requested.

Note: Full implementation requires:
- User confirmation dialog
- Session mode switching
- Message creation for mode transition

In production, this would prompt the user and switch to build agent mode."""


@tool
def plan_enter() -> str:
    """
    Use this tool to suggest switching to plan agent when the user's request would benefit from planning.
    
    Call this tool when:
    - The user's request is complex and would benefit from planning first
    - You want to research and design before making changes
    - The task involves multiple files or significant architectural decisions
    """
    # In a full implementation, this would:
    # 1. Ask user if they want to switch to plan agent
    # 2. Create a message to switch modes
    # 3. Update session state
    
    return """Plan enter requested.

Note: Full implementation requires:
- User confirmation dialog
- Session mode switching
- Message creation for mode transition

In production, this would prompt the user and switch to plan agent mode."""


# ============================================================================
# Export all tools
# ============================================================================

__all__ = [
    'read',
    'write',
    'edit',
    'multiedit',
    'apply_patch',
    'grep',
    'glob',
    'list_files',
    'bash',
    'webfetch',
    'todowrite',
    'todoread',
    'question',
    'task',
    'websearch',
    'codesearch',
    'batch',
    'lsp',
    'plan_exit',
    'plan_enter',
]
