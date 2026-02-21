import asyncio
from pathlib import Path
import json

from server.session.service import SessionService
from server.tools.system_tools import analyze_workspace, check_sync_status, generate_design_from_code
from server.tools.context import set_tool_context, clear_tool_context

async def test_sync_logic():
    print("Testing Sync Logic...")
    
    # 1. Setup a dummy session
    svc = SessionService()
    session = svc.create({"workspace_name": "test_sync_sync"})
    session_id = session.id
    
    workspace_root = Path(f"/Users/alex/openscrum/openscrum/@workspaces/test_sync_sync")
    workspace_root.mkdir(parents=True, exist_ok=True)
    
    # Write a dummy code file
    (workspace_root / "main.py").write_text("print('hello world')")
    
    set_tool_context(session_id, str(workspace_root), [])
    try:
        # 2. Check initial status (should warn about missing design docs)
        status_raw = check_sync_status.invoke({})
        status = json.loads(status_raw)
        print(f"Initial Status (Code only): {json.dumps(status, indent=2)}")
        
        # 3. Generate design docs (simulate sync)
        print("\nGenerating fake design docs...")
        design_dir = workspace_root / ".openscrum" / "design"
        design_dir.mkdir(parents=True, exist_ok=True)
        (design_dir / "architecture.md").write_text("# Fake Architecture")
        
        # Manually update metadata directly referencing tool logic (bypassing fastapi)
        from server.tools.system_tools import load_sync_metadata, save_sync_metadata
        from datetime import datetime
        metadata = load_sync_metadata()
        metadata["design_docs_last_synced"] = datetime.utcnow().timestamp()
        save_sync_metadata(metadata)
        
        # 4. Check status again (should be synced)
        status_raw = check_sync_status.invoke({})
        status = json.loads(status_raw)
        print(f"\nStatus After Fake Sync: {json.dumps(status, indent=2)}")
        
        # 5. Modify code (simulate drift)
        print("\nModifying code to trigger drift...")
        import time
        time.sleep(1) # Ensure timestamp changes
        (workspace_root / "main.py").write_text("print('hello world modified')")
        
        # 6. Check status again (should be unsynced)
        status_raw = check_sync_status.invoke({})
        status = json.loads(status_raw)
        print(f"\nStatus After Code Mod: {json.dumps(status['warnings'], indent=2)}")
        
    finally:
        clear_tool_context()

if __name__ == "__main__":
    asyncio.run(test_sync_logic())
