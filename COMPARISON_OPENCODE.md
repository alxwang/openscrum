# OpenScrum vs OpenCode — Comparison & Codebase Review

**Date:** February 2026  
**Goal:** Python replica of OpenCode; this doc compares the two codebases and reviews OpenScrum.

---

## 1. Stack & Scope

| Aspect | OpenCode | OpenScrum |
|--------|----------|-----------|
| **Language** | TypeScript (Bun/Node) | Python 3 |
| **Runtime** | Bun | CPython |
| **Server** | Hono (TypeScript) | FastAPI |
| **Agent** | Custom processor + AI SDK | LangGraph + LangChain |
| **Client** | TUI (React-based?), Web, CLI | Textual TUI |
| **Scope** | Full product (CLI, serve, MCP, ACP, GitHub, etc.) | Focused: server + TUI + agent |

OpenCode is a full application (CLI with many commands, multiple UIs, MCP, ACP). OpenScrum is a **focused replica**: HTTP API + TUI + session/permission/storage aligned with opencode’s core session/tool flow.

---

## 2. Feature Comparison

### 2.1 Session Management

| Feature | OpenCode | OpenScrum |
|---------|----------|-----------|
| Session CRUD | ✅ `Session.create`, `get`, `update`, `fork`, `remove`, `list`, `children` | ✅ Same in `server/session/session.py` |
| Session status | ✅ Idle / busy / retry (in-memory) | ✅ `server/session/status.py` |
| Message history | ✅ Messages + parts in storage | ✅ Same keys: `["message", sid, mid]`, `["part", mid, part_id]` |
| IDs | ✅ `ses_`, `msg_`, `prt_` (time + random) | ✅ `server/session/id_util.py` |
| Session-based chat | ✅ `POST /:sessionID/message` with history | ✅ `POST /sessions/{id}/message` + history |
| Share / revert / compaction | ✅ Share, revert, compaction flows | ❌ Not implemented |

**Verdict:** Core session lifecycle and session-based chat are in place. Advanced session features (share, revert, compaction) are not.

---

### 2.2 Permission System

| Feature | OpenCode | OpenScrum |
|---------|----------|-----------|
| Ruleset (permission + pattern + action) | ✅ allow / deny / ask | ✅ Same in `server/permission/permission.py` |
| Evaluate + ask + reply | ✅ Async ask, reply once/always/reject | ✅ Same; reply persists “always” to storage |
| Wildcard matching | ✅ `*` / `?` in patterns | ✅ `server/permission/wildcard.py` |
| Tool integration | ✅ Tools call `ctx.ask()` before run | ✅ Wrapper in `server/tools/permission_layer.py`; context + callback |
| API | ✅ GET pending, POST reply | ✅ GET `/permissions`, POST `/permissions/{id}/reply` |
| TUI confirmation | ✅ Permission UI in client | ✅ `PermissionScreen` modal (Once / Always / Reject) |

**Verdict:** Permission flow is implemented end-to-end (rules, ask/reply, tool layer, API, TUI).

---

### 2.3 Storage Layer

| Feature | OpenCode | OpenScrum |
|---------|----------|-----------|
| Backend | File-based JSON | ✅ File-based JSON (`~/.openscrum/storage`) |
| API | write, read, update, list, remove | ✅ Same in `server/storage/storage.py` |
| Session persistence | ✅ `["session", projectID, sessionID]` | ✅ Same |
| Message/part persistence | ✅ message, part keys | ✅ Same |
| Todo persistence | ✅ `["todo", sessionID]` | ✅ `server/storage/todo.py` + GET/PUT `/sessions/{id}/todo` |
| Permission approvals | ✅ `["permission", projectID]` | ✅ Used by `PermissionSystem` |
| Project metadata | ✅ `["project", projectID]` | ✅ `server/storage/project.py` (get/write/update/list) |

**Verdict:** Storage semantics and key layout match opencode; todo and project modules added.

---

### 2.4 Tools

| Tool | OpenCode | OpenScrum |
|------|----------|-----------|
| read, write, edit, multiedit, apply_patch | ✅ | ✅ |
| grep, glob, list_files (ls) | ✅ | ✅ |
| bash | ✅ | ✅ |
| webfetch | ✅ | ✅ |
| todowrite, todoread | ✅ | ✅ (storage-backed via storage/todo) |
| question | ✅ | ✅ (placeholder) |
| task | ✅ | ✅ (placeholder; no full subagent/session wiring) |
| websearch | ✅ Exa | ✅ Exa (env API key) |
| codesearch | ✅ Exa Code | ✅ Exa Code (env API key) |
| batch | ✅ | ✅ (parallel tool execution) |
| lsp | ✅ | ✅ (operations; LSP client lib TBD) |
| plan_exit / plan_enter | ✅ | ✅ |
| skill, external-directory, invalid | ✅ | ❌ |
| Truncation / doom-loop | ✅ | ❌ |

**Verdict:** Most opencode tools have an OpenScrum counterpart. Gaps: skill, external-directory, truncation/doom-loop handling.

---

### 2.5 Agent & Prompts

| Feature | OpenCode | OpenScrum |
|---------|----------|-----------|
| Flow | Custom processor + tool registry + LLM stream | LangGraph (planner → editor → tools) |
| Plan vs Edit | Plan (read-only) vs Edit (tools) | ✅ Same idea in graph routing |
| Prompts | Many .txt prompts per provider/model | ✅ Same prompt files under `prompts/` |
| Tool binding | Per-tool schema + execute with ctx | LangChain tools; permission via wrapper |
| Provider abstraction | ✅ Multi-provider, model config | ❌ Hardcoded OpenAI/Anthropic in main |
| Compaction / summary | ✅ Session compaction, summary | ❌ Not implemented |

**Verdict:** Core plan/edit workflow and prompts are aligned; OpenScrum lacks provider abstraction and compaction/summary.

---

### 2.6 API Surface

| Area | OpenCode | OpenScrum |
|------|----------|-----------|
| Root / health | ✅ | ✅ `/`, `/health` |
| Chat | ✅ (session-based) | ✅ `/chat` (stateless) + `/sessions/{id}/message` (session) |
| Sessions | ✅ List, get, create, patch, delete, children, messages, fork, status, todo, message, init, abort, share, diff, summarize, revert, etc. | ✅ List, get, create, patch, delete, children, messages, fork, status, todo, message. ❌ init, abort, share, diff, summarize, revert |
| Permissions | ✅ List pending, reply | ✅ Same |
| TUI / PTY / Question / MCP | ✅ | ❌ |

**Verdict:** Core session and permission APIs are covered; many opencode session/experimental endpoints are not.

---

### 2.7 Client

| Feature | OpenCode | OpenScrum |
|---------|----------|-----------|
| TUI | Rich TUI (session list, etc.) | ✅ Textual TUI: chat, mode, streaming, session create, permission modal |
| Web app | ✅ | ❌ |
| CLI (run, serve, session, etc.) | ✅ | ❌ (only server + TUI) |

**Verdict:** OpenScrum has a working TUI aligned with session + permission; no web or full CLI.

---

## 3. What OpenCode Has That OpenScrum Doesn’t

- **Session:** Share, revert, compaction, summarization, init, abort.
- **Project/Instance:** Full project/bootstrap/VCS/worktree; OpenScrum has storage and a default project only.
- **Provider:** Unified provider layer and model config; OpenScrum uses a single LLM factory in main.
- **Config:** JSONC config, env substitution, file includes; OpenScrum uses env vars only.
- **Message system:** Rich message-v2 (parts, metadata, streaming); OpenScrum uses simpler message dicts and LangChain messages.
- **Tooling:** Skill system, external-directory, truncation/doom-loop, Bash arity for permission.
- **Infra:** MCP, ACP, CLI commands (run, serve, session, github, export/import, etc.), web app.

---

## 4. Codebase Review (OpenScrum)

### 4.1 Strengths

- **Phase 1 complete:** Session, permission, and storage are implemented and wired (session API, permission API, tool layer, TUI).
- **Clear layout:** `server/` (agent, permission, session, storage, tools), `client/tui.py`, `prompts/`; matches opencode conceptually.
- **Aligned semantics:** Storage keys, session lifecycle, permission rules and reply flow match opencode.
- **Session-based chat:** History is loaded and saved; stream merges permission queue and emits `permission_request` so the TUI can confirm.
- **Single storage backend:** File-based JSON is simple and sufficient for current scope.

### 4.2 Gaps / Tech Debt

- **Provider abstraction:** No `server/provider/`; model choice is hardcoded. Needed for multi-model and config-driven behavior.
- **Config system:** No JSONC/config file; everything is env-based.
- **Error handling:** No custom exception hierarchy; many bare `Exception` or string errors.
- **Tool context:** Session/permission are in context vars and wrapper; tools don’t get an explicit `ctx` (session_id, message_id, abort). Good enough for permission; could be formalized.
- **Streaming:** Token streaming is chunked rather than true token-by-token; no `astream_events`-style refinement.
- **Tests:** No unit/integration tests mentioned in the reviewed code.
- **Docs:** README is minimal; no API docs or architecture notes.

### 4.3 Suggested Next Steps (Priority)

1. **Provider abstraction** — Centralize LLM/model selection and config (opencode’s `provider/`).
2. **Config system** — Optional JSONC (or YAML) for agents, permissions, defaults (opencode’s `config/`).
3. **Error handling** — Custom exceptions and consistent handling in routes and tools.
4. **Session extras** — Abort, then share/revert/summarize if needed.
5. **Tests** — Unit tests for storage, session, permission, and a few tools; one integration test for `/sessions/{id}/message`.
6. **Docs** — README (install, run, env), and a short architecture/API overview.

---

## 5. Summary Table

| Area | OpenScrum vs OpenCode |
|------|------------------------|
| **Session** | Core done; no share/revert/compaction. |
| **Permission** | Full ask/reply + tool layer + TUI. |
| **Storage** | Aligned (file JSON, todo, project, permission). |
| **Tools** | Most tools present; no skill, external-directory, truncation. |
| **Agent** | LangGraph plan/edit; no compaction/summary. |
| **API** | Core session + permission; many opencode endpoints missing. |
| **Client** | TUI only; no web/CLI. |
| **Provider/Config** | Not implemented. |

Overall, OpenScrum is a **working Python replica of OpenCode’s core**: session-based chat, permissions, file storage, and most tools. It does not aim (yet) to replicate the full product surface (CLI, MCP, ACP, web, share/revert/compaction, provider abstraction, or config system).
