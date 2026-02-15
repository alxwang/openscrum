import time
import os
import shutil
import asyncio
from pathlib import Path
from server.storage.memsearch_adapter import MemSearchAdapter

# Setup
TEST_DIR = Path("./test_storage_perf")
if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR)
TEST_DIR.mkdir()

# Initialize adapter (disable actual memsearch to isolate storage logic)
# We mock the _memsearch object to avoid needing an API key, but keep the _memsearch_enabled flag True
# so that it attempts the export logic.
adapter = MemSearchAdapter(base_dir=str(TEST_DIR / "storage"), memory_dir=str(TEST_DIR / "memory"))
adapter._memsearch_enabled = True # Force enable logic
adapter._memsearch = True # Mock object (truthy)

# 1. Seed with many sessions and messages
print("Seeding storage...")
SESSION_COUNT = 50
MESSAGES_PER_SESSION = 5

start_seed = time.time()
for s in range(SESSION_COUNT):
    session_id = f"ses_{s}"
    adapter.write(["session", session_id], {"id": session_id})
    for m in range(MESSAGES_PER_SESSION):
        msg_id = f"msg_{s}_{m}"
        # Write message
        adapter.write(["message", session_id, msg_id], {
            "id": msg_id,
            "role": "user",
            "content": "hello",
            "time": {"created": time.time() * 1000}
        })
print(f"Seeding complete in {time.time() - start_seed:.2f}s")

# 2. Measure performance of adding a NEW message part (which triggers export)
print("Measuring export performance...")
measurements = []

for i in range(10):
    # Create a new message in a new session (worst case for scan if it scans sequentially?)
    # or just any message.
    session_id = "ses_perf_test"
    msg_id = f"msg_perf_{i}"
    
    # Must write session and message first so they exist for the lookup
    adapter.write(["session", session_id], {"id": session_id})
    adapter.write(["message", session_id, msg_id], {
        "id": msg_id,
        "role": "user",
        "time": {"created": time.time() * 1000}
    })
    
    # Now write a PART, which triggers _export_message_to_markdown_by_id
    # We want to measure THIS specific call.
    start = time.time()
    adapter.write(["part", msg_id, "prt_1"], {"type": "text", "text": "test content"})
    duration = time.time() - start
    measurements.append(duration)
    print(f"Export {i}: {duration:.4f}s")

avg = sum(measurements) / len(measurements)
print(f"Average export time: {avg:.4f}s")

# Cleanup
if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR)
