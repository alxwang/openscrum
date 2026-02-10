"""
Instruction files (AGENTS.md, CLAUDE.md) for system prompt and read-tool context.

Ref: opencode packages/opencode/src/session/instruction.ts
- System prompt: project + global AGENTS.md (and CLAUDE.md fallback) injected every turn.
- Read tool: parent-dir AGENTS.md appended to file output as <system-reminder>.
"""

try:
    from server.instruction.instruction import (
        system_paths,
        system,
        resolve_instructions_for_file,
    )
except ImportError:
    from instruction.instruction import (
        system_paths,
        system,
        resolve_instructions_for_file,
    )

__all__ = ["system_paths", "system", "resolve_instructions_for_file"]
