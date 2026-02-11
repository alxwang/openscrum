#!/usr/bin/env python3
"""
Test script to debug permission flow.
Run server in one terminal, then run this script in another to see detailed flow.
"""

import asyncio
import httpx
import json
import sys

SERVER_URL = "http://localhost:8000"

async def test_permission_flow():
    """Test that permissions work correctly with detailed logging."""
    print("="*60)
    print("Testing Permission Flow")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Create session
        print("\n1. Creating session...")
        resp = await client.post(f"{SERVER_URL}/sessions", json={
            "directory": "/Users/alex/openscrum",
            "project_id": "test_permission_flow"
        })
        if resp.status_code != 200:
            print(f"Failed to create session: {resp.status_code} {resp.text}")
            return
        session_info = resp.json()
        session_id = session_info["id"]
        print(f"   Created session: {session_id}")
        
        # 2. Send message that will trigger permissions
        print("\n2. Sending message to trigger tool permissions...")
        message = "List files in the current directory"
        
        # Use EDIT mode so tools are available (plan mode is read-only)
        print(f"   Using mode: edit (to enable tool execution)")
        
        # 3. Stream response and handle permissions
        print("\n3. Streaming response...")
        permission_count = 0
        token_count = 0
        
        async with client.stream(
            "POST",
            f"{SERVER_URL}/sessions/{session_id}/message",
            json={"message": message, "mode": "edit"},  # EDIT mode for tools
            timeout=60.0
        ) as stream:
            async for line in stream.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                    
                try:
                    data = json.loads(line[6:])  # Remove "data: " prefix
                    chunk_type = data.get("type")
                    
                    if chunk_type == "permission_request":
                        permission_count += 1
                        perm = data.get("permission_request", {})
                        req_id = perm.get("id")
                        perm_name = perm.get("permission")
                        patterns = perm.get("patterns", [])
                        
                        print(f"\n   📋 Permission Request #{permission_count}")
                        print(f"      ID: {req_id}")
                        print(f"      Permission: {perm_name}")
                        print(f"      Patterns: {patterns}")
                        print(f"      Metadata: {perm.get('metadata', {})}")
                        
                        # Check server state
                        pending_resp = await client.get(f"{SERVER_URL}/permissions")
                        pending = pending_resp.json()
                        print(f"      Server has {len(pending)} pending permissions")
                        
                        # Auto-approve
                        print(f"      ✅ Auto-approving (once)...")
                        reply_resp = await client.post(
                            f"{SERVER_URL}/permissions/{req_id}/reply",
                            json={"reply": "once"}
                        )
                        print(f"      Reply response: {reply_resp.status_code} {reply_resp.json()}")
                        
                        # Wait a bit to see if agent continues
                        await asyncio.sleep(0.1)
                        
                    elif chunk_type == "token":
                        token_count += 1
                        content = data.get("content", "")
                        if token_count <= 3:
                            print(f"   💬 Token: {content[:50]}")
                            
                    elif chunk_type == "tool_call":
                        tool_name = data.get("tool_name")
                        print(f"   🔧 Tool Call: {tool_name}")
                        
                    elif chunk_type == "tool_result":
                        tool_name = data.get("tool_name")
                        output = data.get("tool_output", "")
                        print(f"   ✅ Tool Result: {tool_name} ({len(output)} chars)")
                        
                    elif chunk_type == "done":
                        print("\n   ✅ Stream DONE")
                        break
                        
                    elif chunk_type == "error":
                        print(f"\n   ❌ Error: {data.get('content')}")
                        break
                        
                except json.JSONDecodeError as e:
                    print(f"   ⚠️  JSON decode error: {e}")
                except Exception as e:
                    print(f"   ⚠️  Error processing chunk: {e}")
        
        print(f"\n4. Summary:")
        print(f"   Permissions requested: {permission_count}")
        print(f"   Tokens received: {token_count}")
        
        # Check if there are any pending permissions left
        pending_resp = await client.get(f"{SERVER_URL}/permissions")
        pending = pending_resp.json()
        if pending:
            print(f"\n   ⚠️  WARNING: {len(pending)} permissions still pending!")
            for p in pending:
                print(f"      - {p.get('id')}: {p.get('permission')} {p.get('patterns')}")
        else:
            print(f"   ✅ No pending permissions")

if __name__ == "__main__":
    print("\nMake sure the server is running: python -m server.main\n")
    try:
        asyncio.run(test_permission_flow())
    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"\n\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
