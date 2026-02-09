# OpenScrum Todo List

**Generated from:** PROJECT_REVIEW.md  
**Date:** February 9, 2026  
**Goal:** Python replica of OpenCode

---

## 🔴 Phase 1: Critical Foundation (Must Have)

### Session Management
- [ ] Create `server/session/session.py`
- [ ] Implement `Session` class with:
  - `id: str`
  - `messages: List[Message]`
  - `state: SessionState` (idle/busy/retry)
  - `workspace_root: str`
  - `created_at: datetime`
  - `updated_at: datetime`
- [ ] Implement session persistence (Storage layer)
- [ ] Add session state tracking (idle/busy/retry)
- [ ] Implement message history management
- [ ] Add session lifecycle methods (create, update, fork)
- [ ] Implement parent/child session relationships

### Permission System
- [ ] Create `server/permission/permission.py`
- [ ] Implement `PermissionSystem` class
- [ ] Add permission ruleset evaluation
- [ ] Implement tool execution authorization
- [ ] Add user approval workflow
- [ ] Implement pattern-based permission matching
- [ ] Add "always allow" patterns support

### Storage Layer
- [ ] Create `server/storage/storage.py`
- [ ] Implement `Storage` class with:
  - `write(key: List[str], value: Any)`
  - `read(key: List[str]) -> Any`
- [ ] Choose storage backend (file-based or SQLite)
- [ ] Implement session persistence
- [ ] Implement todo list persistence
- [ ] Implement permission approvals storage
- [ ] Implement project metadata storage

---

## 🟡 Phase 2: Core Features (Should Have)

### Missing Tools

#### Task Tool
- [x] Implement `task` tool in `server/tools/system_tools.py`
- [x] Add subagent launching capability
- [ ] Integrate with agent registry (requires session management)
- [ ] Connect with session management (requires session management)

#### WebSearch Tool
- [x] Implement `websearch` tool
- [x] Integrate Exa AI API
- [x] Add API key configuration (via environment variables)
- [x] Handle real-time web search requests

#### CodeSearch Tool
- [x] Implement `codesearch` tool
- [x] Integrate Exa Code API
- [x] Add API key configuration (via environment variables)
- [x] Handle code context retrieval

#### Batch Tool
- [x] Implement `batch` tool
- [x] Add parallel tool execution
- [x] Improve tool registry for batch support
- [x] Add performance optimization

### Provider Abstraction
- [ ] Create `server/provider/provider.py`
- [ ] Implement unified provider interface
- [ ] Support OpenAI provider
- [ ] Support Anthropic provider
- [ ] Support Gemini provider (future)
- [ ] Add model configuration management
- [ ] Implement provider-specific prompt selection
- [ ] Add model capabilities detection

### Message System Improvements
- [ ] Create structured message format
- [ ] Implement message parts (text, tool, file, etc.)
- [ ] Add message metadata (timestamps, model info)
- [ ] Improve message streaming support
- [ ] Replace direct LangChain BaseMessage usage

---

## 🟢 Phase 3: Polish (Nice to Have)

### Configuration System
- [ ] Create `server/config/config.py`
- [ ] Implement `Config` class
- [ ] Add config file parsing (JSONC format)
- [ ] Implement environment variable substitution
- [ ] Add file inclusion support (`{file:path}`)
- [ ] Add default agent configuration
- [ ] Add permission rules configuration

### Project Management
- [ ] Implement project metadata tracking
- [ ] Add VCS (Git) integration
- [ ] Improve workspace root management
- [ ] Add project initialization functionality
- [ ] Replace `os.getcwd()` with proper project management

### LSP Integration
- [x] Implement LSP tool
- [ ] Set up LSP client (requires LSP client library)
- [x] Add goToDefinition operation
- [x] Add findReferences operation
- [x] Add hover operation
- [x] Add documentSymbol operation
- [x] Add workspaceSymbol operation
- [x] Add other LSP operations (goToImplementation, prepareCallHierarchy, incomingCalls, outgoingCalls)

### Plan Tools
- [x] Implement `plan_exit` tool
- [x] Implement `plan_enter` tool
- [ ] Add user confirmation workflow (requires session management)
- [ ] Add mode switching logic (requires session management)

---

## 🔧 Code Quality & Technical Debt

### Tool Context Injection
- [ ] Design context injection mechanism
- [ ] Implement custom wrapper for LangChain tools
- [ ] Add middleware for context passing
- [ ] Update all tools to receive context (sessionID, messageID, agent, abort)

### Error Handling
- [ ] Create custom exception hierarchy
- [ ] Standardize error types
- [ ] Replace error strings with exceptions
- [ ] Implement error recovery mechanisms
- [ ] Add proper error propagation

### Streaming Implementation
- [ ] Replace simulated token streaming with real tokens
- [ ] Use `astream_events()` for finer-grained control
- [ ] Improve tool result streaming
- [ ] Add proper LangGraph event streaming

### Graph Routing Logic
- [ ] Add explicit plan approval mechanism
- [ ] Improve mode switching logic
- [ ] Replace keyword matching with robust state management
- [ ] Add user confirmation for plan approval

---

## 🧪 Testing

### Unit Tests
- [ ] Create test directory structure
- [ ] Add tests for `read` tool
- [ ] Add tests for `write` tool
- [ ] Add tests for `edit` tool
- [ ] Add tests for `grep` tool
- [ ] Add tests for `glob` tool
- [ ] Add tests for `bash` tool
- [ ] Add tests for all other tools
- [ ] Add tests for path safety functions
- [ ] Add tests for error handling

### Integration Tests
- [ ] Test graph workflow (plan → edit)
- [ ] Test server `/chat` endpoint
- [ ] Test client-server communication
- [ ] Test streaming functionality
- [ ] Test session management
- [ ] Test permission system
- [ ] Test storage layer

---

## 📚 Documentation

- [ ] Expand README.md with:
  - Project overview
  - Installation instructions
  - Usage examples
  - Architecture overview
  - API documentation
- [ ] Add code comments to all modules
- [ ] Document architecture decisions
- [ ] Create developer guide
- [ ] Add API endpoint documentation
- [ ] Document tool usage examples

---

## 🔍 Dependencies & Infrastructure

- [ ] Add dependency checks for optional packages
- [ ] Handle missing `httpx` gracefully
- [ ] Handle missing `markdownify` gracefully
- [ ] Add Exa AI SDK to requirements (for websearch/codesearch)
- [ ] Add LSP client library (for LSP tool)
- [ ] Add SQLite support (if using for storage)
- [ ] Add JSONC parser (for config system)

---

## 📊 Progress Tracking

**Overall Completion: ~40%**

- ✅ Foundation: 80% (Graph, Server, Client, Prompts)
- ⚠️ Core Systems: 30% (Missing Session, Permission, Storage)
- ✅ Tools: 68% (13/19 implemented)
- ❌ Advanced Features: 10% (Missing most advanced tools)

**Total Tasks:** 20 major items  
**Completed:** 6 (task, websearch, codesearch, batch, lsp, plan tools)  
**In Progress:** 0  
**Pending:** 14

---

## 🎯 Priority Order

1. **Session Management** - Everything depends on this
2. **Permission System** - Security critical
3. **Storage Layer** - Enables persistence
4. **Tool Context Injection** - Required for proper tool execution
5. **Error Handling** - Code quality
6. **Missing Tools** - Feature parity
7. **Provider Abstraction** - Flexibility
8. **Message System** - Better structure
9. **Streaming Improvements** - User experience
10. **Testing** - Quality assurance
11. **Documentation** - Developer experience
12. **Configuration System** - Usability
13. **Project Management** - Better workspace handling
14. **LSP Integration** - Advanced features

---

## 📝 Notes

- All tasks should maintain path safety (workspace root enforcement)
- Follow Python best practices and type hints
- Use Pydantic for validation where applicable
- Maintain compatibility with LangChain/LangGraph patterns
- Reference `opencode/packages/opencode/src/` for implementation details
