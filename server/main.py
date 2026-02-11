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

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from server.agent.graph import create_agent, AgentState
from server.agent.prompt_registry import PromptRegistry

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
DEFAULT_MODEL = os.getenv("OPENAI_MODEL") or os.getenv("OPENSCRUM_MODEL", "gpt-4")
DEFAULT_PROVIDER = os.getenv("OPENSCRUM_PROVIDER", "openai")  # "openai" or "anthropic"


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="OpenScrum Agent API", version="0.1.0")


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
        model = os.getenv("OPENAI_MODEL") or os.getenv("OPENSCRUM_MODEL", "gpt-4")

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
    if not SESSION_AVAILABLE:
        # Fallback to non-saving stream
        async for chunk in stream_agent_response(agent, initial_state):
            yield chunk
        return
    
    session_svc = get_session()
    assistant_message_id = ascending("message")
    assistant_text_parts: list[str] = []
    tool_calls_saved: dict[str, dict] = {}  # call_id -> tool info

    # Set tool context so permission layer can ask for session-scoped permissions.
    # When a tool needs user confirmation, on_permission_request puts the request in a queue
    # so we can emit a permission_request chunk and the stream waits until the user replies.
    import asyncio
    permission_queue: asyncio.Queue = asyncio.Queue()
    _clear_ctx = None
    try:
        from server.tools.context import set_tool_context, clear_tool_context
        _clear_ctx = clear_tool_context
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
                        if not (hasattr(message, 'tool_calls') and message.tool_calls):
                            assistant_text_parts.append(content)
                            chunk_size = 50
                            for i in range(0, len(content), chunk_size):
                                chunk_text = content[i:i + chunk_size]
                                chat_chunk = ChatChunk(type="token", content=chunk_text)
                                yield f"data: {chat_chunk.model_dump_json()}\n\n"
        
        done_chunk = ChatChunk(type="done")
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
    @app.get("/sessions", summary="List sessions")
    async def list_sessions(
        directory: str | None = None,
        roots: bool = False,
        start: int | None = None,
        search: str | None = None,
        limit: int | None = None,
    ):
        session_svc = get_session()
        return [dict(s) for s in session_svc.list(
            directory=directory, roots_only=roots, start=start, search=search, limit=limit
        )]

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
    async def create_session(
        directory: str | None = None,
        title: str | None = None,
        parent_id: str | None = None,
    ):
        session_svc = get_session()
        directory = directory or WORKSPACE_ROOT
        return session_svc.create(directory=directory, title=title, parent_id=parent_id)

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

    @app.post("/sessions/{session_id}/message", summary="Send message to session")
    async def session_message(session_id: str, request: ChatRequest):
        """
        Send a message to a session, streaming the AI response.
        Loads conversation history and maintains context.
        """
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
                
                # 6. Convert previous messages to LangChain format
                langchain_messages = messages_to_langchain(previous_messages)
                
                # Add current user message
                langchain_messages.append(HumanMessage(content=message_text))
                
                # Debug: log history size (remove or set to DEBUG once verified)
                _log = logging.getLogger(__name__)
                roles = [m.get("info", {}).get("role", "?") for m in previous_messages]
                _log.info(
                    "session_message history: session_id=%s previous=%s langchain=%s roles=%s",
                    session_id, len(previous_messages), len(langchain_messages), roles,
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
                inner_stream = stream_agent_response_with_save(
                    agent, initial_state, session_id, workspace_root, user_message_id,
                    session_permission_ruleset=session.get("permission") or [],
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
