import json
import logging
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
    if workspace_root:
        root_path = Path(workspace_root)
        design_path = root_path / ".openscrum" / "design"
        if design_path.exists():
            for md_file in design_path.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    docs_content += f"\n--- {md_file.name} ---\n{content}\n"
                except Exception as e:
                    _log.warning(f"Could not read {md_file.name} for todo generation: {e}")
                    
    sys_prompt = """You are an expert Technical Project Manager.
Your goal is to analyze the project's Design Documents and generate a list of actionable tasks (Todos) for the development agent.

DO NOT duplicate tasks that are already in the Current Todo List.
Focus primarily on implementation steps that are defined in the design documents but haven't been completed or listed yet.

You MUST output an EXACT JSON object with a single "new_tasks" array containing objects:
{{
  "new_tasks": [
    {{"content": "Implement auth middleware", "priority": "high"}},
    {{"content": "Setup database schema", "priority": "medium"}}
  ]
}}
If no new tasks are needed, return an empty array: {{"new_tasks": []}}
"""

    human_msg = f"""
Current Todo List:
{json.dumps(current_todos, indent=2)}

Design Documents:
{docs_content if docs_content.strip() else "No design documents found."}
"""

    try:
        llm = ChatOpenAI(model="gpt-5-mini", temperature=0.1, model_kwargs={"response_format": {"type": "json_object"}})
        
        _log.info(f"[{session_id}] Generating Todos from {len(docs_content)} chars of docs...")
        res = llm.invoke([SystemMessage(content=sys_prompt), HumanMessage(content=human_msg)])
        
        data = json.loads(str(res.content))
        new_tasks = data.get("new_tasks", [])
        
        if not new_tasks:
            return current_todos
            
        # Append new tasks with sequential IDs
        merged_todos = list(current_todos)
        next_id = highest_id + 1
        
        for task in new_tasks:
            # Simple deduplication check via exact/partial string match
            task_str = task.get("content", "").lower()
            if not task_str:
                continue
                
            is_dup = any(task_str in t.get("content", "").lower() or t.get("content", "").lower() in task_str for t in merged_todos)
            if not is_dup:
                merged_todos.append({
                    "id": str(next_id),
                    "content": task.get("content", f"Task {next_id}"),
                    "status": "pending",
                    "priority": task.get("priority", "medium")
                })
                next_id += 1
                
        # Save and return
        update_todos(session_id, merged_todos)
        return merged_todos
        
    except Exception as e:
        _log.error(f"Failed to generate todos: {e}")
        return current_todos
