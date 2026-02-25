import json
import logging
import os
from typing import Dict, Any

from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from .graph import AgentState

_log = logging.getLogger(__name__)


def _render_recent_activity(messages: list, limit: int = 20) -> str:
    """
    Convert recent LangChain messages into plain text lines.
    This avoids sending raw tool-role messages that may violate OpenAI
    chat sequencing requirements when a sliced window is used.
    """
    lines: list[str] = []
    for msg in messages[-limit:]:
        role = getattr(msg, "type", msg.__class__.__name__).lower()
        content = str(getattr(msg, "content", "") or "").strip()

        if role == "human":
            lines.append(f"user: {content}")
            continue

        if role == "ai":
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                names = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        names.append(str(tc.get("name", "unknown")))
                    else:
                        names.append(str(getattr(tc, "name", "unknown")))
                lines.append(f"assistant tool_calls: {', '.join(names)}")
            if content:
                lines.append(f"assistant: {content}")
            continue

        if role == "tool":
            call_id = getattr(msg, "tool_call_id", "")
            if call_id:
                lines.append(f"tool[{call_id}]: {content}")
            else:
                lines.append(f"tool: {content}")
            continue

        if content:
            lines.append(f"{role}: {content}")

    # Keep context compact to reduce tracker cost/latency
    return "\n".join(lines)[-12000:]

def todo_tracker_node(state: AgentState) -> Dict[str, Any]:
    """
    Dedicated node to update the Todo list automatically after every tool cycle.
    Uses a small, fast model to parse recent actions and maintain the Todo JSON
    in the backend storage, and streams a progress update to the frontend.
    """
    try:
        from server.storage.todo import get_todos, update_todos
        from server.tools.context import get_tool_context
    except ImportError:
        from storage.todo import get_todos, update_todos
        from tools.context import get_tool_context

    ctx = get_tool_context()
    if not ctx or len(ctx) == 0:
        return {}
    session_id = ctx[0]
    if not session_id:
        return {}
        
    messages = state.get("messages", [])
    if not messages:
        return {}

    current_todos = get_todos(session_id)
    
    sys_prompt = """You are an invisible background process managing an automated agent's Todo list.
The main agent is executing tasks. Based on the recent conversation history and the CURRENT Todo list, evaluate the agent's progress and update the Todo list.
You must output a JSON object enforcing the state.

Current Todo List:
{current_todos}

Rules for updating:
1. Mark completed steps as 'completed'
2. If the agent discovers new requirements, add new steps to the end
3. Identify the current active 'in_progress' step
4. You MUST retain the exact 'id' string for existing steps (they may be UUIDs). DO NOT change existing IDs.
5. Step statuses: pending, in_progress, completed, cancelled
6. PRIORITY: Always order steps based on strictly required **engineering dependencies** (what needs to be built first to unblock later tasks).
7. NUMBERING: Every step's `content` must start with a `#number` indicating its sequence (e.g., "#1 Create DB schema", "#2 Build API route"). Update numbers if sequence changes.

You MUST output EXACTLY this JSON format:
{{
  "todos": [
    {{"id": "a1b2c3d4", "content": "#1 Step 1 description", "status": "completed", "priority": "high"}},
    {{"id": "e5f6g7h8", "content": "#2 Step 2 description", "status": "in_progress", "priority": "high"}}
  ],
  "status_message": "Brief description of what the agent just accomplished (1-2 sentences)",
  "next_action": "What the agent should do next"
}}
"""

    recent_activity = _render_recent_activity(messages, limit=20)
    
    try:
        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        llm = ChatOpenAI(model=model_name, temperature=0.1, model_kwargs={"response_format": {"type": "json_object"}})
        _log.info(f"[TodoTracker] Analyzing progress with {model_name}...")
        rendered_system = sys_prompt.format(current_todos=json.dumps(current_todos, indent=2))
        rendered_human = f"Recent conversation activity:\n{recent_activity}"
        res = llm.invoke([
            SystemMessage(content=rendered_system),
            HumanMessage(content=rendered_human),
        ])
        
        data = json.loads(str(res.content))
        new_todos = data.get("todos", current_todos)
        status_msg = data.get("status_message", "Executing tasks...")
        next_action = data.get("next_action", "Continuing to next step...")
        
        # 1. Save to backend database (sanitized to implementation-focused tasks)
        new_todos = update_todos(session_id, new_todos)
            
        # 2. Format JSON exactly as frontend App.vue expects
        active_step_id = "1"
        for t in new_todos:
            if t.get("status") == "in_progress":
                active_step_id = str(t.get("id"))
                break
                
        frontend_json = {
            "todos": new_todos,
            "current_progress": {
                "step": int(active_step_id) if active_step_id.isdigit() else active_step_id,
                "status": status_msg,
                "next_step": next_action
            }
        }
        
        # 3. Return an AIMessage so the LLM history tracks progress and the streaming engine pushes it to UI
        # We name it 'todo_tracker' to uniquely identify this message
        _log.info(f"[TodoTracker] Emitting progress update for step {active_step_id}")
        return {"messages": [AIMessage(content=json.dumps(frontend_json, indent=2), name="todo_tracker")]}
        
    except Exception as e:
        _log.error(f"[TodoTracker] Failed to track progress: {e}")
        return {}
