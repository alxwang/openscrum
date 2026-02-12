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
from pathlib import Path
from typing import TypedDict, List, Literal, Dict, Any, Optional, Callable
from typing_extensions import Annotated

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

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
    plan_exit, plan_enter,
    __all__ as TOOL_NAMES,
)


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
    # Extract content - if not present, serialize the entire JSON as a string
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
    Planner node - generates a plan without executing tools.
    
    Uses PLAN_MODE_SYSTEM_REMINDER prompt and operates in read-only mode.
    All responses are parsed as JSON.
    AGENTS.md / CLAUDE.md (project + global) are appended to system prompt.
    """
    # Get plan mode prompt with context injection and JSON enforcement
    system_prompt = registry.get_prompt("PLAN_MODE_SYSTEM_REMINDER", force_json=True)
    if workspace_root:
        parts = instruction_system(workspace_root)
        if parts:
            system_prompt = system_prompt.rstrip() + "\n\n" + "\n\n".join(parts)
    # Escape literal braces so ChatPromptTemplate does not treat JSON examples as variables
    system_prompt = system_prompt.replace("{", "{{").replace("}", "}}")

    # Build messages
    messages = state["messages"]

    # Create prompt with system message
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
    ])
    
    # Call LLM (no tools in plan mode)
    chain = prompt | llm.with_config({"run_name": "planner"})
    
    response = chain.invoke({"messages": messages})
    
    # Parse JSON response
    content = str(response.content) if hasattr(response, 'content') else ""
    json_data = parse_json_response(content)
    parsed_response = create_ai_message_from_json(json_data, response)
    
    # Extract content for scratchpad - ensure it's a string
    scratchpad_content = json_data.get('content', '')
    if isinstance(scratchpad_content, dict):
        scratchpad_content = json.dumps(scratchpad_content)
    else:
        scratchpad_content = str(scratchpad_content)
    
    # Update state
    return {
        "messages": [parsed_response],
        "mode": "plan",
        "scratchpad": state.get("scratchpad", "") + f"\n[PLAN] {scratchpad_content[:200]}...",
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
    # Get editor mode prompt with context injection and JSON enforcement
    # Using BEAST_PROVIDER_SYSTEM as the main system prompt for edit mode
    system_prompt = registry.get_prompt("BEAST_PROVIDER_SYSTEM", force_json=True)
    
    # Add execution progress reporting instructions
    execution_progress_prompt = registry.get_prompt("EXECUTION_PROGRESS_SYSTEM_REMINDER", force_json=False)
    system_prompt = system_prompt.rstrip() + "\n\n" + execution_progress_prompt
    
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
    
    # Call LLM with tools
    chain = prompt | llm_with_tools
    response = chain.invoke({"messages": messages})
    
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
        "mode": "edit",
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
    Entry router: start at editor when user is approving an existing plan OR when mode is explicitly "edit".
    
    If the last message is a user approval and the previous is an assistant message
    (the plan), go straight to editor so the agent uses tools instead of asking
    "which plan?". Also route to editor if initial mode is "edit".
    Otherwise start at planner.
    """
    # Check if mode is explicitly set to "edit" - skip planning and go straight to editor
    if state.get("mode") == "edit":
        return "editor"
    
    messages = state["messages"]
    if len(messages) < 2:
        return "planner"
    last = messages[-1]
    prev = messages[-2]
    if isinstance(last, HumanMessage) and isinstance(prev, AIMessage):
        content = (last.content or "").strip().lower()
        if _is_approval_phrase(content):
            return "editor"
    return "planner"


def should_continue_to_editor(state: AgentState) -> Literal["editor", END]:
    """
    Route function: determines if plan is approved and should move to editor.
    
    Checks if the last message indicates plan approval or contains edit instructions.
    """
    messages = state["messages"]
    if not messages:
        return END
    
    last_message = messages[-1]
    
    # Check for explicit approval keywords
    if isinstance(last_message, AIMessage):
        content = last_message.content.lower() if hasattr(last_message, 'content') else ""
        if any(keyword in content for keyword in ["approved", "ready to implement", "start editing", "begin implementation"]):
            return "editor"
    
    # Check for user approval
    if isinstance(last_message, HumanMessage):
        content = (last_message.content or "").strip().lower()
        if _is_approval_phrase(content):
            return "editor"
    
    # Default: stay in plan mode or end
    if state.get("mode") == "plan":
        return END  # Plan mode complete, need explicit approval
    
    return "editor"  # Already in edit mode or transitioning


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
    
    # Entry: when user said "proceed with your plan", go to editor; else planner
    workflow.set_entry_point("router")
    workflow.add_conditional_edges("router", route_entry, {"planner": "planner", "editor": "editor"})
    
    # Add edges
    workflow.add_conditional_edges(
        "planner",
        should_continue_to_editor,
        {
            "editor": "editor",
            END: END,
        }
    )
    
    workflow.add_conditional_edges(
        "editor",
        should_call_tools,
        {
            "tools": "tools",
            "editor": "editor",  # Continue editing
            END: END,
        }
    )
    
    # Tools always return to editor
    workflow.add_edge("tools", "editor")
    
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
