# Plan Mode Enhancements - Implementation Roadmap

## Overview
Enhance Plan Mode to handle different workspace scenarios:
1. Empty workspace (greenfield)
2. Design docs exist, no code
3. Code exists, no design docs (reverse engineering)
4. Both exist (sync checking)

---

## Phase 1: Smart Plan Mode Entry & Workspace Detection

### 1.1 Backend - Workspace Analysis Tool
- [ ] Create `analyze_workspace()` tool in `server/tools/system_tools.py`
  - [ ] `check_for_code_files()` - detect .py, .js, .ts, .vue, etc.
  - [ ] `count_code_files()` - count non-design files
  - [ ] `check_design_docs_exist()` - check .openscrum/design/
  - [ ] `get_design_doc_status()` - return which docs exist (e.g., 5/7)
  - [ ] `detect_languages()` - identify main languages used
  - [ ] `detect_frameworks()` - parse package.json, requirements.txt, etc.
  - [ ] `get_latest_code_timestamp()` - most recent code file modification
  - [ ] `get_latest_design_timestamp()` - most recent design doc modification
  - [ ] Return comprehensive workspace status dict

### 1.2 Prompt Updates
- [ ] Update `prompts/session/prompt/plan.txt`
  - [ ] Add **WORKSPACE ANALYSIS** section
  - [ ] Add workflow for empty workspace (current)
  - [ ] Add workflow for design-docs-only scenario
  - [ ] Add workflow for code-only scenario (reverse eng trigger)
  - [ ] Add workflow for both-exist scenario (sync check)
  - [ ] Add decision tree for agent to follow

### 1.3 Frontend - Status Display
- [ ] Add workspace status state in `App.vue`
  ```js
  const workspaceStatus = ref({
    has_code: false,
    code_file_count: 0,
    has_design_docs: false,
    design_doc_count: 0,
    needs_sync: false,
    main_languages: [],
    detected_frameworks: []
  })
  ```
- [ ] Add `fetchWorkspaceStatus()` API function in `useApiClient.js`
- [ ] Create workspace status indicator component
  - [ ] Show file count badge
  - [ ] Show design doc count badge (e.g., "5/7 docs")
  - [ ] Show sync warning icon if needed
  - [ ] Position in Plan Mode header/toolbar

### 1.4 API Endpoint
- [ ] Add `/sessions/{session_id}/workspace/analyze` endpoint in `server/main.py`
  - [ ] Call `analyze_workspace()` tool
  - [ ] Return status JSON to frontend
  - [ ] Cache results for 60 seconds (avoid repeated scans)

### 1.5 Testing
- [ ] Test with empty workspace
- [ ] Test with only design docs
- [ ] Test with only code files
- [ ] Test with both code and design docs
- [ ] Test detection accuracy for different languages/frameworks

---

## Phase 2: Reverse Engineering (Code → Design)

### 2.1 Code Scanning Infrastructure
- [ ] Create `scan_codebase()` function in `server/tools/system_tools.py`
  - [ ] Scan folder structure and identify patterns (MVC, monorepo, etc.)
  - [ ] Parse dependency files:
    - [ ] `package.json` → JavaScript/TypeScript stack
    - [ ] `requirements.txt` / `pyproject.toml` → Python stack
    - [ ] `Gemfile` → Ruby stack
    - [ ] `pom.xml` / `build.gradle` → Java stack
  - [ ] Detect frameworks from imports/config:
    - [ ] React, Vue, Angular (frontend)
    - [ ] Express, FastAPI, Django, Rails (backend)
    - [ ] Database adapters (PostgreSQL, MongoDB, Redis)
  - [ ] Return structured dict with findings

### 2.2 Specific Extractors
- [ ] Create `extract_api_routes()` function
  - [ ] Parse route definitions (e.g., `@app.get`, `router.post`)
  - [ ] Extract endpoints, methods, parameters
  - [ ] Return list of API endpoints with metadata

- [ ] Create `extract_db_schemas()` function
  - [ ] Parse ORM models (SQLAlchemy, Mongoose, Prisma)
  - [ ] Extract table/collection names, fields, relationships
  - [ ] Return database schema information

- [ ] Create `list_components()` function
  - [ ] Find React/Vue/Angular components
  - [ ] Extract component hierarchy
  - [ ] Return component list with file paths

- [ ] Create `list_services()` function
  - [ ] Identify service/business logic files
  - [ ] Extract class/function names
  - [ ] Return service structure

### 2.3 Design Document Generation from Code
- [ ] Create `generate_design_from_code()` function
  - [ ] Input: workspace_root, doc_type, scan_results
  - [ ] Use LLM to generate markdown based on extracted data
  - [ ] For each doc type:
    - [ ] **functionalities.md**: Infer features from routes/components
    - [ ] **tech_stack.md**: List detected languages, frameworks, tools
    - [ ] **database_design.md**: Document extracted schemas
    - [ ] **architecture.md**: Describe folder structure and patterns
    - [ ] **api_design.md**: Document all extracted endpoints
    - [ ] **user_flow.md**: Infer flows from component/route relationships
    - [ ] **requirements.md**: Estimate based on complexity

- [ ] Add tool binding to planner node for reverse engineering
- [ ] Update plan.txt to use reverse engineering workflow when code detected

### 2.4 Testing
- [ ] Test on sample Vue 3 project
- [ ] Test on sample Python FastAPI project
- [ ] Test on sample fullstack project
- [ ] Validate accuracy of extracted information
- [ ] Test design doc generation quality

---

## Phase 3: Sync Tracking & Warnings

### 3.1 Metadata Storage
- [ ] Create sync metadata schema
  ```json
  {
    "design_docs_last_synced": "ISO timestamp",
    "code_last_modified": "ISO timestamp",
    "last_sync_hash": "hash of design docs content",
    "tracked_files": ["list of files at last sync"],
    "tracked_dependencies": {"package.json hash", "requirements.txt hash"},
    "sync_warnings": ["warning messages"],
    "last_check": "ISO timestamp"
  }
  ```

- [ ] Store in `.openscrum/sync_metadata.json`
- [ ] Create helper functions:
  - [ ] `load_sync_metadata()`
  - [ ] `save_sync_metadata()`
  - [ ] `update_sync_timestamp()`

### 3.2 Sync Status Checker
- [ ] Create `check_sync_status()` function
  - [ ] Load metadata
  - [ ] Compare current state vs. last sync
  - [ ] Detect changes:
    - [ ] New files added
    - [ ] Files deleted
    - [ ] Dependencies changed (package.json, requirements.txt)
    - [ ] Code modified after design docs updated
  - [ ] Generate warnings list
  - [ ] Generate suggestions
  - [ ] Return status dict

### 3.3 Warning System
- [ ] Define warning types:
  - [ ] `code_modified_after_design` - Code changed since last design update
  - [ ] `new_files_detected` - Files added not in design docs
  - [ ] `dependencies_changed` - Tech stack evolved
  - [ ] `architecture_drift` - Folder structure changed
  - [ ] `design_outdated` - Design docs not updated in X days

- [ ] Add severity levels: `info`, `warning`, `critical`
- [ ] Create warning message templates

### 3.4 UI Components
- [ ] Create `SyncWarningBanner.vue` component
  - [ ] Show warning icon + count
  - [ ] Expandable to show warning list
  - [ ] Action buttons:
    - [ ] "Update Design from Code"
    - [ ] "Review Changes"
    - [ ] "Dismiss"
  - [ ] Position at top of Plan Mode view

- [ ] Add sync status to workspace status indicator
  - [ ] Green checkmark: "In sync"
  - [ ] Yellow warning: "Needs review"
  - [ ] Red alert: "Significant drift"

- [ ] Add "Sync Now" button in design doc toolbar
  - [ ] Trigger reverse engineering for selected doc
  - [ ] Update sync metadata after completion

### 3.5 API Endpoints
- [ ] Add `/sessions/{session_id}/workspace/sync-status` endpoint
  - [ ] Call `check_sync_status()`
  - [ ] Return warnings and suggestions

- [ ] Add `/sessions/{session_id}/workspace/sync` endpoint (POST)
  - [ ] Trigger reverse engineering
  - [ ] Update design docs from code
  - [ ] Update sync metadata
  - [ ] Return updated status

### 3.6 Testing
- [ ] Test with synced workspace (no warnings)
- [ ] Test after modifying code (should show warnings)
- [ ] Test after adding new files (should detect)
- [ ] Test after changing dependencies (should warn)
- [ ] Test sync action (should clear warnings)
- [ ] Test dismiss action (should hide warnings temporarily)

---

## Phase 4: Enhanced Workflows & Dialogs

### 4.1 Decision Dialogs
- [ ] Create dialog for "Design docs exist, no code"
  - Options: Review existing, Start fresh, Proceed to implement
  
- [ ] Create dialog for "Code exists, no design docs"
  - Options: Generate from code, Start fresh, Skip design phase

- [ ] Create dialog for "Both exist, out of sync"
  - Options: Update design from code, Update code from design, Continue as-is

- [ ] Implement using existing `QuestionDialog` component with choice questions

### 4.2 Gap Analysis Feature
- [ ] Create "Compare Design vs Code" function
  - [ ] Compare tech_stack.md vs detected stack (show differences)
  - [ ] Compare api_design.md vs extracted routes (show missing/extra)
  - [ ] Compare database_design.md vs extracted schema (show drift)
  - [ ] Generate gap report

- [ ] Add "Gap Analysis" view/component
  - [ ] Show side-by-side comparison
  - [ ] Highlight differences
  - [ ] Suggest actions

### 4.3 Manual Sync Controls
- [ ] Add "Sync Selected Doc" action per design doc
  - [ ] Context menu or button in doc viewer
  - [ ] Regenerate specific doc from code
  - [ ] Show diff before applying

- [ ] Add "Sync All Docs" action
  - [ ] Regenerate all design docs from code
  - [ ] Show summary of changes
  - [ ] Require confirmation

---

## Implementation Schedule

### Week 1: Core Detection & Status Display
**Goals**: Workspace can be analyzed, status is visible
- Day 1-2: Backend analyze_workspace() tool
- Day 3-4: API endpoint and frontend status display
- Day 5: Testing and refinement

### Week 2: Smart Workflows & Dialogs
**Goals**: Agent responds differently based on workspace state
- Day 1-2: Update plan.txt with workflows
- Day 3-4: Implement decision dialogs
- Day 5: End-to-end testing of scenarios

### Week 3: Reverse Engineering Foundation
**Goals**: Can scan code and extract information
- Day 1-2: scan_codebase() and extractors
- Day 3-4: generate_design_from_code() function
- Day 5: Testing with sample projects

### Week 4: Sync Tracking & Warnings
**Goals**: Sync status tracked, warnings shown
- Day 1-2: Metadata storage and check_sync_status()
- Day 3-4: Warning UI components
- Day 5: Testing sync detection and actions

---

## Future Enhancements (Post-MVP)

### Git Integration
- [ ] Detect if workspace is a git repo
- [ ] Use git history to track when code vs design diverged
- [ ] Show git diff between design updates

### Advanced Analysis
- [ ] Deeper AST parsing for complex logic extraction
- [ ] Dependency graph visualization
- [ ] Performance/security issue detection

### Version Control for Design Docs
- [ ] Track design doc versions (.openscrum/design/history/)
- [ ] Show design evolution over time
- [ ] Revert to previous design versions

### Collaborative Features
- [ ] Mark design sections as "reviewed" or "needs update"
- [ ] Add comments/annotations to design docs
- [ ] Track who made which design decisions

---

## Notes & Considerations

### Performance
- Cache workspace analysis results (60 seconds TTL)
- Scan large codebases in background
- Show progress indicator for long scans

### Edge Cases
- Handle monorepos (multiple projects in one workspace)
- Handle mixed-language projects
- Handle non-standard project structures
- Handle very large codebases (>10k files)

### User Experience
- Don't block user with long scans
- Make sync optional, not forced
- Clear messaging about what each action does
- Easy to dismiss/ignore warnings if user disagrees

### Security
- Don't scan files outside workspace
- Don't expose sensitive data in logs
- Respect .gitignore patterns when scanning
