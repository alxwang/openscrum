# OpenScrum Project Review

**Goal:** Python replica of OpenCode  
**Date:** February 9, 2026  
**Status:** Foundation Complete, Missing Key Components

## 🎯 **Executive Summary**

OpenScrum is a Python replica of OpenCode, implementing a client-server architecture with LangGraph orchestration. The project has a **solid foundation (~40% complete)** with core agent workflow, prompt system, and basic tools implemented. However, **critical infrastructure is missing** for production use:

- ❌ **Session Management** - No conversation persistence
- ❌ **Permission System** - No security/approval workflow  
- ❌ **Storage Layer** - No data persistence
- ⚠️ **6 Missing Tools** - task, websearch, codesearch, batch, lsp, plan tools

**Recommendation:** Implement Phase 1 (Session, Permission, Storage) before production deployment.

---

## ✅ **What's Implemented**

### 1. **Core Architecture** ✓
- **LangGraph State Machine** (`server/agent/graph.py`)
  - Plan → Edit workflow
  - Tool execution routing
  - State management (messages, mode, scratchpad)

- **FastAPI Server** (`server/main.py`)
  - `/chat` endpoint with streaming
  - Server-Sent Events (SSE) support
  - Health check endpoints

- **Textual TUI Client** (`client/tui.py`)
  - Chat interface
  - Mode switching (Plan/Edit)
  - Real-time streaming display
  - Tool call visualization

### 2. **Prompt Registry** ✓
- **Manifest System** (`prompts/manifest.json`)
  - 38 prompts indexed with intent-based keys
  - All prompts copied from reference project

- **Template Rendering** (`server/agent/prompt_registry.py`)
  - Jinja2 integration
  - Context injection (cwd, os_name, project_structure)
  - Dynamic prompt loading

### 3. **System Tools** ✓ (13/19 tools)
**Implemented:**
- ✅ `read` - File reading with line numbers
- ✅ `write` - File writing
- ✅ `edit` - String replacement
- ✅ `multiedit` - Multiple sequential edits
- ✅ `apply_patch` - Patch format application
- ✅ `grep` - Regex content search
- ✅ `glob` - File pattern matching
- ✅ `list_files` - Directory listing
- ✅ `bash` - Command execution
- ✅ `webfetch` - URL fetching
- ✅ `todowrite` - Todo list management (placeholder)
- ✅ `todoread` - Todo list reading (placeholder)
- ✅ `question` - User questions (placeholder)

**Missing from Reference:**
- ❌ `task` - Subagent launching
- ❌ `websearch` - Exa AI web search
- ❌ `codesearch` - Exa Code API search
- ❌ `batch` - Parallel tool execution
- ❌ `lsp` - Language Server Protocol integration

### 4. **Project Structure** ✓
```
openscrum/
├── server/
│   ├── main.py              # FastAPI server
│   ├── agent/
│   │   ├── graph.py         # LangGraph state machine
│   │   └── prompt_registry.py
│   └── tools/
│       └── system_tools.py  # 13 tools implemented
├── client/
│   └── tui.py               # Textual TUI
├── prompts/
│   └── manifest.json        # Prompt registry
└── environment.yml          # Mamba environment
```

---

## ❌ **Critical Missing Components**

### 1. **Session Management** 🔴 HIGH PRIORITY
**Reference:** `opencode/packages/opencode/src/session/`

**Missing:**
- Session persistence (Storage layer)
- Session state tracking (idle/busy/retry)
- Message history management
- Session lifecycle (create, update, fork)
- Parent/child session relationships

**Impact:** Without sessions, the agent can't maintain conversation context across requests.

**Recommendation:**
```python
# server/session/session.py needed
class Session:
    - id: str
    - messages: List[Message]
    - state: SessionState
    - workspace_root: str
    - created_at: datetime
    - updated_at: datetime
```

### 2. **Permission System** 🔴 HIGH PRIORITY
**Reference:** `opencode/packages/opencode/src/permission/`

**Missing:**
- Permission ruleset evaluation
- Tool execution authorization
- User approval workflow
- Pattern-based permission matching
- "always allow" patterns

**Impact:** Tools can execute without user approval, security risk.

**Current State:** Tools execute directly without permission checks.

**Recommendation:**
```python
# server/permission/permission.py needed
class PermissionSystem:
    - evaluate(permission: str, pattern: str, ruleset: Ruleset) -> Action
    - ask(request: PermissionRequest) -> Promise[bool]
    - Ruleset with allow/deny/ask actions
```

### 3. **Storage Layer** 🟡 MEDIUM PRIORITY
**Reference:** `opencode/packages/opencode/src/storage/`

**Missing:**
- Persistent storage for sessions
- Todo list persistence
- Permission approvals storage
- Project metadata storage

**Impact:** No persistence between server restarts.

**Recommendation:**
```python
# server/storage/storage.py needed
class Storage:
    - write(key: List[str], value: Any)
    - read(key: List[str]) -> Any
    - Uses file-based or database storage
```

### 4. **Provider Abstraction** 🟡 MEDIUM PRIORITY
**Reference:** `opencode/packages/opencode/src/provider/`

**Missing:**
- Unified provider interface
- Model configuration management
- Provider-specific prompt selection
- Model capabilities detection

**Current State:** Hardcoded OpenAI/Anthropic in `main.py`.

**Recommendation:**
```python
# server/provider/provider.py needed
class Provider:
    - get_model(provider_id: str, model_id: str) -> Model
    - default_model() -> Model
    - Supports OpenAI, Anthropic, Gemini, etc.
```

### 5. **Missing Tools** 🟡 MEDIUM PRIORITY

**`task` Tool:**
- Launches subagents for complex tasks
- Requires agent registry and session management
- Critical for multi-agent workflows

**`websearch` Tool:**
- Exa AI integration
- Requires API key configuration
- Used for real-time information

**`codesearch` Tool:**
- Exa Code API integration
- Requires API key
- Used for code context retrieval

**`batch` Tool:**
- Parallel tool execution
- Performance optimization
- Requires tool registry improvements

**`lsp` Tool:**
- Language Server Protocol integration
- Requires LSP client setup
- Used for code intelligence

### 6. **Configuration System** 🟢 LOW PRIORITY
**Reference:** `opencode/packages/opencode/src/config/`

**Missing:**
- Config file parsing (JSONC)
- Environment variable substitution
- File inclusion (`{file:path}`)
- Default agent configuration
- Permission rules configuration

**Recommendation:**
```python
# server/config/config.py needed
class Config:
    - load_config() -> ConfigDict
    - Supports opencode.jsonc format
    - Environment variable expansion
```

### 7. **Project/Instance Management** 🟢 LOW PRIORITY
**Reference:** `opencode/packages/opencode/src/project/`

**Missing:**
- Project metadata tracking
- VCS (Git) integration
- Workspace root management
- Project initialization

**Current State:** Uses `os.getcwd()` directly.

### 8. **Message System** 🟡 MEDIUM PRIORITY
**Reference:** `opencode/packages/opencode/src/session/message-v2.ts`

**Missing:**
- Structured message format
- Message parts (text, tool, file, etc.)
- Message metadata (timestamps, model info)
- Message streaming support

**Current State:** Uses LangChain's `BaseMessage` directly.

---

## 🔍 **Code Quality Issues**

### 1. **Tool Context Missing**
**Issue:** Tools don't receive session context (sessionID, messageID, etc.)

**Reference Implementation:**
```typescript
async execute(params, ctx) {
  // ctx has: sessionID, messageID, agent, abort, etc.
}
```

**Current State:**
```python
@tool
def read(file_path: str) -> str:
    # No context available
```

**Fix Needed:** LangChain tools need context injection mechanism.

### 2. **Error Handling**
**Issues:**
- Tools return error strings instead of raising exceptions
- No structured error types
- Missing error recovery mechanisms

**Recommendation:** Use custom exceptions and proper error propagation.

### 3. **Path Safety**
**Status:** ✅ Implemented correctly
- `resolve_path()` prevents traversal
- `ensure_in_workspace()` validates paths
- All paths relative to workspace root

### 4. **Streaming Implementation**
**Issues:**
- Token streaming is simulated (chunks, not real tokens)
- Tool result streaming could be improved
- Missing proper LangGraph event streaming

**Recommendation:** Use `astream_events()` for finer-grained control.

### 5. **Graph Routing Logic**
**Issues:**
- `should_continue_to_editor()` relies on keyword matching
- No explicit plan approval mechanism
- Mode switching logic could be more robust

**Recommendation:** Add explicit approval state or user confirmation.

---

## 📊 **Coverage Analysis**

### Tools: 13/19 (68%)
- ✅ Core file operations: 5/5 (100%)
- ✅ Search operations: 3/3 (100%)
- ✅ Shell operations: 1/1 (100%)
- ✅ Web operations: 1/2 (50%) - Missing websearch
- ✅ Task management: 2/2 (100%) - But placeholders
- ✅ Advanced: 1/6 (17%) - Missing task, codesearch, batch, lsp

### Core Systems: 3/8 (38%)
- ✅ Agent Graph: Implemented
- ✅ Prompt Registry: Implemented
- ✅ Server API: Implemented
- ❌ Session Management: Missing
- ❌ Permission System: Missing
- ❌ Storage Layer: Missing
- ❌ Provider Abstraction: Partial
- ❌ Config System: Missing

### Client: 1/1 (100%)
- ✅ Textual TUI: Implemented

---

## 🎯 **Priority Recommendations**

### **Phase 1: Critical Foundation** (Must Have)
1. **Session Management**
   - Create `server/session/session.py`
   - Implement session persistence
   - Add message history tracking

2. **Permission System**
   - Create `server/permission/permission.py`
   - Implement ruleset evaluation
   - Add user approval workflow

3. **Storage Layer**
   - Create `server/storage/storage.py`
   - File-based or SQLite storage
   - Session/todo/permission persistence

### **Phase 2: Core Features** (Should Have)
4. **Missing Tools**
   - Implement `task` tool (subagent launching)
   - Implement `websearch` tool (Exa AI)
   - Implement `codesearch` tool (Exa Code)
   - Implement `batch` tool (parallel execution)

5. **Provider Abstraction**
   - Create unified provider interface
   - Support multiple LLM providers
   - Model configuration management

6. **Message System**
   - Structured message format
   - Message parts and metadata
   - Better streaming support

### **Phase 3: Polish** (Nice to Have)
7. **Configuration System**
   - Config file parsing
   - Environment variable support

8. **Project Management**
   - VCS integration
   - Project metadata

9. **LSP Integration**
   - Language server support
   - Code intelligence features

---

## 🔧 **Technical Debt**

1. **Tool Context Injection**
   - Need mechanism to pass session context to tools
   - LangChain tools don't natively support this
   - May need custom wrapper or middleware

2. **Error Handling**
   - Standardize error types
   - Proper exception hierarchy
   - Error recovery strategies

3. **Testing**
   - No test files found
   - Need unit tests for tools
   - Integration tests for graph

4. **Documentation**
   - README is minimal
   - No API documentation
   - Missing usage examples

5. **Dependencies**
   - Some tools have optional dependencies (httpx, markdownify)
   - Should handle gracefully when missing
   - Add dependency checks

---

## ✅ **Strengths**

1. **Clean Architecture**
   - Well-organized module structure
   - Separation of concerns
   - Follows Python best practices

2. **Safety First**
   - Path traversal protection
   - Workspace root enforcement
   - Input validation with Pydantic

3. **Modern Stack**
   - LangGraph for orchestration
   - FastAPI for async server
   - Textual for modern TUI

4. **Prompt System**
   - Complete prompt registry
   - Context injection working
   - Jinja2 template support

---

## 📝 **Action Items**

### Immediate (Before Production)
- [ ] Implement session management
- [ ] Add permission system
- [ ] Create storage layer
- [ ] Fix tool context injection
- [ ] Add error handling

### Short Term (Next Sprint)
- [ ] Implement missing tools (task, websearch, codesearch)
- [ ] Add provider abstraction
- [ ] Improve streaming implementation
- [ ] Add comprehensive tests

### Long Term (Future)
- [ ] LSP integration
- [ ] Configuration system
- [ ] Project management
- [ ] Performance optimization
- [ ] Documentation

---

## 📈 **Progress Summary**

**Overall Completion: ~40%**

- ✅ Foundation: 80% (Graph, Server, Client, Prompts)
- ⚠️ Core Systems: 30% (Missing Session, Permission, Storage)
- ✅ Tools: 68% (13/19 implemented)
- ❌ Advanced Features: 10% (Missing most advanced tools)

**Code Statistics:**
- Total lines (Python + JSON): 2,043 lines
- Server code: ~1,400 lines
- Client code: ~200 lines
- Tools: ~750 lines
- Prompts manifest: 198 lines

**Status:** Solid foundation, but missing critical infrastructure for production use.

---

## 📦 **Dependencies**

**Status:** ✅ Complete

All required dependencies are listed in:
- `environment.yml` (Mamba/Conda)
- `requirements.txt` (pip)

**Key Dependencies:**
- FastAPI + Uvicorn (server)
- LangChain Core + OpenAI/Anthropic (LLM)
- LangGraph (orchestration)
- Textual (TUI client)
- Jinja2 (templates)
- Pydantic (validation)
- httpx (HTTP client)

**Optional Dependencies:**
- `markdownify` - For webfetch HTML conversion
- Future: Exa AI SDK (for websearch/codesearch tools)

---

## 🚀 **Next Steps**

1. **Start with Session Management** - Everything depends on this
2. **Add Permission System** - Security critical
3. **Implement Storage** - Enables persistence
4. **Complete Missing Tools** - Feature parity
5. **Add Tests** - Quality assurance

The project has a strong foundation but needs the core infrastructure components to be a complete replica of OpenCode.

---

## 📋 **Quick Reference**

**File Structure:**
```
openscrum/
├── server/
│   ├── main.py              # FastAPI server (273 lines)
│   ├── agent/
│   │   ├── graph.py         # LangGraph state machine (299 lines)
│   │   └── prompt_registry.py # Prompt loader (117 lines)
│   └── tools/
│       └── system_tools.py  # 13 tools (758 lines)
├── client/
│   └── tui.py               # Textual TUI (~200 lines)
├── prompts/
│   ├── manifest.json        # Prompt registry (198 lines)
│   └── **/*.txt            # 38 prompt files
├── environment.yml          # Mamba environment
└── requirements.txt         # Pip dependencies
```

**Total Code:** 2,043 lines (Python + JSON)

**Key Files:**
- `server/main.py` - Entry point, FastAPI app
- `server/agent/graph.py` - Core agent logic
- `server/tools/system_tools.py` - Tool implementations
- `client/tui.py` - User interface
- `prompts/manifest.json` - Prompt registry
