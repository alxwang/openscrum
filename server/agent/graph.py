"""
LangGraph State Machine for OpenScrum Agent

Implements the Plan -> Edit workflow with tool execution.
All LLM communication is forced to JSON format.

Tool execution: tools are run in the order they appear in the LLM response,
one tool at a time (sequential). This ensures deterministic behavior and
allows tools to depend on prior results.
"""

import asyncio
import os
import json
import re
import logging
from pathlib import Path
from typing import TypedDict, List, Literal, Dict, Any, Optional, Callable
from typing_extensions import Annotated

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

try:
    from openai import BadRequestError
except ImportError:
    BadRequestError = None

from .prompt_registry import PromptRegistry
try:
    from server.instruction import system as instruction_system
except ImportError:
    from instruction import system as instruction_system
from ..tools.system_tools import (
    read, write, edit, multiedit, apply_patch,
    grep, glob, list_files, bash, webfetch,
    todowrite, todoread, question,
    task, websearch, codesearch, batch, lsp,
    design_create, design_read, design_write, design_list,
    plan_exit, plan_enter,
    scan_codebase, extract_api_routes, extract_db_schemas, list_components, list_services, generate_design_from_code, generate_gap_analysis,
    __all__ as TOOL_NAMES,
)
try:
    from server.workspace_log import append_workspace_log
    from server.tools.context import get_tool_context
except ImportError:
    try:
        from workspace_log import append_workspace_log
        from tools.context import get_tool_context
    except ImportError:
        def append_workspace_log(*args, **kwargs):
            return None
        def get_tool_context():
            return None


# ============================================================================
# State Definition
# ============================================================================

class AgentState(TypedDict):
    """State for the agent graph."""
    messages: Annotated[List[BaseMessage], add_messages]
    mode: Literal["plan", "edit"]
    scratchpad: str


# ============================================================================
# Prompt Registry Setup
# ============================================================================

def create_prompt_registry(workspace_root: str = None, app_root: str = None) -> PromptRegistry:
    """Create and configure the prompt registry. Uses app_root for prompts/ so they work when workspace is user's project."""
    if app_root is None:
        # OpenScrum app root = directory containing server/ and prompts/
        app_root = str(Path(__file__).resolve().parent.parent.parent)
    return PromptRegistry(workspace_root=workspace_root, app_root=app_root)


def _workspace_log_llm(event: str, payload: Dict[str, Any]) -> None:
    ctx = get_tool_context()
    if not ctx or len(ctx) < 2:
        return
    append_workspace_log(str(ctx[1]), event, payload)


def _serialize_messages_for_log(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = getattr(m, "type", m.__class__.__name__).lower()
        entry: Dict[str, Any] = {"role": role, "content": str(getattr(m, "content", "") or "")}
        tc = getattr(m, "tool_calls", None)
        if tc:
            entry["tool_calls"] = tc
        out.append(entry)
    return out


# ============================================================================
# Tool Setup
# ============================================================================

def get_tools(workspace_root: str = None):
    """Get all available tools for the agent. Wraps with permission layer when available."""
    base = [
        read,
        write,
        edit,
        multiedit,
        apply_patch,
        grep,
        glob,
        list_files,
        bash,
        webfetch,
        todowrite,
        todoread,
        question,
        task,
        websearch,
        codesearch,
        batch,
        lsp,
        design_create,
        design_read,
        design_write,
        design_list,
        plan_exit,
        plan_enter,
        scan_codebase,
        extract_api_routes,
        extract_db_schemas,
        list_components,
        list_services,
        generate_design_from_code,
    ]
    try:
        from server.tools.permission_layer import wrap_tool_with_permission
        root = workspace_root or ""
        return [wrap_tool_with_permission(t, workspace_root=root) for t in base]
    except ImportError:
        try:
            from tools.permission_layer import wrap_tool_with_permission
            root = workspace_root or ""
            return [wrap_tool_with_permission(t, workspace_root=root) for t in base]
        except ImportError:
            return base


def get_plan_mode_tools(workspace_root: str = None):
    """Get safe tools for plan mode: design tools + read-only tools only."""
    base = [
        # Read-only tools
        read,
        grep,
        glob,
        list_files,
        webfetch,
        todoread,
        websearch,
        codesearch,
        # Design document tools (plan mode specific)
        design_create,
        design_read,
        design_write,
        design_list,
        # Reverse Engineering Extractors
        scan_codebase,
        extract_api_routes,
        extract_db_schemas,
        list_components,
        list_services,
        generate_design_from_code,
        generate_gap_analysis,
        # Mode navigation
        plan_exit,
        plan_enter,
    ]
    try:
        from server.tools.permission_layer import wrap_tool_with_permission
        root = workspace_root or ""
        return [wrap_tool_with_permission(t, workspace_root=root) for t in base]
    except ImportError:
        try:
            from tools.permission_layer import wrap_tool_with_permission
            root = workspace_root or ""
            return [wrap_tool_with_permission(t, workspace_root=root) for t in base]
        except ImportError:
            return base


def create_sequential_tool_node(tools_list: list) -> Callable:
    """
    Build a tool node that executes tool_calls in the order they appear in the
    LLM response, one tool at a time. This guarantees order and ensures only
    one tool runs at a time (no parallel execution).
    """
    tools_by_name: Dict[str, Any] = {}
    for t in tools_list:
        n = getattr(t, "name", None)
        if n:
            tools_by_name[n] = t

    async def _sequential_tools_node(state: AgentState) -> Dict[str, Any]:
        messages = state.get("messages") or []
        if not messages:
            return {"messages": []}
        last = messages[-1]
        if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
            return {"messages": []}
        # Preserve exact order from LLM response
        tool_calls = list(last.tool_calls)
        result_messages: List[ToolMessage] = []
        def _args_from_tc(tc: Any) -> dict:
            raw = (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)) or {}
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str) and raw.strip():
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {}
            return {}

        for tc in tool_calls:
            name = (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)) or "unknown"
            args = _args_from_tc(tc)
            call_id = (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)) or f"call_{len(result_messages)}"
            tool = tools_by_name.get(name)
            if not tool:
                result_messages.append(
                    ToolMessage(content=f"Error: unknown tool '{name}'. Try one of: {list(tools_by_name.keys())}", tool_call_id=call_id)
                )
                continue
            try:
                if asyncio.iscoroutinefunction(getattr(tool, "ainvoke", None)):
                    out = await tool.ainvoke(args)
                else:
                    loop = asyncio.get_event_loop()
                    out = await loop.run_in_executor(None, lambda a=args: tool.invoke(a))
                content = out if isinstance(out, str) else str(out)
                result_messages.append(ToolMessage(content=content, tool_call_id=call_id))
            except Exception as e:
                result_messages.append(
                    ToolMessage(content=f"Error executing tool '{name}': {e}", tool_call_id=call_id)
                )
        return {"messages": result_messages}

    return _sequential_tools_node


# ============================================================================
# JSON Response Parsing
# ============================================================================

def parse_json_response(content: str) -> Dict[str, Any]:
    """
    Parse JSON response from LLM, handling various formats.
    
    Args:
        content: Raw content from LLM
    
    Returns:
        Parsed JSON dictionary
    """
    # Try to extract JSON from markdown code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        content = json_match.group(1)
    
    # Try to find JSON object in the content
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        content = json_match.group(0)
    
    # Parse JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # If parsing fails, wrap content in a JSON structure
        return {"content": content}


def create_ai_message_from_json(json_data: Dict[str, Any], original_response: AIMessage) -> AIMessage:
    """
    Create an AIMessage from parsed JSON response.
    
    Args:
        json_data: Parsed JSON dictionary
        original_response: Original AIMessage from LLM
    
    Returns:
        AIMessage with content and tool_calls extracted from JSON
    """
    # Special cases: If JSON contains questions OR progress, preserve the entire JSON structure
    # Use the ORIGINAL response content (not re-serialized) to avoid double-escaping
    
    # Case 1: Questions JSON (from plan mode)
    if "questions" in json_data and isinstance(json_data.get("questions"), dict):
        content = str(original_response.content) if hasattr(original_response, 'content') else json.dumps(json_data)
    
    # Case 2: Progress JSON (from edit mode) - has both plan and current_progress
    elif "plan" in json_data and "current_progress" in json_data:
        # Frontend needs the full structure to display progress tracker
        content = str(original_response.content) if hasattr(original_response, 'content') else json.dumps(json_data)
    
    else:
        # Regular content extraction
        content = json_data.get("content", "")
        
        # Ensure content is always a string, never a dict
        if isinstance(content, dict):
            content = json.dumps(content, indent=2)
        elif not content and json_data:
            # If no content field but we have other data (e.g., steps), serialize it
            content = json.dumps(json_data, indent=2)
        elif not isinstance(content, str):
            # Fallback: convert any other type to string
            content = str(content)
    
    tool_calls_data = json_data.get("tool_calls", [])

    # Helper to normalize/validate tool names against our registry
    def normalize_tool_name(raw: str) -> Optional[str]:
        if not raw:
            return None
        # Exact match
        if raw in TOOL_NAMES:
            return raw
        # Strip common namespace prefixes like "functions." or "tools."
        if "." in raw:
            last = raw.split(".")[-1]
            if last in TOOL_NAMES:
                return last
        # Strip unsupported characters and re-check
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
        if cleaned in TOOL_NAMES:
            return cleaned
        return None

    # Convert tool_calls to LangChain format, dropping invalid/unknown tools
    def normalize_args(raw: Any) -> dict:
        """Ensure args is a dict. Parse JSON string if needed."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return {}

    tool_calls = []
    for tc in tool_calls_data:
        raw_name = tc.get("name", "")
        name = normalize_tool_name(raw_name)
        if not name:
            # Treat unknown/invalid tool names as plain content; skip the call
            continue
        tool_calls.append({
            "name": name,
            "args": normalize_args(tc.get("arguments")),
            "id": tc.get("id", f"call_{len(tool_calls)}"),
        })

    # Create new AIMessage; if no valid tools, tool_calls will be empty (no function calling)
    msg_kwargs = {"content": content}
    if tool_calls:
        msg_kwargs["tool_calls"] = tool_calls
    return AIMessage(**msg_kwargs)


# ============================================================================
# Graph Nodes
# ============================================================================

def planner_node(
    state: AgentState,
    llm: BaseChatModel,
    registry: PromptRegistry,
    workspace_root: str = None,
) -> AgentState:
    """
    Planner node - generates plans and can call design + read-only tools.
    
    Uses PLAN_MODE_SYSTEM_REMINDER prompt with access to safe tools.
    All responses are parsed as JSON.
    AGENTS.md / CLAUDE.md (project + global) are appended to system prompt.
    """
    import logging
    _log = logging.getLogger(__name__)
    _log.info("[PLANNER NODE] Invoked - message count: %d", len(state.get("messages", [])))
    
    # Get user's intended mode from initial state 
    user_mode = state.get("mode", "plan")
    
    # Get plan mode prompt with context injection and JSON enforcement
    system_prompt = registry.get_prompt("PLAN_MODE_SYSTEM_REMINDER", force_json=True)
    
    # Add strong mode reminder at the top
    mode_reminder = f"\n\n<CRITICAL_MODE_CONSTRAINT>\nUSER SELECTED MODE: {user_mode.upper()}\n"
    if user_mode == "plan":
        try:
            plan_switch_msg = registry.get_prompt("PLAN_SWITCH_SYSTEM_REMINDER")
            mode_reminder += f"{plan_switch_msg}\n"
        except Exception:
            mode_reminder += "You are in PLAN MODE - You CAN call design tools and read-only tools. NO file edits, NO system changes. This is ABSOLUTE and overrides all other instructions.\n"
    mode_reminder += "</CRITICAL_MODE_CONSTRAINT>\n\n"
    system_prompt = mode_reminder + system_prompt
    
    if workspace_root:
        parts = instruction_system(workspace_root)
        if parts:
            system_prompt = system_prompt.rstrip() + "\n\n" + "\n\n".join(parts)
    # Escape literal braces so ChatPromptTemplate does not treat JSON examples as variables
    system_prompt = system_prompt.replace("{", "{{").replace("}", "}}")

    # Build messages
    messages = state["messages"]

    def _tool_exec_summary_since_last_user(msgs: list[BaseMessage]) -> tuple[int, int]:
        """
        Returns (tool_result_count, failed_tool_result_count) after the latest HumanMessage.
        """
        last_human_idx = -1
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i], HumanMessage):
                last_human_idx = i
                break
        scan = msgs[last_human_idx + 1:] if last_human_idx >= 0 else msgs
        total = 0
        failed = 0
        for m in scan:
            if isinstance(m, ToolMessage):
                total += 1
                text = str(getattr(m, "content", "") or "").strip().lower()
                if text.startswith("error:") or "error executing tool" in text:
                    failed += 1
        return total, failed

    # Bind plan mode tools (design tools + read-only tools)
    tools = get_plan_mode_tools(workspace_root)
    llm_with_tools = llm.bind_tools(tools).with_config({"run_name": "planner"})

    # Create prompt with system message
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
    ])
    
    def _response_claims_action_without_evidence(ai_content: str) -> bool:
        """
        Detect likely false-positive text-only confirmations.
        We key off the MODEL'S own claims (not user keywords), e.g.:
        "I updated/scanned/changed/wrote/created ..."
        """
        if not ai_content:
            return False
        t = ai_content.strip().lower()

        # Strong completion/operation claims (active + passive voice).
        claim_phrases = [
            "i updated", "updated the", "has been updated", "have been updated",
            "i changed", "changed the", "has been changed", "have been changed",
            "i modified", "modified the", "has been modified", "have been modified",
            "i rewrote", "rewrote the", "has been rewritten", "have been rewritten",
            "i created", "created the", "has been created", "have been created",
            "i wrote", "wrote the", "has been written", "have been written",
            "i scanned", "scanned the", "has been scanned", "have been scanned",
            "is set to", "has been set", "set to vue", "switched to",
            "applied the", "done", "completed", "confirmed",
        ]
        # Future-action commitments that still require immediate tool calls.
        promise_phrases = [
            "i will update", "i'll update", "i can update", "i can modify",
            "i will change", "i'll change", "i will scan", "i'll scan",
            "i can propagate", "i will propagate",
        ]
        # Mutating/scanning objects where tool execution should exist.
        target_phrases = [
            "design", "document", "tech_stack", "tech stack", "frontend",
            "architecture", "api", "database", "requirements",
            "codebase", "workspace", "file", "section",
        ]
        has_target = any(s in t for s in target_phrases)
        has_claim = any(p in t for p in claim_phrases)
        has_promise = any(p in t for p in promise_phrases)
        return has_target and (has_claim or has_promise)

    # Call LLM with tools - catch context length errors
    chain = prompt | llm_with_tools
    
    _log.info("[PLANNER NODE] Calling LLM with %d messages", len(messages))
    ctx = get_tool_context()
    sid = ctx[0] if ctx and len(ctx) > 0 else ""
    _workspace_log_llm(
        "llm_request",
        {
            "session_id": sid,
            "source": "planner_node",
            "messages": _serialize_messages_for_log(messages),
        },
    )
    try:
        response = chain.invoke({"messages": messages})
        _workspace_log_llm(
            "llm_response",
            {
                "session_id": sid,
                "source": "planner_node",
                "content": str(getattr(response, "content", "") or ""),
                "tool_calls": getattr(response, "tool_calls", None) or [],
            },
        )
        _log.info("[PLANNER NODE] LLM response received - content length: %d, tool_calls: %d", 
                  len(str(response.content)) if hasattr(response, 'content') else 0,
                  len(getattr(response, 'tool_calls', [])))
    except Exception as e:
        # Check if it's a context length exceeded error
        error_msg = str(e)
        if BadRequestError and isinstance(e, BadRequestError):
            if "context_length_exceeded" in error_msg or "tokens exceed" in error_msg.lower():
                # Return a helpful message to the user
                error_response = AIMessage(
                    content=json.dumps({
                        "content": "**Context Length Exceeded**\n\nThe conversation history has become too long "
                                   f"({error_msg.split('resulted in ')[1].split(' ')[0] if 'resulted in' in error_msg else 'exceeded'} tokens). "
                                   "Please use the **Compress Context** button to summarize older messages and continue.\n\n"
                                   "The Compress Context feature will:\n"
                                   "- Keep your recent messages intact\n"
                                   "- Summarize older conversation history\n"
                                   "- Allow you to continue working\n\n"
                                   "After compressing, you can send your message again."
                    }),
                    tool_calls=[]
                )
                return {
                    "messages": [error_response],
                    # Don't overwrite mode - preserve user's choice
                    # "mode": "plan",  # REMOVED
                    "scratchpad": state.get("scratchpad", "") + "\n[ERROR] Context length exceeded",
                }
        # Re-raise if it's not a context length error
        raise
    
    raw_tool_calls = getattr(response, "tool_calls", None)
    response_text = str(getattr(response, "content", "") or "")
    tool_exec_count, failed_tool_exec_count = _tool_exec_summary_since_last_user(messages)
    had_any_tool_exec = tool_exec_count > 0
    had_failed_tool_exec = failed_tool_exec_count > 0

    def _tool_call_name(tc: Any) -> str:
        if isinstance(tc, dict):
            return str(tc.get("name", "") or "")
        return str(getattr(tc, "name", "") or "")

    # Guardrail: if model text claims it changed/scanned something but returned no tool_calls,
    # force one retry with strict reminder to emit concrete design_* tool calls.
    if (
        not had_any_tool_exec
        and _response_claims_action_without_evidence(response_text)
        and not (isinstance(raw_tool_calls, list) and raw_tool_calls)
    ):
        _log.warning("[PLANNER NODE] Missing tool call for design-update intent; retrying with strict reminder")
        retry_messages = list(messages) + [
            HumanMessage(
                content=(
                    "SYSTEM ENFORCEMENT: Your prior response claimed or committed an action but provided no tool_calls. "
                    "You MUST execute tool calls in this retry. "
                    "At minimum call design_read(doc_type='tech_stack') to verify current state. "
                    "If any change is needed, call design_write with the full updated document content. "
                    "Do NOT respond with text-only confirmation."
                )
            )
        ]
        try:
            _workspace_log_llm(
                "llm_request",
                {
                    "session_id": sid,
                    "source": "planner_node_retry_missing_tool_call",
                    "messages": _serialize_messages_for_log(retry_messages),
                },
            )
            response_retry = chain.invoke({"messages": retry_messages})
            _workspace_log_llm(
                "llm_response",
                {
                    "session_id": sid,
                    "source": "planner_node_retry_missing_tool_call",
                    "content": str(getattr(response_retry, "content", "") or ""),
                    "tool_calls": getattr(response_retry, "tool_calls", None) or [],
                },
            )
            retry_tool_calls = getattr(response_retry, "tool_calls", None)
            if isinstance(retry_tool_calls, list) and retry_tool_calls:
                response = response_retry
                raw_tool_calls = retry_tool_calls
                _log.info("[PLANNER NODE] Retry produced %d tool calls", len(retry_tool_calls))
            else:
                _log.error("[PLANNER NODE] Retry still produced no tool calls after claimed action text")
                response = AIMessage(
                    content=json.dumps({
                        "content": (
                            "I claimed an update but no tool call was produced. "
                            "No document changes were executed. Please retry the request."
                        )
                    }),
                    tool_calls=[]
                )
                raw_tool_calls = []
        except Exception as retry_err:
            _log.exception("[PLANNER NODE] Retry failed: %s", retry_err)

    # Guardrail: action/update claims must include at least one mutating design call.
    # Repeated read-only verification should not count as execution evidence.
    if (
        not had_any_tool_exec
        and _response_claims_action_without_evidence(response_text)
        and isinstance(raw_tool_calls, list)
        and raw_tool_calls
    ):
        names = [_tool_call_name(tc) for tc in raw_tool_calls]
        has_mutating_design_call = any(n in {"design_write", "design_create"} for n in names)
        if not has_mutating_design_call:
            _log.warning(
                "[PLANNER NODE] Claimed action but only read-only tool calls were emitted (%s); retrying for mutating call",
                names,
            )
            retry_messages = list(messages) + [
                HumanMessage(
                    content=(
                        "SYSTEM ENFORCEMENT: Your prior response claimed an update/change, but only read-only tool calls were emitted. "
                        "You MUST call design_write with the full updated document content now. "
                        "If the document is already correct, still call design_write to normalize/overwrite stale variants and ensure consistency. "
                        "Do NOT reply with read-only verification only."
                    )
                )
            ]
            try:
                _workspace_log_llm(
                    "llm_request",
                    {
                        "session_id": sid,
                        "source": "planner_node_retry_mutating_call",
                        "messages": _serialize_messages_for_log(retry_messages),
                    },
                )
                response_retry = chain.invoke({"messages": retry_messages})
                _workspace_log_llm(
                    "llm_response",
                    {
                        "session_id": sid,
                        "source": "planner_node_retry_mutating_call",
                        "content": str(getattr(response_retry, "content", "") or ""),
                        "tool_calls": getattr(response_retry, "tool_calls", None) or [],
                    },
                )
                retry_tool_calls = getattr(response_retry, "tool_calls", None)
                if isinstance(retry_tool_calls, list) and retry_tool_calls:
                    response = response_retry
                    raw_tool_calls = retry_tool_calls
                    _log.info("[PLANNER NODE] Retry produced %d tool calls after read-only mismatch", len(retry_tool_calls))
                else:
                    _log.error("[PLANNER NODE] Retry still produced no tool calls after read-only mismatch")
                    response = AIMessage(
                        content=json.dumps({
                            "content": (
                                "No document changes were executed. "
                                "The model emitted read-only verification without a mutating design tool call."
                            )
                        }),
                        tool_calls=[]
                    )
                    raw_tool_calls = []
            except Exception as retry_err:
                _log.exception("[PLANNER NODE] Retry failed after read-only mismatch: %s", retry_err)

    # If previous tools in this user turn failed, do not allow text-only completion claims.
    if (
        had_failed_tool_exec
        and _response_claims_action_without_evidence(response_text)
        and not (isinstance(raw_tool_calls, list) and raw_tool_calls)
    ):
        _log.warning(
            "[PLANNER NODE] Prior tool failures detected (%d/%d); blocking text-only completion claim",
            failed_tool_exec_count,
            tool_exec_count,
        )
        retry_messages = list(messages) + [
            HumanMessage(
                content=(
                    "SYSTEM ENFORCEMENT: One or more prior tool executions failed in this turn. "
                    "Do NOT claim completion in text-only form. "
                    "Either emit corrective tool calls now, or explicitly report that changes were not completed due to tool errors."
                )
            )
        ]
        try:
            _workspace_log_llm(
                "llm_request",
                {
                    "session_id": sid,
                    "source": "planner_node_retry_failed_tool_exec",
                    "messages": _serialize_messages_for_log(retry_messages),
                },
            )
            response_retry = chain.invoke({"messages": retry_messages})
            _workspace_log_llm(
                "llm_response",
                {
                    "session_id": sid,
                    "source": "planner_node_retry_failed_tool_exec",
                    "content": str(getattr(response_retry, "content", "") or ""),
                    "tool_calls": getattr(response_retry, "tool_calls", None) or [],
                },
            )
            retry_tool_calls = getattr(response_retry, "tool_calls", None)
            retry_text = str(getattr(response_retry, "content", "") or "")
            if isinstance(retry_tool_calls, list) and retry_tool_calls:
                response = response_retry
                raw_tool_calls = retry_tool_calls
                _log.info("[PLANNER NODE] Failure-recovery retry produced %d tool calls", len(retry_tool_calls))
            elif _response_claims_action_without_evidence(retry_text):
                response = AIMessage(
                    content=json.dumps({
                        "content": (
                            "Some tool executions failed, so no further changes were completed in this turn. "
                            "Please retry or adjust the request."
                        )
                    }),
                    tool_calls=[]
                )
                raw_tool_calls = []
            else:
                response = response_retry
                raw_tool_calls = retry_tool_calls
        except Exception as retry_err:
            _log.exception("[PLANNER NODE] Failure-recovery retry failed: %s", retry_err)

    # Use response directly if it has valid tool_calls (LangChain format)
    if isinstance(raw_tool_calls, list) and raw_tool_calls:
        # LLM made proper tool calls - use response as-is
        parsed_response = response
    else:
        # Parse JSON response for questions/content
        content = str(response.content) if hasattr(response, 'content') else ""
        json_data = parse_json_response(content)
        parsed_response = create_ai_message_from_json(json_data, response)
    
    # Extract content for scratchpad
    content_str = str(parsed_response.content) if hasattr(parsed_response, 'content') else ""
    scratchpad_content = content_str[:200] if content_str else "(tool calls)"
    
    _log.info("[PLANNER NODE] Returning - content length: %d, first 100 chars: %s", 
              len(content_str), content_str[:100])
    
    # Update state
    return {
        "messages": [parsed_response],
        # Don't overwrite mode - let user's choice persist
        # "mode": "plan",  # REMOVED - was overwriting user's mode choice
        "scratchpad": state.get("scratchpad", "") + f"\n[PLAN] {scratchpad_content}...",
    }


def editor_node(
    state: AgentState,
    llm: BaseChatModel,
    registry: PromptRegistry,
    workspace_root: str = None,
) -> AgentState:
    """
    Editor node - executes edits and tool calls.
    
    Uses BEAST_PROVIDER_SYSTEM prompt (or similar) and has access to all tools.
    All responses are parsed as JSON.
    AGENTS.md / CLAUDE.md (project + global) are appended to system prompt.
    Includes execution progress reporting instructions.
    """
    # Get user's intended mode from initial state
    user_mode = state.get("mode", "edit")
    
    # Get editor mode prompt with context injection and JSON enforcement
    # Using BEAST_PROVIDER_SYSTEM as the main system prompt for edit mode
    system_prompt = registry.get_prompt("BEAST_PROVIDER_SYSTEM", force_json=True)
    
    # Add mode reminder 
    mode_reminder = f"\n\n<MODE_CONTEXT>\nUSER SELECTED MODE: {user_mode.upper()}\n"
    if user_mode == "edit":
        try:
            build_switch_msg = registry.get_prompt("BUILD_SWITCH_SYSTEM_REMINDER")
            mode_reminder += f"{build_switch_msg}\n"
        except Exception:
            mode_reminder += "You are in EDIT/BUILD MODE - You CAN make file edits and execute tools to implement solutions.\n"
    mode_reminder += "</MODE_CONTEXT>\n\n"
    system_prompt = system_prompt + mode_reminder
    
    if workspace_root:
        parts = instruction_system(workspace_root)
        if parts:
            system_prompt = system_prompt.rstrip() + "\n\n" + "\n\n".join(parts)
    # Escape literal braces so ChatPromptTemplate does not treat JSON examples as variables
    system_prompt = system_prompt.replace("{", "{{").replace("}", "}}")

    # Build messages
    messages = state["messages"]

    # Bind tools to LLM
    tools = get_tools()
    llm_with_tools = llm.bind_tools(tools).with_config({"run_name": "editor"})
    
    # Create prompt with system message
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
    ])
    
    # Call LLM with tools - catch context length errors
    chain = prompt | llm_with_tools
    ctx = get_tool_context()
    sid = ctx[0] if ctx and len(ctx) > 0 else ""
    _workspace_log_llm(
        "llm_request",
        {
            "session_id": sid,
            "source": "editor_node",
            "messages": _serialize_messages_for_log(messages),
        },
    )
    try:
        response = chain.invoke({"messages": messages})
        _workspace_log_llm(
            "llm_response",
            {
                "session_id": sid,
                "source": "editor_node",
                "content": str(getattr(response, "content", "") or ""),
                "tool_calls": getattr(response, "tool_calls", None) or [],
            },
        )
    except Exception as e:
        # Check if it's a context length exceeded error
        error_msg = str(e)
        if BadRequestError and isinstance(e, BadRequestError):
            if "context_length_exceeded" in error_msg or "tokens exceed" in error_msg.lower():
                # Return a helpful message to the user
                error_response = AIMessage(
                    content=json.dumps({
                        "content": "**Context Length Exceeded**\n\nThe conversation history has become too long "
                                   f"({error_msg.split('resulted in ')[1].split(' ')[0] if 'resulted in' in error_msg else 'exceeded'} tokens). "
                                   "Please use the **Compress Context** button to summarize older messages and continue.\n\n"
                                   "The Compress Context feature will:\n"
                                   "- Keep your recent messages intact\n"
                                   "- Summarize older conversation history\n"
                                   "- Allow you to continue working\n\n"
                                   "After compressing, you can send your message again."
                    }),
                    tool_calls=[]
                )
                return {
                    "messages": [error_response],
                    # Don't overwrite mode - preserve user's choice
                    # "mode": "edit",  # REMOVED
                    "scratchpad": state.get("scratchpad", "") + "\n[ERROR] Context length exceeded",
                }
        # Re-raise if it's not a context length error
        raise
    
    # Parse JSON response if it contains JSON
    content = str(response.content) if hasattr(response, 'content') else ""
    
    # Use response directly only if tool_calls is a valid list (LangChain requires list, not None)
    raw_tool_calls = getattr(response, "tool_calls", None)
    if isinstance(raw_tool_calls, list) and raw_tool_calls:
        parsed_response = response
    else:
        # Parse JSON or build AIMessage with tool_calls=[] so validation passes
        json_data = parse_json_response(content)
        parsed_response = create_ai_message_from_json(json_data, response)
    
    # Update state
    scratchpad_content = ""
    if isinstance(parsed_response, AIMessage):
        if parsed_response.tool_calls:
            scratchpad_content = "Tool calls"
        else:
            content = str(parsed_response.content) if parsed_response.content else ""
            json_data = parse_json_response(content)
            scratchpad_content = json_data.get('content', '')[:200]
    
    return {
        "messages": [parsed_response],
        # Don't overwrite mode - let user's choice persist
        # "mode": "edit",  # REMOVED - was overwriting user's mode choice
        "scratchpad": state.get("scratchpad", "") + f"\n[EDIT] {scratchpad_content}...",
    }


def _is_approval_phrase(content: str) -> bool:
    """True if the user message is approving / asking to proceed with a plan."""
    if not content or not isinstance(content, str):
        return False
    lower = content.strip().lower()
    phrases = [
        "proceed", "go ahead", "implement", "approve", "yes", "start",
        "do it", "execute", "begin", "sounds good", "looks good", "approved",
    ]
    return any(p in lower for p in phrases)


def route_entry(state: AgentState) -> Literal["planner", "editor"]:
    """
    Entry router: STRICTLY routes based on user's mode choice.
    
    - mode="plan" → always routes to planner (read-only, planning only)
    - mode="edit" → always routes to editor (execution with tools)
    
    NOTE: Mode is determined by user's UI selection and NEVER changes based on 
    message content or approval phrases. User must explicitly toggle mode in UI.
    """
    # Strictly enforce user's mode choice - no automatic transitions
    mode = state.get("mode", "plan")
    
    if mode == "edit":
        return "editor"
    else:
        return "planner"


def should_call_tools_from_planner(state: AgentState) -> Literal["tools", END]:
    """
    Route function from planner node - check if tools should be called.
    
    Prevents infinite loops by checking if tools were just executed.
    """
    from langchain_core.messages import ToolMessage
    
    messages = state["messages"]
    if not messages:
        return END
    
    last_message = messages[-1]
    
    # Check for tool calls
    if isinstance(last_message, AIMessage):
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            def _tc_name(tc: Any) -> str:
                if isinstance(tc, dict):
                    return str(tc.get("name", "") or "")
                return str(getattr(tc, "name", "") or "")

            def _tc_args(tc: Any) -> dict:
                raw = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
                if isinstance(raw, dict):
                    return raw
                if isinstance(raw, str) and raw.strip():
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return {}
                return {}

            def _tool_call_signature(ai_msg: AIMessage) -> tuple:
                calls = getattr(ai_msg, "tool_calls", None) or []
                sig = []
                for tc in calls:
                    name = _tc_name(tc)
                    args = _tc_args(tc)
                    sig.append((name, json.dumps(args, sort_keys=True, default=str)))
                return tuple(sig)

            pending_calls = list(last_message.tool_calls)
            pending_names = [_tc_name(tc) for tc in pending_calls]

            # Loop breaker: prevent repeated read-only verification cycles.
            # Pattern seen in logs: design_read -> planner -> design_read (same docs) -> ...
            if pending_names and all(n == "design_read" for n in pending_names):
                prev_ai_with_tools = None
                for msg in reversed(messages[:-1]):
                    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                        prev_ai_with_tools = msg
                        break
                if prev_ai_with_tools is not None:
                    prev_sig = _tool_call_signature(prev_ai_with_tools)
                    curr_sig = _tool_call_signature(last_message)
                    if prev_sig == curr_sig:
                        _log = logging.getLogger(__name__)
                        _log.warning(
                            "[Loop Prevention] Blocking repeated planner read-only cycle: %s",
                            [n for n in pending_names],
                        )
                        return END

            # Before executing tools, check if we just executed the same tools
            # Look for ToolMessages in the last 20 messages
            recent_tool_messages = [
                msg for msg in messages[-20:] 
                if isinstance(msg, ToolMessage)
            ]
            
            # If we have recent tool executions and the LLM is trying to call tools again,
            # check if it's calling the SAME tools (likely infinite loop)
            if recent_tool_messages:
                # Count how many design_create calls we've made recently
                # Look for the specific success pattern "✓ Created" to avoid counting design_list
                design_create_count = sum(
                    1 for msg in recent_tool_messages 
                    if "✓ created" in str(msg.content).lower()
                )
                
                _log = logging.getLogger(__name__)
                _log.info(f"[Loop Prevention] design_create_count={design_create_count}, tool_calls_pending={len(last_message.tool_calls)}")
                
                # If we've already created all 7 documents, allow ONE more turn for the agent to respond
                # This prevents the infinite loop but allows the agent to ask questions after creating docs
                if design_create_count >= 7:
                    # Check if the pending tool call is ANOTHER design_create (would be 8th)
                    next_tool_names = [tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "") for tc in last_message.tool_calls]
                    if "design_create" in next_tool_names:
                        _log.info(f"[Loop Prevention] Blocking 8th design_create call - documents complete")
                        return END
                    # Otherwise allow other tool calls (agent might need to read docs, etc.)
                    _log.info(f"[Loop Prevention] Allowing non-create tool call: {next_tool_names}")
                    return "tools"
            
            # Otherwise, proceed with tool calls
            return "tools"
    
    return END


def should_continue_to_editor(state: AgentState) -> Literal["editor", END]:
    """
    Route function from planner node.
    
    In PLAN mode: ALWAYS return END (stay in planning, never transition to editor)
    In EDIT mode: This should never be called (edit mode routes directly to editor)
    
    Mode transitions ONLY happen when user explicitly toggles mode in UI.
    """
    # In plan mode, planner always ends - never transition to editor
    # User must toggle to edit mode in UI to use editor
    if state.get("mode") == "plan":
        return END
    
    # This branch should not be reached (edit mode goes straight to editor)
    # But if somehow we're here in edit mode, go to editor
    return "editor"


def should_call_tools(state: AgentState) -> Literal["tools", "editor", END]:
    """
    Route function: determines if tools should be called or continue to editor.
    
    Checks if the last message contains tool calls.
    """
    messages = state["messages"]
    if not messages:
        return END
    
    last_message = messages[-1]
    
    # Check for tool calls
    if isinstance(last_message, AIMessage):
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
    
    # Check if we're done
    if isinstance(last_message, AIMessage):
        content = last_message.content.lower() if hasattr(last_message, 'content') else ""
        if any(keyword in content for keyword in ["done", "complete", "finished"]):
            return END
    
    return "editor"


# ============================================================================
# Graph Construction
# ============================================================================

def create_agent_graph(
    llm: BaseChatModel,
    workspace_root: str = None,
    registry: PromptRegistry = None
) -> StateGraph:
    """
    Create the LangGraph state machine for the agent.
    
    Args:
        llm: The language model to use
        workspace_root: Workspace root directory
        registry: Prompt registry (creates new one if not provided)
    
    Returns:
        Compiled StateGraph ready to run
    """
    if registry is None:
        registry = create_prompt_registry(workspace_root)
    
    # Create graph
    workflow = StateGraph(AgentState)
    
    # Router: no state change, only routes entry to planner or editor
    workflow.add_node("router", lambda state: state)
    wr = workspace_root or ""
    workflow.add_node("planner", lambda state: planner_node(state, llm, registry, wr))
    workflow.add_node("editor", lambda state: editor_node(state, llm, registry, wr))
    
    # Add tool node: execute tools in LLM order, one at a time (sequential)
    tools = get_tools(workspace_root=workspace_root)
    workflow.add_node("tools", create_sequential_tool_node(tools))
    
    # Add Todo Tracker node
    try:
        from server.agent.todo_tracker import todo_tracker_node
    except ImportError:
        from todo_tracker import todo_tracker_node
    workflow.add_node("todo_tracker", todo_tracker_node)
    
    # Entry: when user said "proceed with your plan", go to editor; else planner
    workflow.set_entry_point("router")
    workflow.add_conditional_edges("router", route_entry, {"planner": "planner", "editor": "editor"})
    
    # Add edges for planner - can call tools, then returns to planner or ends
    workflow.add_conditional_edges(
        "planner",
        should_call_tools_from_planner,
        {
            "tools": "tools",
            END: END,
        }
    )
    
    # Add edges for editor - can call tools
    workflow.add_conditional_edges(
        "editor",
        should_call_tools,
        {
            "tools": "tools",
            "editor": "editor",  # Continue editing
            END: END,
        }
    )
    
    # Route tools back based on mode
    def route_from_tools(state: AgentState) -> Literal["planner", "todo_tracker"]:
        """After tools execute, return to the appropriate node based on mode."""
        mode = state.get("mode", "plan")
        return "planner" if mode == "plan" else "todo_tracker"
    
    workflow.add_conditional_edges("tools", route_from_tools, {"planner": "planner", "todo_tracker": "todo_tracker"})
    
    def route_from_todo_tracker(state: AgentState) -> Literal["editor", END]:
        """
        In single-todo runs (triggered by "Process Todo #X"), stop once that todo is completed.
        This prevents the agent from auto-executing the next todo without an explicit user click.
        """
        scratchpad = state.get("scratchpad", "") or ""
        marker = "SINGLE_TODO_ID="
        if marker not in scratchpad:
            return "editor"
        # Extract target todo id from scratchpad marker like: [SINGLE_TODO_ID=2]
        try:
            start = scratchpad.index(marker) + len(marker)
            end = scratchpad.find("]", start)
            target_id = scratchpad[start:end] if end != -1 else scratchpad[start:]
            target_id = target_id.strip()
        except Exception:
            return "editor"
        if not target_id:
            return "editor"

        messages = state.get("messages") or []
        if not messages:
            return "editor"
        last = messages[-1]
        if not isinstance(last, AIMessage):
            return "editor"
        try:
            data = json.loads(str(last.content))
        except Exception:
            return "editor"
        todos = data.get("todos") if isinstance(data, dict) else None
        if not isinstance(todos, list):
            return "editor"

        target_completed = False
        for t in todos:
            if str(t.get("id")) == target_id and str(t.get("status", "")).lower() == "completed":
                target_completed = True
                break
        if target_completed:
            return END
        return "editor"

    workflow.add_conditional_edges("todo_tracker", route_from_todo_tracker, {"editor": "editor", END: END})
    
    return workflow.compile()


# ============================================================================
# Convenience Functions
# ============================================================================

def create_agent(
    llm: BaseChatModel,
    workspace_root: str = None,
    initial_mode: Literal["plan", "edit"] = "plan"
) -> StateGraph:
    """
    Create a configured agent graph.
    
    Args:
        llm: Language model instance
        workspace_root: Workspace root directory
        initial_mode: Starting mode ("plan" or "edit") - currently always starts at planner
    
    Returns:
        Compiled agent graph
    """
    registry = create_prompt_registry(workspace_root)
    graph = create_agent_graph(llm, workspace_root, registry)
    
    # Note: The graph always starts at "planner" node
    # The mode in state is used for tracking, but entry is always planner
    return graph


__all__ = [
    "AgentState",
    "PromptRegistry",
    "create_prompt_registry",
    "create_agent_graph",
    "create_agent",
    "planner_node",
    "editor_node",
    "should_continue_to_editor",
    "should_call_tools",
]
