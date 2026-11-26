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
from .escalation import (
    VALID_ESCALATION_POLICIES,
    CourseDisagreement,
    EscalationPolicy,
    EscalationReport,
    compare_call_readings,
    select_escalation_outcome,
    should_escalate_closure,
    validate_escalation_policy,
)
from .extract import (
    PDFProcessor,
    compute_llm_confidence,
    has_legal_measurement_signals,
    parse_located_pages,
    verify_normalization_integrity,
)
from .preprocessing import (
    count_pdf_pages,
    preprocess_pdf_pages_for_ocr,
    render_pdf_pages_to_pngs,
    strip_green_watermark_and_crop,
)

__version__ = "1.0.1"

__all__ = [
    "BaseLLMClient",
    "CachedLLMClient",
    "CourseDisagreement",
    "EscalationPolicy",
    "EscalationReport",
    "GeminiClient",
    "LLMClientError",
    "LLMConfigurationError",
    "OpenAIClient",
    "OpenRouterClient",
    "PDFProcessor",
    "VALID_ESCALATION_POLICIES",
    "compare_call_readings",
    "compute_llm_confidence",
    "count_pdf_pages",
    "has_legal_measurement_signals",
    "parse_located_pages",
    "preprocess_pdf_pages_for_ocr",
    "render_pdf_pages_to_pngs",
    "select_escalation_outcome",
    "should_escalate_closure",
    "strip_green_watermark_and_crop",
    "validate_escalation_policy",
    "verify_normalization_integrity",
]
