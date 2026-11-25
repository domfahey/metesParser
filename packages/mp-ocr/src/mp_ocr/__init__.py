"""LLM-based OCR extraction for deed PDFs."""

from .cache import CachedLLMClient
from .clients import (
    BaseLLMClient,
    GeminiClient,
    LLMClientError,
    LLMConfigurationError,
    OpenAIClient,
    OpenRouterClient,
)
from .extract import PDFProcessor, compute_llm_confidence

__version__ = "1.0.1"

__all__ = [
    "BaseLLMClient",
    "CachedLLMClient",
    "GeminiClient",
    "LLMClientError",
    "LLMConfigurationError",
    "OpenAIClient",
    "OpenRouterClient",
    "PDFProcessor",
    "compute_llm_confidence",
]
