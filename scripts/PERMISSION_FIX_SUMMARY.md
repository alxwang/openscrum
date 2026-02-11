# Permission Flow Fix Summary

## Problem Description
After approving the first permission request, the application gets stuck and doesn't continue processing. The agent appears frozen.

## Root Causes Identified

### 1. **Queue Task Race Condition** ([main.py](../server/main.py#L297-L350))
**Problem**: After emitting a permission_request chunk to the client, the stream loop immediately created a new `queue_task` to wait for the next permission. This caused:
- Multiple queue_tasks being created unnecessarily
- Confusion about which task to wait on
- Potential race between agent completing and new queue items

**Fix**: 
- First drain ALL queued permission requests with non-blocking `get_nowait()` loop
- Only create ONE new `queue_task` after draining
- This ensures all pending permissions are emitted before waiting for more

### 2. **Future Resolution Thread Safety** ([permission.py](../server/permission/permission.py#L258-L310))
**Problem**: The permission reply endpoint runs in FastAPI's event loop, but might be in a different context than where the future was created. Calling `future.set_result()` directly could fail silently.

**Fix**:
- Check if we're in the same event loop before calling `future.set_result()`
- If in different loop/context, use `call_soon_threadsafe()`
- Added extensive logging at each step to track future lifecycle

### 3. **Missing Visibility** (Throughout)
**Problem**: No logging made it impossible to diagnose where the hang occurred.

**Fix**: Added INFO-level logging for:
- Permission request creation (with ID, session, permission, patterns)
- Permission future creation (with future ID and event loop ID)
- Permission reply received (with full details)
- Future resolve/reject calls (with success/failure status)
- Agent task completion
- Stream loop events

## Key Code Changes

### Stream Loop (main.py:297-350)
```python
while True:
    agent_task = asyncio.create_task(agent_iter.__anext__())
    
    while True:
        # DRAIN all queued permissions first (non-blocking)
        while True:
            try:
                perm_info = permission_queue.get_nowait()
                yield permission_request_chunk
            except asyncio.QueueEmpty:
                break
        
        # NOW wait for agent OR new permission
        queue_task = asyncio.create_task(permission_queue.get())
        done, pending = await asyncio.wait([agent_task, queue_task], ...)
        
        if agent_task in done:
            # Agent completed - cancel queue_task and process
            queue_task.cancel()
            break
        
        if queue_task in done:
            # New permission - emit and LOOP BACK to drain more
            yield permission_request_chunk
            continue
```

### Future Resolution (permission.py:258-310)
```python
loop = asyncio.get_running_loop()
future = loop.create_future()

def resolve():
    if not future.done():
        try:
            running_loop = asyncio.get_running_loop()
            if running_loop is loop:
                future.set_result(None)  # Same loop - direct call
            else:
                loop.call_soon_threadsafe(future.set_result, None)  # Cross-loop
        except RuntimeError:
            loop.call_soon_threadsafe(future.set_result, None)  # No running loop
```

## Testing Instructions

### 1. Start Server with Logging
```bash
cd /Users/alex/openscrum/openscrum
export OPENSCRUM_LOG_LEVEL=INFO
python -m server.main
```

### 2. Run Automated Test
```bash
python scripts/test_permission_flow.py
```

The test will:
- Create a session
- Send a message requiring permissions
- Auto-approve each permission
- Report if agent continues or hangs

### 3. Manual Test with TUI
```bash
python -m client.tui
```

Try: `list files in this directory`

### Expected Log Output (Success)
```
INFO server.permission.permission: permission request created: request_id=perm_xxx
INFO server.main: permission_request emitted (drained): id=perm_xxx
INFO server.main: POST /permissions/perm_xxx/reply body={'reply': 'once'}
INFO server.permission.permission: permission resolve() called: request_id=perm_xxx future_done=False
INFO server.permission.permission: permission future.set_result(None) called: request_id=perm_xxx
INFO server.permission.permission: permission approved: request_id=perm_xxx
INFO server.main: agent step completed
```

### If Still Stuck, Look For:
1. **"permission resolve() called"** but no **"permission approved"**
   - Future not resolving properly, check event loop mismatch
   
2. **"permission approved"** but no **"agent step completed"**
   - Agent hung after permission, check tool execution
   
3. **"permission reply for unknown request_id"**
   - Reply arriving after request already cleaned up, timing issue

4. **Multiple "permission_request emitted"** but only one reply
   - Multiple tools needing permission, need to approve all

## Files Modified

1. **[server/main.py](../server/main.py)**
   - Lines 297-350: Fixed stream loop to drain permissions properly
   - Lines 899-920: Enhanced permission reply endpoint with logging
   - Lines 928-951: Added startup logging configuration

2. **[server/permission/permission.py](../server/permission/permission.py)**
   - Lines 238-310: Added logging and thread-safe future resolution
   - Lines 320-345: Enhanced reply() with detailed logging

3. **[scripts/test_permission_flow.py](./test_permission_flow.py)** (NEW)
   - Automated test script for permission flow

4. **[scripts/PERMISSION_DEBUG.md](./PERMISSION_DEBUG.md)** (NEW)
   - Debugging guide for permission issues

## Technical Details

### Why Drain First?
When a tool needs permission, `check_tool_permission()` calls `permission.ask()` which:
1. Calls `on_pending(request)` → puts request in queue
2. Awaits future (blocks tool execution)

The stream loop must:
1. Detect permission in queue → emit it to client
2. Wait for client to reply
3. Reply calls `resolve()` → unblocks tool
4. Tool continues, agent continues

By draining first, we ensure if multiple permissions arrive at once, we emit them all before waiting for the agent to proceed.

### Why Thread-Safe?
FastAPI endpoints run in uvicorn's event loop. The permission future is created in the agent's event loop (which is the same loop for workers=1, but we handle it defensively). Using `call_soon_threadsafe()` ensures the future is set from the correct loop context.

### Why Workers=1?
With multiple workers, the stream (creating permissions) runs in one worker process, and the reply endpoint might hit a different worker. The in-memory `_pending` dict wouldn't be shared. Workers=1 ensures everything shares the same process and memory.

## Next Steps if Issue Persists

1. **Capture full logs**: Run with `OPENSCRUM_LOG_LEVEL=DEBUG`
2. **Check which log line is last**: Pinpoints exactly where it hangs
3. **Use curl to manually send reply**: 
   ```bash
   curl -X POST http://localhost:8000/permissions/<ID>/reply \
     -H "Content-Type: application/json" \
     -d '{"reply": "once"}'
   ```
4. **Check event loop state**: May need to add asyncio debug mode
