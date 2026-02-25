"""
FastAPI Server for OpenScrum

Provides HTTP API for the agent with streaming support.
Loads ~/.env for OPENAI_API_KEY, OPENAI_MODEL, etc. when present.
"""

import asyncio
import argparse
import logging
import os
import json
import time
import shutil
import re
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

from fastapi import FastAPI, HTTPException, Body
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
from server.design_docs import DesignDocumentManager

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
WORKSPACE_LOG_FILENAME = "openscrum-detailed-log.jsonl"


def _env_truthy(name: str, default: str = "0") -> bool:
    value = str(os.getenv(name, default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


DETAILED_LOGGING_ENABLED = _env_truthy("OPENSCRUM_DETAILED_LOG", "0")


def _workspace_log_path(workspace_root: str) -> Path:
    return Path(workspace_root) / WORKSPACE_LOG_FILENAME


def _serialize_langchain_messages(messages: list[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for msg in messages:
        role = getattr(msg, "type", msg.__class__.__name__).lower()
        entry: dict[str, Any] = {
            "role": role,
            "content": str(getattr(msg, "content", "") or ""),
        }
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            normalized = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    normalized.append({
                        "id": str(tc.get("id", "")),
                        "name": str(tc.get("name", "")),
                        "args": tc.get("args", {}),
                    })
                else:
                    normalized.append({
                        "id": str(getattr(tc, "id", "")),
                        "name": str(getattr(tc, "name", "")),
                        "args": getattr(tc, "args", {}),
                    })
            entry["tool_calls"] = normalized
        serialized.append(entry)
    return serialized


def _append_workspace_log(workspace_root: str, event: str, payload: dict[str, Any]) -> None:
    if not DETAILED_LOGGING_ENABLED:
        return
    try:
        path = _workspace_log_path(workspace_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp_ms": int(time.time() * 1000),
            "event": event,
            **payload,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to write workspace log: %s", e)


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

class UpdateSessionRequest(BaseModel):
    title: str | None = None
    mode: str | None = None

class FileUpdateRequest(BaseModel):
    """File update request model."""
    path: str
    content: str


class ChatChunk(BaseModel):
    """Streaming chat chunk."""
    type: str  # "token", "tool_call", "tool_result", "done", "error", "permission_request"
    content: str = ""
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_output: str | None = None
    # When type=="permission_request", client must POST /permissions/{id}/reply before tool runs
    permission_request: dict | None = None
    # For background UI metadata like the Edit Mode Todo list
    progress: dict | None = None


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


def _detect_large_edit_request(message: str) -> tuple[bool, str]:
    """
    Heuristic guardrail for edit mode.
    Returns (is_large_change, reason).
    """
    if not message or not message.strip():
        return False, ""
    lower = message.strip().lower()

    explicit_patterns = [
        r"\brewrite (the )?(entire|whole|full)\b",
        r"\brefactor (the )?(entire|whole|full)\b",
        r"\bmigrate\b.*\bframework\b",
        r"\bfrom scratch\b",
        r"\bstart over\b",
        r"\bcomplete redesign\b",
        r"\boverhaul\b",
        r"\brebuild\b.*\b(all|everything|entire)\b",
        r"\bchange (the )?architecture\b",
        r"\breplace (the )?stack\b",
    ]
    for pattern in explicit_patterns:
        if re.search(pattern, lower):
            return True, f"matched:{pattern}"

    # Broader scope signals.
    scope_hits = 0
    scope_terms = [
        "entire codebase",
        "whole codebase",
        "all files",
        "every file",
        "all modules",
        "full system",
        "end-to-end rewrite",
    ]
    for term in scope_terms:
        if term in lower:
            scope_hits += 1

    if len(message) > 1200:
        scope_hits += 1
    if lower.count(" and ") >= 8:
        scope_hits += 1

    if scope_hits >= 2:
        return True, f"scope_hits:{scope_hits}"
    return False, ""


def _load_design_docs_context(workspace_root: str, max_per_doc_chars: int = 3500) -> str | None:
    """
    Load current design docs as authoritative context for edit mode.
    """
    try:
        mgr = DesignDocumentManager(workspace_root)
        docs = mgr.get_all_documents()
        existing = []
        for doc_type, payload in docs.items():
            if payload.get("exists") and payload.get("content"):
                content = str(payload["content"])[:max_per_doc_chars]
                existing.append(f"## {doc_type}\n{content}")
        if not existing:
            return None
        return (
            "AUTHORITATIVE DESIGN DOCUMENTS (SOURCE OF TRUTH FOR EDIT MODE)\n"
            "Use these docs over memory or assumptions. If code changes, keep docs synchronized.\n\n"
            + "\n\n".join(existing)
        )
    except Exception:
        return None


def _auto_sync_design_docs_from_code(session_id: str, workspace_root: str) -> dict[str, Any]:
    """
    Deterministically refresh design docs from current code scan outputs.
    Runs after a successful edit-mode commit to keep docs aligned with code.
    """
    try:
        from server.tools.system_tools import (
            scan_codebase,
            extract_api_routes,
            extract_db_schemas,
            list_components,
            list_services,
        )
        from server.tools.context import set_tool_context, clear_tool_context
    except ImportError:
        return {"success": False, "message": "sync_tools_unavailable"}

    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    _append_workspace_log(
        workspace_root,
        "auto_sync_start",
        {"session_id": session_id, "source": "git_commit"},
    )
    set_tool_context(session_id, workspace_root, [])
    try:
        sync_call_id = f"autosync_{int(time.time() * 1000)}"

        _append_workspace_log(
            workspace_root,
            "tool_call",
            {"session_id": session_id, "call_id": f"{sync_call_id}_scan", "tool_name": "scan_codebase", "tool_input": {}},
        )
        overview = scan_codebase.invoke({})
        _append_workspace_log(
            workspace_root,
            "tool_result",
            {"session_id": session_id, "call_id": f"{sync_call_id}_scan", "tool_name": "scan_codebase", "tool_output": str(overview)},
        )

        _append_workspace_log(
            workspace_root,
            "tool_call",
            {"session_id": session_id, "call_id": f"{sync_call_id}_api", "tool_name": "extract_api_routes", "tool_input": {}},
        )
        api_routes = extract_api_routes.invoke({})
        _append_workspace_log(
            workspace_root,
            "tool_result",
            {"session_id": session_id, "call_id": f"{sync_call_id}_api", "tool_name": "extract_api_routes", "tool_output": str(api_routes)},
        )

        _append_workspace_log(
            workspace_root,
            "tool_call",
            {"session_id": session_id, "call_id": f"{sync_call_id}_db", "tool_name": "extract_db_schemas", "tool_input": {}},
        )
        db_schemas = extract_db_schemas.invoke({})
        _append_workspace_log(
            workspace_root,
            "tool_result",
            {"session_id": session_id, "call_id": f"{sync_call_id}_db", "tool_name": "extract_db_schemas", "tool_output": str(db_schemas)},
        )

        _append_workspace_log(
            workspace_root,
            "tool_call",
            {"session_id": session_id, "call_id": f"{sync_call_id}_components", "tool_name": "list_components", "tool_input": {}},
        )
        components = list_components.invoke({})
        _append_workspace_log(
            workspace_root,
            "tool_result",
            {"session_id": session_id, "call_id": f"{sync_call_id}_components", "tool_name": "list_components", "tool_output": str(components)},
        )

        _append_workspace_log(
            workspace_root,
            "tool_call",
            {"session_id": session_id, "call_id": f"{sync_call_id}_services", "tool_name": "list_services", "tool_input": {}},
        )
        services = list_services.invoke({})
        _append_workspace_log(
            workspace_root,
            "tool_result",
            {"session_id": session_id, "call_id": f"{sync_call_id}_services", "tool_name": "list_services", "tool_output": str(services)},
        )
    finally:
        clear_tool_context()

    mgr = DesignDocumentManager(workspace_root)
    doc_payloads: dict[str, str] = {
        "functionalities": f"# Functionalities\n\n## Source\nAuto-synced from code on {now}.\n\n## Observed Features\n{overview}\n\n## Components\n{components}\n\n## Services\n{services}\n",
        "tech_stack": f"# Tech Stack\n\n## Source\nAuto-synced from code on {now}.\n\n## Inferred Stack\n{overview}\n",
        "database_design": f"# Database Design\n\n## Source\nAuto-synced from code on {now}.\n\n## Observed Schemas\n{db_schemas}\n",
        "user_flow": f"# User Flow Design\n\n## Source\nAuto-synced from code on {now}.\n\n## Inferred from Components and Services\n{components}\n\n{services}\n",
        "architecture": f"# Architecture\n\n## Source\nAuto-synced from code on {now}.\n\n## System Overview\n{overview}\n\n## Components\n{components}\n\n## Services\n{services}\n",
        "api_design": f"# API Design\n\n## Source\nAuto-synced from code on {now}.\n\n## Observed Routes\n{api_routes}\n",
        "requirements": f"# Requirements\n\n## Source\nAuto-synced from code on {now}.\n\n## Implementation-Derived Requirements\n{overview}\n",
    }

    written_docs: list[str] = []
    for doc_type, content in doc_payloads.items():
        try:
            mgr.write_document(doc_type, content)
            written_docs.append(doc_type)
        except Exception:
            continue

    result = {
        "success": len(written_docs) > 0,
        "written_docs": written_docs,
        "timestamp": now,
    }
    _append_workspace_log(
        workspace_root,
        "auto_sync_done",
        {"session_id": session_id, **result},
    )
    return result


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
        
        # Auto-approve read-only codebase scanning operations
        {"permission": "analyze_workspace", "pattern": "*", "action": "allow"},
        {"permission": "scan_codebase", "pattern": "*", "action": "allow"},
        {"permission": "extract_api_routes", "pattern": "*", "action": "allow"},
        {"permission": "extract_db_schemas", "pattern": "*", "action": "allow"},
        {"permission": "list_components", "pattern": "*", "action": "allow"},
        {"permission": "list_services", "pattern": "*", "action": "allow"},
        {"permission": "generate_design_from_code", "pattern": "*", "action": "allow"},
        {"permission": "generate_gap_analysis", "pattern": "*", "action": "allow"},
        
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
    _append_workspace_log(
        workspace_root,
        "agent_stream_start",
        {"session_id": session_id, "user_message_id": user_message_id},
    )
    
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
                            _name = (tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "") or "") or "unknown"
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
                            _append_workspace_log(
                                workspace_root,
                                "tool_call",
                                {
                                    "session_id": session_id,
                                    "message_id": assistant_message_id,
                                    "call_id": call_id,
                                    "tool_name": _name,
                                    "tool_input": args,
                                },
                            )
                            chat_chunk = ChatChunk(
                                type="tool_call",
                                tool_name=_name,
                                tool_input=args,
                            )
                            yield f"data: {chat_chunk.model_dump_json()}\n\n"
                    # Handle tool results
                    if isinstance(message, ToolMessage):
                        call_id = str(getattr(message, "tool_call_id", "") or "")
                        saved_tool = tool_calls_saved.get(call_id, {}) if call_id else {}
                        tool_name = getattr(message, "name", None) or saved_tool.get("name")
                        if not tool_name:
                            # LangChain ToolMessage may omit `name`; keep a final defensive fallback.
                            try:
                                msg_dump = message.model_dump()
                                tool_name = (
                                    msg_dump.get("name")
                                    or msg_dump.get("additional_kwargs", {}).get("name")
                                )
                            except Exception:
                                tool_name = None
                        tool_name = str(tool_name or "unknown")
                        tool_output = str(message.content)
                        _log.info(f"[Tool Result] {tool_name} returned: {tool_output[:200]}")
                        _append_workspace_log(
                            workspace_root,
                            "tool_result",
                            {
                                "session_id": session_id,
                                "message_id": assistant_message_id,
                                "call_id": call_id,
                                "tool_name": tool_name,
                                "tool_output": tool_output,
                            },
                        )
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
                        msg_name = getattr(message, "name", "")
                        
                        # Background tracker messages should never be streamed as visible text
                        if msg_name == "todo_tracker":
                            _log.info(f"[Stream Node] Intercepted todo_tracker metadata ({len(content)} bytes)")
                            try:
                                progress_data = json.loads(content)
                                chat_chunk = ChatChunk(type="progress", progress=progress_data)
                                yield f"data: {chat_chunk.model_dump_json()}\n\n"
                            except Exception as e:
                                _log.error(f"Failed to parse tracker JSON: {e}")
                            continue
                            
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
        if not full_text and tool_calls_saved:
            tool_names = [v.get("name", "unknown") for v in tool_calls_saved.values()]
            preview = ", ".join(tool_names[:3])
            if len(tool_names) > 3:
                preview += f", +{len(tool_names) - 3} more"
            full_text = (
                "Execution finished with tool calls but no textual assistant response was generated.\n\n"
                f"Tools called: {preview}"
            )
        _append_workspace_log(
            workspace_root,
            "llm_response",
            {
                "session_id": session_id,
                "message_id": assistant_message_id,
                "content": full_text,
            },
        )
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
        _append_workspace_log(
            workspace_root,
            "agent_stream_error",
            {"session_id": session_id, "error": error_msg},
        )
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
        _append_workspace_log(
            workspace_root,
            "agent_stream_end",
            {"session_id": session_id, "assistant_message_id": assistant_message_id},
        )


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
        "detailed_logging": DETAILED_LOGGING_ENABLED,
        "workspace_log_filename": WORKSPACE_LOG_FILENAME,
    }

@app.get("/testping")
async def testping():
    return {"ping": "pong"}

@app.post("/testpatch")
async def testpatch(request: dict):
    return {"received": request}


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

    def _workspace_path_for_session(session: dict) -> Path:
        """Resolve canonical workspace path from persisted session metadata."""
        directory = session.get("directory")
        if directory:
            return Path(directory)
        # Backward compatibility fallback for older session records
        session_id = session.get("id", "")
        workspace_name = session.get("workspace_name", f"session_{session_id}")
        return Path(get_workspace_root()) / workspace_name

    def _ensure_within_workspace(workspace_root_path: Path, target_path: Path) -> None:
        """Reject path traversal outside workspace root."""
        try:
            target_path.resolve().relative_to(workspace_root_path.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")
    
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
            filtered_sessions = []
            for session in sessions:
                workspace_path = _workspace_path_for_session(session)
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
    async def update_session(session_id: str, request: UpdateSessionRequest):
        print(f"PATCH SESSION {session_id} - request: {request}", flush=True)
        session_svc = get_session()
        current_session = session_svc.get(session_id)
        if request.mode is not None:
            mode_value = str(request.mode).strip().lower()
            if mode_value not in {"plan", "edit"}:
                raise HTTPException(status_code=400, detail="mode must be either 'plan' or 'edit'")
        mode_changed = False
        old_mode = str(current_session.get("mode", "plan")).strip().lower()
        new_mode = old_mode
        if request.mode is not None:
            new_mode = str(request.mode).strip().lower()
            mode_changed = new_mode != old_mode
        def editor(d):
            if request.title is not None:
                d["title"] = request.title
            if request.mode is not None:
                d["mode"] = new_mode
                if mode_changed:
                    # Context boundary: LLM history before this timestamp is ignored after mode switch.
                    now_ms = int(time.time() * 1000)
                    d["mode_context_start_ms"] = now_ms
                    d["mode_switch"] = {
                        "from": old_mode,
                        "to": new_mode,
                        "at_ms": now_ms,
                    }
        updated = session_svc.update(session_id, editor, touch=False)
        if mode_changed:
            try:
                _append_workspace_log(
                    str(current_session.get("directory", "")),
                    "mode_switch",
                    {
                        "session_id": session_id,
                        "from_mode": old_mode,
                        "to_mode": new_mode,
                        "mode_context_start_ms": int(updated.get("mode_context_start_ms") or 0),
                    },
                )
            except Exception:
                pass
        return updated

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

    @app.get("/sessions/{session_id}/workspace/analyze", summary="Analyze workspace state")
    async def analyze_workspace_api(session_id: str):
        try:
            from server.tools.system_tools import analyze_workspace
            from server.tools.context import set_tool_context, clear_tool_context
            
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            
            set_tool_context(session_id, str(workspace_root_path), [])
            try:
                _append_workspace_log(
                    str(workspace_root_path),
                    "tool_call",
                    {"session_id": session_id, "tool_name": "analyze_workspace", "tool_input": {}},
                )
                result_json = analyze_workspace.invoke({})
                _append_workspace_log(
                    str(workspace_root_path),
                    "tool_result",
                    {"session_id": session_id, "tool_name": "analyze_workspace", "tool_output": str(result_json)},
                )
                import json
                return json.loads(result_json)
            finally:
                clear_tool_context()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
    @app.get("/sessions/{session_id}/workspace/sync-status", summary="Check design vs code sync status")
    async def check_sync_status_api(session_id: str):
        try:
            from server.tools.system_tools import check_sync_status
            from server.tools.context import set_tool_context, clear_tool_context
            
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            
            set_tool_context(session_id, str(workspace_root_path), [])
            try:
                _append_workspace_log(
                    str(workspace_root_path),
                    "tool_call",
                    {"session_id": session_id, "tool_name": "check_sync_status", "tool_input": {}},
                )
                result_json = check_sync_status.invoke({})
                _append_workspace_log(
                    str(workspace_root_path),
                    "tool_result",
                    {"session_id": session_id, "tool_name": "check_sync_status", "tool_output": str(result_json)},
                )
                import json
                return json.loads(result_json)
            finally:
                clear_tool_context()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
    @app.post("/sessions/{session_id}/workspace/sync", summary="Trigger design document sync from code")
    async def trigger_workspace_sync_api(session_id: str):
        try:
            from server.tools.system_tools import generate_design_from_code, load_sync_metadata, save_sync_metadata, check_sync_status
            from server.tools.context import set_tool_context, clear_tool_context
            from datetime import datetime
            import json
            
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            
            set_tool_context(session_id, str(workspace_root_path), [])
            try:
                # 1. First trigger generation to run against the LangGraph LLM loop and write the files
                # This could be handled via agent execution, but for explicit sync let's update metadata directly 
                # acknowledging that code is now the source of truth for the synced timestamp.
                
                # Update metadata assuming the user has reviewed/is actively syncing
                metadata = load_sync_metadata()
                
                # Check current status before updating so we have accurate timestamps
                _append_workspace_log(
                    str(workspace_root_path),
                    "tool_call",
                    {"session_id": session_id, "tool_name": "check_sync_status", "tool_input": {}},
                )
                status_raw = check_sync_status.invoke({})
                _append_workspace_log(
                    str(workspace_root_path),
                    "tool_result",
                    {"session_id": session_id, "tool_name": "check_sync_status", "tool_output": str(status_raw)},
                )
                status = json.loads(status_raw)
                
                analysis = status.get("workspace_analysis", {})
                current_time = datetime.utcnow().timestamp()
                
                # We update the timestamp to now so that no warnings show up unless
                # the code is manipulated AFTER this point.
                metadata["design_docs_last_synced"] = current_time
                metadata["code_last_modified"] = analysis.get("latest_code_timestamp", 0)
                metadata["sync_warnings"] = []
                metadata["last_check"] = datetime.utcnow().isoformat()
                
                save_sync_metadata(metadata)
                
                return {"message": "Sync complete. Metadata updated.", "metadata": metadata}
            finally:
                clear_tool_context()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/sessions/{session_id}/workspace/tree", summary="Get workspace file tree")
    async def get_workspace_tree_api(session_id: str):
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            
            if not workspace_root_path.exists():
                return {"name": "root", "type": "directory", "children": []}
                
            def build_tree(dir_path: Path):
                tree = {"name": dir_path.name, "type": "directory", "children": []}
                try:
                    for item in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                        # Ignore standard hidden dirs/files except .openscrum
                        if item.name.startswith('.') and item.name != '.openscrum':
                            continue
                        if item.name in ('node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build'):
                            continue
                            
                        if item.is_dir():
                            tree["children"].append(build_tree(item))
                        else:
                            try:
                                rel_path = str(item.relative_to(workspace_root_path))
                            except ValueError:
                                rel_path = item.name
                            tree["children"].append({"name": item.name, "type": "file", "path": rel_path})
                except OSError:
                    pass
                return tree
                
            return build_tree(workspace_root_path)
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/sessions/{session_id}/workspace/file", summary="Get workspace file content")
    async def get_workspace_file_api(session_id: str, path: str):
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            
            # Resolve the requested path against the workspace root
            # using resolve() and carefully checking if it's still inside root
            requested_path = (workspace_root_path / path).resolve()
            
            # Prevent directory traversal attacks
            _ensure_within_workspace(workspace_root_path, requested_path)
                
            if not requested_path.exists() or not requested_path.is_file():
                raise HTTPException(status_code=404, detail="File not found")
                
            with open(requested_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            return {"content": content}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")

    @app.put("/sessions/{session_id}/workspace/file", summary="Update file in workspace")
    async def update_workspace_file_api(session_id: str, request: FileUpdateRequest):
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            
            if not workspace_root_path.exists():
                raise HTTPException(status_code=404, detail="Workspace does not exist")
                
            # Sanitize and resolve the path
            target_path = (workspace_root_path / request.path).resolve()
            
            # Ensure the path is within the workspace
            _ensure_within_workspace(workspace_root_path, target_path)
                
            # Create parent directories if they don't exist
            target_path.parent.mkdir(parents=True, exist_ok=True)
                
            try:
                target_path.write_text(request.content, encoding="utf-8")
                return {"message": "File updated successfully", "path": str(target_path.relative_to(workspace_root_path))}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to write file: {str(e)}")
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/sessions/{session_id}/children", summary="List child sessions")
    async def list_session_children(session_id: str):
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
        todos = get_todos(session_id)
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            _append_workspace_log(
                str(_workspace_path_for_session(session)),
                "todo_get",
                {"session_id": session_id, "count": len(todos)},
            )
        except Exception:
            pass
        return todos

    @app.put("/sessions/{session_id}/todo", summary="Update session todo list")
    async def session_todo_put(session_id: str, todos: Any = Body(default_factory=list)):
        try:
            from server.storage import update_todos
        except ImportError:
            from storage import update_todos
        safe_todos = todos if isinstance(todos, list) else []
        if not isinstance(todos, list):
            logging.getLogger(__name__).warning(
                "session_todo_put received non-list payload for %s; coercing to [] (type=%s)",
                session_id,
                type(todos).__name__,
            )
        saved_todos = update_todos(session_id, safe_todos)
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            _append_workspace_log(
                str(_workspace_path_for_session(session)),
                "todo_put",
                {
                    "session_id": session_id,
                    "count": len(saved_todos) if isinstance(saved_todos, list) else 0,
                },
            )
        except Exception:
            pass
        return saved_todos
        
    @app.post("/sessions/{session_id}/todo/generate", summary="Auto-generate todo list from context")
    def session_todo_generate(session_id: str):
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            session_mode = str(session.get("mode", "plan")).strip().lower()
            if session_mode != "edit":
                raise HTTPException(
                    status_code=409,
                    detail="Todo generation is only allowed in edit mode."
                )
            workspace_root_path = str(_workspace_path_for_session(session))
            _append_workspace_log(
                workspace_root_path,
                "todo_generate_start",
                {"session_id": session_id, "mode": session_mode},
            )
            
            try:
                from server.agent.todo_generator import generate_todos_for_session
            except ImportError:
                from agent.todo_generator import generate_todos_for_session
                
            merged_todos = generate_todos_for_session(session_id, workspace_root_path)
            _append_workspace_log(
                workspace_root_path,
                "todo_generate_done",
                {
                    "session_id": session_id,
                    "mode": session_mode,
                    "count": len(merged_todos) if isinstance(merged_todos, list) else 0,
                },
            )
            return merged_todos
        except HTTPException:
            raise
        except Exception as e:
            try:
                session_svc = get_session()
                session = session_svc.get(session_id)
                _append_workspace_log(
                    str(_workspace_path_for_session(session)),
                    "todo_generate_error",
                    {"session_id": session_id, "error": str(e)},
                )
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(e))
            
    # --- GIT INTEGRATION ENDPOINTS ---

    @app.get("/sessions/{session_id}/git/status", summary="Get current git status and diff")
    def get_git_status(session_id: str):
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = str(_workspace_path_for_session(session))
            
            try:
                from server.git_service import GitService
            except ImportError:
                from git_service import GitService
                
            git_svc = GitService(workspace_root_path)
            return git_svc.get_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
            
    @app.post("/sessions/{session_id}/git/commit", summary="Auto-commit changes using LLM for message")
    def auto_commit_changes(session_id: str):
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = str(_workspace_path_for_session(session))
            
            try:
                from server.git_service import GitService
            except ImportError:
                from git_service import GitService
                
            git_svc = GitService(workspace_root_path)
            status = git_svc.get_status()
            
            if not status.get("has_changes"):
                return {"success": True, "message": "No changes to commit."}
                
            diff_text = status.get("diff", "")
            
            # Generate commit message using LLM
            import os
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import SystemMessage, HumanMessage
            
            model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            llm = ChatOpenAI(model=model_name, temperature=0.1)
            
            sys_prompt = "You are an expert software engineer. Write a concise, conventional git commit message summarizing this diff. Do not include markdown formatting, backticks, or extra explanation. Just the raw message string. Keep it under 72 characters."
            human_msg = f"Diff:\n{diff_text[:10000]}" # cap length for safety
            _append_workspace_log(
                workspace_root_path,
                "llm_request",
                {
                    "session_id": session_id,
                    "source": "git_auto_commit",
                    "mode": str(session.get("mode", "unknown")),
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "human", "content": human_msg},
                    ],
                },
            )
            
            res = llm.invoke([SystemMessage(content=sys_prompt), HumanMessage(content=human_msg)])
            commit_msg = str(res.content).strip().strip('`').strip('\"').strip('\'')
            _append_workspace_log(
                workspace_root_path,
                "llm_response",
                {
                    "session_id": session_id,
                    "source": "git_auto_commit",
                    "content": str(res.content),
                },
            )
            
            if not commit_msg:
                commit_msg = "Auto-commit from OpenScrum agent"
                
            success = git_svc.commit_changes(commit_msg)
            docs_sync: dict[str, Any] | None = None
            if success:
                # Keep docs synchronized automatically after accepted edit commits.
                docs_sync = _auto_sync_design_docs_from_code(session_id, workspace_root_path)
            return {"success": success, "commit_message": commit_msg, "docs_sync": docs_sync}
            
        except Exception as e:
            try:
                session_svc = get_session()
                session = session_svc.get(session_id)
                _append_workspace_log(
                    str(_workspace_path_for_session(session)),
                    "llm_error",
                    {"session_id": session_id, "source": "git_auto_commit", "error": str(e)},
                )
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=str(e))
            
    @app.post("/sessions/{session_id}/git/reject", summary="Hard reset workspace changes")
    def reject_git_changes(session_id: str):
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = str(_workspace_path_for_session(session))
            
            try:
                from server.git_service import GitService
            except ImportError:
                from git_service import GitService
                
            git_svc = GitService(workspace_root_path)
            success = git_svc.reset_hard()
            return {"success": success}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # ---------------------------------
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
            
            # Get all messages (for total) and mode-scoped messages (for active context)
            all_messages = session_svc.messages(session_id=session_id)
            mode_context_start_ms = int(session.get("mode_context_start_ms") or 0)
            if mode_context_start_ms > 0:
                messages = []
                for msg in all_messages:
                    info = msg.get("info", {}) if isinstance(msg, dict) else {}
                    ts = int((info.get("time") or {}).get("created", 0) or 0)
                    if ts >= mode_context_start_ms:
                        messages.append(msg)
            else:
                messages = all_messages

            # Count tokens for active mode context
            token_count = count_message_tokens(messages, model)
            total_token_count = count_message_tokens(all_messages, model)
            token_limit = get_token_limit(model)
            usage_percentage = round((token_count / token_limit) * 100, 1)
            total_usage_percentage = round((total_token_count / token_limit) * 100, 1)
            should_compress_now = should_compress(token_count, model, threshold=0.8)
            
            return {
                "token_count": token_count,
                "token_limit": token_limit,
                "usage_percentage": usage_percentage,
                "total_token_count": total_token_count,
                "total_usage_percentage": total_usage_percentage,
                "should_compress": should_compress_now,
                "model": model,
                "message_count": len(messages),
                "total_message_count": len(all_messages),
                "mode_context_start_ms": mode_context_start_ms,
            }
        except HTTPException:
            raise
        except Exception as e:
            _log = logging.getLogger(__name__)
            _log.error(f"Failed to get token usage: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to get token usage: {str(e)}")

    @app.get("/sessions/{session_id}/workspace/logging", summary="Get workspace logging status")
    async def get_workspace_logging_status(session_id: str):
        """Return detailed logging status and file metadata for this session workspace."""
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            log_path = _workspace_log_path(str(workspace_root_path))
            return {
                "enabled": DETAILED_LOGGING_ENABLED,
                "file_name": WORKSPACE_LOG_FILENAME,
                "path": str(log_path),
                "exists": log_path.exists(),
                "size_bytes": log_path.stat().st_size if log_path.exists() else 0,
            }
        except NotFoundError:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/sessions/{session_id}/workspace/logging/content", summary="Get workspace detailed log content")
    async def get_workspace_logging_content(session_id: str, lines: int = 400):
        """Read detailed workspace log content (tail by line count)."""
        try:
            session_svc = get_session()
            session = session_svc.get(session_id)
            workspace_root_path = _workspace_path_for_session(session)
            log_path = _workspace_log_path(str(workspace_root_path))
            if not log_path.exists():
                return {
                    "enabled": DETAILED_LOGGING_ENABLED,
                    "path": str(log_path),
                    "content": "",
                }
            safe_lines = max(1, min(lines, 5000))
            raw_lines = log_path.read_text(encoding="utf-8").splitlines()
            return {
                "enabled": DETAILED_LOGGING_ENABLED,
                "path": str(log_path),
                "content": "\n".join(raw_lines[-safe_lines:]),
            }
        except NotFoundError:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
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
        4. Deleting todos
        This completely resets the session to a fresh state.
        """
        _log = logging.getLogger(__name__)
        
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
                        _log.warning(f"Failed to remove message {msg_id}: {e}")
            
            # Delete todos
            try:
                from server.storage import update_todos
            except ImportError:
                from storage import update_todos
            update_todos(session_id, [])
            
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
                        _log.warning(f"Failed to remove {item}: {e}")
            
            # Create default Agent.md after clearing workspace
            try:
                from server.workspace import create_default_agent_rules
                create_default_agent_rules(workspace_root)
                _log.info(f"Created default Agent.md for session {session_id}")
            except Exception as e:
                _log.warning(f"Failed to create default Agent.md: {e}")
            
            return {
                "message": f"Session reset complete - deleted {deleted_messages} messages and {deleted_files} files/directories",
                "deleted_messages": deleted_messages,
                "deleted_files": deleted_files
            }
        except HTTPException:
            raise
        except Exception as e:
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

    @app.post("/sessions/{session_id}/abort", summary="Abort current session operation")
    async def abort_session(session_id: str):
        """
        Abort the current operation for a session.
        Sets the session status back to idle.
        """
        try:
            session_svc = get_session()
            
            # Check if session exists
            try:
                session = session_svc.get(session_id)
            except NotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            
            # Set status back to idle
            SessionStatus.set(session_id, {"type": "idle"})
            
            return {"status": "aborted", "session_id": session_id}
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

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
                session_mode = str(session.get("mode", "plan")).strip().lower()
                mode_context_start_ms = int(session.get("mode_context_start_ms") or 0)
                if mode_context_start_ms > 0:
                    filtered_messages = []
                    for msg in previous_messages:
                        info = msg.get("info", {}) if isinstance(msg, dict) else {}
                        ts = int((info.get("time") or {}).get("created", 0) or 0)
                        if ts >= mode_context_start_ms:
                            filtered_messages.append(msg)
                    dropped = len(previous_messages) - len(filtered_messages)
                    if dropped > 0:
                        _log.info(
                            "Mode context boundary applied: dropped %d historical messages before %d for session %s",
                            dropped,
                            mode_context_start_ms,
                            session_id,
                        )
                    previous_messages = filtered_messages
                
                # 5. Resolve message (e.g. /init -> init command prompt)
                workspace_root = session["directory"]
                is_init_command = (request.command or "").strip().lower() == "init"
                message_text = get_init_prompt(workspace_root) if is_init_command else request.message
                _append_workspace_log(
                    workspace_root,
                    "user_message",
                    {
                        "session_id": session_id,
                        "mode": session_mode,
                        "is_init_command": is_init_command,
                        "content": message_text,
                    },
                )

                # Guardrail: in edit mode, reject large-scope change requests and ask user to switch to plan mode.
                if not is_init_command and session_mode == "edit":
                    is_large, reason = _detect_large_edit_request(message_text or "")
                    if is_large:
                        _log.info("Rejected large edit request for session %s (%s)", session_id, reason)

                        async def large_change_stream():
                            guidance = (
                                "This request looks too large for EDIT mode.\n\n"
                                "Please switch to PLAN mode first, update design docs, then return to EDIT mode for implementation.\n"
                                "Mode transitions are user-controlled.\n"
                            )
                            yield _sse_chunk("token", content=guidance)
                            yield _sse_chunk("done", content=guidance)

                        return StreamingResponse(
                            large_change_stream(),
                            media_type="text/event-stream",
                            headers={
                                "Cache-Control": "no-cache",
                                "Connection": "keep-alive",
                                "X-Accel-Buffering": "no",
                            },
                        )
                
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
                        # previous_messages is chronological here; keep the most recent 5
                        recent_messages = previous_messages[-5:]
                        old_messages = previous_messages[:-5]
                        
                        # Create summary
                        summary_parts = []
                        for msg in old_messages:
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
                
                if has_search and has_enabled and is_enabled and session_mode != "edit":
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
                
                # In edit mode, design docs are authoritative context.
                if session_mode == "edit":
                    docs_context = _load_design_docs_context(workspace_root)
                    if docs_context:
                        from langchain_core.messages import SystemMessage
                        langchain_messages.insert(0, SystemMessage(content=docs_context))

                # If context was reset at mode switch, make the boundary explicit to the model.
                if mode_context_start_ms > 0:
                    from langchain_core.messages import SystemMessage
                    mode_switch = session.get("mode_switch") or {}
                    switch_from = str(mode_switch.get("from", "unknown"))
                    switch_to = str(mode_switch.get("to", session_mode))
                    langchain_messages.insert(
                        0,
                        SystemMessage(
                            content=(
                                "MODE CONTEXT RESET ACTIVE.\n"
                                f"Current mode: {session_mode}. Last mode switch: {switch_from} -> {switch_to} at {mode_context_start_ms}.\n"
                                "Ignore conversational context from before that switch and use current design docs/workspace state as source of truth."
                            )
                        ),
                    )

                # Add memory context as system message if found (plan mode only)
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
                _append_workspace_log(
                    workspace_root,
                    "llm_request",
                    {
                        "session_id": session_id,
                        "mode": session_mode,
                        "messages": _serialize_langchain_messages(langchain_messages),
                    },
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

                # Mode is controlled by the persisted session state (user toggles mode via session update).
                run_mode = "edit" if is_init_command else session_mode
                single_todo_id: str | None = None
                if isinstance(request.message, str):
                    m = re.match(r"\s*Process Todo #([^:]+):", request.message)
                    if m:
                        single_todo_id = m.group(1).strip()
                scratchpad = f"[SINGLE_TODO_ID={single_todo_id}]" if single_todo_id else ""
                initial_state: AgentState = {
                    "messages": langchain_messages,
                    "mode": run_mode,
                    "scratchpad": scratchpad,
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
            "detailed_logging": DETAILED_LOGGING_ENABLED,
            "workspace_log_filename": WORKSPACE_LOG_FILENAME,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


if __name__ == "__main__":
    import uvicorn
    import sys
    parser = argparse.ArgumentParser(description="OpenScrum server")
    parser.add_argument("--log", action="store_true", dest="detailed_log", help="Enable detailed workspace JSONL logging")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.detailed_log:
        os.environ["OPENSCRUM_DETAILED_LOG"] = "1"
        DETAILED_LOGGING_ENABLED = True

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
    _log.info("Detailed workspace logging: %s", "enabled" if DETAILED_LOGGING_ENABLED else "disabled")
    _log.info("="*60)
    
    # Use one worker so permission replies and the agent stream share the same process
    uvicorn.run(
        app, 
        host=args.host,
        port=args.port,
        workers=1,
        log_level=log_level.lower(),
        access_log=True
    )
