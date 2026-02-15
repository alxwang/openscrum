"""
Memsearch storage adapter for semantic memory search.

This adapter extends the file-based storage with semantic search capabilities
using memsearch (https://github.com/zilliztech/memsearch).

Usage:
- Set OPENSCRUM_STORAGE_BACKEND=memsearch to enable
- Set OPENSCRUM_MEMSEARCH_MEMORY_DIR to specify memory directory (default: ~/.openscrum/memory)
- Set OPENSCRUM_MEMSEARCH_EMBEDDING_MODEL to configure embedding model (default: text-embedding-ada-002)
- Messages and conversation data are exported to markdown for semantic search
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

from server.storage.storage import Storage, NotFoundError, _STORAGE_DIR

# Try to import memsearch from local fork first, then fall back to pip-installed version
MEMSEARCH_AVAILABLE = False
MemSearch = None

try:
    # First try local fork at ../../../memsearch/src (relative to this file)
    current_file = Path(__file__).resolve()
    local_memsearch_root = current_file.parent.parent.parent.parent / "memsearch"
    local_memsearch_src = local_memsearch_root / "src"
    
    if local_memsearch_src.exists() and str(local_memsearch_src) not in sys.path:
        sys.path.insert(0, str(local_memsearch_src))
    
    from memsearch import MemSearch
    MEMSEARCH_AVAILABLE = True
    
    import logging
    _init_log = logging.getLogger(__name__)
    if local_memsearch_src.exists():
        _init_log.info(f"Using local memsearch fork from {local_memsearch_src}")
    else:
        _init_log.info("Using pip-installed memsearch")
except ImportError as e:
    import logging
    _init_log = logging.getLogger(__name__)
    _init_log.warning(f"Failed to import memsearch: {e}")


class MemSearchAdapter(Storage):
    """
    Storage adapter that combines file-based JSON storage with memsearch semantic search.
    
    - All structured data (sessions, messages, etc.) is stored in JSON files (via parent Storage)
    - Conversation data is also exported to markdown files for semantic search
    - Provides search() method for semantic queries
    """

    def __init__(self, base_dir: str | None = None, memory_dir: str | None = None):
        """
        Initialize storage with optional memsearch integration.
        
        Args:
            base_dir: Base directory for JSON storage (default: ~/.openscrum/storage)
            memory_dir: Directory for markdown memory files (default: ~/.openscrum/memory)
        """
        super().__init__(base_dir)
        
        # Memory directory for markdown files
        self._memory_dir = memory_dir or os.path.join(
            os.path.dirname(self._dir), "memory"
        )
        Path(self._memory_dir).mkdir(parents=True, exist_ok=True)
        
        # Initialize memsearch if available
        self._memsearch: Optional[Any] = None
        self._last_index_time = 0.0  # Track last indexing time for rate limiting
        self._index_cooldown = 30.0  # Minimum seconds between indexing operations
        storage_backend = os.getenv("OPENSCRUM_STORAGE_BACKEND")
        self._memsearch_enabled = MEMSEARCH_AVAILABLE and storage_backend == "memsearch"
        
        import logging
        _init_log = logging.getLogger(__name__)
        _init_log.info(f"Storage init: MEMSEARCH_AVAILABLE={MEMSEARCH_AVAILABLE}, backend={storage_backend}, will_enable={self._memsearch_enabled}")
        
        if self._memsearch_enabled:
            if not MEMSEARCH_AVAILABLE:
                import logging
                logging.warning(
                    "OPENSCRUM_STORAGE_BACKEND=memsearch but memsearch not installed. "
                    "Run: pip install memsearch"
                )
                self._memsearch_enabled = False
            else:
                try:
                    import logging
                    _log = logging.getLogger(__name__)
                    
                    # Load API key from .env if not in environment
                    openai_api_key = os.getenv("OPENAI_API_KEY")
                    _log.info(f"OPENAI_API_KEY in env: {bool(openai_api_key)}")
                    
                    if not openai_api_key:
                        # Try loading from ~/.env
                        try:
                            from dotenv import load_dotenv
                            env_path = Path.home() / ".env"
                            if env_path.exists():
                                _log.info(f"Loading from {env_path}")
                                load_dotenv(env_path, override=False)
                                openai_api_key = os.getenv("OPENAI_API_KEY")
                                _log.info(f"OPENAI_API_KEY after loading .env: {bool(openai_api_key)}")
                        except ImportError:
                            _log.warning("dotenv not available")
                    
                    if not openai_api_key:
                        _log.warning("OPENAI_API_KEY not found - memsearch will not work")
                        self._memsearch_enabled = False
                    else:
                        # Ensure API key is in environment for memsearch
                        os.environ["OPENAI_API_KEY"] = openai_api_key
                        
                        # Configure embedding model (default to 3-small)
                        embedding_model = os.getenv("OPENSCRUM_MEMSEARCH_EMBEDDING_MODEL", "text-embedding-3-small")
                        _log.info(f"Initializing memsearch with model: {embedding_model}, memory_dir: {self._memory_dir}")
                        
                        self._memsearch = MemSearch(
                            paths=[self._memory_dir],
                            embedding_model=embedding_model
                        )
                        _log.info(f"✓ Memsearch initialized successfully with {embedding_model}")
                        # Trigger initial indexing
                        self._trigger_indexing()
                except Exception as e:
                    import logging
                    _err_log = logging.getLogger(__name__)
                    _err_log.error(f"✗ Failed to initialize memsearch: {e}", exc_info=True)
                    _err_log.error(f"Try setting OPENSCRUM_MEMSEARCH_EMBEDDING_MODEL=text-embedding-ada-002 if you have model access issues")
                    self._memsearch_enabled = False

    async def _index_memories(self):
        """Background task to index memory files."""
        if self._memsearch:
            try:
                import logging
                _log = logging.getLogger(__name__)
                _log.debug("Indexing memories...")
                await self._memsearch.index()
                _log.debug("Memory indexing complete")
            except Exception as e:
                import logging
                logging.error(f"Failed to index memories: {e}")

    def _trigger_indexing(self):
        """Trigger background indexing with rate limiting (safe to call from sync context)."""
        if not self._memsearch:
            return
        
        # Rate limit: only index once per cooldown period
        current_time = time.time()
        if current_time - self._last_index_time < self._index_cooldown:
            import logging
            _log = logging.getLogger(__name__)
            _log.debug(f"Skipping indexing (cooldown: {self._index_cooldown - (current_time - self._last_index_time):.1f}s remaining)")
            return
        
        self._last_index_time = current_time
        
        try:
            import asyncio
            # Try to get current event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, schedule task
                asyncio.create_task(self._index_memories())
            except RuntimeError:
                # No running loop - this is a sync context
                # Create new event loop and run indexing
                import threading
                def index_in_thread():
                    import asyncio
                    asyncio.run(self._index_memories())
                thread = threading.Thread(target=index_in_thread, daemon=True)
                thread.start()
        except Exception as e:
            import logging
            logging.debug(f"Could not trigger indexing: {e}")

    def write(self, key: List[str], value: Any) -> None:
        """Write value to JSON storage and optionally export to markdown.
        
        Also maintains a reverse index for message_id -> session_id to enable O(1) lookups.
        Index key format: ["index", "message_session", message_id] -> session_id
        """
        super().write(key, value)
        
        # Maintain index: message_id -> session_id
        if len(key) == 3 and key[0] == "message":
            # key = ["message", session_id, message_id]
            session_id = key[1]
            message_id = key[2]
            # Write index entry (recurses to super().write via this method, but key starts with "index")
            self.write(["index", "message_session", message_id], session_id)
        
        # Export when parts are written (messages have content then)
        if self._memsearch_enabled and len(key) >= 2:
            if key[0] == "part":
                # key = ["part", message_id, part_id]
                message_id = key[1]
                self._export_message_to_markdown_by_id(message_id)
                self._trigger_indexing()

    def _export_message_to_markdown_by_id(self, message_id: str) -> None:
        """
        Export a message by ID to markdown format for memsearch indexing.
        Fetches message info and parts from storage.
        """
        try:
            # Find the message - try O(1) index lookup first
            message = None
            session_id = None
            
            try:
                # fast path: lookup session_id from index
                session_id = self.read(["index", "message_session", message_id])
                if session_id:
                    # Verify session exists (optional, but good for consistency)
                    # Now read the message directly: ["message", session_id, message_id]
                    try:
                        message = self.read(["message", session_id, message_id])
                    except Exception:
                        # Message might have been deleted or index is stale
                        message = None
            except Exception:
                # Index missing (backward compatibility for old messages)
                session_id = None

            # Fallback: O(N) scan if index lookup failed
            if not message or not session_id:
                # Get all message keys to find the session
                all_keys = self.list(["message"])
                for key in all_keys:
                    if len(key) == 3 and key[2] == message_id:
                        session_id = key[1]
                        message = self.read(key)
                        
                        # Backfill index for next time
                        if session_id:
                            self.write(["index", "message_session", message_id], session_id)
                        break
            
            if not message or not session_id:
                return
            
            role = message.get("role", "unknown")
            timestamp = message.get("time", {}).get("created", 0)
            
            # Look up parts for this message
            parts = []
            try:
                part_keys = self.list(["part", message_id])
                for pk in part_keys:
                    if len(pk) == 3:  # ["part", message_id, part_id]
                        try:
                            part = self.read(pk)
                            parts.append(part)
                        except Exception:
                            pass
            except Exception as e:
                import logging
                logging.debug(f"Could not fetch parts for message {message_id}: {e}")
            
            # Skip if no text content - don't bloat memory with empty messages
            text_parts = [p.get("text", "") for p in parts if p.get("type") == "text" and p.get("text")]
            if not text_parts:
                return
            
            # Create session-specific memory directory
            session_memory_dir = Path(self._memory_dir) / session_id
            session_memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create or append to daily log
            date_str = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d") if timestamp else datetime.now().strftime("%Y-%m-%d")
            memory_file = session_memory_dir / f"{date_str}.md"
            
            # Format message content
            content_lines = []
            
            # Add message header
            content_lines.append(f"\n## {role.capitalize()} ({message_id})")
            content_lines.append(f"*Time: {datetime.fromtimestamp(timestamp / 1000).isoformat() if timestamp else 'unknown'}*\n")
            
            # Add message text
            for text in text_parts:
                content_lines.append(text)
            
            # Add tool executions (optional, can be verbose)
            tools = [p for p in parts if p.get("type") == "tool"]
            if tools:
                content_lines.append("\n### Tool Executions")
                for tool in tools:
                    tool_name = tool.get("tool", "unknown")
                    state = tool.get("state", {})
                    status = state.get("status", "pending")
                    content_lines.append(f"\n**{tool_name}** ({status})")
                    if state.get("input"):
                        # Truncate large inputs
                        input_str = json.dumps(state['input'], indent=2)
                        if len(input_str) > 300:
                            input_str = input_str[:300] + "..."
                        content_lines.append(f"```json\n{input_str}\n```")
                    if state.get("output"):
                        output = str(state['output'])
                        # Truncate very long outputs
                        if len(output) > 500:
                            output = output[:500] + "..."
                        content_lines.append(f"\nOutput:\n```\n{output}\n```")
            
            content_lines.append("\n---\n")
            
            # Write to file
            content = "\n".join(content_lines)
            with memory_file.open("a", encoding="utf-8") as f:
                f.write(content)
                
        except Exception as e:
            import logging
            logging.error(f"Failed to export message {message_id} to markdown: {e}", exc_info=True)

    def _export_message_to_markdown(self, key: List[str], message: dict) -> None:
        """
        DEPRECATED: Use _export_message_to_markdown_by_id instead.
        Export a message to markdown format for memsearch indexing.
        
        Creates daily markdown files organized by session.
        Note: Messages in storage don't include parts - we need to fetch them separately.
        """
        message_id = message.get("id", key[-1])
        self._export_message_to_markdown_by_id(message_id)

    async def search(self, query: str, top_k: int = 5, session_id: Optional[str] = None) -> List[dict]:
        """
        Semantic search across conversation memories.
        
        Args:
            query: Search query
            top_k: Number of results to return
            session_id: Optional session ID to limit search scope
        
        Returns:
            List of search results with content and score
        """
        if not self._memsearch_enabled or not self._memsearch:
            return []
        
        try:
            # If session_id provided, filter to that session's memory
            if session_id:
                # TODO: memsearch doesn't support path filtering yet
                # For now, search all and filter results
                results = await self._memsearch.search(query, top_k=top_k * 2)
                # Filter by session path
                filtered = [
                    r for r in results 
                    if session_id in r.get("source", "")
                ]
                return filtered[:top_k]
            else:
                return await self._memsearch.search(query, top_k=top_k)
        except Exception as e:
            import logging
            logging.error(f"Search failed: {e}")
            return []

    def get_memory_stats(self) -> dict:
        """Get statistics about memory storage."""
        memory_path = Path(self._memory_dir)
        if not memory_path.exists():
            return {"enabled": False, "memory_dir": str(memory_path)}
        
        md_files = list(memory_path.rglob("*.md"))
        total_size = sum(f.stat().st_size for f in md_files if f.exists())
        
        return {
            "enabled": self._memsearch_enabled,
            "available": MEMSEARCH_AVAILABLE,
            "memory_dir": str(memory_path),
            "markdown_files": len(md_files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }


# Module-level instance
_memsearch_storage: Optional[MemSearchAdapter] = None


def get_memsearch_storage(base_dir: str | None = None, memory_dir: str | None = None) -> MemSearchAdapter:
    """Get or create memsearch storage adapter."""
    global _memsearch_storage
    if _memsearch_storage is None:
        _memsearch_storage = MemSearchAdapter(base_dir=base_dir, memory_dir=memory_dir)
    return _memsearch_storage
