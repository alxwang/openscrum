"""
Textual TUI Client for OpenScrum

Provides a terminal user interface for interacting with the OpenScrum agent.
"""

import asyncio
import json
from typing import Optional

import httpx
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Input, Button, RichLog, Header, Footer, Static
from textual.binding import Binding
from textual.reactive import reactive


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
    ]
    
    def __init__(self, server_url: str = SERVER_URL, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_url = server_url
        self.client = httpx.AsyncClient(timeout=300.0)  # 5 minute timeout for long operations
        self.mode = reactive(DEFAULT_MODE)
    
    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header(show_clock=True)
        
        with Vertical(id="chat-container"):
            yield Static("[bold cyan]OpenScrum Agent[/bold cyan]", id="title")
            yield RichLog(id="chat-log", markup=True, wrap=True)
            
            with Horizontal(id="input-container"):
                yield Input(
                    placeholder="Type your message... (Ctrl+Enter to send)",
                    id="message-input",
                )
                yield Button("Send", id="send-button", variant="primary")
                yield Button("Plan", id="plan-mode", variant="default")
                yield Button("Edit", id="edit-mode", variant="default")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when widget is mounted."""
        self.query_one("#message-input").focus()
        self.update_mode_buttons()
    
    def update_mode_buttons(self) -> None:
        """Update mode button states."""
        plan_btn = self.query_one("#plan-mode")
        edit_btn = self.query_one("#edit-mode")
        
        if self.mode == "plan":
            plan_btn.variant = "success"
            edit_btn.variant = "default"
        else:
            plan_btn.variant = "default"
            edit_btn.variant = "success"
    
    @on(Button.Pressed, "#send-button")
    @on(Input.Submitted, "#message-input")
    async def on_send(self) -> None:
        """Handle send button or Enter key."""
        input_widget = self.query_one("#message-input", Input)
        message = input_widget.value.strip()
        
        if not message:
            return
        
        # Clear input
        input_widget.value = ""
        
        # Display user message
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write(f"[bold green]You[/bold green]: {message}")
        
        # Send to server
        await self.send_message(message)
    
    @on(Button.Pressed, "#plan-mode")
    def on_plan_mode(self) -> None:
        """Switch to plan mode."""
        self.mode = "plan"
        self.update_mode_buttons()
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write("[dim]Mode: [bold]Plan[/bold] (read-only)[/dim]")
    
    @on(Button.Pressed, "#edit-mode")
    def on_edit_mode(self) -> None:
        """Switch to edit mode."""
        self.mode = "edit"
        self.update_mode_buttons()
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write("[dim]Mode: [bold]Edit[/bold] (with tools)[/dim]")
    
    async def send_message(self, message: str) -> None:
        """
        Send message to server and stream response.
        
        Args:
            message: User message to send
        """
        chat_log = self.query_one("#chat-log", RichLog)
        
        try:
            # Show thinking indicator
            chat_log.write("[dim]Agent is thinking...[/dim]")
            
            # Prepare request
            request_data = {
                "message": message,
                "mode": self.mode,
            }
            
            # Stream response
            async with self.client.stream(
                "POST",
                f"{self.server_url}/chat",
                json=request_data,
            ) as response:
                response.raise_for_status()
                
                current_content = ""
                current_tool = None
                agent_message_started = False
                
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    
                    try:
                        data = json.loads(line[6:])  # Remove "data: " prefix
                        chunk_type = data.get("type")
                        
                        if chunk_type == "token":
                            # Stream tokens incrementally
                            content = data.get("content", "")
                            
                            if not agent_message_started:
                                # Clear thinking indicator and start agent message
                                chat_log.clear()  # Clear last line (thinking indicator)
                                chat_log.write("[bold cyan]Agent[/bold cyan]: ", end="")
                                agent_message_started = True
                            
                            # Append content
                            chat_log.write(content, end="")
                            current_content += content
                        
                        elif chunk_type == "tool_call":
                            # Tool call started - finalize any pending agent message
                            if agent_message_started:
                                chat_log.write("")  # Newline
                                agent_message_started = False
                                current_content = ""
                            
                            tool_name = data.get("tool_name")
                            tool_input = data.get("tool_input", {})
                            current_tool = tool_name
                            chat_log.write(
                                f"[yellow]🔧 Calling tool: [bold]{tool_name}[/bold][/yellow]"
                            )
                            if tool_input:
                                # Format tool input nicely
                                input_str = json.dumps(tool_input, indent=2)
                                if len(input_str) > 200:
                                    input_str = input_str[:200] + "..."
                                chat_log.write(f"[dim]  Input: {input_str}[/dim]")
                        
                        elif chunk_type == "tool_result":
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
                            # Response complete
                            if agent_message_started and current_content:
                                # Finalize message with newline
                                chat_log.write("")  # Newline
                                current_content = ""
                                agent_message_started = False
                            chat_log.write("[dim]---[/dim]")
                        
                        elif chunk_type == "error":
                            # Error occurred
                            error_msg = data.get("content", "Unknown error")
                            chat_log.write(f"[bold red]Error:[/bold red] {error_msg}")
                    
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        chat_log.write(f"[bold red]Error processing chunk:[/bold red] {str(e)}")
        
        except httpx.HTTPError as e:
            chat_log.write(f"[bold red]HTTP Error:[/bold red] {str(e)}")
        except Exception as e:
            chat_log.write(f"[bold red]Error:[/bold red] {str(e)}")
        finally:
            # Clear thinking indicator
            pass
    
    def action_clear(self) -> None:
        """Clear chat log."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()
    
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
    
    #message-input {
        width: 1fr;
        margin-right: 1;
    }
    
    #send-button {
        margin-right: 1;
    }
    
    #plan-mode, #edit-mode {
        margin-right: 1;
    }
    """
    
    TITLE = "OpenScrum Agent"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
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
