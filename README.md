# openscrum

AI agent server with LangGraph for collaborative development.

## Features

- 🤖 **LangGraph Agent** - Multi-mode agent (plan/edit) with tool execution
- 💬 **Session Management** - Persistent conversation history across sessions
- 🔐 **Permission System** - User-approved tool execution for safety
- 🌐 **Web Interface** - Vue.js web client with real-time streaming
- 📝 **Semantic Memory** - Optional memsearch integration for semantic search across conversations
- 🎨 **TUI Client** - Terminal UI client built with Textual

## Quick Start

### Installation

```bash
# Create conda environment
conda env create -f environment.yml
conda activate openscrum

# Install dependencies
pip install -r requirements.txt
```

### Run Server

```bash
./server.sh
# Or: uvicorn server.main:app --reload --port 8000
```

### Run Web Client

```bash
cd webclient
npm install
npm run dev
```

## Configuration

Create `~/.env` file with your API keys:

```bash
# Required: Choose one provider
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...

# Optional: LangSmith tracing
LANGSMITH_KEY=lsv2_...

# Optional: Semantic memory search (see MEMSEARCH.md)
OPENSCRUM_STORAGE_BACKEND=memsearch  # Options: file (default), memsearch
```

## Semantic Memory Search

OpenScrum supports semantic search across conversation history using [memsearch](https://github.com/zilliztech/memsearch).

**Quick setup:**

```bash
# Install memsearch
pip install memsearch

# Enable in ~/.env
echo "OPENSCRUM_STORAGE_BACKEND=memsearch" >> ~/.env

# Restart server
./server.sh
```

See [MEMSEARCH.md](MEMSEARCH.md) for full documentation.

## Architecture

- **FastAPI Server** - REST API with SSE streaming
- **LangGraph Agent** - Stateful agent with tool execution
- **Storage Layer** - File-based JSON storage with optional memsearch integration
- **Permission System** - User approval workflow for sensitive operations
- **Session Management** - Persistent conversations with message history

## API Endpoints

### Sessions

- `GET /sessions` - List sessions
- `POST /sessions` - Create session
- `GET /sessions/{id}` - Get session details
- `POST /sessions/{id}/message` - Send message (streaming response)
- `POST /sessions/{id}/reset` - Clear conversation history
- `POST /sessions/{id}/compress` - Compress older messages

### Memory (when memsearch enabled)

- `GET /memory/search?query=...&top_k=5` - Semantic search
- `GET /memory/stats` - Memory storage statistics

### Permissions

- `GET /permissions` - List pending permissions
- `POST /permissions/{id}/reply` - Respond to permission request

## Project Structure

```
openscrum/
├── server/
│   ├── agent/           # LangGraph agent implementation
│   ├── command/         # Command handlers (init, etc.)
│   ├── instruction/     # Agent prompts and instructions
│   ├── permission/      # Permission system
│   ├── session/         # Session management
│   ├── storage/         # Storage layer (JSON + memsearch)
│   ├── tools/           # Agent tools
│   └── main.py          # FastAPI server
├── client/              # TUI client
├── webclient/           # Vue.js web client
├── scripts/             # Utility scripts
└── prompts/             # Prompt templates
```

## Development

### Run Tests

```bash
# Test session management
python scripts/test_agent_session.py

# Test memsearch integration
export OPENSCRUM_STORAGE_BACKEND=memsearch
python scripts/test_memsearch.py
```

### Storage Backends

**File storage (default):**
- Simple JSON file storage
- Fast writes
- No dependencies

**Memsearch storage:**
- JSON + markdown export
- Semantic search enabled
- Requires: `pip install memsearch`
- See [MEMSEARCH.md](MEMSEARCH.md)

## License

See [LICENSE](LICENSE)
