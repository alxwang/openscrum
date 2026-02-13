#!/usr/bin/env python3
"""
Test script for memsearch integration.

Usage:
    # Install memsearch first
    pip install memsearch

    # Enable memsearch backend
    export OPENSCRUM_STORAGE_BACKEND=memsearch

    # Run test
    python scripts/test_memsearch.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.storage import get_storage
from server.storage.memsearch_adapter import MemSearchAdapter


async def test_memsearch():
    """Test memsearch integration."""
    
    print("=" * 60)
    print("OpenScrum Memsearch Integration Test")
    print("=" * 60)
    print()
    
    # Check if memsearch backend is enabled
    backend = os.getenv("OPENSCRUM_STORAGE_BACKEND", "file")
    print(f"Storage backend: {backend}")
    print()
    
    # Get storage instance
    storage = get_storage()
    print(f"Storage type: {type(storage).__name__}")
    print()
    
    if not isinstance(storage, MemSearchAdapter):
        print("❌ Memsearch not enabled!")
        print()
        print("To enable memsearch:")
        print("1. Install: pip install memsearch")
        print("2. Set: export OPENSCRUM_STORAGE_BACKEND=memsearch")
        print("3. Restart server")
        return
    
    print("✅ Memsearch enabled!")
    print()
    
    # Get memory stats
    print("Memory Statistics:")
    print("-" * 60)
    stats = storage.get_memory_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print()
    
    # Create a test memory if memory directory is empty
    if stats["markdown_files"] == 0:
        print("Creating test memory...")
        memory_dir = Path(stats["memory_dir"])
        test_session_dir = memory_dir / "ses_test_001"
        test_session_dir.mkdir(parents=True, exist_ok=True)
        
        test_memory_file = test_session_dir / "2026-02-13.md"
        test_memory_file.write_text("""
# Test Memory

## User (msg_001)
*Time: 2026-02-13T10:00:00*

How do I configure Redis for production use?

---

## Assistant (msg_002)
*Time: 2026-02-13T10:00:15*

Here are the key Redis configuration settings for production:

1. **Memory Management**
   - Set maxmemory limit
   - Choose eviction policy (allkeys-lru recommended)

2. **Persistence**
   - Enable AOF for durability
   - Configure snapshot intervals

3. **Security**
   - Set requirepass for authentication
   - Bind to specific interfaces
   - Disable dangerous commands

### Tool Executions

**read_file** (completed)
```json
{
  "path": "redis.conf"
}
```

Output:
```
maxmemory 2gb
maxmemory-policy allkeys-lru
requirepass your_secure_password_here
```

---

## User (msg_003)
*Time: 2026-02-13T10:05:00*

What about database optimization?

---

## Assistant (msg_004)
*Time: 2026-02-13T10:05:10*

For PostgreSQL database optimization:

1. **Indexing**
   - Create indexes on frequently queried columns
   - Use partial indexes for filtered queries
   - Monitor index usage with pg_stat_user_indexes

2. **Connection Pooling**
   - Use pgBouncer or connection pooling in app
   - Set appropriate max_connections

3. **Query Optimization**
   - Use EXPLAIN ANALYZE to identify slow queries
   - Avoid SELECT * in production
   - Use prepared statements

---
""", encoding="utf-8")
        
        print("✅ Test memory created")
        print()
        
        # Index the test memory
        print("Indexing test memory...")
        await storage._index_memories()
        print("✅ Indexing complete")
        print()
    
    # Test semantic search
    print("Testing Semantic Search:")
    print("-" * 60)
    
    test_queries = [
        "redis configuration",
        "database optimization",
        "security settings",
        "how to improve performance",
    ]
    
    for query in test_queries:
        print(f"\nQuery: '{query}'")
        results = await storage.search(query, top_k=2)
        
        if results:
            for i, result in enumerate(results, 1):
                print(f"\n  Result {i}:")
                print(f"    Score: {result.get('score', 0):.3f}")
                print(f"    Source: {Path(result.get('source', '')).name}")
                content = result.get('content', '')
                preview = content[:150].replace('\n', ' ')
                print(f"    Content: {preview}...")
        else:
            print("  No results found")
    
    print()
    print("=" * 60)
    print("Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_memsearch())
