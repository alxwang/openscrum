# OpenScrum Project Review

**Goal:** Python replica of OpenCode  
**Date:** February 9, 2026  
**Status:** Phase 1 Complete (Session, Permission, Storage); Provider/Config/Advanced Session Pending

## 🎯 **Executive Summary**

OpenScrum is a Python replica of OpenCode, implementing a client-server architecture with LangGraph orchestration. **Phase 1 is complete:**

- ✅ **Session Management** — Persistence, status, message history, fork, session-based chat
- ✅ **Permission System** — Rules, ask/reply, tool layer, TUI confirmation
- ✅ **Storage Layer** — File-based JSON; session, message, todo, project, permission keys

Remaining gaps: provider abstraction, config system, advanced session (share/revert/compaction), some tools (skill, external-directory), tests, and docs. See **COMPARISON_OPENCODE.md** for a full OpenScrum vs OpenCode comparison.

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

### 3. **System Tools** ✓ (most opencode tools)
**Implemented:**
- ✅ `read`, `write`, `edit`, `multiedit`, `apply_patch`, `grep`, `glob`, `list_files`, `bash`, `webfetch`
- ✅ `todowrite` / `todoread` — Storage-backed via `server/storage/todo.py`
- ✅ `question` — Placeholder
- ✅ `task` — Placeholder (no full subagent wiring)
- ✅ `websearch` — Exa (env API key)
- ✅ `codesearch` — Exa Code (env API key)
- ✅ `batch` — Parallel tool execution
- ✅ `lsp` — Operations (LSP client TBD)
- ✅ `plan_exit` / `plan_enter`

**Not implemented:** skill, external-directory; truncation/doom-loop handling.

### 4. **Session, Permission, Storage** ✓ (Phase 1)
- **Session:** `server/session/` — session.py, message.py, status.py, id_util.py; API: list, get, create, patch, delete, children, messages, fork, status, todo, **message** (session-based chat).
- **Permission:** `server/permission/` — permission.py, wildcard.py; tool wrapper in `server/tools/permission_layer.py`; API: GET pending, POST reply; TUI PermissionScreen.
- **Storage:** `server/storage/` — storage.py, todo.py, project.py; file-based JSON under `~/.openscrum/storage` (or `OPENSCRUM_DATA_DIR`).

### 5. **Project Structure** ✓
```
openscrum/
├── server/
│   ├── main.py              # FastAPI server
│   ├── agent/               # LangGraph, prompt_registry
│   ├── session/             # Session, message, status, id_util
│   ├── permission/          # Permission, wildcard
│   ├── storage/             # Storage, todo, project
│   └── tools/               # system_tools, permission_layer, context
├── client/
│   └── tui.py               # Textual TUI (session + permission UI)
├── prompts/
│   └── manifest.json        # Prompt registry
└── environment.yml          # Mamba environment
```

---

## ❌ **Remaining Gaps (Post–Phase 1)**

### 1. **Provider Abstraction** 🟡 MEDIUM PRIORITY
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

### 2. **Configuration System** 🟢 LOW PRIORITY
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

### 3. **Project/Instance Management** 🟢 LOW PRIORITY
**Reference:** `opencode/packages/opencode/src/project/`

**Missing:**
- Project metadata tracking
- VCS (Git) integration
- Workspace root management
- Project initialization

**Current State:** Uses `os.getcwd()` directly.

### 4. **Message System** 🟡 MEDIUM PRIORITY
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

### Core Systems: 6/8 (Phase 1 done)
- ✅ Agent Graph: Implemented
- ✅ Prompt Registry: Implemented
- ✅ Server API: Implemented
- ✅ Session Management: Implemented (session, message, status, session-based chat)
- ✅ Permission System: Implemented (rules, ask/reply, tool layer, TUI)
- ✅ Storage Layer: Implemented (file JSON, todo, project)
- ❌ Provider Abstraction: Partial (hardcoded in main)
- ❌ Config System: Missing

### Client: 1/1 (100%)
- ✅ Textual TUI: Implemented

---

## 🎯 **Priority Recommendations**

### **Phase 1: Critical Foundation** ✅ DONE
1. **Session Management** — Done (`server/session/`, session-based chat)
2. **Permission System** — Done (`server/permission/`, tool layer, TUI)
3. **Storage Layer** — Done (`server/storage/`, todo, project)

### **Phase 2: Core Features** (Should Have)
4. **Remaining Tools / Polish**
   - Implement `skill`, `external-directory` if needed; truncation/doom-loop handling

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
- [x] Implement session management
- [x] Add permission system
- [x] Create storage layer
- [ ] Formalize tool context (session_id, abort) if needed
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

**Overall Completion: Phase 1 complete**

- ✅ Foundation: 80% (Graph, Server, Client, Prompts)
- ✅ Core Systems: Session, Permission, Storage implemented
- ✅ Tools: Most opencode tools (websearch, codesearch, batch, lsp, plan; no skill/external-directory)
- ⚠️ Advanced: Provider, config, share/revert/compaction, tests, docs pending

**Code Statistics:**
- Total lines (Python + JSON): 2,043 lines
- Server code: ~1,400 lines
- Client code: ~200 lines
- Tools: ~750 lines
- Prompts manifest: 198 lines

**Status:** Phase 1 (Session, Permission, Storage) complete; see COMPARISON_OPENCODE.md for full OpenScrum vs OpenCode comparison.

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

1. **Provider abstraction** — Centralize LLM/model selection (opencode’s provider layer).
2. **Config system** — Optional JSONC for agents, permissions, defaults.
3. **Error handling** — Custom exceptions and consistent handling in routes/tools.
4. **Session extras** — Abort; share/revert/summarize if needed.
5. **Tests** — Unit tests for storage, session, permission; integration test for session chat.
6. **Docs** — README (install, run, env) and short architecture/API overview.

See **COMPARISON_OPENCODE.md** for a full OpenScrum vs OpenCode comparison and next steps.

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
