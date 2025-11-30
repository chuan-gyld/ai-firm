from __future__ import annotations
"""LLM Port - interface for language model interactions"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMMessage:
    """A message in a conversation with the LLM"""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM call"""
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)  # tokens used
    finish_reason: str = "stop"
    raw_response: Optional[Any] = None
    
    @property
    def tokens_used(self) -> int:
        """Total tokens used in this response"""
        return self.usage.get("total_tokens", 0)


class LLMPort(ABC):
    """
    Port for LLM interactions.
    Implementations can use OpenAI, Anthropic, local models, etc.
    """
    
    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stop: Optional[list[str]] = None,
    ) -> LLMResponse:
        """
        Generate a completion from the LLM.
        
        Args:
            messages: Conversation history
            model: Model to use (None = use default)
            temperature: Randomness (0.0 = deterministic)
            max_tokens: Maximum tokens in response
            stop: Stop sequences
            
        Returns:
            LLMResponse with generated content
        """
        pass
    
    @abstractmethod
    async def complete_with_structured_output(
        self,
        messages: list[LLMMessage],
        output_schema: dict[str, Any],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> tuple[LLMResponse, dict[str, Any]]:
        """
        Generate a completion with structured JSON output.
        
        Args:
            messages: Conversation history
            output_schema: JSON schema for expected output
            model: Model to use
            temperature: Randomness
            
        Returns:
            Tuple of (LLMResponse, parsed_output_dict)
        """
        pass
    
    @property
    @abstractmethod
    def default_model(self) -> str:
        """Get the default model name"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> list[str]:
        """Get list of available models"""
        pass
