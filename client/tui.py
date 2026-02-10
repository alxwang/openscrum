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
import subprocess
from collections import deque
from pathlib import Path
from typing import Optional

import httpx
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Button, RichLog, Header, Footer, Static
from textual.binding import Binding
from textual.reactive import reactive


class CopyableRichLog(RichLog):
    """RichLog that keeps a plain-text tail for copy and optionally appends to a workspace MD file."""

    def __init__(self, *args, log_tail: Optional[deque] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._log_tail = log_tail
        self._log_file_path: Optional[Path] = None  # set by ChatWidget to workspace_root/openscrum-chat.md

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

    def _on_key(self, event: Key) -> None:
        key = (event.key or "").lower()
        # Let Ctrl+C always quit the app (Input would otherwise consume it)
        if key == "ctrl+c":
            self.app.exit()
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
        super()._on_key(event)


# ============================================================================
# Permission confirmation dialog
# ============================================================================


class PermissionScreen(ModalScreen[str]):
    """Modal to confirm or reject a tool permission (once / always / reject)."""

    BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

    def __init__(self, request_id: str, permission: str, patterns: list, tool_name: str) -> None:
        super().__init__()
        self._request_id = request_id
        self._permission = permission
        self._patterns = patterns
        self._tool_name = tool_name

    def action_quit(self) -> None:
        self.app.exit()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                f"[bold]Permission: {self._permission}[/bold] ([dim]{self._tool_name}[/dim])\n"
                f"Patterns: {self._patterns}\n\n"
                "[dim]Tip: Use [Always] to allow all similar requests this session (e.g. multiple webfetch).[/dim]"
            )
            with Horizontal():
                yield Button("Once", id="once", variant="primary")
                yield Button("Always", id="always", variant="success")
                yield Button("Reject", id="reject", variant="error")

    @on(Button.Pressed, "#once")
    def once(self) -> None:
        self.dismiss("once")

    @on(Button.Pressed, "#always")
    def always(self) -> None:
        self.dismiss("always")

    @on(Button.Pressed, "#reject")
    def reject(self) -> None:
        self.dismiss("reject")


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
    
    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=True)
        
        with Vertical(id="chat-container"):
            yield Static("", id="title")
            yield CopyableRichLog(id="chat-log", markup=True, wrap=True, log_tail=self._log_tail)
            
            with Horizontal(id="input-container"):
                yield MessageInputWidget(
                    placeholder="Message. /init /help … Enter=send Ctrl+Enter=newline",
                    id="message-input",
                )
                yield Button("Send", id="send-button", variant="primary")
            
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
        self._focus_input()
        self._update_footer_mode()
        self._update_hint_bar()
        asyncio.create_task(self._fetch_model())
        asyncio.create_task(self.ensure_session())

    def _set_chat_log_file(self) -> None:
        """Point chat log to workspace_root/openscrum-chat.md for easy access."""
        root = (self.workspace_root or "").strip()
        if not root:
            return
        path = Path(root) / "openscrum-chat.md"
        if not path.is_file() and path.parent.exists():
            try:
                path.write_text("# OpenScrum Chat\n\n", encoding="utf-8")
            except Exception:
                pass
        try:
            log_widget = self.query_one("#chat-log", CopyableRichLog)
            log_widget._log_file_path = path
        except Exception:
            pass
    
    async def _ask_permission_reply(
        self, request_id: str, permission: str, patterns: list, tool_name: str
    ) -> Optional[str]:
        """Show permission dialog and return user choice: once, always, or reject."""
        if not request_id:
            return None
        try:
            screen = PermissionScreen(request_id, permission, patterns, tool_name)
            result = await self.app.push_screen(screen)
            self._focus_input()
            return result
        except Exception:
            self._focus_input()
            return "once"  # Default allow once if dialog fails

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
            
            chat_log = self.query_one("#chat-log", RichLog)
            chat_log.write(f"[dim]Session created: {self.session_id[:8]}...[/dim]")
            self._set_chat_log_file()
            self._update_footer_mode()
            await self._fetch_model()
        except Exception as e:
            # Fallback to stateless mode if sessions not available
            chat_log = self.query_one("#chat-log", RichLog)
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

    @on(MessageInputTabMode)
    def on_tab_mode(self) -> None:
        """Tab: switch between Plan and Edit mode (OpenCode agent_cycle style)."""
        self.mode = "edit" if self.mode == "plan" else "plan"
        self._update_footer_mode()
        self._update_hint_bar()
        chat_log = self.query_one("#chat-log", RichLog)
        label = "Plan (read-only)" if self.mode == "plan" else "Edit (with tools)"
        chat_log.write(f"[dim]Mode: [bold]{label}[/bold][/dim]")

    @on(Button.Pressed, "#send-button")
    @on(MessageInputSubmit)
    async def on_send(self) -> None:
        """Handle send button or Enter key."""
        input_widget = self.query_one("#message-input", MessageInputWidget)
        raw = input_widget.value.strip()
        
        if not raw:
            return
        
        # Clear input
        input_widget.value = ""
        
        # Display user message
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write(f"[bold green]You[/bold green]: {raw}")
        
        # Built-in commands start with / (OpenCode-style)
        command = None
        message = raw
        raw_lower = raw.strip().lower()
        if raw_lower == "/init":
            command = "init"
            message = ""
        elif raw_lower == "/help":
            chat_log = self.query_one("#chat-log", RichLog)
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
        chat_log = self.query_one("#chat-log", RichLog)
        
        try:
            # Ensure we have a session
            await self.ensure_session()
            
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
                    return
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
                        data = json.loads(line[6:])  # Remove "data: " prefix
                        chunk_type = data.get("type")
                        
                        if chunk_type == "token":
                            if not agent_message_started:
                                chat_log.clear()
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
                            if not agent_message_started:
                                chat_log.clear()
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
                            # For bash, show the actual command (and optional workdir).
                            if tool_name == "bash":
                                try:
                                    cmd = (tool_input or {}).get("command")
                                    workdir = (tool_input or {}).get("workdir")
                                    if cmd:
                                        chat_log.write(f"[dim]  command: {cmd}[/dim]")
                                    if workdir:
                                        chat_log.write(f"[dim]  workdir: {workdir}[/dim]")
                                except Exception:
                                    pass
                            # Show effective working directory for commands (especially bash)
                            try:
                                workspace = (self.workspace_root or "").strip() or os.getenv("OPENSCRUM_WORKSPACE_ROOT", os.getcwd())
                                effective_cwd = None
                                if tool_name == "bash":
                                    workdir = (tool_input or {}).get("workdir")
                                    if workdir:
                                        effective_cwd = str((Path(workspace) / workdir).resolve())
                                    elif workspace:
                                        effective_cwd = str(Path(workspace).resolve())
                                elif workspace:
                                    # For non-bash tools, workspace root is the implicit working directory
                                    effective_cwd = str(Path(workspace).resolve())
                                if effective_cwd:
                                    chat_log.write(f"[dim]  cwd: {effective_cwd}[/dim]")
                            except Exception:
                                pass
                            if tool_input:
                                # Format tool input nicely
                                input_str = json.dumps(tool_input, indent=2)
                                if len(input_str) > 200:
                                    input_str = input_str[:200] + "..."
                                chat_log.write(f"[dim]  Input: {input_str}[/dim]")
                        
                        elif chunk_type == "permission_request":
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
                            chat_log.write(
                                f"[yellow]Permission: [bold]{perm_name}[/bold] ({tool_name}) "
                                f"for {patterns}[/yellow]"
                            )
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
                                        chat_log.write(f"[dim]  command: {cmd}[/dim]")
                                except Exception:
                                    pass
                            reply = await self._ask_permission_reply(
                                req_id, perm_name, patterns, tool_name
                            )
                            if reply and req_id:
                                # Fire-and-forget: don't block stream reading. Server needs the
                                # reply to unblock the tool; we must keep reading to receive
                                # tool_result and avoid deadlock (server writing while we're blocked).
                                async def _send_reply():
                                    try:
                                        await self.client.post(
                                            f"{self.server_url}/permissions/{req_id}/reply",
                                            json={"reply": reply},
                                            timeout=10.0,
                                        )
                                    except Exception as e:
                                        chat_log.write(f"[red]Permission reply failed: {e}[/red]")
                                asyncio.create_task(_send_reply())
                        
                        elif chunk_type == "tool_result":
                            if not agent_message_started:
                                chat_log.clear()
                                agent_message_started = True
                            # Tool result
                            tool_output = data.get("tool_output", "")
                            tool_name = data.get("tool_name") or current_tool
                            
                            if tool_name:
                                chat_log.write(
                                    f"[green]✓ Tool [bold]{tool_name}[/bold] completed[/green]"
                                )
                                if tool_output:
                                    # Truncate long outputs
                                    output_preview = tool_output[:300]
                                    if len(tool_output) > 300:
                                        output_preview += f"\n... ({len(tool_output) - 300} more characters)"
                                    # Show output in a code block style
                                    chat_log.write(f"[dim]{output_preview}[/dim]")
                                current_tool = None
                        
                        elif chunk_type == "done":
                            if agent_message_started:
                                flush_agent_stream()
                                agent_message_started = False
                            else:
                                # No token/tool_call received — clear "Agent is thinking..." and show placeholder
                                chat_log.clear()
                                chat_log.write("[dim]Agent: (no output)[/dim]")
                            current_content = ""
                            chat_log.write("[dim]---[/dim]")
                        
                        elif chunk_type == "error":
                            if not agent_message_started:
                                chat_log.clear()
                            error_msg = data.get("content", "Unknown error")
                            chat_log.write(f"[bold red]Error:[/bold red] {error_msg}")
                    
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        chat_log.write(f"[bold red]Error processing chunk:[/bold red] {str(e)}")
        
        except httpx.HTTPStatusError as e:
            detail = str(e)
            try:
                body = getattr(e.response, "text", None) or getattr(e.response, "content", b"").decode("utf-8", errors="replace")
                if body:
                    detail = json.loads(body).get("detail", body)
            except Exception:
                pass
            chat_log.write(f"[bold red]HTTP {e.response.status_code}:[/bold red] {detail}")
        except httpx.HTTPError as e:
            chat_log.write(f"[bold red]HTTP Error:[/bold red] {str(e)}")
        except Exception as e:
            chat_log.write(f"[bold red]Error:[/bold red] {str(e)}")
        finally:
            self._focus_input()
    
    def action_clear(self) -> None:
        """Clear chat log."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()
        self._log_tail.clear()
        self._focus_input()

    def action_copy_log(self) -> None:
        """Copy last 80 lines of chat log (plain text) to clipboard."""
        lines = list(self._log_tail)[-80:]
        text = "\n".join(lines).strip()
        if not text:
            self._focus_input()
            return
        if _set_clipboard(text):
            chat_log = self.query_one("#chat-log", RichLog)
            chat_log.write("[dim]Copied to clipboard (Ctrl+Shift+C). Paste here or in another app with Ctrl+V.[/dim]")
        else:
            chat_log = self.query_one("#chat-log", RichLog)
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
    
    #chat-log {
        height: 1fr;
        border: solid $primary;
        padding: 1;
        margin: 1;
    }
    
    #input-container {
        height: auto;
        padding: 1;
        border-top: solid $primary;
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
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+shift+c", "copy_log", "Copy log"),
        Binding("ctrl+v", "paste", "Paste"),
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


# ============================================================================
# Entry Point
# ============================================================================

def main():
    """Run the TUI application."""
    import sys
    
    # Parse command line arguments
    server_url = SERVER_URL
    if len(sys.argv) > 1:
        server_url = sys.argv[1]
    
    app = OpenScrumApp(server_url=server_url)
    app.run()


if __name__ == "__main__":
    main()
