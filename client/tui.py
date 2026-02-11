"""
Textual TUI Client for OpenScrum

Provides a terminal user interface for interacting with the OpenScrum agent.
Keybinds (OpenCode-style): Tab = switch Plan/Edit, Enter = send, Ctrl+Enter = newline.
All built-in commands start with / (e.g. /init, /help).
Copy: Ctrl+Shift+C copies chat log to clipboard. Paste: Ctrl+V pastes into input.
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Optional

import httpx
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.events import Key
from textual.message import Message
from textual.widgets import Input, Button, RichLog, Header, Footer, Static
from textual.binding import Binding
from textual.reactive import reactive


class CopyableRichLog(RichLog):
    """RichLog that keeps a plain-text tail for copy and optionally appends to a workspace MD file."""
    
    # Enable mouse support and focus for terminal's native selection
    can_focus = True
    COMPONENT_CLASSES = {"richlog--highlight-key"}

    def __init__(self, *args, log_tail: Optional[deque] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._log_tail = log_tail
        self._log_file_path: Optional[Path] = None  # set by ChatWidget to workspace_root/openscrum-chat.md
        # Allow terminal's native selection to work
        self.auto_scroll = True

    def write(self, *args, **kwargs):
        super().write(*args, **kwargs)
        if not args:
            return
        plain = _strip_rich_markup(str(args[0]))
        if self._log_tail is not None:
            self._log_tail.append(plain)
        if self._log_file_path and plain.strip():
            try:
                with open(self._log_file_path, "a", encoding="utf-8") as f:
                    f.write(plain.rstrip() + "\n")
                    f.flush()  # Flush immediately for debugging
                    os.fsync(f.fileno())  # Ensure OS writes to disk
            except Exception:
                pass

# ============================================================================
# Clipboard helpers (for copy/paste when terminal doesn't support it)
# ============================================================================

def _strip_rich_markup(s: str) -> str:
    """Remove Rich/Textual markup tags like [bold], [dim], [/], etc."""
    return re.sub(r"\[/?[^\]]*\]", "", s)


def _get_clipboard() -> str:
    """Read system clipboard. macOS: pbpaste, Linux: xclip -o or xsel -o."""
    try:
        import shutil
        if shutil.which("pbpaste"):
            return subprocess.run(
                ["pbpaste"], capture_output=True, text=True, timeout=2
            ).stdout or ""
        if shutil.which("xclip"):
            return subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True, timeout=2,
            ).stdout or ""
        if shutil.which("xsel"):
            return subprocess.run(
                ["xsel", "--clipboard", "--output"],
                capture_output=True, text=True, timeout=2,
            ).stdout or ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _set_clipboard(text: str) -> bool:
    """Write text to system clipboard. Returns True if successful."""
    if not text:
        return True
    try:
        import shutil
        if shutil.which("pbcopy"):
            subprocess.run(
                ["pbcopy"], input=text, capture_output=True, text=True, timeout=2
            )
            return True
        if shutil.which("xclip"):
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text, capture_output=True, text=True, timeout=2,
            )
            return True
        if shutil.which("xsel"):
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text, capture_output=True, text=True, timeout=2,
            )
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


# ============================================================================
# Message input: Enter=send, Ctrl+Enter=newline, Tab=toggle mode (OpenCode-style)
# ============================================================================


class MessageInputSubmit(Message):
    """Emitted when user presses Enter to send."""

    pass


class MessageInputTabMode(Message):
    """Emitted when user presses Tab to switch Plan/Edit mode."""

    pass


class MessageInputWidget(Input):
    """Input: Enter=send, Ctrl+Enter=add newline to message, Tab=toggle Plan/Edit mode."""

    def action_delete_left(self) -> None:
        """Backspace: delete character before cursor. Override so it works when bindings fire instead of on_key."""
        pos = self.cursor_position
        if pos > 0:
            self.value = self.value[: pos - 1] + self.value[pos:]
            self.cursor_position = pos - 1

    def action_delete_right(self) -> None:
        """Delete: remove character after cursor. Override so it works when bindings fire instead of on_key."""
        pos = self.cursor_position
        n = len(self.value)
        if pos < n:
            self.value = self.value[:pos] + self.value[pos + 1 :]

    def on_key(self, event: Key) -> None:
        """Handle key so Enter sends, Ctrl+Enter adds newline, Tab toggles mode. Textual dispatches Key events to on_key."""
        key = (event.key or "").lower()
        # Let Ctrl+C always quit the app (Input would otherwise consume it)
        if key == "ctrl+c":
            self.app.exit()
            # Force process exit after Textual cleanup using threading (works even when event loop is shutting down)
            threading.Timer(0.2, lambda: os._exit(0)).start()
            event.prevent_default()
            return
        # Textual encodes modifiers in key string (e.g. ctrl+enter), not event.ctrl_key
        is_ctrl_enter = key in ("ctrl+enter", "ctrl+return")
        is_return = key in ("enter", "return")
        if is_ctrl_enter:
            self.value += "\n"
            event.prevent_default()
            return
        if is_return:
            self.post_message(MessageInputSubmit())
            event.prevent_default()
            return
        if key == "tab":
            self.post_message(MessageInputTabMode())
            event.prevent_default()
            return
        # Always handle editing keys ourselves so they work regardless of base Input's on_key
        pos = self.cursor_position
        n = len(self.value)
        if key == "left":
            self.cursor_position = max(0, pos - 1)
            event.prevent_default()
            return
        if key == "right":
            self.cursor_position = min(n, pos + 1)
            event.prevent_default()
            return
        if key in ("home", "ctrl+a"):
            self.cursor_position = 0
            event.prevent_default()
            return
        if key in ("end", "ctrl+e"):
            self.cursor_position = n
            event.prevent_default()
            return
        if key == "backspace":
            if pos > 0:
                self.value = self.value[:pos - 1] + self.value[pos:]
                self.cursor_position = pos - 1
            event.prevent_default()
            event.stop()
            return
        if key == "delete":
            if pos < n:
                self.value = self.value[:pos] + self.value[pos + 1:]
            event.prevent_default()
            event.stop()
            return
        # Typing: use parent's on_key if available, else insert character ourselves
        parent_on_key = getattr(super(), "on_key", None)
        if callable(parent_on_key):
            parent_on_key(event)
        else:
            char = getattr(event, "character", None)
            if char:
                self.value = self.value[:pos] + char + self.value[pos:]
                self.cursor_position = pos + 1
                event.prevent_default()


# ============================================================================
# Permission confirmation dialog
# ============================================================================


# ============================================================================
# Configuration
# ============================================================================

SERVER_URL = "http://localhost:8000"
DEFAULT_MODE = "plan"


# ============================================================================
# Chat Widget
# ============================================================================

class ChatWidget(Container):
    """Chat interface widget."""
    
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+r", "clear", "Clear"),
        Binding("ctrl+shift+c", "copy_log", "Copy log"),
        Binding("ctrl+v", "paste", "Paste"),
    ]
    
    def __init__(self, server_url: str = SERVER_URL, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_url = server_url
        self.client = httpx.AsyncClient(timeout=300.0)  # 5 minute timeout for long operations
        self.mode = reactive(DEFAULT_MODE)
        self.session_id: Optional[str] = None  # Current session ID
        self.workspace_root: Optional[str] = None  # Current workspace
        self.model_name: str = ""  # From server /health
        self._log_tail: deque = deque(maxlen=100)  # plain-text tail for copy
        self._pending_permission: Optional[dict] = None  # Current permission awaiting response
        self._permission_reply_event: Optional[asyncio.Event] = None  # Signal when user responds
        self._permission_reply_value: Optional[str] = None  # User's choice
    
    def compose(self) -> ComposeResult:
        """Create child widgets. Main area: left 1/3 messages, right 2/3 tool/terminal output."""
        yield Header(show_clock=True)
        
        with Vertical(id="chat-container"):
            yield Static("", id="title")
            with Horizontal(id="main-split"):
                with Container(id="panel-left"):
                    yield CopyableRichLog(id="chat-log", markup=True, wrap=True, log_tail=self._log_tail)
                with Container(id="panel-right"):
                    yield CopyableRichLog(id="tool-output", markup=True, wrap=True)
            
            with Horizontal(id="input-container"):
                yield MessageInputWidget(
                    placeholder="Message. /init /help … Enter=send Ctrl+Enter=newline",
                    id="message-input",
                )
                yield Button("Send", id="send-button", variant="primary")
            
            yield Static("", id="status-bar")
            yield Static("", id="hint-bar")
        
        yield Footer()
    
    def _focus_input(self) -> None:
        """Route focus to the message input so keyboard input goes there."""
        try:
            self.query_one("#message-input", MessageInputWidget).focus()
        except Exception:
            pass

    def on_mount(self) -> None:
        """Called when widget is mounted."""
        self.workspace_root = os.getenv("OPENSCRUM_WORKSPACE_ROOT", os.getcwd())
        self._set_chat_log_file()
        self._clear_logs_on_start()
        self._focus_input()
        self._update_footer_mode()
        self._update_hint_bar()
        asyncio.create_task(self._fetch_model())
        asyncio.create_task(self.ensure_session())
    
    async def on_unmount(self) -> None:
        """Called when widget is unmounted - cleanup resources."""
        try:
            await self.client.aclose()
        except Exception:
            pass

    def _clear_logs_on_start(self) -> None:
        """Clear chatbox.md and toolbox.md, chat log, and tool output when TUI starts."""
        root = (self.workspace_root or "").strip()
        if root:
            chat_path = Path(root) / "chatbox.md"
            tool_path = Path(root) / "toolbox.md"
            if chat_path.parent.exists():
                try:
                    chat_path.write_text("# OpenScrum Chat\n\n", encoding="utf-8")
                    tool_path.write_text("# OpenScrum Tool Output\n\n", encoding="utf-8")
                except Exception:
                    pass
        self._log_tail.clear()
        try:
            chat_log = self.query_one("#chat-log", CopyableRichLog)
            chat_log.clear()
        except Exception:
            pass
        try:
            self.query_one("#tool-output", CopyableRichLog).clear()
        except Exception:
            pass

    def _set_chat_log_file(self) -> None:
        """Point chat log to workspace_root/chatbox.md and tool output to toolbox.md."""
        root = (self.workspace_root or "").strip()
        if not root:
            return
        chat_path = Path(root) / "chatbox.md"
        tool_path = Path(root) / "toolbox.md"
        if not chat_path.is_file() and chat_path.parent.exists():
            try:
                chat_path.write_text("# OpenScrum Chat\n\n", encoding="utf-8")
            except Exception:
                pass
        if not tool_path.is_file() and tool_path.parent.exists():
            try:
                tool_path.write_text("# OpenScrum Tool Output\n\n", encoding="utf-8")
            except Exception:
                pass
        try:
            chat_widget = self.query_one("#chat-log", CopyableRichLog)
            chat_widget._log_file_path = chat_path
        except Exception:
            pass
        try:
            tool_widget = self.query_one("#tool-output", CopyableRichLog)
            tool_widget._log_file_path = tool_path
        except Exception:
            pass
    
    async def _ask_permission_reply(
        self, request_id: str, permission: str, patterns: list, tool_name: str
    ) -> Optional[str]:
        """Show permission inline in chat and wait for keyboard input."""
        if not request_id:
            return None
        
        chat_log = self.query_one("#chat-log", CopyableRichLog)
        
        # Store permission info
        self._pending_permission = {
            "id": request_id,
            "permission": permission,
            "patterns": patterns,
            "tool_name": tool_name,
        }
        self._permission_reply_event = asyncio.Event()
        self._permission_reply_value = None
        
        # Blur input so it doesn't capture keys - don't focus anything specific
        # so keys bubble up to App level
        try:
            input_widget = self.query_one("#message-input", Input)
            input_widget.blur()
        except Exception:
            pass
        
        # Wait for user to press a key
        await self._permission_reply_event.wait()
        
        # Clear pending permission and restore focus to input
        reply = self._permission_reply_value
        self._pending_permission = None
        self._permission_reply_event = None
        self._permission_reply_value = None
        self._focus_input()
        
        return reply

    async def ensure_session(self) -> None:
        """Ensure we have an active session, create one if needed."""
        if self.session_id:
            return
        
        try:
            # Workspace root is where the user started the TUI (set by
            # OPENSCRUM_WORKSPACE_ROOT in the launcher, or fallback to cwd).
            workspace = os.getenv("OPENSCRUM_WORKSPACE_ROOT", os.getcwd())
            self.workspace_root = workspace
            
            # Create new session, explicitly telling the server our workspace root.
            response = await self.client.post(
                f"{self.server_url}/sessions",
                params={"directory": workspace},
            )
            response.raise_for_status()
            session = response.json()
            self.session_id = session["id"]
            
            chat_log = self.query_one("#chat-log", CopyableRichLog)
            chat_log.write(f"[dim]Session created: {self.session_id[:8]}...[/dim]")
            self._set_chat_log_file()
            self._update_footer_mode()
            await self._fetch_model()
        except Exception as e:
            # Fallback to stateless mode if sessions not available
            chat_log = self.query_one("#chat-log", CopyableRichLog)
            chat_log.write(f"[dim]Note: Session management unavailable, using stateless mode[/dim]")
    
    async def _fetch_model(self) -> None:
        """Fetch model name from server /health."""
        try:
            r = await self.client.get(f"{self.server_url}/health")
            if r.status_code == 200:
                data = r.json()
                self.model_name = (data.get("model") or "").strip()
                self._update_footer_mode()
                self._update_hint_bar()
        except Exception:
            pass

    def _update_footer_mode(self) -> None:
        """Update title bar with workspace, model, and mode (Plan/Edit)."""
        try:
            title = self.query_one("#title", Static)
            mode_label = "Plan" if self.mode == "plan" else "Edit"
            workspace = (self.workspace_root or "").strip() or "(no workspace)"
            model = (self.model_name or "").strip() or "—"
            title.update(
                f"[bold cyan]OpenScrum Agent[/bold cyan] • [dim]{workspace}[/dim] • [dim]{model}[/dim] • [bold]{mode_label}[/]"
            )
        except Exception:
            pass

    def _update_hint_bar(self) -> None:
        """Update bottom hint bar with Tab/Enter/commands."""
        try:
            bar = self.query_one("#hint-bar", Static)
            bar.update(
                "[dim]Tab=switch Plan/Edit   Enter=send   Ctrl+Enter=newline   /init /help[/dim]"
            )
        except Exception:
            pass

    def _set_status(self, msg: str) -> None:
        """Update the live status bar at the bottom (Sending, Receiving, Tool: x, etc.)."""
        try:
            self.query_one("#status-bar", Static).update(f"[bold cyan]{msg}[/bold cyan]")
        except Exception:
            pass

    def _write_tool_output(self, text: str) -> None:
        """Append to the right-panel tool/terminal output (no markup)."""
        try:
            self.query_one("#tool-output", CopyableRichLog).write(text)
        except Exception:
            pass

    @on(MessageInputTabMode)
    def on_tab_mode(self) -> None:
        """Tab: switch between Plan and Edit mode (OpenCode agent_cycle style)."""
        self.mode = "edit" if self.mode == "plan" else "plan"
        self._update_footer_mode()
        self._update_hint_bar()
        chat_log = self.query_one("#chat-log", CopyableRichLog)
        label = "Plan (read-only)" if self.mode == "plan" else "Edit (with tools)"
        chat_log.write(f"[dim]Mode: [bold]{label}[/bold][/dim]")

    @on(Button.Pressed, "#send-button")
    @on(MessageInputSubmit)
    async def on_send(self) -> None:
        """Handle send button or Enter key."""
        input_widget = self.query_one("#message-input", MessageInputWidget)
        raw = input_widget.value.strip()
        
        if not raw:
            # If there's a pending permission, treat empty Enter as approval (once)
            if self._pending_permission and self._permission_reply_event:
                chat_log = self.query_one("#chat-log", CopyableRichLog)
                chat_log.write("✓ [green]Approved (once)[/green]")
                self._permission_reply_value = "once"
                self._permission_reply_event.set()
            return
        
        # Clear input
        input_widget.value = ""
        
        # Display user message
        chat_log = self.query_one("#chat-log", CopyableRichLog)
        chat_log.write(f"[bold green]You[/bold green]: {raw}")
        
        # Built-in commands start with / (OpenCode-style)
        command = None
        message = raw
        raw_lower = raw.strip().lower()
        if raw_lower == "/init":
            command = "init"
            message = ""
        elif raw_lower == "/help":
            chat_log = self.query_one("#chat-log", CopyableRichLog)
            chat_log.write(
                "[dim]Commands: /init (create AGENTS.md), /help (this). "
                "Tab=Plan/Edit, Enter=send, Ctrl+Enter=newline.[/dim]"
            )
            input_widget.value = ""
            self._focus_input()
            return
        
        await self.send_message(message, command=command)
    
    async def send_message(self, message: str, command: Optional[str] = None) -> None:
        """
        Send message to server and stream response.
        Uses session-based endpoint if available, falls back to /chat.
        
        Args:
            message: User message to send
            command: Optional command (e.g. "init") for server to substitute prompt and run
        """
        chat_log = self.query_one("#chat-log", CopyableRichLog)
        
        try:
            self._set_status("Sending...")
            # Ensure we have a session
            await self.ensure_session()
            
            self._set_status("Thinking...")
            # Show thinking indicator
            chat_log.write("[dim]Agent is thinking...[/dim]")
            
            # Prepare request (reactive is not JSON-serializable; send plain string)
            request_data: dict = {
                "message": message,
                "mode": "plan" if self.mode == "plan" else "edit",
            }
            if command:
                request_data["command"] = command
            
            # Use session endpoint if we have a session_id
            if self.session_id:
                endpoint = f"{self.server_url}/sessions/{self.session_id}/message"
            else:
                # Fallback to stateless /chat endpoint
                endpoint = f"{self.server_url}/chat"
                if self.workspace_root:
                    request_data["workspace_root"] = self.workspace_root
            
            # Stream response
            async with self.client.stream(
                "POST",
                endpoint,
                json=request_data,
            ) as response:
                if response.status_code >= 400:
                    body = ""
                    try:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                    except Exception:
                        pass
                    try:
                        detail = json.loads(body).get("detail", body) if body else response.reason_phrase
                    except Exception:
                        detail = body or response.reason_phrase
                    chat_log.write(f"[bold red]HTTP {response.status_code}:[/bold red] {detail}")
                    self._set_status("Error")
                    return
                self._set_status("Receiving...")
                current_content = ""
                stream_buffer = ""  # buffer for streaming tokens (RichLog has no end="")
                agent_message_started = False
                agent_line_prefix = True  # prepend "Agent: " on first line only
                
                def flush_agent_stream():
                    nonlocal stream_buffer, agent_line_prefix
                    if not stream_buffer:
                        return
                    if agent_line_prefix:
                        chat_log.write(f"[bold cyan]Agent[/bold cyan]: {stream_buffer}")
                        agent_line_prefix = False
                    else:
                        chat_log.write(stream_buffer)
                    stream_buffer = ""

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    
                    try:
                        data = json.loads(line[6:].strip())  # Remove "data: " prefix
                        chunk_type = data.get("type")
                        
                        if chunk_type == "token":
                            self._set_status("Receiving...")
                            if not agent_message_started:
                                agent_message_started = True
                                agent_line_prefix = True
                            content = data.get("content", "")
                            current_content += content
                            stream_buffer += content
                            # Flush on newline so we show progress (RichLog.write() has no end=)
                            while "\n" in stream_buffer:
                                idx = stream_buffer.index("\n") + 1
                                line_chunk = stream_buffer[:idx].rstrip("\n")
                                stream_buffer = stream_buffer[idx:]
                                if agent_line_prefix:
                                    chat_log.write(f"[bold cyan]Agent[/bold cyan]: {line_chunk}")
                                    agent_line_prefix = False
                                else:
                                    chat_log.write(line_chunk)
                        
                        elif chunk_type == "tool_call":
                            tool_name = data.get("tool_name") or "tool"
                            self._set_status(f"Tool: {tool_name}")
                            if not agent_message_started:
                                agent_message_started = True
                            else:
                                flush_agent_stream()
                                agent_message_started = False
                            current_content = ""
                            
                            tool_name = data.get("tool_name")
                            tool_input = data.get("tool_input", {})
                            current_tool = tool_name
                            chat_log.write(
                                f"[yellow]🔧 Calling tool: [bold]{tool_name}[/bold][/yellow]"
                            )
                            # Right panel: terminal-style header and command/cwd
                            self._write_tool_output(f"\n[bold]--- Tool: {tool_name} ---[/bold]\n")
                            try:
                                workspace = (self.workspace_root or "").strip() or os.getenv("OPENSCRUM_WORKSPACE_ROOT", os.getcwd())
                                effective_cwd = None
                                if tool_name == "bash":
                                    cmd = (tool_input or {}).get("command")
                                    workdir = (tool_input or {}).get("workdir")
                                    if cmd:
                                        chat_log.write(f"[dim]  command: {cmd}[/dim]")
                                        self._write_tool_output(f"[dim]$[/dim] {cmd}\n")
                                    if workdir:
                                        chat_log.write(f"[dim]  workdir: {workdir}[/dim]")
                                    if workdir:
                                        effective_cwd = str((Path(workspace) / workdir).resolve())
                                    elif workspace:
                                        effective_cwd = str(Path(workspace).resolve())
                                    if effective_cwd:
                                        chat_log.write(f"[dim]  cwd: {effective_cwd}[/dim]")
                                        self._write_tool_output(f"[dim]cwd: {effective_cwd}[/dim]\n")
                                else:
                                    if workspace:
                                        effective_cwd = str(Path(workspace).resolve())
                                        if effective_cwd:
                                            chat_log.write(f"[dim]  cwd: {effective_cwd}[/dim]")
                                    if tool_input:
                                        input_str = json.dumps(tool_input, indent=2)
                                        if len(input_str) > 200:
                                            input_str = input_str[:200] + "..."
                                        chat_log.write(f"[dim]  Input: {input_str}[/dim]")
                                        self._write_tool_output(f"[dim]{input_str}[/dim]\n")
                            except Exception:
                                pass
                        
                        elif chunk_type == "permission_request":
                            self._set_status("Waiting for permission...")
                            # Don't clear: keep "Calling tool: X" visible, then show permission below
                            if agent_message_started:
                                flush_agent_stream()
                                agent_message_started = False
                            perm = data.get("permission_request") or {}
                            req_id = perm.get("id")
                            perm_name = perm.get("permission", "?")
                            patterns = perm.get("patterns", [])
                            metadata = perm.get("metadata") or {}
                            tool_name = metadata.get("tool", "?")
                            
                            # Show clear permission request in chat
                            chat_log.write("")
                            chat_log.write(f"[yellow]━━━ Permission Required ━━━[/yellow]")
                            chat_log.write(f"[yellow]Tool: [bold]{tool_name}[/bold][/yellow]")
                            chat_log.write(f"[yellow]Action: {perm_name}[/yellow]")
                            for pattern in patterns:
                                chat_log.write(f"[yellow]  • {pattern}[/yellow]")
                            # Also show effective working directory for the pending tool, when known.
                            try:
                                workspace = (self.workspace_root or "").strip() or os.getenv("OPENSCRUM_WORKSPACE_ROOT", os.getcwd())
                                args = metadata.get("args") or {}
                                effective_cwd = None
                                if tool_name == "bash":
                                    workdir = args.get("workdir")
                                    if workdir:
                                        effective_cwd = str((Path(workspace) / workdir).resolve())
                                    elif workspace:
                                        effective_cwd = str(Path(workspace).resolve())
                                elif workspace:
                                    effective_cwd = str(Path(workspace).resolve())
                                if effective_cwd:
                                    chat_log.write(f"[dim]  cwd: {effective_cwd}[/dim]")
                            except Exception:
                                pass
                            # For bash, also show the actual command being requested.
                            if tool_name == "bash":
                                try:
                                    cmd = (metadata.get("args") or {}).get("command")
                                    if cmd:
                                        chat_log.write(f"[yellow]  Command: [bold]{cmd}[/bold][/yellow]")
                                except Exception:
                                    pass
                            
                            # Show prompt for user response
                            chat_log.write(f"[green]✓ [O]nce[/green] | [green]✓ [A]lways[/green] | [red]✗ [R]eject[/red]")
                            chat_log.write("")
                            
                            reply = await self._ask_permission_reply(
                                req_id, perm_name, patterns, tool_name
                            )
                            # chat_log.write(f"[dim]DEBUG: User replied: {reply}[/dim]")
                            if reply and req_id:
                                # Await the reply so the server gets it before we read more
                                # (matches test script behaviour and avoids races).
                                try:
                                    # chat_log.write(f"[dim]DEBUG: Sending reply to server...[/dim]")
                                    await self.client.post(
                                        f"{self.server_url}/permissions/{req_id}/reply",
                                        json={"reply": reply},
                                        timeout=10.0,
                                    )
                                    # chat_log.write(f"[dim]DEBUG: Reply sent successfully[/dim]")
                                    # Show we sent the reply and are waiting for tool to run (avoids looking stuck)
                                    # For bash, show the full command in status line
                                    if tool_name == "bash":
                                        try:
                                            cmd = (metadata.get("args") or {}).get("command", "")
                                            if cmd:
                                                # Truncate long commands to fit status bar
                                                max_len = 80
                                                if len(cmd) > max_len:
                                                    cmd = cmd[:max_len-3] + "..."
                                                self._set_status(f"Running: {cmd}")
                                            else:
                                                self._set_status(f"Running tool: {tool_name}...")
                                        except Exception:
                                            self._set_status(f"Running tool: {tool_name}...")
                                    else:
                                        self._set_status(f"Running tool: {tool_name}...")
                                except Exception as e:
                                    chat_log.write(f"[red]Permission reply failed: {e}[/red]")
                                    self._set_status("Error")
                        
                        elif chunk_type == "tool_result":
                            tool_name = data.get("tool_name") or current_tool
                            self._set_status(f"Done: {tool_name}" if tool_name else "Receiving...")
                            if not agent_message_started:
                                agent_message_started = True
                            # Tool result
                            tool_output = data.get("tool_output", "")
                            tool_name = data.get("tool_name") or current_tool
                            
                            if tool_name:
                                # Only show in tool output panel (right side), not in chat
                                if tool_output:
                                    self._write_tool_output(tool_output if tool_output.endswith("\n") else tool_output + "\n")
                                    self._write_tool_output("[dim]--- done ---[/dim]\n")
                                current_tool = None
                        
                        elif chunk_type == "done":
                            self._set_status("Ready")
                            if agent_message_started:
                                flush_agent_stream()
                                agent_message_started = False
                            else:
                                # No token/tool_call received — show placeholder (don't clear; keep user message visible)
                                chat_log.write("[dim]Agent: (no output)[/dim]")
                            current_content = ""
                            chat_log.write("[dim]---[/dim]")
                        
                        elif chunk_type == "error":
                            self._set_status("Error")
                            error_msg = data.get("content", "Unknown error")
                            chat_log.write(f"[bold red]Error:[/bold red] {error_msg}")
                        else:
                            # Unknown chunk type — avoid writing raw payload; log type only for debugging
                            unknown = data.get("type", "?")
                            chat_log.write(f"[dim]Received unknown event: {unknown}[/dim]")
                    
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        self._set_status("Error")
                        chat_log.write(f"[bold red]Error processing chunk:[/bold red] {str(e)}")
        
        except httpx.HTTPStatusError as e:
            detail = str(e)
            try:
                body = getattr(e.response, "text", None) or getattr(e.response, "content", b"").decode("utf-8", errors="replace")
                if body:
                    detail = json.loads(body).get("detail", body)
            except Exception:
                pass
            self._set_status("Error")
            chat_log.write(f"[bold red]HTTP {e.response.status_code}:[/bold red] {detail}")
        except httpx.HTTPError as e:
            self._set_status("Error")
            chat_log.write(f"[bold red]HTTP Error:[/bold red] {str(e)}")
        except Exception as e:
            self._set_status("Error")
            chat_log.write(f"[bold red]Error:[/bold red] {str(e)}")
        finally:
            self._set_status("")
            self._focus_input()
    
    def action_clear(self) -> None:
        """Clear chat log and tool output panel."""
        chat_log = self.query_one("#chat-log", CopyableRichLog)
        chat_log.clear()
        self._log_tail.clear()
        try:
            self.query_one("#tool-output", CopyableRichLog).clear()
        except Exception:
            pass
        self._focus_input()

    def action_copy_log(self) -> None:
        """Copy last 80 lines of chat log (plain text) to clipboard."""
        lines = list(self._log_tail)[-80:]
        text = "\n".join(lines).strip()
        if not text:
            self._focus_input()
            return
        if _set_clipboard(text):
            chat_log = self.query_one("#chat-log", CopyableRichLog)
            chat_log.write("[dim]Copied to clipboard (Ctrl+Shift+C). Paste here or in another app with Ctrl+V.[/dim]")
        else:
            chat_log = self.query_one("#chat-log", CopyableRichLog)
            chat_log.write("[dim]Clipboard not available (install pbcopy on macOS or xclip/xsel on Linux).[/dim]")
        self._focus_input()

    def action_paste(self) -> None:
        """Paste from clipboard into the message input."""
        text = _get_clipboard()
        if not text:
            self._focus_input()
            return
        try:
            input_widget = self.query_one("#message-input", Input)
            input_widget.value = input_widget.value + text
        except Exception:
            pass
        self._focus_input()

    def action_quit(self) -> None:
        """Quit application."""
        self.app.exit()


# ============================================================================
# Main App
# ============================================================================

class OpenScrumApp(App):
    """Main Textual application."""
    
    CSS = """
    #chat-container {
        height: 1fr;
        padding: 1;
    }
    
    #title {
        text-align: center;
        padding: 1;
        border-bottom: solid $primary;
    }
    
    #main-split {
        height: 1fr;
        min-height: 5;
    }
    
    #panel-left {
        width: 2fr;
        min-width: 20;
        height: 100%;
        border: solid $primary;
        padding: 1;
        margin: 0 1 0 0;
    }
    
    #panel-right {
        width: 1fr;
        min-width: 12;
        height: 100%;
        border: solid $primary;
        padding: 1;
        margin: 0;
    }
    
    #chat-log {
        height: 1fr;
        padding: 0;
        margin: 0;
        border: none;
    }
    
    #chat-log:focus {
        border: solid $accent;
    }
    
    #tool-output {
        height: 1fr;
        padding: 0;
        margin: 0;
        border: none;
        text-style: dim;
    }
    
    RichLog {
        scrollbar-size: 1 1;
    }
    
    #tool-output RichLog {
        text-opacity: 70%;
    }
    
    #tool-output {
        height: 1fr;
        padding: 0;
        margin: 0;
        border: none;
        background: $surface-darken-1;
    }
    
    #input-container {
        height: auto;
        padding: 1;
        border-top: solid $primary;
    }
    
    #status-bar {
        height: auto;
        padding: 0 1;
        text-align: left;
        border-top: solid $primary 30%;
        color: $primary;
    }
    
    #hint-bar {
        height: auto;
        padding: 0 1 1 1;
        text-align: center;
        border-top: solid $primary 50%;
    }
    
    #message-input {
        width: 1fr;
        margin-right: 1;
    }
    
    #send-button {
        margin-right: 1;
    }
    """
    
    TITLE = "OpenScrum Agent"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+shift+c", "copy_log", "Copy log"),
        Binding("ctrl+v", "paste", "Paste"),
        Binding("ctrl+t", "test_permission", "Test Permission", show=False),
        Binding("o", "permission_once", "", show=False, priority=True),
        Binding("a", "permission_always", "", show=False, priority=True),
        Binding("r", "permission_reject", "", show=False, priority=True),
    ]

    def __init__(self, server_url: str = SERVER_URL, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_url = server_url

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield ChatWidget(server_url=self.server_url)

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()
        # Force process exit using threading (works even when event loop is shutting down)
        threading.Timer(0.2, lambda: os._exit(0)).start()

    def action_copy_log(self) -> None:
        """Copy chat log to clipboard (works from any focus)."""
        try:
            chat = self.query_one(ChatWidget)
            chat.action_copy_log()
        except Exception:
            pass

    def action_paste(self) -> None:
        """Paste from clipboard into message input (works from any focus)."""
        try:
            chat = self.query_one(ChatWidget)
            chat.action_paste()
        except Exception:
            pass
    
    def action_permission_once(self) -> None:
        """Handle O key for permission approval (once)."""
        try:
            chat = self.query_one(ChatWidget)
            if chat._pending_permission and chat._permission_reply_event:
                chat_log = chat.query_one("#chat-log", CopyableRichLog)
                chat_log.write("✓ [green]Approved (once)[/green]")
                chat._permission_reply_value = "once"
                chat._permission_reply_event.set()
        except Exception as e:
            pass
    
    def action_permission_always(self) -> None:
        """Handle A key for permission approval (always)."""
        try:
            chat = self.query_one(ChatWidget)
            if chat._pending_permission and chat._permission_reply_event:
                chat_log = chat.query_one("#chat-log", CopyableRichLog)
                chat_log.write("✓ [green]Approved (always)[/green]")
                chat._permission_reply_value = "always"
                chat._permission_reply_event.set()
        except Exception as e:
            pass
    
    def action_permission_reject(self) -> None:
        """Handle R key for permission rejection."""
        try:
            chat = self.query_one(ChatWidget)
            if chat._pending_permission and chat._permission_reply_event:
                chat_log = chat.query_one("#chat-log", CopyableRichLog)
                chat_log.write("✗ [red]Rejected[/red]")
                chat._permission_reply_value = "reject"
                chat._permission_reply_event.set()
        except Exception as e:
            pass
    
    def action_test_permission(self) -> None:
        """Test permission handling with fake request (Ctrl+T)."""
        try:
            chat = self.query_one(ChatWidget)
            chat_log = chat.query_one("#chat-log", CopyableRichLog)
            
            # Simulate a permission request
            chat_log.write("")
            chat_log.write("[yellow]━━━ Permission Required (TEST) ━━━[/yellow]")
            chat_log.write("[yellow]Tool: [bold]bash[/bold][/yellow]")
            chat_log.write("[yellow]Action: bash[/yellow]")
            chat_log.write("[yellow]  • test command[/yellow]")
            chat_log.write("[yellow]  Command: [bold]echo 'test'[/bold][/yellow]")
            chat_log.write("[green]✓ [O]nce[/green] | [green]✓ [A]lways[/green] | [red]✗ [R]eject[/red]")
            chat_log.write("")
            
            # Set up fake permission state
            import asyncio
            test_id = "test_permission"
            chat._pending_permission = {
                "id": test_id,
                "permission": "bash",
                "patterns": ["test command"],
                "tool_name": "bash",
            }
            chat._permission_reply_event = asyncio.Event()
            chat._permission_reply_value = None
            
            # Set status
            chat._set_status("[O]nce | [A]lways | [R]eject - TEST MODE")
            
            # Blur input and focus chat log
            chat_log.focus()
            
            # Schedule cleanup after 30 seconds if no response
            async def cleanup():
                await asyncio.sleep(30)
                # Only show timeout if permission is still pending with same test ID
                if (chat._pending_permission and 
                    chat._pending_permission.get("id") == test_id):
                    chat_log.write("[dim]Test permission timed out[/dim]")
                    chat._pending_permission = None
                    chat._permission_reply_event = None
                    chat._permission_reply_value = None
                    chat._focus_input()
                    chat._set_status("")
            
            asyncio.create_task(cleanup())
            
        except Exception as e:
            pass
    
    def on_key(self, event: Key) -> None:
        """Handle permission response keys at app level (highest priority)."""
        key = (event.key or "").lower()
        
        # ALWAYS handle Ctrl+C first, before any other logic
        if key == "ctrl+c":
            event.prevent_default()
            event.stop()
            # Exit Textual to restore terminal, then force process exit
            self.exit()
            async def force_exit():
                await asyncio.sleep(0.1)
                os._exit(0)
            asyncio.create_task(force_exit())
            return
        
        try:
            chat = self.query_one(ChatWidget)
            
            # Only handle permission keys if there's a pending permission
            if not chat._pending_permission or not chat._permission_reply_event:
                # No pending permission, let the event propagate normally
                return
            
            # Check for permission response keys - only handle o, a, r
            if key == "o":
                event.prevent_default()
                event.stop()
                chat_log = chat.query_one("#chat-log", CopyableRichLog)
                chat_log.write("✓ [green]Approved (once)[/green]")
                chat._permission_reply_value = "once"
                chat._permission_reply_event.set()
            elif key == "a":
                event.prevent_default()
                event.stop()
                chat_log = chat.query_one("#chat-log", CopyableRichLog)
                chat_log.write("✓ [green]Approved (always)[/green]")
                chat._permission_reply_value = "always"
                chat._permission_reply_event.set()
            elif key == "r":
                event.prevent_default()
                event.stop()
                chat_log = chat.query_one("#chat-log", CopyableRichLog)
                chat_log.write("✗ [red]Rejected[/red]")
                chat._permission_reply_value = "reject"
                chat._permission_reply_event.set()
            # For any other key when permission is pending, let it propagate
        except Exception:
            pass


# ============================================================================
# Entry Point
# ============================================================================

def main():
    """Run the TUI application."""
    import sys

    # Parse command line arguments
    server_url = (sys.argv[1] if len(sys.argv) > 1 else SERVER_URL).strip() or SERVER_URL

    try:
        app = OpenScrumApp(server_url=server_url)
        app.run()
    except Exception as e:
        # Ensure terminal gets control back on crash (e.g. restore echo, cursor)
        import traceback
        sys.stderr.write(f"OpenScrum TUI error: {e}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
