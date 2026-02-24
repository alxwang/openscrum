import sys
import logging
from pprint import pprint

# Set up logging to stdout to see what LLM is doing
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

from server.agent.todo_generator import generate_todos_for_session

session_id = "ses_0000009c231e890b8Aniw2bOnR"
try:
    with open(".openscrum/session.json") as f:
        pass
except:
    pass # Assume we are in root

workspace_root = "/Users/alex/openscrum/workspaces/session_ses_0000009c231e890b8Aniw2bOnR"

try:
    todos = generate_todos_for_session(session_id, workspace_root)
    print("OUTPUT:")
    pprint(todos)
except Exception as e:
    print(f"Error: {e}")
