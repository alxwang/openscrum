"""
FastAPI Server for OpenScrum

Provides HTTP API for the agent with streaming support.
Loads ~/.env for OPENAI_API_KEY, OPENAI_MODEL, etc. when present.
"""

import asyncio
import logging
import os
import json
import time
import shutil
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Optional

# Load ~/.env so OPENAI_API_KEY and OPENAI_MODEL are available (e.g. when server is run without the launcher)
try:
    from dotenv import load_dotenv
    env_path = Path.home() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        # Configure LangSmith for LLM tracing
        if os.getenv("LANGSMITH_KEY"):
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGSMITH_KEY")
            os.environ["LANGCHAIN_PROJECT"] = "openscrum"
            os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
except ImportError:
    pass

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from server.agent.graph import create_agent, AgentState
from server.agent.prompt_registry import PromptRegistry
from server.token_counter import (
    count_message_tokens,
    get_token_limit,
    should_compress,
)

# Configure logging so our permission/tool logs are visible when running uvicorn
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Session management (ref: opencode server/routes/session.ts)
try:
    from server.session import get_session, SessionStatus, messages_to_langchain
    from server.session.id_util import ascending
    from server.session.session import BusyError
    from server.storage import get_storage
    from server.storage.storage import NotFoundError
    SESSION_AVAILABLE = True
except ImportError:
    try:
        from session import get_session, SessionStatus, messages_to_langchain
        from session.id_util import ascending
        from session.session import BusyError
        from storage import get_storage
        from storage.storage import NotFoundError
        SESSION_AVAILABLE = True
    except ImportError:
        SESSION_AVAILABLE = False
        NotFoundError = Exception  # no-op when session not available
        BusyError = Exception

# Permission system (ref: opencode server/routes/permission.ts, permission/next.ts)
try:
    from server.permission import (
        get_permission_system,
        PermissionRule,
        Reply as PermissionReply,
        RejectedError as PermissionRejectedError,
        DeniedError as PermissionDeniedError,
        CorrectedError as PermissionCorrectedError,
    )
    PERMISSION_AVAILABLE = True
except ImportError:
    try:
        from permission import (
            get_permission_system,
            PermissionRule,
            Reply as PermissionReply,
            RejectedError as PermissionRejectedError,
            DeniedError as PermissionDeniedError,
            CorrectedError as PermissionCorrectedError,
        )
        PERMISSION_AVAILABLE = True
    except ImportError:
        PERMISSION_AVAILABLE = False

# Commands (ref: opencode command/index.ts - init creates/updates AGENTS.md)
try:
    from server.command import get_init_prompt
except ImportError:
    from command import get_init_prompt


# ============================================================================
# Configuration
# ============================================================================

WORKSPACE_ROOT = os.getenv("OPENSCRUM_WORKSPACE_ROOT", os.getcwd())
# Prefer OPENAI_MODEL from ~/.env when using OpenAI; fall back to OPENSCRUM_MODEL
DEFAULT_MODEL = os.getenv("OPENAI_MODEL") or os.getenv("OPENSCRUM_MODEL", "gpt-5-mini")
DEFAULT_PROVIDER = os.getenv("OPENSCRUM_PROVIDER", "openai")  # "openai" or "anthropic"


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="OpenScrum Agent API", version="0.1.0")

# CORS configuration so the web client (e.g. Vite on localhost:3000) can call the API
allowed_origins = os.getenv("OPENSCRUM_CORS_ORIGINS")
if allowed_origins:
    origins = [o.strip() for o in allowed_origins.split(",") if o.strip()]
else:
    # Default to common local dev origins; can be overridden via env
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    mode: str = "plan"  # "plan" or "edit"
    workspace_root: str = None  # Optional override
    session_id: str | None = None  # Optional session ID (creates new if not provided)
    command: str | None = None  # e.g. "init" -> substitute message with command prompt, mark project initialized on success


class CreateSessionRequest(BaseModel):
    """Create session request model."""
    directory: str | None = None
    workspace_name: str | None = None
    title: str | None = None
    parent_id: str | None = None


class ChatChunk(BaseModel):
    """Streaming chat chunk."""
    type: str  # "token", "tool_call", "tool_result", "done", "error", "permission_request"
    content: str = ""
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_output: str | None = None
    # When type=="permission_request", client must POST /permissions/{id}/reply before tool runs
    permission_request: dict | None = None


def _sse_chunk(chunk_type: str, content: str = "", **kwargs) -> str:
    """Format a ChatChunk as an SSE line."""
    chunk = ChatChunk(type=chunk_type, content=content, **kwargs)
    return f"data: {chunk.model_dump_json()}\n\n"


def _normalize_tool_args(raw: Any) -> dict:
    """Ensure tool args are a dict for streaming/logging. Parse JSON string if needed."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


# ============================================================================
# LLM Factory
# ============================================================================

def create_llm(provider: str = None, model: str = None) -> object:
    """
    Create LLM instance based on provider.
    Configured to enforce JSON responses.
    If the chosen provider's API key is missing, tries the other provider.
    
    Args:
        provider: Provider name ("openai" or "anthropic")
        model: Model name
    
    Returns:
        LLM instance configured for JSON mode
    
    Raises:
        ValueError: If no API key is set for either provider
    """
    provider = provider or DEFAULT_PROVIDER
    model = model or DEFAULT_MODEL
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    # If chosen provider has no key, try the other
    if provider == "openai" and not openai_key and anthropic_key:
        provider = "anthropic"
        model = os.getenv("OPENSCRUM_MODEL", "claude-3-5-sonnet-20241022")
    elif provider == "anthropic" and not anthropic_key and openai_key:
        provider = "openai"
        model = os.getenv("OPENAI_MODEL") or os.getenv("OPENSCRUM_MODEL", "gpt-5-mini")

    if provider == "openai" and not openai_key:
        raise ValueError(
            "OPENAI_API_KEY is not set. Set it in the environment or use Anthropic by setting ANTHROPIC_API_KEY and OPENSCRUM_PROVIDER=anthropic."
        )
    if provider == "anthropic" and not anthropic_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Set it in the environment or use OpenAI by setting OPENAI_API_KEY and OPENSCRUM_PROVIDER=openai."
        )

    # Common parameters for JSON mode
    json_mode_kwargs = {
        "temperature": 0.7,
        "streaming": True,
    }

    if provider == "openai":
        if "gpt-4" in model.lower() or "gpt-3.5" in model.lower():
            json_mode_kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return ChatOpenAI(model=model, **json_mode_kwargs)
    elif provider == "anthropic":
        return ChatAnthropic(model=model, temperature=0.7)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ============================================================================
# Agent Factory
# ============================================================================

def get_agent(workspace_root: str = None) -> object:
    """
    Get or create agent instance.
    
    Args:
        workspace_root: Workspace root directory (now set via tool context per-session)
    
    Returns:
        Compiled agent graph
    """
    workspace = workspace_root or WORKSPACE_ROOT
    llm = create_llm()
    return create_agent(llm, workspace_root=workspace)


# ============================================================================
# Default Permissions
# ============================================================================

def get_default_workspace_permissions() -> list[dict]:
    """
    Get default permission rules for workspace operations.
    
    Pre-approves safe read and write operations within the workspace,
    while requiring explicit approval for potentially dangerous operations.
    
    Returns:
        List of permission rule dicts for session creation
    """
    return [
        # Auto-approve safe read operations
        {"permission": "list", "pattern": "*", "action": "allow"},
        {"permission": "read", "pattern": "*", "action": "allow"},
        {"permission": "grep", "pattern": "*", "action": "allow"},
        {"permission": "glob", "pattern": "*", "action": "allow"},
        
        # Auto-approve file editing (core agent functionality)
        {"permission": "edit", "pattern": "*", "action": "allow"},
        
        # Auto-approve code intelligence operations
        {"permission": "codesearch", "pattern": "*", "action": "allow"},
        {"permission": "lsp", "pattern": "*", "action": "allow"},
        
        # Auto-approve reading the todo list
        {"permission": "todoread", "pattern": "*", "action": "allow"},
        
        # Auto-approve design document operations (plan mode)
        {"permission": "design_create", "pattern": "*", "action": "allow"},
        {"permission": "design_read", "pattern": "*", "action": "allow"},
        {"permission": "design_write", "pattern": "*", "action": "allow"},
        {"permission": "design_list", "pattern": "*", "action": "allow"},
        {"permission": "design_update_section", "pattern": "*", "action": "allow"},
        
        # Require approval for shell commands (can modify system)
        {"permission": "bash", "pattern": "*", "action": "ask"},
        
        # Require approval for external access
        {"permission": "webfetch", "pattern": "*", "action": "ask"},
        {"permission": "websearch", "pattern": "*", "action": "ask"},
        
        # Require approval for user interaction
        {"permission": "question", "pattern": "*", "action": "ask"},
        
        # Require approval for subtasks (separate permission scope)
        {"permission": "task", "pattern": "*", "action": "ask"},
        
        # Require approval for modifying the plan
        {"permission": "todowrite", "pattern": "*", "action": "ask"},
    ]


# ============================================================================
# Streaming Helper
# ============================================================================

async def stream_agent_response_with_save(
    agent: object,
    initial_state: AgentState,
    session_id: str,
    workspace_root: str,
    user_message_id: str,
    session_permission_ruleset: list | None = None,
) -> AsyncIterator[str]:
    """
    Stream agent responses and save assistant message/parts to session.
    
    Args:
        agent: Compiled agent graph
        initial_state: Initial state for the agent
        session_id: Session ID to save messages to
        workspace_root: Workspace root directory for this session
        user_message_id: User message ID (parent of assistant message)
        session_permission_ruleset: Optional permission rules for tool execution
    
    Yields:
        JSON strings of ChatChunk objects in Server-Sent Events format
    """
    _log = logging.getLogger(__name__)
    
    if not SESSION_AVAILABLE:
        # Fallback to non-saving stream
        async for chunk in stream_agent_response(agent, initial_state):
            yield chunk
        return
    
    session_svc = get_session()
    assistant_message_id = ascending("message")
    assistant_text_parts: list[str] = []
    tool_calls_saved: dict[str, dict] = {}  # call_id -> tool info
    sent_content_length = 0  # Track how much content we've already sent
    is_json_response = None  # Track if response is JSON (check once on first content chunk)

    # Set tool context so permission layer can ask for session-scoped permissions.
    # When a tool needs user confirmation, on_permission_request puts the request in a queue
    # so we can emit a permission_request chunk and the stream waits until the user replies.
    import asyncio
    permission_queue: asyncio.Queue = asyncio.Queue()
    _clear_ctx = None
    try:
        from server.tools.context import set_tool_context, clear_tool_context
        _clear_ctx = clear_tool_context
        _log.info(f"[Context] Setting tool context: session={session_id}, workspace={workspace_root}")
        set_tool_context(
            session_id,
            workspace_root,
            session_permission_ruleset or [],
            on_permission_request=lambda info: permission_queue.put_nowait(info),
        )
    except ImportError:
        try:
            from tools.context import set_tool_context, clear_tool_context
            _clear_ctx = clear_tool_context
            _log.info(f"[Context] Setting tool context: session={session_id}, workspace={workspace_root}")
            set_tool_context(
                session_id,
                workspace_root,
                session_permission_ruleset or [],
                on_permission_request=lambda info: permission_queue.put_nowait(info),
            )
        except ImportError:
            pass
    
    _log = logging.getLogger(__name__)
    recursion_limit = int(os.environ.get("OPENSCRUM_RECURSION_LIMIT", "200"))
    try:
        last_messages_count = 0
        run_config = {"recursion_limit": recursion_limit}
        agent_iter = agent.astream(initial_state, config=run_config)
        
        while True:
            agent_task = asyncio.create_task(agent_iter.__anext__())
            state_update = None
            queue_task = None
            
            # Check for permission requests while waiting for agent step to complete
            try:
                while True:
                    # First, drain all permission requests already in the queue (non-blocking)
                    drained_any = False
                    while True:
                        try:
                            perm_info = permission_queue.get_nowait()
                            drained_any = True
                            _log.info("permission_request emitted (drained): id=%s", perm_info.get("id"))
                            yield f"data: {ChatChunk(type='permission_request', permission_request=perm_info).model_dump_json()}\n\n"
                            # Yield control briefly to allow event loop to process any incoming replies
                            await asyncio.sleep(0)
                        except asyncio.QueueEmpty:
                            break
                    
                    # After draining, wait for either agent to complete OR new permission request
                    queue_task = asyncio.create_task(permission_queue.get())
                    done, pending = await asyncio.wait(
                        [agent_task, queue_task], return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    if agent_task in done:
                        # Agent step completed - get result and cancel queue monitoring
                        try:
                            state_update = agent_task.result()
                            _log.debug("agent step completed, state_update type: %s", type(state_update).__name__)
                        except StopAsyncIteration:
                            state_update = None
                            _log.info("agent stream ended (graph finished)")
                        except Exception as task_err:
                            _log.exception("agent task failed: %s", task_err)
                            raise
                        # Cancel the queue_task since we're done with this step
                        queue_task.cancel()
                        try:
                            await queue_task
                        except asyncio.CancelledError:
                            pass
                        queue_task = None
                        break  # Exit inner loop
                    
                    if queue_task in done:
                        # New permission request arrived - emit it then loop back to drain more
                        perm_info = queue_task.result()
                        _log.info("permission_request emitted (queued): id=%s", perm_info.get("id"))
                        yield f"data: {ChatChunk(type='permission_request', permission_request=perm_info).model_dump_json()}\n\n"
                        queue_task = None
                        # Loop back to drain any additional queued requests before waiting again
                        continue
            finally:
                # Ensure queue_task is always cancelled if still pending
                if queue_task and not queue_task.done():
                    queue_task.cancel()
                    try:
                        await queue_task
                    except asyncio.CancelledError:
                        pass
            
            if state_update is None:
                break

            for node_name, node_state in state_update.items():
                if not isinstance(node_state, dict):
                    continue
                messages = node_state.get("messages", [])
                # LangGraph astream yields per-node *updates* (deltas). Router returns
                # full state; planner/editor/tools return only new messages. So we must
                # not use last_messages_count for non-router nodes or we skip new content.
                if node_name == "router":
                    last_messages_count = len(messages)
                    continue
                new_messages = messages  # delta from this node
                _log.debug("stream node=%s messages_count=%s", node_name, len(new_messages))
                _log.info(f"[Stream Node] node={node_name}, new_messages={len(new_messages)}")
                for message in new_messages:
                    # Handle tool calls
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        for tool_call in message.tool_calls:
                            _name = tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "") or ""
                            call_id = tool_call.get("id", f"call_{len(tool_calls_saved)}") if isinstance(tool_call, dict) else getattr(tool_call, "id", f"call_{len(tool_calls_saved)}")
                            raw_args = tool_call.get("args") if isinstance(tool_call, dict) else getattr(tool_call, "args", None)
                            args = _normalize_tool_args(raw_args)
                            tool_calls_saved[call_id] = {
                                "name": _name,
                                "args": args,
                            }
                            # Save tool part (pending)
                            part = {
                                "id": ascending("part"),
                                "type": "tool",
                                "session_id": session_id,
                                "message_id": assistant_message_id,
                                "call_id": call_id,
                                "tool": _name,
                                "state": {
                                    "status": "pending",
                                    "input": args,
                                    "raw": json.dumps(args),
                                },
                            }
                            session_svc.update_part(part)
                            _log.info(f"[Tool Call] {_name} with args: {str(args)[:200]}")
                            chat_chunk = ChatChunk(
                                type="tool_call",
                                tool_name=_name,
                                tool_input=args,
                            )
                            yield f"data: {chat_chunk.model_dump_json()}\n\n"
                    # Handle tool results
                    if isinstance(message, ToolMessage):
                        call_id = message.tool_call_id
                        tool_name = getattr(message, 'name', tool_calls_saved.get(call_id, {}).get("name", "unknown"))
                        tool_output = str(message.content)
                        _log.info(f"[Tool Result] {tool_name} returned: {tool_output[:200]}")
                        storage = get_storage()
                        for part_key in storage.list(["part", assistant_message_id]):
                            try:
                                part = storage.read(part_key)
                                if part.get("call_id") == call_id and part.get("type") == "tool":
                                    part["state"] = {
                                        "status": "completed",
                                        "input": tool_calls_saved.get(call_id, {}).get("args", {}),
                                        "output": tool_output,
                                        "title": tool_name,
                                        "metadata": {},
                                        "time": {
                                            "start": int(time.time() * 1000),
                                            "end": int(time.time() * 1000),
                                        },
                                    }
                                    session_svc.update_part(part)
                                    break
                            except Exception:
                                pass
                        chat_chunk = ChatChunk(
                            type="tool_result",
                            tool_name=tool_name,
                            tool_output=tool_output,
                        )
                        yield f"data: {chat_chunk.model_dump_json()}\n\n"
                    # Handle text content
                    elif isinstance(message, AIMessage) and message.content:
                        content = str(message.content)
                        _log.info(f"[AIMessage Content] node={node_name}, content_length={len(content)}, sent_so_far={sent_content_length}, first_100={content[:100]}")
                        
                        # If content is shorter than what we've already sent, this is a new message - reset tracking
                        if len(content) < sent_content_length:
                            _log.info(f"[AIMessage Content] New message detected (length {len(content)} < sent {sent_content_length}), resetting tracking")
                            sent_content_length = 0
                            is_json_response = None  # Also reset JSON detection for new message
                        
                        # On first chunk, detect if this is JSON (before any streaming)
                        if is_json_response is None:
                            is_json_response = content.strip().startswith('{')
                            _log.info(f"[LLM Response] First content chunk, length: {len(content)}")
                            _log.info(f"[LLM Response] Detected response type: {'JSON (will buffer)' if is_json_response else 'plain text (will stream)'}")
                            _log.info(f"[LLM Response] First 200 chars: {content[:200]}")
                        
                        # Accumulate content
                        new_content = content[sent_content_length:]
                        if new_content:
                            assistant_text_parts.append(new_content)
                            sent_content_length = len(content)
                            
                            # Only stream non-JSON content incrementally
                            if is_json_response:
                                # JSON: buffer completely, send only in 'done' chunk
                                _log.debug(f"[LLM Response] Buffered {len(new_content)} JSON chars (not streaming)")
                            else:
                                # Plain text: stream incrementally for better UX
                                chunk_size = 50
                                for i in range(0, len(new_content), chunk_size):
                                    chunk_text = new_content[i:i + chunk_size]
                                    chat_chunk = ChatChunk(type="token", content=chunk_text)
                                    yield f"data: {chat_chunk.model_dump_json()}\n\n"
        
        # Send the complete final content in the done chunk so frontend can check for questions
        full_text = "\n".join(assistant_text_parts) if assistant_text_parts else ""
        _log.info(f"[Done Chunk] Sending full_text length: {len(full_text)}, starts with {{? {full_text.strip().startswith('{') if full_text else False}")
        _log.info(f"[Done Chunk] First 200 chars: {full_text[:200] if full_text else '(empty)'}")
        done_chunk = ChatChunk(type="done", content=full_text)
        yield f"data: {done_chunk.model_dump_json()}\n\n"

    except Exception as e:
        import traceback
        _log = logging.getLogger(__name__)
        _log.exception("agent stream error: %s", e)
        err_str = str(e)
        if "recursion" in err_str.lower() or "GRAPH_RECURSION" in err_str:
            error_msg = (
                f"Agent stopped: step limit reached ({recursion_limit} steps). "
                f"Set OPENSCRUM_RECURSION_LIMIT=400 (or higher) and retry."
            )
        else:
            error_msg = f"{err_str}\n{traceback.format_exc()}"
        error_chunk = ChatChunk(type="error", content=error_msg)
        yield f"data: {error_chunk.model_dump_json()}\n\n"
    finally:
        # Always persist assistant message so the agent has memory even if stream errored mid-way
        if assistant_text_parts or tool_calls_saved:
            full_text = "\n".join(assistant_text_parts)
            assistant_message = {
                "id": assistant_message_id,
                "role": "assistant",
                "session_id": session_id,
                "parent_id": user_message_id,
                "time": {
                    "created": int(time.time() * 1000),
                    "completed": int(time.time() * 1000),
                },
            }
            try:
                session_svc.update_message(assistant_message)
                if full_text:
                    text_part = {
                        "id": ascending("part"),
                        "type": "text",
                        "session_id": session_id,
                        "message_id": assistant_message_id,
                        "text": full_text,
                    }
                    session_svc.update_part(text_part)
            except Exception:
                pass
        if _clear_ctx is not None:
            _clear_ctx()


async def stream_agent_response(
    agent: object,
    initial_state: AgentState
) -> AsyncIterator[str]:
    """
    Stream agent responses including tokens and tool results.
    
    Uses LangGraph's astream for state updates and processes messages/tool calls.
    
    Args:
        agent: Compiled agent graph
        initial_state: Initial state for the agent
    
    Yields:
        JSON strings of ChatChunk objects in Server-Sent Events format
    """
    recursion_limit = int(os.environ.get("OPENSCRUM_RECURSION_LIMIT", "200"))
    try:
        last_messages_count = 0
        run_config = {"recursion_limit": recursion_limit}
        async for state_update in agent.astream(initial_state, config=run_config):
            for node_name, node_state in state_update.items():
                if not isinstance(node_state, dict):
                    continue
                messages = node_state.get("messages", [])
                if node_name == "router":
                    last_messages_count = len(messages)
                    continue
                new_messages = messages  # delta from this node
                for message in new_messages:
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        for tool_call in message.tool_calls:
                            chat_chunk = ChatChunk(
                                type="tool_call",
                                tool_name=tool_call.get("name", ""),
                                tool_input=tool_call.get("args", {}),
                            )
                            yield f"data: {chat_chunk.model_dump_json()}\n\n"
                    if isinstance(message, ToolMessage):
                        chat_chunk = ChatChunk(
                            type="tool_result",
                            tool_name=getattr(message, 'name', 'unknown'),
                            tool_output=str(message.content),
                        )
                        yield f"data: {chat_chunk.model_dump_json()}\n\n"
                    elif isinstance(message, AIMessage) and message.content:
                        content = str(message.content)
                        if not (hasattr(message, 'tool_calls') and message.tool_calls):
                            chunk_size = 50
                            for i in range(0, len(content), chunk_size):
                                chunk_text = content[i:i + chunk_size]
                                chat_chunk = ChatChunk(type="token", content=chunk_text)
                                yield f"data: {chat_chunk.model_dump_json()}\n\n"
        
        # Send done signal
        done_chunk = ChatChunk(type="done")
        yield f"data: {done_chunk.model_dump_json()}\n\n"
    
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        error_chunk = ChatChunk(
            type="error",
            content=error_msg,
        )
        yield f"data: {error_chunk.model_dump_json()}\n\n"


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "workspace_root": WORKSPACE_ROOT,
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint that streams agent responses.
    If session_id is provided, uses session-based chat with history.
    Otherwise, creates a new session or uses stateless mode.
    
    Args:
        request: Chat request with message, optional mode/workspace/session_id
    
    Returns:
        StreamingResponse with Server-Sent Events
    """
    try:
        workspace_root = request.workspace_root or WORKSPACE_ROOT
        
        # If session_id provided and sessions available, use session endpoint
        if request.session_id and SESSION_AVAILABLE:
            return await session_message(request.session_id, request)
        
        # Otherwise, stateless mode (backward compatibility)
        if not Path(workspace_root).exists():
            raise HTTPException(
                status_code=400,
                detail=f"Workspace root does not exist: {workspace_root}"
            )
        
        agent = get_agent(workspace_root=workspace_root)
        initial_state: AgentState = {
            "messages": [HumanMessage(content=request.message)],
            "mode": request.mode,
            "scratchpad": "",
        }
        
        return StreamingResponse(
            stream_agent_response(agent, initial_state),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Session API (ref: opencode packages/opencode/src/server/routes/session.ts)
# ============================================================================

if SESSION_AVAILABLE:
    from server.workspace import get_workspace_manager, get_workspace_root
    
    # Initialize workspace root on startup
    workspace_mgr = get_workspace_manager()
    
    @app.get("/sessions", summary="List sessions")
    async def list_sessions(
        directory: str | None = None,
        roots: bool = False,
        start: int | None = None,
        search: str | None = None,
        limit: int | None = None,
        require_workspace: bool = True,
    ):
        """
        List sessions.
        
        Args:
            directory: Filter by directory path
            roots: Only return root sessions (no parent_id)
            start: Filter by updated timestamp (only sessions updated after this)
            search: Search in session titles
            limit: Maximum number of sessions to return
            require_workspace: If True, only return sessions that have corresponding workspace directories
        
        Returns:
            List of session dictionaries
        """
        session_svc = get_session()
        sessions = list(session_svc.list(
            directory=directory, roots_only=roots, start=start, search=search, limit=None
        ))
        
        # Filter to only sessions with existing workspaces if required
        if require_workspace:
            workspace_root = get_workspace_root()
            filtered_sessions = []
            for session in sessions:
                session_id = session.get("id")
                if session_id:
                    # Check if workspace directory exists
                    workspace_path = workspace_root / f"session_{session_id}"
                    if workspace_path.exists() and workspace_path.is_dir():
                        filtered_sessions.append(session)
            sessions = filtered_sessions
        
        # Apply limit after filtering
        if limit is not None:
            sessions = sessions[:limit]
        
        return [dict(s) for s in sessions]

    @app.get("/sessions/status", summary="Get session statuses")
    async def session_status():
        return SessionStatus.list_all()

    @app.get("/sessions/{session_id}", summary="Get session")
    async def get_session_api(session_id: str):
        try:
            session_svc = get_session()
            return session_svc.get(session_id)
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/sessions", summary="Create session")
    async def create_session(request: CreateSessionRequest):
        """
        Create a new session.
        
        Args:
            request: CreateSessionRequest with:
                - directory: Legacy parameter - if provided, workspace will be created at this path
                            (for backward compatibility). If not provided, workspace will be created
                            under ~/openscrum/workspaces/ directory.
                - workspace_name: Optional workspace name (ignored, kept for compatibility).
                                 Workspace folders always use session_SESSIONID format.
                - title: Session title (required unless directory is provided for legacy mode).
                        Used as project name.
                - parent_id: Optional parent session ID
        
        Returns:
            SessionInfo with workspace_root set to the workspace directory
        
        Raises:
            HTTPException: If title is missing and not in legacy mode
        """
        session_svc = get_session()
        
        # Extract fields from request
        directory = request.directory
        workspace_name = request.workspace_name
        title = request.title
        parent_id = request.parent_id
        
        # Log for debugging
        _log = logging.getLogger(__name__)
        _log.info(f"Creating session: title={title}, workspace_name={workspace_name}, directory={directory}")
        
        # If directory is explicitly provided, use it (legacy mode - title optional)
        # Otherwise, title is required (new mode)
        if directory:
            # Legacy mode: use provided directory, title optional
            session = session_svc.create(
                directory=directory,
                title=title,
                parent_id=parent_id,
                permission=get_default_workspace_permissions()
            )
            return dict(session)
        else:
            # New mode: title is required (used as project name)
            if not title:
                raise HTTPException(
                    status_code=400,
                    detail="title is required when creating a new session (used as project name)"
                )
            # Use title as workspace_name for consistency (though workspace_name is ignored)
            session = session_svc.create(
                workspace_name=workspace_name or title,
                title=title,
                parent_id=parent_id,
                permission=get_default_workspace_permissions()
            )
            # Return as explicit dict so FastAPI serializes title correctly
            return dict(session)

    @app.patch("/sessions/{session_id}", summary="Update session")
    async def update_session(session_id: str, title: str | None = None):
        session_svc = get_session()
        def editor(d):
            if title is not None:
                d["title"] = title
        return session_svc.update(session_id, editor, touch=False)

    @app.delete("/sessions/{session_id}", summary="Delete session")
    async def delete_session(session_id: str):
        try:
            session_svc = get_session()
            session_svc.remove(session_id)
            return True
        except NotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/sessions/{session_id}/children", summary="Get child sessions")
    async def session_children(session_id: str):
        session_svc = get_session()
        return [dict(s) for s in session_svc.children(session_id)]

    @app.get("/sessions/{session_id}/messages", summary="Get session messages")
    async def session_messages(session_id: str, limit: int | None = None):
        session_svc = get_session()
        return session_svc.messages(session_id=session_id, limit=limit)

    @app.post("/sessions/{session_id}/fork", summary="Fork session")
    async def fork_session(session_id: str, message_id: str | None = None):
        session_svc = get_session()
        return session_svc.fork(session_id=session_id, message_id=message_id)

    @app.get("/sessions/{session_id}/todo", summary="Get session todo list")
    async def session_todo_get(session_id: str):
        try:
            from server.storage import get_todos
        except ImportError:
            from storage import get_todos
        return get_todos(session_id)

    @app.put("/sessions/{session_id}/todo", summary="Update session todo list")
    async def session_todo_put(session_id: str, todos: list):
        try:
            from server.storage import update_todos
        except ImportError:
            from storage import update_todos
        update_todos(session_id, todos)
        return todos
    
    @app.post("/sessions/{session_id}/compress", summary="Compress session context")
    async def compress_session_context(session_id: str):
        """
        Compress session context by summarizing older messages.
        Keeps recent messages and creates a summary of older ones.
        """
        try:
            session_svc = get_session()
            
            # Get session to verify it exists
            try:
                session = session_svc.get(session_id)
            except NotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            # Get all messages
            messages = session_svc.messages(session_id=session_id)
            if len(messages) <= 5:
                return {"message": "Not enough messages to compress", "compressed": 0}
            
            # Keep last 5 messages, summarize the rest
            recent_messages = messages[:5]  # Already newest first
            old_messages = messages[5:]
            
            # Create summary text
            summary_parts = []
            for msg in reversed(old_messages):  # Chronological order for summary
                info = msg.get("info", {})
                role = info.get("role", "unknown")
                parts = msg.get("parts", [])
                text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
                if text_parts:
                    content = " ".join(text_parts)[:200]  # Truncate long messages
                    summary_parts.append(f"{role}: {content}...")
            
            summary_text = f"[Compressed {len(old_messages)} older messages]\n" + "\n".join(summary_parts[:10])
            
            # Delete old messages
            for msg in old_messages:
                msg_id = msg.get("info", {}).get("id")
                if msg_id:
                    try:
                        session_svc.remove_message(session_id, msg_id)
                    except Exception as e:
                        _log = logging.getLogger(__name__)
                        _log.warning(f"Failed to remove message {msg_id}: {e}")
            
            # Create a summary message
            summary_msg_id = ascending("message")
            now_ms = int(time.time() * 1000)
            summary_message = {
                "id": summary_msg_id,
                "role": "assistant",
                "session_id": session_id,
                "time": {"created": now_ms},
            }
            session_svc.update_message(summary_message)
            
            # Save summary text part
            text_part = {
                "id": ascending("part"),
                "type": "text",
                "session_id": session_id,
                "message_id": summary_msg_id,
                "text": summary_text,
            }
            session_svc.update_part(text_part)
            
            return {
                "message": f"Compressed {len(old_messages)} messages",
                "compressed": len(old_messages),
                "remaining": len(recent_messages) + 1  # +1 for summary
            }
        except HTTPException:
            raise
        except Exception as e:
            _log = logging.getLogger(__name__)
            _log.error(f"Failed to compress context: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to compress context: {str(e)}")
    
    @app.get("/sessions/{session_id}/token-usage", summary="Get token usage for session")
    async def get_token_usage(session_id: str):
        """
        Get current token usage for the session.
        Returns token count, limit, percentage, and whether compression is recommended.
        """
        try:
            session_svc = get_session()
            
            # Get session to verify it exists
            try:
                session = session_svc.get(session_id)
            except NotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            # Get model from environment or default
            model = os.getenv("OPENAI_MODEL", "gpt-4")
            
            # Get all messages
            messages = session_svc.messages(session_id=session_id)
            
            # Count tokens
            token_count = count_message_tokens(messages, model)
            token_limit = get_token_limit(model)
            usage_percentage = round((token_count / token_limit) * 100, 1)
            should_compress_now = should_compress(token_count, model, threshold=0.8)
            
            return {
                "token_count": token_count,
                "token_limit": token_limit,
                "usage_percentage": usage_percentage,
                "should_compress": should_compress_now,
                "model": model,
                "message_count": len(messages),
            }
        except HTTPException:
            raise
        except Exception as e:
            _log = logging.getLogger(__name__)
            _log.error(f"Failed to get token usage: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to get token usage: {str(e)}")
    
    @app.post("/sessions/{session_id}/reset", summary="Reset session context")
    async def reset_session_context(session_id: str):
        """
        Reset session context by deleting all messages.
        This clears the entire conversation history.
        """
        try:
            session_svc = get_session()
            
            # Get session to verify it exists
            try:
                session = session_svc.get(session_id)
            except NotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            # Get all messages
            messages = session_svc.messages(session_id=session_id)
            
            # Delete all messages
            deleted_count = 0
            for msg in messages:
                msg_id = msg.get("info", {}).get("id")
                if msg_id:
                    try:
                        session_svc.remove_message(session_id, msg_id)
                        deleted_count += 1
                    except Exception as e:
                        _log = logging.getLogger(__name__)
                        _log.warning(f"Failed to remove message {msg_id}: {e}")
            
            return {
                "message": f"Reset context - deleted {deleted_count} messages",
                "deleted": deleted_count
            }
        except HTTPException:
            raise
        except Exception as e:
            _log = logging.getLogger(__name__)
            _log.error(f"Failed to reset context: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to reset context: {str(e)}")
    
    @app.post("/sessions/{session_id}/reset-session", summary="Reset entire session")
    async def reset_entire_session(session_id: str):
        """
        Reset entire session by:
        1. Deleting all messages
        2. Deleting all files in workspace directory
        3. Deleting design documents
        This completely resets the session to a fresh state.
        """
        try:
            session_svc = get_session()
            
            # Get session to verify it exists and get workspace path
            try:
                session = session_svc.get(session_id)
            except NotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            workspace_root = Path(session["directory"])
            deleted_files = 0
            deleted_messages = 0
            
            # Delete all messages
            messages = session_svc.messages(session_id=session_id)
            for msg in messages:
                msg_id = msg.get("info", {}).get("id")
                if msg_id:
                    try:
                        session_svc.remove_message(session_id, msg_id)
                        deleted_messages += 1
                    except Exception as e:
                        _log = logging.getLogger(__name__)
                        _log.warning(f"Failed to remove message {msg_id}: {e}")
            
            # Delete all files in workspace (except .openscrum directory metadata)
            if workspace_root.exists():
                for item in workspace_root.iterdir():
                    try:
                        # Skip .openscrum directory itself, but we'll clean design docs inside
                        if item.name == ".openscrum":
                            # Delete design documents
                            design_dir = item / "design"
                            if design_dir.exists():
                                for design_file in design_dir.iterdir():
                                    if design_file.is_file():
                                        design_file.unlink()
                                        deleted_files += 1
                        elif item.is_file():
                            item.unlink()
                            deleted_files += 1
                        elif item.is_dir():
                            shutil.rmtree(item)
                            deleted_files += 1
                    except Exception as e:
                        _log = logging.getLogger(__name__)
                        _log.warning(f"Failed to remove {item}: {e}")
            
            return {
                "message": f"Session reset complete - deleted {deleted_messages} messages and {deleted_files} files/directories",
                "deleted_messages": deleted_messages,
                "deleted_files": deleted_files
            }
        except HTTPException:
            raise
        except Exception as e:
            _log = logging.getLogger(__name__)
            _log.error(f"Failed to reset session: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to reset session: {str(e)}")
    
    @app.get("/workspaces", summary="List all workspaces")
    async def list_workspaces():
        """
        List all workspace directories under ~/openscrum/workspaces/.
        Only returns workspaces that match the session_SESSIONID pattern.
        """
        workspaces = workspace_mgr.list_workspaces()
        session_svc = get_session()
        
        # Enrich with session info if available
        result = []
        for workspace_path in workspaces:
            # Extract session_id from folder name (session_SESSIONID)
            if workspace_path.name.startswith("session_"):
                session_id = workspace_path.name[8:]  # Remove "session_" prefix
                session_info = None
                try:
                    session_info = session_svc.get(session_id)
                except Exception:
                    pass  # Session not found in storage, but workspace exists
                
                result.append({
                    "path": str(workspace_path),
                    "name": workspace_path.name,
                    "session_id": session_id,
                    "exists": workspace_path.exists(),
                    "session": dict(session_info) if session_info else None,
                })
            else:
                # Non-standard workspace folder
                result.append({
                    "path": str(workspace_path),
                    "name": workspace_path.name,
                    "session_id": None,
                    "exists": workspace_path.exists(),
                    "session": None,
                })
        
        return result
    
    @app.get("/workspaces/root", summary="Get workspace root directory")
    async def get_workspace_root_endpoint():
        """Get the root directory where all workspaces are stored."""
        return {
            "workspace_root": str(get_workspace_root()),
            "exists": get_workspace_root().exists(),
        }
    
    @app.post("/workspaces/migrate", summary="Create workspace directories for existing sessions")
    async def migrate_workspaces():
        """
        Create workspace directories for all existing sessions that don't have one.
        This is useful for migrating old sessions to the new workspace structure.
        """
        session_svc = get_session()
        workspace_root = get_workspace_root()
        workspace_root.mkdir(parents=True, exist_ok=True)
        
        all_sessions = list(session_svc.list())
        created_count = 0
        skipped_count = 0
        
        for session in all_sessions:
            session_id = session.get("id")
            if not session_id:
                continue
            
            workspace_path = workspace_root / f"session_{session_id}"
            
            if workspace_path.exists():
                skipped_count += 1
                continue
            
            # Create workspace directory
            workspace_path.mkdir(parents=True, exist_ok=True)
            
            # Update session directory field to point to new workspace
            try:
                session_svc.update(
                    session_id,
                    lambda d: d.update({"directory": str(workspace_path)}),
                    touch=False
                )
                created_count += 1
            except Exception as e:
                # If update fails, workspace still created
                created_count += 1
        
        return {
            "created": created_count,
            "skipped": skipped_count,
            "total": len(all_sessions),
        }

    @app.post("/sessions/{session_id}/message", summary="Send message to session")
    async def session_message(session_id: str, request: ChatRequest):
        """
        Send a message to a session, streaming the AI response.
        Loads conversation history and maintains context.
        """
        _log = logging.getLogger(__name__)
        try:
            session_svc = get_session()
            
            # 1. Load session
            try:
                session = session_svc.get(session_id)
            except NotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            # 2. Check if session is busy
            status = SessionStatus.get(session_id)
            if status["type"] == "busy":
                raise HTTPException(
                    status_code=409,
                    detail=f"Session {session_id} is busy. Please wait or abort the current operation."
                )
            
            # 3. Set status to busy
            SessionStatus.set(session_id, {"type": "busy"})
            
            try:
                # 4. Load previous messages (session returns newest first; agent needs chronological order)
                previous_messages = list(reversed(session_svc.messages(session_id=session_id)))
                
                # 5. Resolve message (e.g. /init -> init command prompt)
                workspace_root = session["directory"]
                is_init_command = (request.command or "").strip().lower() == "init"
                message_text = get_init_prompt(workspace_root) if is_init_command else request.message
                
                # Create user message
                user_message_id = ascending("message")
                now_ms = int(time.time() * 1000)
                user_message = {
                    "id": user_message_id,
                    "role": "user",
                    "session_id": session_id,
                    "time": {"created": now_ms},
                }
                session_svc.update_message(user_message)
                
                # Save user message text part
                text_part = {
                    "id": ascending("part"),
                    "type": "text",
                    "session_id": session_id,
                    "message_id": user_message_id,
                    "text": message_text,
                }
                session_svc.update_part(text_part)
                
                # 6. Auto-compression if context is too large
                model = os.getenv("OPENAI_MODEL") or os.getenv("OPENSCRUM_MODEL", "gpt-5-mini")
                token_count = count_message_tokens(previous_messages, model)
                _log.info(f"Current token count: {token_count}, model: {model}")
                
                if should_compress(token_count, model, threshold=0.8):
                    _log.info(f"Auto-compressing context (token count: {token_count} >= 80% of limit)")
                    
                    # Perform compression similar to /compress endpoint
                    if len(previous_messages) > 5:
                        recent_messages = previous_messages[:5]  # Already newest first
                        old_messages = previous_messages[5:]
                        
                        # Create summary
                        summary_parts = []
                        for msg in reversed(old_messages):  # Chronological order
                            info = msg.get("info", {})
                            role = info.get("role", "unknown")
                            parts = msg.get("parts", [])
                            text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
                            if text_parts:
                                content = " ".join(text_parts)[:150]  # Truncate
                                summary_parts.append(f"{role}: {content}...")
                        
                        summary_text = f"[Auto-compressed {len(old_messages)} older messages to save context]\n" + "\n".join(summary_parts[:8])
                        
                        # Delete old messages
                        for msg in old_messages:
                            msg_id = msg.get("info", {}).get("id")
                            if msg_id:
                                try:
                                    session_svc.remove_message(session_id, msg_id)
                                except Exception as e:
                                    _log.warning(f"Failed to remove message {msg_id}: {e}")
                        
                        # Create summary message
                        summary_msg_id = ascending("message")
                        now_ms = int(time.time() * 1000)
                        summary_message = {
                            "id": summary_msg_id,
                            "role": "assistant",
                            "session_id": session_id,
                            "time": {"created": now_ms},
                        }
                        session_svc.update_message(summary_message)
                        
                        # Save summary text part
                        text_part_summary = {
                            "id": ascending("part"),
                            "type": "text",
                            "session_id": session_id,
                            "message_id": summary_msg_id,
                            "text": summary_text,
                        }
                        session_svc.update_part(text_part_summary)
                        
                        # Reload messages after compression
                        previous_messages = session_svc.messages(session_id=session_id)
                        _log.info(f"Auto-compression complete: {len(old_messages)} messages compressed, {len(recent_messages) + 1} remaining")
                
                # 7. Convert previous messages to LangChain format
                langchain_messages = messages_to_langchain(previous_messages)
                
                # 8. RECALL - Search semantic memory for relevant context (memsearch integration)
                memory_context = None
                storage = get_storage()
                
                # Debug: check memsearch status
                has_search = hasattr(storage, 'search')
                has_enabled = hasattr(storage, '_memsearch_enabled')
                is_enabled = getattr(storage, '_memsearch_enabled', False)
                storage_backend = os.getenv('OPENSCRUM_STORAGE_BACKEND')
                _log.info(f"Memory check: has_search={has_search}, has_enabled={has_enabled}, is_enabled={is_enabled}, backend={storage_backend}, storage_type={type(storage).__name__}")
                
                if has_search and has_enabled and is_enabled:
                    try:
                        # Search for memories relevant to original user question (not substituted command prompts)
                        # Configurable minimum relevance threshold (default 0.3)
                        MIN_RELEVANCE = float(os.getenv('OPENSCRUM_MEMSEARCH_MIN_RELEVANCE', '0.3'))
                        
                        all_memories = await storage.search(request.message, top_k=5, session_id=session_id)  # type: ignore
                        # Filter out low-relevance memories (likely noise)
                        memories = [m for m in all_memories if m.get('score', 0) >= MIN_RELEVANCE]
                        
                        if len(all_memories) > len(memories):
                            _log.info(f"Filtered out {len(all_memories) - len(memories)} low-relevance memories (threshold: {MIN_RELEVANCE})")
                        
                        if memories:
                            memory_lines = [
                                "CONTEXT FROM MEMORY:",
                                "Below are relevant excerpts from past conversations. Use them to maintain continuity and context, but prioritize information from the current conversation.\n",
                                "## Relevant memories from past conversations:\n"
                            ]
                            for i, mem in enumerate(memories, 1):
                                content = mem.get('content', '')[:500]  # Show more context per memory
                                score = mem.get('score', 0)
                                memory_lines.append(f"{i}. [Relevance: {score:.2f}]\n{content}\n")
                            
                            memory_context = "\n".join(memory_lines)
                            scores_str = ', '.join([f"{m.get('score', 0):.2f}" for m in memories])
                            _log.info(f"Injecting {len(memories)} high-relevance memories (scores: {scores_str})")
                        else:
                            _log.info(f"No memories above relevance threshold {MIN_RELEVANCE}")
                    except Exception as e:
                        _log.warning(f"Memory search failed: {e}")
                else:
                    if not has_search:
                        _log.info("Memory search disabled: storage doesn't have search method")
                    elif not has_enabled:
                        _log.info("Memory search disabled: storage doesn't have _memsearch_enabled attribute")
                    elif not is_enabled:
                        _log.info(f"Memory search disabled: _memsearch_enabled=False (set OPENSCRUM_STORAGE_BACKEND=memsearch in ~/.env)")
                
                # Add memory context as system message if found
                if memory_context:
                    from langchain_core.messages import SystemMessage
                    # Insert system message with memories at the beginning
                    langchain_messages.insert(0, SystemMessage(content=memory_context))
                
                # Add current user message
                langchain_messages.append(HumanMessage(content=message_text))
                
                # Debug: log history size (remove or set to DEBUG once verified)
                roles = [m.get("info", {}).get("role", "?") for m in previous_messages]
                _log.info(
                    "session_message history: session_id=%s previous=%s langchain=%s roles=%s memories=%s",
                    session_id, len(previous_messages), len(langchain_messages), roles,
                    "yes" if memory_context else "no",
                )
                
                # 7. Create agent and run with full history
                workspace_root = session["directory"]
                if not Path(workspace_root).exists():
                    raise HTTPException(
                        status_code=400,
                        detail=f"Workspace root does not exist: {workspace_root}"
                    )

                try:
                    agent = get_agent(workspace_root=workspace_root)
                except ValueError as e:
                    if is_init_command and ("API" in str(e) or "api_key" in str(e).lower() or "OPENAI" in str(e) or "ANTHROPIC" in str(e)):
                        # No API key: create minimal AGENTS.md so /init still "succeeds"
                        agents_path = Path(workspace_root) / "AGENTS.md"
                        if not agents_path.exists():
                            agents_path.write_text(
                                "# AGENTS.md\n\n"
                                "Add build/lint/test commands and code style guidelines here.\n"
                                "Set OPENAI_API_KEY or ANTHROPIC_API_KEY and run /init again for an AI-generated version.\n",
                                encoding="utf-8",
                            )
                        project_id = session.get("project_id", "default")
                        try:
                            from server.storage import set_initialized
                            set_initialized(project_id)
                        except Exception:
                            try:
                                from storage import set_initialized
                                set_initialized(project_id)
                            except Exception:
                                pass
                        async def no_key_init_stream():
                            yield _sse_chunk("token", content="Created AGENTS.md (placeholder). Set OPENAI_API_KEY or ANTHROPIC_API_KEY and run /init again for an AI-generated version.\n")
                            yield _sse_chunk("done")
                        return StreamingResponse(
                            no_key_init_stream(),
                            media_type="text/event-stream",
                            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
                        )
                    raise HTTPException(status_code=503, detail=str(e))

                run_mode = "edit" if is_init_command else request.mode
                initial_state: AgentState = {
                    "messages": langchain_messages,
                    "mode": run_mode,
                    "scratchpad": "",
                }

                # 8. Stream response and save assistant message (with permission context)
                # For sessions without permission rules, apply default workspace permissions
                session_permissions = session.get("permission")
                if not session_permissions:
                    _log.info(f"Session {session_id} has no permission rules, applying defaults")
                    session_permissions = get_default_workspace_permissions()
                
                inner_stream = stream_agent_response_with_save(
                    agent, initial_state, session_id, workspace_root, user_message_id,
                    session_permission_ruleset=session_permissions,
                )
                project_id = session.get("project_id", "default")

                async def stream_with_init_done():
                    try:
                        async for chunk in inner_stream:
                            yield chunk
                    finally:
                        if is_init_command:
                            try:
                                from server.storage import set_initialized
                                set_initialized(project_id)
                            except Exception:
                                try:
                                    from storage import set_initialized
                                    set_initialized(project_id)
                                except Exception:
                                    pass

                return StreamingResponse(
                    stream_with_init_done(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    }
                )
            
            finally:
                # 9. Set status back to idle
                SessionStatus.set(session_id, {"type": "idle"})
                
                # 10. Update session timestamp
                session_svc.touch(session_id)
        
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except BusyError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            import traceback
            raise HTTPException(
                status_code=500,
                detail=f"Error processing message: {str(e)}\n{traceback.format_exc()}"
            )


# ============================================================================
# Memsearch API (Semantic Memory Search)
# ============================================================================

if SESSION_AVAILABLE:
    try:
        from server.storage.memsearch_adapter import MemSearchAdapter
        MEMSEARCH_ADAPTER_AVAILABLE = True
    except ImportError:
        MEMSEARCH_ADAPTER_AVAILABLE = False

    if MEMSEARCH_ADAPTER_AVAILABLE:
        @app.get("/memory/search", summary="Semantic search across conversation memories")
        async def memory_search(
            query: str,
            top_k: int = 5,
            session_id: str | None = None
        ):
            """
            Semantic search across conversation memories using memsearch.
            
            Args:
                query: Search query
                top_k: Number of results to return (default: 5)
                session_id: Optional session ID to limit search scope
            
            Returns:
                List of search results with content, score, and source
            
            Note:
                Requires OPENSCRUM_STORAGE_BACKEND=memsearch
            """
            storage = get_storage()
            
            # Check if storage is memsearch-enabled
            if not hasattr(storage, 'search'):
                raise HTTPException(
                    status_code=503,
                    detail="Memsearch not enabled. Set OPENSCRUM_STORAGE_BACKEND=memsearch and restart server."
                )
            
            try:
                results = await storage.search(query, top_k=top_k, session_id=session_id)  # type: ignore
                return {
                    "query": query,
                    "results": results,
                    "count": len(results),
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

        @app.get("/memory/stats", summary="Get memory storage statistics")
        async def memory_stats():
            """
            Get statistics about semantic memory storage.
            
            Returns information about memory storage including:
            - Whether memsearch is enabled
            - Number of markdown memory files
            - Total storage size
            """
            storage = get_storage()
            
            # Check if storage is memsearch-enabled
            if not hasattr(storage, 'get_memory_stats'):
                return {
                    "enabled": False,
                    "backend": "file",
                    "message": "Memsearch not enabled. Set OPENSCRUM_STORAGE_BACKEND=memsearch to enable semantic search."
                }
            
            try:
                stats = storage.get_memory_stats()  # type: ignore
                return stats
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


# ============================================================================
# Design Documents API (Plan Mode)
# ============================================================================

if SESSION_AVAILABLE:
    @app.get("/sessions/{session_id}/design/list", summary="List design documents")
    async def list_design_documents(session_id: str):
        """List all design documents and their status for a session."""
        try:
            # Get session to ensure it exists and to get workspace
            session_svc = get_session()
            session_info = session_svc.get(session_id)
            if not session_info:
                raise HTTPException(status_code=404, detail="Session not found")
            
            workspace_root = session_info.directory
            
            from server.design_docs import DesignDocumentManager
            manager = DesignDocumentManager(workspace_root)
            docs = manager.list_documents()
            
            return {"documents": docs}
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Failed to list design documents: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/sessions/{session_id}/design/{doc_type}", summary="Get design document")
    async def get_design_document(session_id: str, doc_type: str):
        """Get the content of a specific design document."""
        try:
            # Get session to ensure it exists and to get workspace
            session_svc = get_session()
            session_info = session_svc.get(session_id)
            if not session_info:
                raise HTTPException(status_code=404, detail="Session not found")
            
            workspace_root = session_info.directory
            
            logging.info(f"[API] Fetching design doc: session={session_id}, doc_type={doc_type}, workspace={workspace_root}")
            
            from server.design_docs import DesignDocumentManager, DESIGN_DOC_TYPES
            
            if doc_type not in DESIGN_DOC_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid document type: {doc_type}")
            
            manager = DesignDocumentManager(workspace_root)
            content = manager.read_document(doc_type)
            
            logging.info(f"[API] Read design doc {doc_type}: exists={content is not None}, content_length={len(content) if content else 0}")
            
            if content is None:
                return {
                    "exists": False,
                    "doc_type": doc_type,
                    "content": None
                }
            
            return {
                "exists": True,
                "doc_type": doc_type,
                "name": DESIGN_DOC_TYPES[doc_type]["name"],
                "content": content
            }
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Failed to get design document: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    class DesignDocumentUpdate(BaseModel):
        content: str
    
    @app.put("/sessions/{session_id}/design/{doc_type}", summary="Update design document")
    async def update_design_document(session_id: str, doc_type: str, update: DesignDocumentUpdate):
        """Update the content of a specific design document (used for user manual edits)."""
        try:
            # Get session to ensure it exists and to get workspace
            session_svc = get_session()
            session_info = session_svc.get(session_id)
            if not session_info:
                raise HTTPException(status_code=404, detail="Session not found")
            
            workspace_root = session_info.directory
            
            from server.design_docs import DesignDocumentManager, DESIGN_DOC_TYPES
            
            if doc_type not in DESIGN_DOC_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid document type: {doc_type}")
            
            manager = DesignDocumentManager(workspace_root)
            doc_path = manager.write_document(doc_type, update.content)
            
            return {
                "success": True,
                "doc_type": doc_type,
                "path": doc_path,
                "message": f"Updated {DESIGN_DOC_TYPES[doc_type]['name']}"
            }
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Failed to update design document: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/sessions/{session_id}/design", summary="Get all design documents")
    async def get_all_design_documents(session_id: str):
        """Get all design documents for a session."""
        try:
            # Get session to ensure it exists and to get workspace
            session_svc = get_session()
            session_info = session_svc.get(session_id)
            if not session_info:
                raise HTTPException(status_code=404, detail="Session not found")
            
            workspace_root = session_info.directory
            
            from server.design_docs import DesignDocumentManager
            manager = DesignDocumentManager(workspace_root)
            all_docs = manager.get_all_documents()
            
            return {"documents": all_docs}
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Failed to get all design documents: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Permission API (ref: opencode server/routes/permission.ts)
# ============================================================================

if PERMISSION_AVAILABLE:
    def _get_permission():
        storage = get_storage() if SESSION_AVAILABLE else None
        return get_permission_system(storage=storage)

    @app.get("/permissions", summary="List pending permissions")
    async def list_pending_permissions():
        """Get all pending permission requests across sessions."""
        pending = _get_permission().list_pending()
        _log = logging.getLogger(__name__)
        _log.info("GET /permissions returned %d pending", len(pending))
        return pending
    
    @app.get("/permissions/debug", summary="Debug permission state")
    async def debug_permissions():
        """Debug endpoint to inspect permission system state."""
        perm_sys = _get_permission()
        return {
            "pending_count": len(perm_sys._pending),
            "pending_ids": list(perm_sys._pending.keys()),
            "approved_count": len(perm_sys._approved),
        }

    class PermissionReplyBody(BaseModel):
        reply: Literal["once", "always", "reject"]
        message: str | None = None

    @app.post("/permissions/{request_id}/reply", summary="Respond to permission request")
    async def permission_reply(request_id: str, body: PermissionReplyBody):
        """Approve (once/always) or reject a permission request."""
        _log = logging.getLogger(__name__)
        _log.info("POST /permissions/%s/reply body=%s", request_id, body.model_dump())
        
        perm_sys = _get_permission()
        
        # Check if request exists
        if request_id not in perm_sys._pending:
            _log.warning("POST /permissions/%s/reply - request not found. pending=%s", 
                        request_id, list(perm_sys._pending.keys()))
            raise HTTPException(status_code=404, detail=f"Permission request {request_id} not found or already processed")
        
        try:
            perm_sys.reply(request_id=request_id, reply=body.reply, message=body.message)
            _log.info("POST /permissions/%s/reply completed successfully", request_id)
            
            # Give event loop time to process the scheduled future.set_result
            # Use multiple yields to ensure the future callback runs
            for _ in range(5):
                await asyncio.sleep(0)
            
            _log.info("POST /permissions/%s/reply - future should be resolved now", request_id)
            return {"status": "ok", "request_id": request_id, "reply": body.reply}
        except Exception as e:
            _log.exception("POST /permissions/%s/reply failed: %s", request_id, e)
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check with agent validation."""
    try:
        agent = get_agent()
        return {
            "status": "healthy",
            "agent_ready": True,
            "workspace_root": WORKSPACE_ROOT,
            "model": DEFAULT_MODEL,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


if __name__ == "__main__":
    import uvicorn
    import sys
    # Configure logging to see permission flow
    log_level = os.getenv("OPENSCRUM_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True
    )
    # Set specific loggers to INFO to see permission flow
    logging.getLogger("server.permission.permission").setLevel(logging.INFO)
    logging.getLogger("server.main").setLevel(logging.INFO)
    
    _log = logging.getLogger(__name__)
    _log.info("="*60)
    _log.info("Starting OpenScrum Server")
    _log.info("Workspace: %s", WORKSPACE_ROOT)
    _log.info("Provider: %s, Model: %s", DEFAULT_PROVIDER, DEFAULT_MODEL)
    _log.info("Session support: %s, Permission support: %s", SESSION_AVAILABLE, PERMISSION_AVAILABLE)
    _log.info("="*60)
    
    # Use one worker so permission replies and the agent stream share the same process
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000, 
        workers=1,
        log_level=log_level.lower(),
        access_log=True
    )
