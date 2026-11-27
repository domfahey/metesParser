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
    is_escalated_subset_truncated,
    select_escalation_outcome,
    should_escalate_closure,
    tail_note_categories,
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
    DEFAULT_MAX_RENDER_PAGES,
    MAX_RENDER_DPI,
    count_pdf_pages,
    preprocess_pdf_pages_for_ocr,
    render_pdf_pages_to_pngs,
    strip_green_watermark_and_crop,
    validate_pdf_pages,
    validate_render_dpi,
)

__version__ = "1.0.1"

__all__ = [
    "BaseLLMClient",
    "CachedLLMClient",
    "CourseDisagreement",
    "DEFAULT_MAX_RENDER_PAGES",
    "EscalationPolicy",
    "EscalationReport",
    "GeminiClient",
    "LLMClientError",
    "LLMConfigurationError",
    "MAX_RENDER_DPI",
    "OpenAIClient",
    "OpenRouterClient",
    "PDFProcessor",
    "VALID_ESCALATION_POLICIES",
    "compare_call_readings",
    "compute_llm_confidence",
    "count_pdf_pages",
    "has_legal_measurement_signals",
    "is_escalated_subset_truncated",
    "parse_located_pages",
    "preprocess_pdf_pages_for_ocr",
    "render_pdf_pages_to_pngs",
    "select_escalation_outcome",
    "should_escalate_closure",
    "strip_green_watermark_and_crop",
    "tail_note_categories",
    "validate_escalation_policy",
    "validate_pdf_pages",
    "validate_render_dpi",
    "verify_normalization_integrity",
]
