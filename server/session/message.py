"""
Message and Part models for session history (ref: opencode session/message.ts, message-v2.ts).

Simplified for OpenScrum: MessageInfo (id, role, session_id, ...), Part types (text, tool).
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel


# ----- Part types (simplified from MessageV2) -----

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    id: str
    session_id: str
    message_id: str
    text: str


class ToolPart(BaseModel):
    type: Literal["tool"] = "tool"
    id: str
    session_id: str
    message_id: str
    call_id: str
    tool: str
    state: dict[str, Any]  # pending | running | completed | error


MessagePart = TextPart | ToolPart


# ----- Message info (ref: MessageV2.User / MessageV2.Assistant) -----

class MessageTime(BaseModel):
    created: int
    completed: Optional[int] = None


class MessageInfo(BaseModel):
    """Message metadata stored per message; parts stored separately."""
    id: str
    role: Literal["user", "assistant"]
    session_id: str
    parent_id: Optional[str] = None  # for assistant messages, parent user message
    time: MessageTime
    # Optional summary/title for display
    summary: Optional[dict[str, Any]] = None
    # Assistant-only: model, cost, tokens
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    cost: Optional[float] = None
    tokens: Optional[dict[str, int]] = None

    class Config:
        extra = "allow"  # allow metadata from opencode compat


def message_to_dict(msg: MessageInfo) -> dict:
    """Serialize for storage (snake_case -> match our Pydantic)."""
    return msg.model_dump()


def message_from_dict(d: dict) -> MessageInfo:
    return MessageInfo.model_validate(d)


# ----- Conversion to LangChain format -----

def messages_to_langchain(messages_with_parts: list[dict]) -> list:
    """
    Convert stored messages (with parts) to LangChain message format.
    Ref: opencode MessageV2.toModelMessages
    
    Args:
        messages_with_parts: List of {"info": MessageInfo dict, "parts": [part dicts]}
    
    Returns:
        List of LangChain BaseMessage objects (HumanMessage, AIMessage, ToolMessage)
    """
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    
    langchain_messages = []
    
    for msg_data in messages_with_parts:
        msg_info = msg_data["info"]
        parts = msg_data.get("parts", [])
        role = msg_info["role"]
        
        if role == "user":
            # Build content from text parts
            content_parts = []
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    if text and not part.get("ignored", False):
                        content_parts.append(text)
            
            if content_parts:
                content = "\n".join(content_parts)
                langchain_messages.append(HumanMessage(content=content))
        
        elif role == "assistant":
            # Build content from text parts
            content_parts = []
            tool_calls = []
            
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        content_parts.append(text)
                elif part.get("type") == "tool":
                    # Extract tool call info
                    tool_state = part.get("state", {})
                    if tool_state.get("status") == "completed":
                        tool_calls.append({
                            "name": part.get("tool", ""),
                            "args": tool_state.get("input", {}),
                            "id": part.get("call_id", ""),
                        })
            
            content = "\n".join(content_parts) if content_parts else ""
            
            # Create AIMessage with tool_calls if any
            ai_msg = AIMessage(content=content)
            if tool_calls:
                ai_msg.tool_calls = tool_calls
            
            langchain_messages.append(ai_msg)
            
            # Add ToolMessage for each completed tool call
            for part in parts:
                if part.get("type") == "tool":
                    tool_state = part.get("state", {})
                    if tool_state.get("status") == "completed":
                        tool_output = tool_state.get("output", "")
                        langchain_messages.append(
                            ToolMessage(
                                content=tool_output,
                                tool_call_id=part.get("call_id", ""),
                                name=part.get("tool", ""),
                            )
                        )
    
    return langchain_messages
