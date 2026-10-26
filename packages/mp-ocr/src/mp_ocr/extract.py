"""PDF processing using pluggable LLM providers for OCR and extraction.

Extracted from the monolith ``metesparser.pdf_processor`` module.
The ``process_deed_pdf`` orchestration method lives in the
top-level orchestrator (see Task 14); this module provides
the LLM-interaction layer: prompt loading, text extraction,
normalisation, confidence scoring, and audit-context
construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import structlog
import yaml  # type: ignore[import-untyped]
from mp_models import LLMStageRecord

from .cache import CachedLLMClient
from .clients import BaseLLMClient, GeminiClient, LLMClientError, OpenAIClient

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level confidence scorer (was PDFProcessor._compute_llm_confidence)
# ---------------------------------------------------------------------------


def compute_llm_confidence(text: str) -> tuple[float, dict[str, bool]]:
    """Score the quality of extracted legal description text.

    Returns ``(confidence, signals)`` where *confidence* is 0.0-1.0
    and *signals* maps signal names to their boolean results.

    Heuristic signals (7 total, weighted):
    - has_pob (+0.20)
    - has_bearing_calls (+0.20)
    - has_closure_language (+0.15)
    - has_distances (+0.15)
    - text_length_reasonable (+0.10)
    - has_plss (+0.10)
    - no_garbled_chars (+0.10)
    """
    has_pob = bool(
        re.search(r"(?:POINT\s+OF\s+BEGINNING|BEGINNING\s+at|POB)\b", text, re.IGNORECASE)
    )

    bearing_matches = re.findall(r"(?:North|South|[NS])\s+\d+\s+degrees?", text, re.IGNORECASE)
    has_bearing_calls = len(bearing_matches) >= 3

    has_closure_language = bool(
        re.search(
            r"(?:POINT\s+OF\s+BEGINNING|place\s+of\s+beginning)\s*(?:[.;]|\s*$)",
            text,
            re.IGNORECASE,
        )
    )

    has_distances = bool(re.search(r"\d+\.\d+\s+(?:feet|ft)", text, re.IGNORECASE))

    text_length_reasonable = 50 < len(text) < 50_000

    has_plss = bool(re.search(r"(?:Section|Township|Range)", text, re.IGNORECASE))

    # Non-ASCII ratio excluding common surveying symbols
    allowed_non_ascii = set("\u00b0\u2032\u2033\u2018\u2019\u201c\u201d\u2013\u2014")
    non_ascii_count = sum(1 for ch in text if ord(ch) > 127 and ch not in allowed_non_ascii)
    total_chars = max(len(text), 1)
    no_garbled_chars = (non_ascii_count / total_chars) < 0.05

    signals: dict[str, bool] = {
        "has_pob": has_pob,
        "has_bearing_calls": has_bearing_calls,
        "has_closure_language": has_closure_language,
        "has_distances": has_distances,
        "text_length_reasonable": text_length_reasonable,
        "has_plss": has_plss,
        "no_garbled_chars": no_garbled_chars,
    }

    weights: dict[str, float] = {
        "has_pob": 0.20,
        "has_bearing_calls": 0.20,
        "has_closure_language": 0.15,
        "has_distances": 0.15,
        "text_length_reasonable": 0.10,
        "has_plss": 0.10,
        "no_garbled_chars": 0.10,
    }

    confidence = sum(weights[k] for k, v in signals.items() if v)
    # Clamp to [0.0, 1.0] to be safe with floating point
    confidence = max(0.0, min(1.0, confidence))

    return confidence, signals


# ---------------------------------------------------------------------------
# Prior-conveyance pattern compilation
# ---------------------------------------------------------------------------

# Lazy import guard: mp_models may not carry PRIOR_CONVEYANCE_SIGNALS on
# every installation, so fall back gracefully.
try:
    from mp_models import PRIOR_CONVEYANCE_SIGNALS as _SIGNALS
except ImportError:  # pragma: no cover
    _SIGNALS: list[str] = []  # type: ignore[no-redef]

_PRIOR_CONVEYANCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(sig, re.IGNORECASE) for sig in _SIGNALS
]


# ---------------------------------------------------------------------------
# PDFProcessor class
# ---------------------------------------------------------------------------


class PDFProcessor:
    """Process PDF deeds and extract legal descriptions via LLM."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        provider: str | None = None,
        client: BaseLLMClient | None = None,
        cache: bool | None = None,
        cache_dir: Path | None = None,
    ):
        """Initialize PDF processor with configurable LLM provider.

        Args:
            api_key: Optional API key override for the chosen provider
            provider: LLM provider name ("openai" or "gemini")
            client: Optional pre-constructed LLM client implementation
            cache: Enable/disable LLM response caching (default: True, env: METESPARSER_LLM_CACHE)
            cache_dir: Directory for cached responses (env: METESPARSER_CACHE_DIR)
        """
        self._configured_api_key = api_key
        self._audit_stage_records: list[LLMStageRecord] | None = None
        self.client = client or self._create_client(provider)
        # Default prompts directory: package-embedded prompts
        self.prompts_dir = Path(__file__).parent / "prompts"

        # Wrap client with caching if enabled
        cache_enabled = (
            cache
            if cache is not None
            else os.getenv("METESPARSER_LLM_CACHE", "true").lower() != "false"
        )
        if cache_enabled:
            resolved_cache_dir = cache_dir or Path(os.getenv("METESPARSER_CACHE_DIR", ".cache/llm"))
            self.client = CachedLLMClient(
                self._unwrap_client(self.client), cache_dir=resolved_cache_dir
            )

    def _load_prompt(self, prompt_name: str) -> dict[str, Any]:
        """Load a prompt from YAML file.

        Args:
            prompt_name: Name of prompt file (without .yaml extension)

        Returns:
            Dict with prompt configuration
        """
        prompt_file = f"{prompt_name}.yaml"
        candidate_paths = [
            self.prompts_dir / prompt_file,
            Path(__file__).parent / "prompts" / prompt_file,
        ]

        prompt_text: str | None = None
        for prompt_path in candidate_paths:
            if prompt_path.exists():
                prompt_text = prompt_path.read_text()
                break

        if prompt_text is None:
            try:
                from importlib import resources

                packaged_prompt = resources.files("mp_ocr").joinpath("prompts", prompt_file)
                if packaged_prompt.is_file():
                    prompt_text = packaged_prompt.read_text()
            except (ModuleNotFoundError, FileNotFoundError):
                prompt_text = None

        if prompt_text is None:
            raise FileNotFoundError(
                f"Prompt file not found for '{prompt_name}' in configured prompt locations"
            )

        prompt_config = yaml.safe_load(prompt_text)

        if not isinstance(prompt_config, dict):
            raise ValueError(f"Prompt file '{prompt_name}' did not contain a mapping")

        return cast(dict[str, Any], prompt_config)

    def extract_text_from_pdf(self, pdf_path: str, *, audit: bool = False) -> str:
        """Extract all text from a PDF using the configured LLM provider."""
        if not audit:
            self._audit_stage_records = None
        if audit and self._audit_stage_records is None:
            self._audit_stage_records = []
        try:
            prompt_config = self._load_prompt("extract_text_from_pdf")
            prompt_text = prompt_config["user_prompt_template"]
            response_mime_type = prompt_config.get("response_mime_type")
            response = self.client.generate_text_with_pdf(
                prompt_text, pdf_path, response_mime_type=response_mime_type
            )
        except Exception:
            if audit:
                self._audit_stage_records = None
            raise
        self._record_llm_stage("extract_text_from_pdf", prompt_text, response)
        return response

    def extract_legal_description(self, pdf_path: str, *, audit: bool = False) -> str:
        """Extract legal description from a deed PDF."""
        try:
            self._audit_stage_records = [] if audit else None
            document_text = (
                self.extract_text_from_pdf(pdf_path, audit=True)
                if audit
                else self.extract_text_from_pdf(pdf_path)
            )
            prompt_config = self._load_prompt("extract_legal_description")
            user_prompt = prompt_config["user_prompt_template"].replace(
                "{document_text}", document_text
            )
            combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"
            response = self.client.generate_text(combined_prompt)
        except Exception:
            self._audit_stage_records = None
            raise
        self._record_llm_stage("extract_legal_description", combined_prompt, response)
        return response

    def normalize_legal_description(self, legal_desc_text: str, *, audit: bool = False) -> str:
        """Normalize and clean up legal description text."""
        if not audit:
            self._audit_stage_records = None
        elif self._audit_stage_records is None:
            self._audit_stage_records = []

        try:
            prompt_config = self._load_prompt("normalize_text")
            user_prompt = prompt_config["user_prompt_template"].replace(
                "{legal_description_text}", legal_desc_text
            )
            combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"
            response = self.client.generate_text(combined_prompt)
        except Exception:
            if audit:
                self._audit_stage_records = None
            raise
        self._record_llm_stage("normalize_text", combined_prompt, response)
        return response

    def _record_llm_stage(self, stage: str, prompt: str, response: str) -> None:
        """Capture provenance only while an audited caller has enabled collection."""
        if self._audit_stage_records is None:
            return
        inner = self._unwrap_client(self.client)
        provider = (
            "openai"
            if isinstance(inner, OpenAIClient)
            else "gemini"
            if isinstance(inner, GeminiClient)
            else "unknown"
        )
        model = getattr(inner, "model", None)
        self._audit_stage_records.append(
            LLMStageRecord(
                stage=stage,
                prompt=prompt,
                prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
                response=response,
                response_sha256=sha256(response.encode("utf-8")).hexdigest(),
                provider=provider,
                model=model if isinstance(model, str) else "unknown",
            )
        )

    def extract_calls_ai(self, legal_desc_text: str) -> list[dict[str, Any]]:
        """Extract calls using the configured LLM (experimental)."""
        prompt_config = self._load_prompt("extract_calls")

        user_prompt = prompt_config["user_prompt_template"].replace(
            "{legal_description_text}", legal_desc_text
        )
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"

        raw_response = self.client.generate_text(
            combined_prompt, response_mime_type="application/json"
        )

        try:
            result = json.loads(raw_response or "{}")
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError("LLM returned invalid JSON when extracting calls") from exc

        if not isinstance(result, dict):
            raise ValueError("LLM returned a non-object JSON payload for calls extraction")

        calls = result.get("calls", [])
        if not isinstance(calls, list):
            raise ValueError("LLM returned malformed calls payload (expected list)")

        return cast(list[dict[str, Any]], calls)

    # -- Audit helpers ----------------------------------------------------------

    def _build_audit_context(
        self,
        *,
        pdf_path: str,
        legal_desc_text: str,
        normalized_text: str,
        distance_unit: str,
        parser_version: str = "unknown",
    ) -> Any:
        """Build an ``AuditContext`` populated with run metadata and extraction record.

        Args:
            pdf_path: Path to the source PDF.
            legal_desc_text: Raw LLM-extracted legal description text.
            normalized_text: Normalised legal description text.
            distance_unit: Resolved distance unit string.
            parser_version: Caller-provided version string (e.g. ``metesparser.__version__``).
        """
        from mp_models import AuditContext, ExtractionRecord, RunMetadata

        inner = self._unwrap_client(self.client)
        if isinstance(inner, OpenAIClient):
            llm_provider = "openai"
        elif isinstance(inner, GeminiClient):
            llm_provider = "gemini"
        else:
            llm_provider = "unknown"

        llm_model = self._get_model_name()
        prompt_hash = self._compute_prompt_hash("normalize_text")
        log_level = os.getenv("LOG_LEVEL", "INFO")

        run_metadata = RunMetadata(
            parser_version=parser_version,
            llm_provider=llm_provider,
            llm_model=llm_model,
            prompt_hash=prompt_hash,
            timestamp_utc=datetime.now(UTC),
            source_pdf=Path(pdf_path).name,
            cache_enabled=isinstance(self.client, CachedLLMClient),
            config={
                "closure_tolerance_ft": 0.01,
                "distance_unit": distance_unit,
                "log_level": log_level,
            },
        )

        ctx = AuditContext(run_metadata=run_metadata)

        llm_confidence, confidence_signals = compute_llm_confidence(normalized_text)

        ctx.extraction_record = ExtractionRecord(
            raw_llm_response=legal_desc_text,
            normalized_text=normalized_text,
            llm_confidence=llm_confidence,
            confidence_signals=confidence_signals,
            llm_stages=list(self._audit_stage_records or []),
        )
        self._audit_stage_records = None

        return ctx

    def _get_model_name(self) -> str:
        """Return the LLM model name from the underlying client."""
        inner = self._unwrap_client(self.client)
        model: object = getattr(inner, "model", None)
        if isinstance(model, str):
            return model
        return "unknown"

    def _compute_prompt_hash(self, prompt_name: str) -> str:
        """Return SHA-256 hex digest of a prompt template's content."""
        try:
            prompt_config = self._load_prompt(prompt_name)
            content = yaml.dump(prompt_config, sort_keys=True)
            return hashlib.sha256(content.encode()).hexdigest()
        except FileNotFoundError:
            return "unknown"

    @staticmethod
    def _unwrap_client(client: BaseLLMClient) -> BaseLLMClient:
        """Unwrap an already-cached client to avoid double-wrapping."""
        if isinstance(client, CachedLLMClient):
            return client._client
        return client

    def _create_client(self, provider: str | None) -> BaseLLMClient:
        provider_name = (provider or os.getenv("METESPARSER_LLM_PROVIDER") or "openai").lower()

        try:
            if provider_name == "openai":
                return OpenAIClient(api_key=self._configured_api_key)
            if provider_name == "gemini":
                return GeminiClient(api_key=self._configured_api_key)
        except LLMClientError as exc:
            raise ValueError(str(exc)) from exc

        raise ValueError(
            f"Unsupported LLM provider '{provider_name}'. Choose from: openai, gemini."
        )

    def check_prior_conveyance(self, text: str) -> list[str]:
        """Return matched prior conveyance patterns in the given text."""
        return [p.pattern for p in _PRIOR_CONVEYANCE_PATTERNS if p.search(text)]
