"""
LangGraph State Machine for OpenScrum Agent

Implements the Plan -> Edit workflow with tool execution.
All LLM communication is forced to JSON format.
"""

import os
import json
import re
from typing import TypedDict, List, Literal, Dict, Any
from typing_extensions import Annotated

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages

from .prompt_registry import PromptRegistry
from ..tools.system_tools import (
    read, write, edit, multiedit, apply_patch,
    grep, glob, list_files, bash, webfetch,
    todowrite, todoread, question,
    task, websearch, codesearch, batch, lsp,
    plan_exit, plan_enter
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

def create_prompt_registry(workspace_root: str = None) -> PromptRegistry:
    """Create and configure the prompt registry."""
    return PromptRegistry(workspace_root=workspace_root)


# ============================================================================
# Tool Setup
# ============================================================================

def get_tools():
    """Get all available tools for the agent."""
    return [
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
    content = json_data.get("content", "")
    tool_calls_data = json_data.get("tool_calls", [])
    
    # Convert tool_calls to LangChain format
    tool_calls = []
    for tc in tool_calls_data:
        tool_calls.append({
            "name": tc.get("name", ""),
            "args": tc.get("arguments", {}),
            "id": tc.get("id", f"call_{len(tool_calls)}"),
        })
    
    # Create new AIMessage
    return AIMessage(
        content=content,
        tool_calls=tool_calls if tool_calls else None,
    )


# ============================================================================
# Graph Nodes
# ============================================================================

def planner_node(state: AgentState, llm: BaseChatModel, registry: PromptRegistry) -> AgentState:
    """
    Planner node - generates a plan without executing tools.
    
    Uses PLAN_MODE_SYSTEM_REMINDER prompt and operates in read-only mode.
    All responses are parsed as JSON.
    """
    # Get plan mode prompt with context injection and JSON enforcement
    system_prompt = registry.get_prompt("PLAN_MODE_SYSTEM_REMINDER", force_json=True)
    
    # Build messages
    messages = state["messages"]
    
    # Create prompt with system message
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
    ])
    
    # Call LLM (no tools in plan mode)
    chain = prompt | llm
    response = chain.invoke({"messages": messages})
    
    # Parse JSON response
    content = str(response.content) if hasattr(response, 'content') else ""
    json_data = parse_json_response(content)
    parsed_response = create_ai_message_from_json(json_data, response)
    
    # Update state
    return {
        "messages": [parsed_response],
        "mode": "plan",
        "scratchpad": state.get("scratchpad", "") + f"\n[PLAN] {json_data.get('content', '')[:200]}...",
    }


def editor_node(state: AgentState, llm: BaseChatModel, registry: PromptRegistry) -> AgentState:
    """
    Editor node - executes edits and tool calls.
    
    Uses BEAST_PROVIDER_SYSTEM prompt (or similar) and has access to all tools.
    All responses are parsed as JSON.
    """
    # Get editor mode prompt with context injection and JSON enforcement
    # Using BEAST_PROVIDER_SYSTEM as the main system prompt for edit mode
    system_prompt = registry.get_prompt("BEAST_PROVIDER_SYSTEM", force_json=True)
    
    # Build messages
    messages = state["messages"]
    
    # Bind tools to LLM
    tools = get_tools()
    llm_with_tools = llm.bind_tools(tools)
    
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
    
    # If response has tool_calls, use them directly (LangChain handles this)
    if hasattr(response, 'tool_calls') and response.tool_calls:
        parsed_response = response
    else:
        # Parse JSON response for content
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
        content = last_message.content.lower()
        if any(keyword in content for keyword in ["yes", "approve", "go ahead", "implement", "start"]):
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
    
    # Add nodes
    workflow.add_node("planner", lambda state: planner_node(state, llm, registry))
    workflow.add_node("editor", lambda state: editor_node(state, llm, registry))
    
    # Add tool node
    tools = get_tools()
    tool_node = ToolNode(tools)
    workflow.add_node("tools", tool_node)
    
    # Set entry point based on initial mode
    # Entry point will be determined by initial state mode
    workflow.set_entry_point("planner")  # Default to planner, can be overridden
    
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
