import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

try:
    from server.storage.todo import get_todos, update_todos
except ImportError:
    from storage.todo import get_todos, update_todos

_log = logging.getLogger(__name__)

def generate_todos_for_session(session_id: str, workspace_root: str) -> List[Dict[str, Any]]:
    """
    Reads workspace Design Documents (*.md) and current Todo list,
    then uses a fast LLM to generate missing actionable tasks.
    Merges them without duplicating existing logic.
    """
    current_todos = get_todos(session_id)
    
    # Extract existing highest ID
    highest_id = 0
    for t in current_todos:
        try:
            tid = int(t.get("id", 0))
            if tid > highest_id:
                highest_id = tid
        except ValueError:
            pass
            
    # Read design docs
    docs_content = ""
    has_design_docs = False
    if workspace_root:
        root_path = Path(workspace_root)
        design_path = root_path / ".openscrum" / "design"
        if design_path.exists():
            for md_file in design_path.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    if content.strip():
                        has_design_docs = True
                        docs_content += f"\n--- {md_file.name} ---\n{content}\n"
                except Exception as e:
                    _log.warning(f"Could not read {md_file.name} for todo generation: {e}")

    # Strict guardrail: do not generate todos when no design docs exist.
    if not has_design_docs:
        _log.info(f"[{session_id}] Skipping todo generation: no design docs found")
        return current_todos
                    
    sys_prompt = """You are an expert Technical Project Manager.
Your goal is to analyze the project's Design Documents and the Current Todo List, and output a SINGLE, Comprehensive, properly merged Todo List.

CRITICAL RULES:
1. MERGE & DEDUPLICATE: Retain all uncompleted tasks from the Current Todo List. Add any missing implementation steps defined in the Design Documents. DO NOT duplicate tasks.
2. PRIORITY: Always order ALL steps based on strictly required **engineering dependencies** (what needs to be built first to unblock later tasks).
3. NUMBERING: Every single step's `content` MUST start with a `#number` indicating its sequence (e.g., "#1 Create DB schema", "#2 Build API route"). 
4. DO NOT DOUBLE NUMBER: If an existing task already has a `#number` in its text, you MUST remove the old number before adding the new one. (e.g., Change "#4 Setup Database" to "#6 Setup Database", NOT "#6 #4 Setup Database").
5. IDs: For existing tasks that you keep, you MUST preserve their original `id` and `status`. For entirely new tasks, you do not need to provide an `id` (the system will assign one).

You MUST output an EXACT JSON object with a single "todos" array containing the full plan:
{{
  "todos": [
    {{"id": "1", "content": "#1 Setup database schema", "status": "pending", "priority": "high"}},
    {{"id": "2", "content": "#2 Implement auth middleware", "status": "pending", "priority": "high"}},
    {{"content": "#3 Create frontend login view", "status": "pending", "priority": "medium"}}
  ]
}}
"""

    human_msg = f"""
Current Todo List:
{json.dumps(current_todos, indent=2)}

Design Documents:
{docs_content}
"""

    try:
        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        llm = ChatOpenAI(model=model_name, temperature=0.1, model_kwargs={"response_format": {"type": "json_object"}})
        
        _log.info(f"[{session_id}] Generating Todos from {len(docs_content)} chars of docs using {model_name}...")
        res = llm.invoke([SystemMessage(content=sys_prompt), HumanMessage(content=human_msg)])
        
        data = json.loads(str(res.content))
        new_todos = data.get("todos", [])
        
        if not new_todos:
            return current_todos
            
        # Assign IDs to newly created tasks that lack them
        final_todos = []
        for task in new_todos:
            if "id" not in task or not str(task["id"]).strip():
                task["id"] = str(highest_id + 1)
                highest_id += 1
            if "status" not in task:
                task["status"] = "pending"
            final_todos.append(task)
            
        # Save and return the sanitized implementation-focused todo list
        saved_todos = update_todos(session_id, final_todos)
        return saved_todos
        
    except Exception as e:
        _log.error(f"Failed to generate todos: {e}")
        return current_todos
