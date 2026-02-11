#!/usr/bin/env python3
"""
Simple permission test - creates one permission request and approves it.
Watch the logs to see if the future resolves properly.
"""

import asyncio
import httpx
import json
import sys

SERVER_URL = "http://localhost:8000"

async def test_one_permission():
    """Test a single permission request and approval."""
    print("="*60)
    print("Simple Permission Test")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create session
        print("\n1. Creating session...")
        resp = await client.post(f"{SERVER_URL}/sessions", json={
            "directory": "/Users/alex/openscrum",
            "project_id": "test_simple"
        })
        if resp.status_code != 200:
            print(f"❌ Failed to create session: {resp.status_code}")
            return
        session = resp.json()
        session_id = session["id"]
        print(f"   ✅ Session: {session_id}")
        
        # Send message in edit mode (so tools are available)
        print("\n2. Sending message (edit mode)...")
        message = "Use webfetch to get https://httpbin.org/get"
        
        print("\n3. Streaming response...")
        permission_seen = False
        permission_id = None
        tool_started = False
        completed = False
        
        async with client.stream(
            "POST",
            f"{SERVER_URL}/sessions/{session_id}/message",
            json={"message": message, "mode": "edit"},
            timeout=30.0
        ) as stream:
            async for line in stream.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                    
                try:
                    data = json.loads(line[6:])
                    chunk_type = data.get("type")
                    
                    if chunk_type == "permission_request":
                        permission_seen = True
                        perm = data.get("permission_request", {})
                        permission_id = perm.get("id")
                        print(f"\n   📋 Permission Request:")
                        print(f"      ID: {permission_id}")
                        print(f"      Permission: {perm.get('permission')}")
                        print(f"      Patterns: {perm.get('patterns')}")
                        
                        # Check server state before replying
                        debug_resp = await client.get(f"{SERVER_URL}/permissions/debug")
                        debug = debug_resp.json()
                        print(f"      Server state: {debug}")
                        
                        # Approve immediately
                        print(f"\n   ✅ Approving permission {permission_id}...")
                        reply_resp = await client.post(
                            f"{SERVER_URL}/permissions/{permission_id}/reply",
                            json={"reply": "once"}
                        )
                        print(f"      Reply status: {reply_resp.status_code}")
                        print(f"      Reply body: {reply_resp.json()}")
                        
                        # Check server state after replying
                        await asyncio.sleep(0.05)  # Give server time to process
                        debug_resp = await client.get(f"{SERVER_URL}/permissions/debug")
                        debug = debug_resp.json()
                        print(f"      After reply: {debug}")
                        
                    elif chunk_type == "tool_call":
                        tool_started = True
                        tool_name = data.get("tool_name")
                        print(f"\n   🔧 Tool started: {tool_name}")
                        
                    elif chunk_type == "tool_result":
                        print(f"   ✅ Tool completed")
                        
                    elif chunk_type == "token":
                        content = data.get("content", "")
                        if content:
                            print(f"   💬 {content[:60]}")
                        
                    elif chunk_type == "done":
                        completed = True
                        print(f"\n   ✅ Stream DONE")
                        break
                        
                    elif chunk_type == "error":
                        print(f"\n   ❌ Error: {data.get('content')}")
                        break
                        
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    print(f"   ⚠️  Error: {e}")
        
        # Summary
        print(f"\n4. Test Summary:")
        print(f"   Permission seen: {permission_seen}")
        print(f"   Tool started: {tool_started}")
        print(f"   Completed: {completed}")
        
        if permission_seen and not tool_started:
            print(f"\n   ⚠️  STUCK: Permission approved but tool never started!")
            print(f"   This means the future didn't resolve properly.")
            return False
        elif permission_seen and tool_started:
            print(f"\n   ✅ SUCCESS: Permission approved and tool executed!")
            return True
        else:
            print(f"\n   ⚠️  No permission was requested (agent may not have used tools)")
            return None

if __name__ == "__main__":
    print("\n⚠️  Make sure server is running with:")
    print("   export OPENSCRUM_LOG_LEVEL=INFO")
    print("   python -m server.main\n")
    
    try:
        result = asyncio.run(test_one_permission())
        if result is True:
            print("\n✅ Test PASSED")
            sys.exit(0)
        elif result is False:
            print("\n❌ Test FAILED - Permission deadlock detected")
            sys.exit(1)
        else:
            print("\n⚠️  Test inconclusive")
            sys.exit(2)
    except KeyboardInterrupt:
        print("\n\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
