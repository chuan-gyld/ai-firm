from __future__ import annotations
"""LiteLLM adapter - supports multiple LLM providers through unified interface"""

import json
import os
from typing import Any, Optional

import litellm
from litellm import acompletion

from ..core.ports.llm import LLMPort, LLMMessage, LLMResponse


class LiteLLMAdapter(LLMPort):
    """
    LLM adapter using LiteLLM for multi-provider support.
    
    Supports:
    - OpenAI: gpt-4o, gpt-4-turbo, gpt-3.5-turbo
    - Anthropic: claude-3-opus, claude-3-sonnet, claude-3-haiku
    - And many more through LiteLLM
    """
    
    def __init__(
        self,
        default_model: str = "claude-sonnet-4-20250514",
        fallback_model: Optional[str] = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        self._default_model = default_model
        self._fallback_model = fallback_model
        self._default_temperature = temperature
        self._default_max_tokens = max_tokens
        
        # Configure LiteLLM
        litellm.set_verbose = False
        
        # Check for API keys
        self._validate_api_keys()
    
    def _validate_api_keys(self) -> None:
        """Check that required API keys are set"""
        model = self._default_model.lower()
        
        if "claude" in model or "anthropic" in model:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ValueError(
                    "ANTHROPIC_API_KEY environment variable required for Claude models. "
                    "Set it with: export ANTHROPIC_API_KEY='your-key'"
                )
        elif "gpt" in model or "openai" in model:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ValueError(
                    "OPENAI_API_KEY environment variable required for OpenAI models. "
                    "Set it with: export OPENAI_API_KEY='your-key'"
                )
    
    async def complete(
        self,
        messages: list[LLMMessage],
        model: Optional[str] = None,
        temperature: float = None,
        max_tokens: int = None,
        stop: Optional[list[str]] = None,
    ) -> LLMResponse:
        """Generate a completion from the LLM"""
        
        model = model or self._default_model
        temperature = temperature if temperature is not None else self._default_temperature
        max_tokens = max_tokens or self._default_max_tokens
        
        # Convert messages to LiteLLM format
        llm_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
        
        try:
            response = await acompletion(
                model=model,
                messages=llm_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
            )
            
            return LLMResponse(
                content=response.choices[0].message.content,
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                finish_reason=response.choices[0].finish_reason,
                raw_response=response,
            )
            
        except Exception as e:
            # Try fallback model if available
            if self._fallback_model and model != self._fallback_model:
                print(f"Primary model {model} failed, trying fallback {self._fallback_model}: {e}")
                return await self.complete(
                    messages=messages,
                    model=self._fallback_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=stop,
                )
            raise
    
    async def complete_with_structured_output(
        self,
        messages: list[LLMMessage],
        output_schema: dict[str, Any],
        model: Optional[str] = None,
        temperature: float = None,
    ) -> tuple[LLMResponse, dict[str, Any]]:
        """Generate a completion with structured JSON output"""
        
        # Add schema instruction to the last message
        schema_instruction = f"""

Please respond with valid JSON matching this schema:
```json
{json.dumps(output_schema, indent=2)}
```

Respond ONLY with the JSON, no other text."""

        enhanced_messages = list(messages)
        if enhanced_messages:
            last_msg = enhanced_messages[-1]
            enhanced_messages[-1] = LLMMessage(
                role=last_msg.role,
                content=last_msg.content + schema_instruction,
            )
        
        response = await self.complete(
            messages=enhanced_messages,
            model=model,
            temperature=temperature if temperature is not None else 0.3,  # Lower temp for structured output
        )
        
        # Parse JSON from response
        try:
            # Try to extract JSON from the response
            content = response.content.strip()
            
            # Handle markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            parsed = json.loads(content)
            return response, parsed
            
        except json.JSONDecodeError as e:
            # Return empty dict if parsing fails
            print(f"Failed to parse JSON from response: {e}")
            return response, {}
    
    @property
    def default_model(self) -> str:
        """Get the default model name"""
        return self._default_model
    
    def get_available_models(self) -> list[str]:
        """Get list of commonly used models"""
        return [
            # Anthropic
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
            # OpenAI
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
        ]
