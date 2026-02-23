#!/usr/bin/env python3
"""Test that Agent.md is created with agent_rules.md template content."""

from server.workspace import create_workspace_for_session
from pathlib import Path
import shutil

def test_agent_rules_integration():
    # Create test workspace
    test_session_id = "test_integration_verify"
    workspace = create_workspace_for_session(test_session_id)
    
    try:
        # Check Agent.md exists
        agent_file = workspace / "Agent.md"
        assert agent_file.exists(), "Agent.md should exist"
        
        # Read content
        content = agent_file.read_text()
        
        # Verify it's the full template, not the old simple one
        assert len(content) > 10000, f"Content should be > 10000 chars, got {len(content)}"
        
        # Verify key sections from agent_rules.md are present
        expected_sections = [
            "OpenScrum Philosophy",
            "Design documents are the source of truth",
            "TODO lists bridge design to implementation",
            "Plan Mode (Read-Only)",
            "EDIT MODE (Implementation)",
            "Mode-Specific Quick Checklists"
        ]
        
        for section in expected_sections:
            assert section in content, f"Missing section: {section}"
        
        print("✅ All checks passed!")
        print(f"   Agent.md has {len(content)} characters")
        print(f"   Contains all expected sections from agent_rules.md")
        
    finally:
        # Clean up
        shutil.rmtree(workspace)
        print(f"   Cleaned up test workspace")

if __name__ == "__main__":
    test_agent_rules_integration()
