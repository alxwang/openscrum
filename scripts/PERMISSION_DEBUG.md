# Permission Flow Debugging Guide

## The Issue
After approving the first permission, the app gets stuck. The agent doesn't continue processing.

## Changes Made

### 1. Fixed Stream Loop Logic ([main.py](../server/main.py#L297-L350))
- **Problem**: After emitting a permission_request, the code created a new queue_task immediately, causing potential race conditions
- **Fix**: Properly drain all queued permissions first with `get_nowait()` loop, then create ONE queue_task to wait for new requests

### 2. Thread-Safe Future Resolution ([permission.py](../server/permission/permission.py#L258-L280))
- **Problem**: Future resolution might fail if called from different event loop context  
- **Fix**: Use `call_soon_threadsafe()` to safely resolve futures across contexts

### 3. Comprehensive Logging
- Added INFO-level logs for entire permission lifecycle:
  - Permission request created with ID
  - Permission reply received with details
  - Future resolution status
  - Agent task completion

## Testing

### Terminal 1: Start Server with Logging
```bash
cd /Users/alex/openscrum/openscrum
export OPENSCRUM_LOG_LEVEL=INFO
python -m server.main
```

You should see:
```
============================================================
Starting OpenScrum Server
Workspace: /Users/alex/openscrum
Provider: openai, Model: gpt-4
Session support: True, Permission support: True
============================================================
```

### Terminal 2: Run Test Script
```bash
cd /Users/alex/openscrum/openscrum
python scripts/test_permission_flow.py
```

This will:
1. Create a session
2. Send a message that triggers tool permissions
3. Auto-approve each permission
4. Show if the agent continues or gets stuck

### Terminal 3: Run TUI Client
```bash
cd /Users/alex/openscrum/openscrum
python -m client.tui
```

Try commands that need permissions:
- `list files in this directory` (needs `list` permission)
- `read the README.md file` (needs `read` permission)  
- `create a test.txt file with hello world` (needs `edit` permission)

## What to Look For

### In Server Logs (Terminal 1):
```
INFO server.permission.permission: permission request created: request_id=perm_xxx session_id=sess_xxx permission=list patterns=['.']
INFO server.permission.permission: permission future created: request_id=perm_xxx future=123456
INFO server.main: permission_request emitted (drained): id=perm_xxx
INFO server.main: POST /permissions/perm_xxx/reply body={'reply': 'once', 'message': None}
INFO server.permission.permission: permission reply received: request_id='perm_xxx' reply=once permission=list patterns=['.'] session=sess_xxx
INFO server.permission.permission: permission resolve called: request_id=perm_xxx future_done=False
INFO server.permission.permission: permission future resolved: request_id=perm_xxx
INFO server.main: POST /permissions/perm_xxx/reply completed successfully
INFO server.permission.permission: permission approved: request_id=perm_xxx
INFO server.main: agent step completed
```

### If It's Still Stuck:

Look for:
1. **Missing "permission future resolved"** → Future not being set properly
2. **Missing "permission approved"** → await not returning from permission.ask()
3. **Missing "agent step completed"** → Agent task not finishing
4. **"permission reply for unknown request_id"** → Permission request cleaned up before reply arrives

### Debug Commands
While stuck, in another terminal:
```bash
# Check pending permissions
curl http://localhost:8000/permissions

# Manually approve a stuck permission (use ID from above)
curl -X POST http://localhost:8000/permissions/perm_xxx/reply \
  -H "Content-Type: application/json" \
  -d '{"reply": "once"}'
```

## Common Issues

1. **Multiple server workers**: Make sure uvicorn runs with `workers=1` (already set)
2. **Different event loops**: Fixed with `call_soon_threadsafe()`
3. **Queue task accumulation**: Fixed with proper drain loop
4. **Missing reply**: Check network/client logs

## Next Steps

If still stuck after testing:
1. Check the server logs for WHERE it stops
2. Note which log message is the LAST one you see
3. Share the full log output from both server and test script
