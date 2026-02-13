# Memsearch Integration

## Overview

OpenScrum integrates **semantic memory search** using [memsearch](https://github.com/zilliztech/memsearch) with the **Recall-Think-Remember** pattern inspired by OpenClaw.

This integration provides:
- 📝 **Automatic memory** - All conversations exported to markdown (.md files)
- 🧠 **Recall** - Before each LLM call, relevant memories are automatically retrieved
- 💭 **Think** - LLM receives memory context in system prompt
- ✍️ **Remember** - New conversations auto-saved and indexed
- 🔄 **Live sync** - File watcher auto-indexes changes

## How It Works

### Recall-Think-Remember Pattern

```
User Message → RECALL (search memories) → THINK (LLM with context) → REMEMBER (save & index)
```

**1. Recall** - When you send a message:
- Searches past conversations for relevant context
- Retrieves top 3 most relevant memories
- Uses semantic similarity (not keyword matching)

**2. Think** - LLM receives:
- Your current message
- Relevant memories as system context
- Full conversation history

**3. Remember** - After response:
- Conversation exported to markdown
- Automatically indexed for future recall
- Organized by session and date

## Installation

### 1. Install memsearch

```bash
pip install memsearch
```

**Optional embedding providers:**

```bash
pip install "memsearch[google]"      # Google Gemini
pip install "memsearch[voyage]"      # Voyage AI
pip install "memsearch[ollama]"      # Ollama (local)
pip install "memsearch[local]"       # sentence-transformers (local, no API key)
pip install "memsearch[all]"         # Everything
```

### 2. Enable memsearch backend

Set the environment variable:

```bash
export OPENSCRUM_STORAGE_BACKEND=memsearch
```

Or add to your `~/.env` file:

```bash
OPENSCRUM_STORAGE_BACKEND=memsearch
```

### 3. Restart the server

```bash
cd openscrum
./server.sh
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENSCRUM_STORAGE_BACKEND` | `file` | Set to `memsearch` to enable semantic memory |
| `OPENSCRUM_MEMSEARCH_MEMORY_DIR` | `~/.openscrum/memory` | Directory for markdown memory files |
| `OPENSCRUM_MEMSEARCH_EMBEDDING_MODEL` | `text-embedding-ada-002` | OpenAI embedding model (ada-002 has widest availability) |
| `OPENSCRUM_DATA_DIR` | `~/.openscrum` | Base directory for all storage |

**Note on embedding models:**
- `text-embedding-ada-002` - Default, available to all OpenAI projects (older, widely compatible)
- `text-embedding-3-small` - Newer, better quality, requires API access
- `text-embedding-3-large` - Best quality, requires API access

If you see "model_not_found" errors, your OpenAI project may not have access to newer models. Stick with the default `ada-002`.

## Usage

### Automatic Memory Recall

**Memsearch is completely transparent** - no special commands or API calls needed!

When enabled, every message you send:
1. **Automatically searches** past conversations for relevant context
2. **Agent receives** those memories in its prompt
3. **Your response** is saved and indexed for future recall

```bash
# Example conversation
You: "How did we configure Redis earlier?"

# Behind the scenes:
# 1. RECALL: Searches for Redis-related memories
# 2. THINK: LLM sees: "Relevant memories: Redis config from session_abc..."
# 3. REMEMBER: This exchange saved to markdown and indexed

Agent: "Based on our earlier discussion, we configured Redis with..."
```

### Manual API Access (Optional)

While memory recall is automatic, you can also query memories directly:

#### Semantic Search API

```bash
GET /memory/search?query=redis%20configuration&top_k=5&session_id=ses_123
```

**Parameters:**
- `query` (required): Search query in natural language
- `top_k` (optional): Number of results to return (default: 5)
- `session_id` (optional): Limit search to specific session

**Response:**
```json
{
  "query": "redis configuration",
  "results": [
    {
      "content": "## User\nHow do I configure Redis for caching?",
      "score": 0.89,
      "source": "/Users/user/.openscrum/memory/ses_123/2026-02-13.md"
    }
  ],
  "count": 1
}
```

#### Memory Statistics

```bash
GET /memory/stats
```

**Response:**
```json
{
  "enabled": true,
  "available": true,
  "memory_dir": "/Users/user/.openscrum/memory",
  "markdown_files": 15,
  "total_size_bytes": 102400,
  "total_size_mb": 0.10
}
```

## Memory File Structure

Conversations are automatically exported to markdown files organized by session and date:

```
~/.openscrum/memory/
├── ses_abc123/
│   ├── 2026-02-13.md
│   ├── 2026-02-14.md
│   └── ...
├── ses_def456/
│   ├── 2026-02-13.md
│   └── ...
└── ...
```

### Memory File Format

Each message is formatted as a markdown section:

```markdown
## User (msg_123)
*Time: 2026-02-13T10:30:00*

How do I configure Redis for production?

---

## Assistant (msg_124)
*Time: 2026-02-13T10:30:15*

Here's how to configure Redis for production...

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
...
```

---
```

## Storage Modes

### File-only mode (default)

```bash
# Do not set OPENSCRUM_STORAGE_BACKEND, or set it to "file"
unset OPENSCRUM_STORAGE_BACKEND
```

- JSON storage only
- No semantic search
- Faster writes
- Lower memory usage

### Memsearch mode

```bash
export OPENSCRUM_STORAGE_BACKEND=memsearch
```

- JSON storage + markdown export
- Semantic search enabled
- Slightly slower writes (markdown export)
- Additional memory for vector embeddings
- Enables `/memory/search` API

## Benefits

### 1. Automatic Semantic Recall
The agent automatically remembers relevant past discussions:

```
You: "Update the database connection to use the new credentials"

Agent thinks: 
  [Recalls: Earlier discussion about PostgreSQL connection in session_abc]
  [Recalls: Database credentials stored in .env file]
  [Thinks with context: User wants to update existing DB connection...]

Agent: "I'll update the PostgreSQL connection in database.py to use the new 
credentials from your .env file, like we configured earlier..."
```

### 2. Cross-Session Memory
Memories persist across all sessions:

```bash
# Session 1 (yesterday): Configure Redis
You: "Set up Redis with 2GB memory limit"
Agent: "Configured redis.conf with maxmemory 2gb"

# Session 2 (today): New question
You: "Why is my cache using so much memory?"
Agent: [Recalls Redis config from yesterday]
       "Your Redis is configured with a 2GB limit as we set yesterday..."
```

### 3. Human-Readable Memory
All memories stored as markdown files:
- Read with any text editor
- Version control with git
- Search with grep/ripgrep
- Process with custom scripts
- **Zero vendor lock-in**

### 4. Transparent Operation
No special commands needed:
- ✅ No "search memory" tool calls
- ✅ No manual API requests  
- ✅ No configuration per session
- ✅ Just talk naturally

### 5. Intelligent Context
Only relevant memories included:
- Top 3 most relevant (by semantic similarity)
- Prevents context overflow
- Maintains conversation focus

## Troubleshooting

### Memsearch not enabled

**Error:** `Memsearch not enabled. Set OPENSCRUM_STORAGE_BACKEND=memsearch`

**Solution:** Set the environment variable and restart the server.

### Import error

**Error:** `memsearch not installed`

**Solution:** Install memsearch:
```bash
pip install memsearch
```

### Slow indexing

If you have many memory files, initial indexing may take time. The server will continue to work while indexing happens in the background.

Monitor indexing in server logs:
```bash
tail -f logs/server.log | grep memsearch
```

### Memory files not created

Check that:
1. `OPENSCRUM_STORAGE_BACKEND=memsearch` is set
2. Server has write permissions to `~/.openscrum/memory`
3. Sessions are active and messages are being created

## Performance Considerations

- **Initial indexing**: First startup may be slow if you have many sessions
- **Write overhead**: Each message write also exports to markdown (~1-2ms additional latency)
- **Memory usage**: Vector embeddings require additional RAM (depends on embedding model)
- **Storage**: Markdown files add ~2x storage compared to JSON-only mode

## Future Enhancements

- [ ] Periodic memory consolidation/summarization
- [ ] Session-specific memory scoping in search
- [ ] Memory export/import tools
- [ ] Integration with external knowledge bases
- [ ] Custom embedding model selection
