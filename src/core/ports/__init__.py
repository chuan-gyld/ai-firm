from __future__ import annotations
"""Ports - interfaces for external dependencies (hexagonal architecture)"""

from .llm import LLMPort, LLMResponse
from .storage import StoragePort

__all__ = ["LLMPort", "LLMResponse", "StoragePort"]
