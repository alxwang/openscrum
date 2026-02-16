"""
Token counting utilities for context management.

Uses tiktoken for accurate token estimation compatible with OpenAI models.
"""

import logging
from typing import List, Dict, Any

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logging.warning("tiktoken not available - token counting will use rough estimation")

_log = logging.getLogger(__name__)


def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Estimate token count for a text string.
    
    Args:
        text: Text to count tokens for
        model: Model name (e.g., "gpt-4", "gpt-3.5-turbo")
        
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    
    if TIKTOKEN_AVAILABLE:
        try:
            # Get encoding for the model
            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except Exception as e:
            _log.warning(f"tiktoken encoding failed: {e}, using rough estimation")
    
    # Rough estimation: ~4 characters per token on average
    return len(text) // 4


def count_message_tokens(messages: List[Dict[str, Any]], model: str = "gpt-4") -> int:
    """
    Count tokens in a list of messages (LangChain format).
    
    Args:
        messages: List of LangChain message dicts
        model: Model name
        
    Returns:
        Total token count including message overhead
    """
    if not messages:
        return 0
    
    total_tokens = 0
    
    # Add per-message overhead (approximately 4 tokens per message)
    total_tokens += len(messages) * 4
    
    for msg in messages:
        # Extract content from message
        if hasattr(msg, 'content'):
            # LangChain BaseMessage object
            content = str(msg.content) if msg.content else ""
            total_tokens += estimate_tokens(content, model)
            
            # Add tokens for tool calls if present
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if isinstance(tool_call, dict):
                        tool_str = str(tool_call)
                    else:
                        tool_str = str(tool_call)
                    total_tokens += estimate_tokens(tool_str, model)
        
        elif isinstance(msg, dict):
            # Dictionary format from session storage
            parts = msg.get("parts", [])
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    total_tokens += estimate_tokens(text, model)
                elif part.get("type") == "tool":
                    # Tool state has input/output
                    state = part.get("state", {})
                    input_str = str(state.get("input", ""))
                    output_str = str(state.get("output", ""))
                    total_tokens += estimate_tokens(input_str + output_str, model)
    
    return total_tokens


def get_token_limit(model: str) -> int:
    """
    Get the token limit for a given model.
    
    Args:
        model: Model name
        
    Returns:
        Token limit
    """
    # Common model limits
    limits = {
        "gpt-4": 8192,
        "gpt-4-32k": 32768,
        "gpt-4-turbo": 128000,
        "gpt-4-turbo-preview": 128000,
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-5-mini": 272000,
        "gpt-3.5-turbo": 16385,
        "gpt-3.5-turbo-16k": 16385,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-5-sonnet": 200000,
        "claude-3-haiku": 200000,
    }
    
    # Check for partial match
    for key, limit in limits.items():
        if key in model.lower():
            return limit
    
    # Default to conservative 8K if unknown
    _log.warning(f"Unknown model '{model}', using default 8K token limit")
    return 8192


def should_compress(token_count: int, model: str, threshold: float = 0.8) -> bool:
    """
    Determine if context should be compressed based on token usage.
    
    Args:
        token_count: Current token count
        model: Model name
        threshold: Compression threshold (0.0-1.0), default 0.8 (80%)
        
    Returns:
        True if compression is recommended
    """
    limit = get_token_limit(model)
    usage_percentage = token_count / limit
    return usage_percentage >= threshold
