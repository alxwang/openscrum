"""
Prompt Registry for OpenScrum

Loads prompts from manifest.json and provides Jinja2 template rendering with context injection.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from jinja2 import Template, Environment, FileSystemLoader


class PromptRegistry:
    """Registry for loading and rendering prompts with context injection."""
    
    def __init__(self, manifest_path: str = "prompts/manifest.json", workspace_root: Optional[str] = None):
        """
        Initialize the prompt registry.
        
        Args:
            manifest_path: Path to manifest.json relative to workspace root
            workspace_root: Workspace root directory (defaults to current working directory)
        """
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        manifest_file = self.workspace_root / manifest_path
        
        with open(manifest_file, 'r') as f:
            self.manifest = json.load(f)
        
        # Set up Jinja2 environment
        prompts_dir = self.workspace_root / "prompts"
        self.env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True
        )
    
    def get_prompt_path(self, key: str) -> Optional[Path]:
        """Get the file path for a prompt key."""
        if key not in self.manifest:
            return None
        
        prompt_info = self.manifest[key]
        prompt_path = self.workspace_root / prompt_info["path"]
        return prompt_path if prompt_path.exists() else None
    
    def get_prompt(
        self,
        key: str,
        context: Optional[Dict[str, Any]] = None,
        inject_default_context: bool = True,
        force_json: bool = True
    ) -> str:
        """
        Get a prompt by key and render it with context.
        
        Args:
            key: Prompt key from manifest.json
            context: Additional context variables for template rendering
            inject_default_context: Whether to inject default context (cwd, os_name, project_structure)
            force_json: Whether to append JSON format instructions to the prompt
        
        Returns:
            Rendered prompt string
        """
        prompt_path = self.get_prompt_path(key)
        if not prompt_path:
            raise ValueError(f"Prompt key '{key}' not found in manifest")
        
        # Load template
        # Calculate relative path from prompts directory
        prompts_dir = self.workspace_root / "prompts"
        try:
            relative_path = prompt_path.relative_to(prompts_dir)
        except ValueError:
            # If not relative to prompts, use the path as-is
            relative_path = Path(prompt_path.name)
        
        template = self.env.get_template(str(relative_path))
        
        # Build context
        render_context = {}
        
        if inject_default_context:
            # Inject default context
            render_context.update({
                "cwd": str(self.workspace_root),
                "os_name": os.name,
                "platform": os.uname().sysname if hasattr(os, 'uname') else os.name,
            })
            
            # Get project structure using list_dir tool
            try:
                # Import here to avoid circular dependency
                import sys
                from pathlib import Path
                server_path = Path(__file__).parent.parent
                if str(server_path) not in sys.path:
                    sys.path.insert(0, str(server_path))
                from tools.system_tools import list_files
                project_structure = list_files.invoke({})
                render_context["project_structure"] = project_structure
            except Exception as e:
                # Fallback if tool not available
                render_context["project_structure"] = f"Error loading project structure: {e}"
        
        # Add custom context
        if context:
            render_context.update(context)
        
        # Render template
        prompt = template.render(**render_context)
        
        # Append JSON format instructions if requested
        if force_json:
            json_instruction = """

---
CRITICAL: You MUST respond in valid JSON format only. All responses must be valid JSON objects.

Response Format:
- If you need to call tools, use tool_calls in your JSON response
- If you are providing text content, include it in a "content" field
- All tool calls must be in the "tool_calls" array with "name" and "arguments" fields
- Never include any text outside of JSON structure
- Ensure all JSON is properly escaped and valid

Example JSON response format:
{
  "content": "Your text response here",
  "tool_calls": [
    {
      "name": "tool_name",
      "arguments": {
        "param1": "value1",
        "param2": "value2"
      }
    }
  ]
}

If you have no tool calls, respond with:
{
  "content": "Your text response here"
}

Remember: ALL responses must be valid JSON. No markdown, no plain text, only JSON."""
            prompt += json_instruction
        
        return prompt
    
    def list_prompts(self) -> Dict[str, Dict[str, Any]]:
        """List all available prompts."""
        return self.manifest.copy()
