"""
FastAPI Server for OpenScrum

Provides HTTP API for the agent with streaming support.
"""

import os
import json
from typing import AsyncIterator, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from agent.graph import create_agent, AgentState
from agent.prompt_registry import PromptRegistry


# ============================================================================
# Configuration
# ============================================================================

WORKSPACE_ROOT = os.getenv("OPENSCRUM_WORKSPACE_ROOT", os.getcwd())
DEFAULT_MODEL = os.getenv("OPENSCRUM_MODEL", "gpt-4")
DEFAULT_PROVIDER = os.getenv("OPENSCRUM_PROVIDER", "openai")  # "openai" or "anthropic"


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="OpenScrum Agent API", version="0.1.0")


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    mode: str = "plan"  # "plan" or "edit"
    workspace_root: str = None  # Optional override


class ChatChunk(BaseModel):
    """Streaming chat chunk."""
    type: str  # "token", "tool_call", "tool_result", "done", "error"
    content: str = ""
    tool_name: Optional[str] = None
    tool_input: Optional[dict] = None
    tool_output: Optional[str] = None


# ============================================================================
# LLM Factory
# ============================================================================

def create_llm(provider: str = None, model: str = None) -> object:
    """
    Create LLM instance based on provider.
    Configured to enforce JSON responses.
    
    Args:
        provider: Provider name ("openai" or "anthropic")
        model: Model name
    
    Returns:
        LLM instance configured for JSON mode
    """
    provider = provider or DEFAULT_PROVIDER
    model = model or DEFAULT_MODEL
    
    # Common parameters for JSON mode
    json_mode_kwargs = {
        "temperature": 0.7,
        "streaming": True,
    }
    
    if provider == "openai":
        # OpenAI supports response_format parameter for JSON mode
        # Use gpt-4-turbo or newer models that support JSON mode
        if "gpt-4" in model.lower() or "gpt-3.5" in model.lower():
            json_mode_kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return ChatOpenAI(model=model, **json_mode_kwargs)
    elif provider == "anthropic":
        # Anthropic models support JSON mode via system prompts
        # The prompt registry will add JSON instructions
        return ChatAnthropic(model=model, temperature=0.7)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# ============================================================================
# Agent Factory
# ============================================================================

def get_agent(workspace_root: str = None) -> object:
    """
    Get or create agent instance.
    
    Args:
        workspace_root: Workspace root directory
    
    Returns:
        Compiled agent graph
    """
    workspace = workspace_root or WORKSPACE_ROOT
    llm = create_llm()
    return create_agent(llm, workspace_root=workspace)


# ============================================================================
# Streaming Helper
# ============================================================================

async def stream_agent_response(
    agent: object,
    initial_state: AgentState
) -> AsyncIterator[str]:
    """
    Stream agent responses including tokens and tool results.
    
    Uses LangGraph's astream for state updates and processes messages/tool calls.
    
    Args:
        agent: Compiled agent graph
        initial_state: Initial state for the agent
    
    Yields:
        JSON strings of ChatChunk objects in Server-Sent Events format
    """
    try:
        # Track state for incremental updates
        last_messages_count = 0
        
        # Stream state updates
        async for state_update in agent.astream(initial_state):
            # Process each node's output
            for node_name, node_state in state_update.items():
                if isinstance(node_state, dict):
                    messages = node_state.get("messages", [])
                    
                    # Process new messages
                    new_messages = messages[last_messages_count:]
                    last_messages_count = len(messages)
                    
                    for message in new_messages:
                        # Check for tool calls
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            for tool_call in message.tool_calls:
                                chat_chunk = ChatChunk(
                                    type="tool_call",
                                    tool_name=tool_call.get("name", ""),
                                    tool_input=tool_call.get("args", {}),
                                )
                                yield f"data: {chat_chunk.model_dump_json()}\n\n"
                        
                        # Check for tool results (ToolMessage)
                        if hasattr(message, 'content') and hasattr(message, 'name'):
                            # This is a tool result
                            chat_chunk = ChatChunk(
                                type="tool_result",
                                tool_name=getattr(message, 'name', 'unknown'),
                                tool_output=str(message.content),
                            )
                            yield f"data: {chat_chunk.model_dump_json()}\n\n"
                        
                        # Check for text content (AIMessage)
                        elif hasattr(message, 'content') and message.content:
                            # Stream content (split into chunks for better UX)
                            content = str(message.content)
                            
                            # Only send if not a tool call message
                            if not (hasattr(message, 'tool_calls') and message.tool_calls):
                                # Send content in chunks for streaming effect
                                chunk_size = 50  # Characters per chunk
                                for i in range(0, len(content), chunk_size):
                                    chunk_text = content[i:i + chunk_size]
                                    chat_chunk = ChatChunk(
                                        type="token",
                                        content=chunk_text,
                                    )
                                    yield f"data: {chat_chunk.model_dump_json()}\n\n"
        
        # Send done signal
        done_chunk = ChatChunk(type="done")
        yield f"data: {done_chunk.model_dump_json()}\n\n"
    
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        error_chunk = ChatChunk(
            type="error",
            content=error_msg,
        )
        yield f"data: {error_chunk.model_dump_json()}\n\n"


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "workspace_root": WORKSPACE_ROOT,
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint that streams agent responses.
    
    Args:
        request: Chat request with message and optional mode/workspace
    
    Returns:
        StreamingResponse with Server-Sent Events
    """
    try:
        # Determine workspace root
        workspace_root = request.workspace_root or WORKSPACE_ROOT
        
        # Validate workspace exists
        if not Path(workspace_root).exists():
            raise HTTPException(
                status_code=400,
                detail=f"Workspace root does not exist: {workspace_root}"
            )
        
        # Create agent
        agent = get_agent(workspace_root=workspace_root)
        
        # Create initial state
        initial_state: AgentState = {
            "messages": [HumanMessage(content=request.message)],
            "mode": request.mode,
            "scratchpad": "",
        }
        
        # Stream response
        return StreamingResponse(
            stream_agent_response(agent, initial_state),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check with agent validation."""
    try:
        agent = get_agent()
        return {
            "status": "healthy",
            "agent_ready": True,
            "workspace_root": WORKSPACE_ROOT,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
