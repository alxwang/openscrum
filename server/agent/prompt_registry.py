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

    def __init__(
        self,
        manifest_path: str = "prompts/manifest.json",
        workspace_root: Optional[str] = None,
        app_root: Optional[str] = None,
    ):
        """
        Initialize the prompt registry.

        Args:
            manifest_path: Path to manifest.json relative to app root (or workspace if app_root not set)
            workspace_root: User workspace directory (for context: cwd, project_structure)
            app_root: OpenScrum app directory containing prompts/ (default: use workspace_root)
        """
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        # Load manifest and prompts from app root so they work when workspace is user's project
        self._prompts_base = Path(app_root) if app_root else self.workspace_root
        manifest_file = self._prompts_base / manifest_path

        with open(manifest_file, "r", encoding="utf-8") as f:
            self.manifest = json.load(f)

        prompts_dir = self._prompts_base / "prompts"
        self.env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    
    def get_prompt_path(self, key: str) -> Optional[Path]:
        """Get the file path for a prompt key."""
        if key not in self.manifest:
            return None
        
        prompt_info = self.manifest[key]
        base = getattr(self, "_prompts_base", self.workspace_root)
        prompt_path = base / prompt_info["path"]
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
        prompts_dir = self._prompts_base / "prompts"
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
        
        return prompt
    
    def list_prompts(self) -> Dict[str, Dict[str, Any]]:
        """List all available prompts."""
        return self.manifest.copy()
