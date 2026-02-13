# Memsearch: Complete Example

This document shows a real conversation demonstrating automatic memory recall.

## Setup

```bash
# Install memsearch
pip install memsearch

# Enable in ~/.env
echo "OPENSCRUM_STORAGE_BACKEND=memsearch" >> ~/.env

# Start server
./server.sh
```

## Example Conversation Flow

### Day 1: Initial Configuration

**You:** "Set up Redis for session caching with a 2GB memory limit"

```
[Behind the scenes - RECALL phase]
- Searches past conversations: No relevant memories found (first discussion)

[THINK phase - LLM receives]
- User message: "Set up Redis for session caching with a 2GB memory limit"
- No memory context (first time)

[Agent response]
```

**Agent:** "I'll configure Redis for session caching. Let me:

1. Check if Redis is installed
2. Create/update redis.conf with your settings
3. Set the memory limit

[Agent runs tools: bash, write, etc.]

Done! Redis configured with:
- maxmemory 2gb
- maxmemory-policy allkeys-lru
- Save persistence enabled
"

```
[REMEMBER phase]
- Conversation exported to: ~/.openscrum/memory/ses_abc123/2026-02-13.md
- Markdown content:

  ## User (msg_001)
  *Time: 2026-02-13T10:00:00*
  
  Set up Redis for session caching with a 2GB memory limit
  
  ---
  
  ## Assistant (msg_002)
  *Time: 2026-02-13T10:00:15*
  
  I'll configure Redis for session caching...
  
  ### Tool Executions
  **bash** (completed)
  ...

- File indexed automatically
```

---

### Day 2: Related Question (New Session)

**You:** "Why is my application cache using so much memory?"

```
[RECALL phase - Automatic search]
Query: "Why is my application cache using so much memory?"

Memories found (top 3):
1. [Relevance: 0.87] Session ses_abc123
   "## User: Set up Redis for session caching with a 2GB memory limit
    ## Assistant: Done! Redis configured with maxmemory 2gb..."

2. [Relevance: 0.62] Session ses_def456  
   "## User: How do I monitor Redis memory usage?
    ## Assistant: Use redis-cli INFO memory..."

3. [Relevance: 0.54] Session ses_abc123
   "## User: Configure application session storage
    ## Assistant: I'll set up session middleware..."

[THINK phase - LLM receives]
- System message with memory context:
  ## Relevant memories from past conversations:
  
  1. [Relevance: 0.87]
  ## User: Set up Redis for session caching with a 2GB memory limit
  ## Assistant: Done! Redis configured with maxmemory 2gb, 
  maxmemory-policy allkeys-lru...
  
  2. [Relevance: 0.62]
  ## User: How do I monitor Redis memory usage?
  ...

- User message: "Why is my application cache using so much memory?"
```

**Agent:** "Based on our earlier configuration, your Redis cache is set to use up to 2GB 
(maxmemory 2gb). Let me check current usage...

[Agent runs: bash redis-cli INFO memory]

Your Redis is using 1.8GB out of the 2GB limit. This is expected behavior - Redis will 
use up to the limit and then apply the LRU eviction policy we configured. If you need 
more cache space, we can increase the maxmemory setting."

```
[REMEMBER phase]
- This new conversation appended to ~/.openscrum/memory/ses_xyz789/2026-02-14.md
- Indexed automatically
- Future queries about "cache", "memory", "redis" will now find this too
```

---

### Same Day: Follow-up Question

**You:** "Increase it to 4GB"

```
[RECALL phase]
Query: "Increase it to 4GB"

Memories found:
1. [Relevance: 0.91] Session ses_xyz789 (current session, earlier today)
   "## User: Why is my application cache using so much memory?
    ## Assistant: Your Redis is using 1.8GB out of the 2GB limit..."

2. [Relevance: 0.85] Session ses_abc123 (yesterday)
   "## User: Set up Redis for session caching with a 2GB memory limit
    ## Assistant: Done! Redis configured with maxmemory 2gb..."

[THINK phase - LLM receives BOTH memories]
- Memory from current session (context: asking about memory usage)
- Memory from yesterday (context: initial 2GB configuration)
- User message: "Increase it to 4GB"
```

**Agent:** "I'll update your Redis configuration from 2GB to 4GB. Let me modify redis.conf...

[Agent runs: edit redis.conf, bash systemctl restart redis]

Done! Redis memory limit increased from 2GB to 4GB. Your cache now has more space 
before LRU eviction kicks in."

```
[REMEMBER phase]
- Full conversation saved to today's markdown file
- Indexed automatically
- Now has complete history: initial 2GB → memory question → 4GB increase
```

---

## What You See in Memory Files

### `~/.openscrum/memory/ses_abc123/2026-02-13.md`
```markdown
## User (msg_001)
*Time: 2026-02-13T10:00:00*

Set up Redis for session caching with a 2GB memory limit

---

## Assistant (msg_002)
*Time: 2026-02-13T10:00:15*

I'll configure Redis for session caching. Let me:
1. Check if Redis is installed
2. Create/update redis.conf with your settings
...

### Tool Executions

**bash** (completed)
```json
{
  "command": "redis-cli INFO memory"
}
```

Output:
```
used_memory:52428800
used_memory_human:50.00M
maxmemory:2147483648
```

---
```

### `~/.openscrum/memory/ses_xyz789/2026-02-14.md`
```markdown
## User (msg_010)
*Time: 2026-02-14T09:30:00*

Why is my application cache using so much memory?

---

## Assistant (msg_011)
*Time: 2026-02-14T09:30:15*

Based on our earlier configuration, your Redis cache is set to use up to 2GB...

---

## User (msg_012)
*Time: 2026-02-14T09:35:00*

Increase it to 4GB

---

## Assistant (msg_013)
*Time: 2026-02-14T09:35:10*

I'll update your Redis configuration from 2GB to 4GB...

---
```

---

## Key Benefits Demonstrated

### 1. **Zero Manual Effort**
- No "search memory" commands
- No manual context injection
- Just natural conversation

### 2. **Cross-Session Recall**
- Day 2 question automatically found Day 1 configuration
- Agent knew about 2GB limit without you mentioning it

### 3. **Context-Aware Responses**
- "Based on our earlier configuration..." (automatically recalled)
- "from 2GB to 4GB" (remembered the current value)

### 4. **Human-Readable Archive**
- All memories in plain markdown
- Can grep, version control, backup
- No proprietary format

### 5. **Intelligent Ranking**
- Most relevant memories surface first
- Similarity scores guide context selection
- Prevents irrelevant context pollution

---

## How to Verify It's Working

### 1. Check Memory Files
```bash
ls ~/.openscrum/memory/
# Output: ses_abc123/  ses_xyz789/  ...

ls ~/.openscrum/memory/ses_abc123/
# Output: 2026-02-13.md  2026-02-14.md

cat ~/.openscrum/memory/ses_abc123/2026-02-13.md
# See full conversation in markdown
```

### 2. Check Server Logs
```bash
# Look for memory search logs
tail -f logs/server.log | grep -i memory

# Example output:
# [INFO] Found 3 relevant memories for current message
# [DEBUG] Indexing memories...
# [DEBUG] Memory indexing complete
```

### 3. Test Cross-Session Recall
```bash
# Day 1: Configure something specific
You: "Use PostgreSQL with connection pool size 20"

# Day 2: New session, related question
You: "Why are database connections being refused?"

Agent: "Based on your earlier configuration with pool size 20..." ✓
```

### 4. Query API Stats
```bash
curl http://localhost:8000/memory/stats

# Output:
{
  "enabled": true,
  "memory_dir": "/Users/you/.openscrum/memory",
  "markdown_files": 42,
  "total_size_mb": 3.5
}
```

---

## Troubleshooting

### Agent Not Recalling Past Conversations

**Check 1: Memsearch enabled?**
```bash
# Should see: OPENSCRUM_STORAGE_BACKEND=memsearch
cat ~/.env | grep STORAGE_BACKEND
```

**Check 2: Memory files exist?**
```bash
ls -la ~/.openscrum/memory/
```

**Check 3: Server logs**
```bash
# Look for "Found N relevant memories" in logs
tail -100 logs/server.log | grep "relevant memories"
```

### Indexing Errors

If you see indexing errors, manually trigger:
```bash
# In Python shell
from server.storage import get_storage
storage = get_storage()
await storage._index_memories()
```

---

## Advanced: Custom Memory Queries

While automatic recall is the main feature, you can also manually search:

```bash
# Find all Docker-related conversations
curl "http://localhost:8000/memory/search?query=docker+configuration&top_k=10"

# Search only current session
curl "http://localhost:8000/memory/search?query=database&session_id=ses_abc123"
```

This is useful for:
- Reviewing what you've discussed
- Finding specific implementation details
- Auditing agent actions
- Building custom tooling

---

## Conclusion

Memsearch provides **transparent, intelligent memory** for your agent:
- ✅ Automatic recall
- ✅ Cross-session context
- ✅ Human-readable storage
- ✅ Zero configuration after setup
- ✅ Privacy-preserving (local storage)

Just enable it and talk naturally - the agent remembers everything!
