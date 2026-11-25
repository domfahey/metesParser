"""PDF processing using pluggable LLM providers for OCR and extraction."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any, cast

import structlog
import yaml  # type: ignore[import-untyped]

from .llm_cache import CachedLLMClient
from .llm_clients import BaseLLMClient, GeminiClient, LLMClientError, OpenAIClient
from .models import (
    PRIOR_CONVEYANCE_SIGNALS,
    AuditContext,
    ConversionFactors,
    DistanceUnit,
    ExtractionRecord,
    LegalDescription,
    LLMStageRecord,
    RunMetadata,
    Tract,
    TractType,
)

logger = structlog.get_logger(__name__)

_PRIOR_CONVEYANCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(signal, re.IGNORECASE) for signal in sorted(PRIOR_CONVEYANCE_SIGNALS)
]

_POB_RE = re.compile(r"(?:POINT\s+OF\s+BEGINNING|BEGINNING\s+at|POB)\b", re.IGNORECASE)
_BEARING_CALL_RE = re.compile(
    r"\b(?:North|South|[NS])\.?\s*\d+(?:\.\d+)?\s*(?:°|degrees?\b|deg\.?)",
    re.IGNORECASE,
)
_CLOSURE_RE = re.compile(
    r"(?:POINT\s+OF\s+BEGINNING|place\s+of\s+beginning)\s*(?:[.;]|\s*$)",
    re.IGNORECASE,
)
_DISTANCE_RE = re.compile(
    r"\b\d+(?:,\d{3})*(?:\.\d+)?\s+"
    r"(?:feet|foot|ft|poles?|rods?|perch(?:es)?|chains?|links?|varas?|arpents?|toises?|furlongs?|meters?|miles?)\b",
    re.IGNORECASE,
)
_PLSS_RE = re.compile(
    r"\b(?:Section|Township|Range)\b|\bT\.?\s*\d+\s*[NS]\b|\bR\.?\s*\d+\s*[EW]\b",
    re.IGNORECASE,
)
_ALLOWED_NON_ASCII = frozenset("\u00b0\u2032\u2033\u2018\u2019\u201c\u201d\u2013\u2014")
_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "has_pob": 0.20,
    "has_bearing_calls": 0.20,
    "has_closure_language": 0.15,
    "has_distances": 0.15,
    "text_length_reasonable": 0.10,
    "has_plss": 0.10,
    "no_garbled_chars": 0.10,
}


class PDFProcessor:
    """Process PDF deeds and extract legal descriptions."""

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
        self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"

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
        candidate_paths = list(
            dict.fromkeys(
                [
                    self.prompts_dir / prompt_file,
                    Path(__file__).parent / "prompts" / prompt_file,
                    Path(__file__).parent.parent.parent / "prompts" / prompt_file,
                ]
            )
        )

        prompt_text: str | None = None
        for prompt_path in candidate_paths:
            if prompt_path.exists():
                prompt_text = prompt_path.read_text(encoding="utf-8")
                break

        if prompt_text is None:
            try:
                packaged_prompt = resources.files("metesparser").joinpath("prompts", prompt_file)
                if packaged_prompt.is_file():
                    prompt_text = packaged_prompt.read_text(encoding="utf-8")
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

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract all text from a PDF using the configured LLM provider."""
        prompt_config = self._load_prompt("extract_text_from_pdf")
        system_prompt = prompt_config.get("system_prompt")
        user_prompt = prompt_config["user_prompt_template"]
        prompt_text = (
            f"{system_prompt.strip()}\n\n{user_prompt}"
            if isinstance(system_prompt, str) and system_prompt.strip()
            else user_prompt
        )
        response_mime_type = prompt_config.get("response_mime_type")
        response = self.client.generate_text_with_pdf(
            prompt_text, pdf_path, response_mime_type=response_mime_type
        )
        self._record_llm_stage("extract_text_from_pdf", prompt_text, response)
        return response

    def extract_legal_description(self, pdf_path: str) -> str:
        """Extract legal description from a deed PDF."""
        document_text = self.extract_text_from_pdf(pdf_path)
        prompt_config = self._load_prompt("extract_legal_description")

        user_prompt = prompt_config["user_prompt_template"].replace(
            "{document_text}", document_text
        )
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"
        response = self.client.generate_text(combined_prompt)
        self._record_llm_stage("extract_legal_description", combined_prompt, response)
        return response

    def normalize_legal_description(self, legal_desc_text: str) -> str:
        """Normalize and clean up legal description text."""
        prompt_config = self._load_prompt("normalize_text")

        user_prompt = prompt_config["user_prompt_template"].replace(
            "{legal_description_text}", legal_desc_text
        )
        combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"

        response = self.client.generate_text(combined_prompt)
        self._record_llm_stage("normalize_text", combined_prompt, response)
        return response

    def _record_llm_stage(self, stage: str, prompt: str, response: str) -> None:
        """Capture rendered LLM evidence only during an audited pipeline run."""
        if self._audit_stage_records is None:
            return
        inner = self._unwrap_client(self.client)
        if isinstance(inner, OpenAIClient):
            provider = "openai"
        elif isinstance(inner, GeminiClient):
            provider = "gemini"
        else:
            provider = "unknown"
        model = getattr(inner, "model", None)
        self._audit_stage_records.append(
            LLMStageRecord(
                stage=stage,
                prompt=prompt,
                prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                response=response,
                response_sha256=hashlib.sha256(response.encode("utf-8")).hexdigest(),
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

    def process_deed_pdf(
        self, pdf_path: str, *, audit: bool = False
    ) -> LegalDescription | tuple[LegalDescription, AuditContext]:
        """Process a deed PDF and return structured LegalDescription.

        Args:
            pdf_path: Path to the deed PDF file.
            audit: When True, return ``(LegalDescription, AuditContext)``
                with full pipeline provenance.  Defaults to False (returns
                ``LegalDescription`` only, preserving existing behaviour).
        """
        from .call_extractor import CallExtractor
        from .text_parser import TextParser

        processing_logger = logger.bind(pdf_path=pdf_path)

        self._audit_stage_records = [] if audit else None
        try:
            processing_logger.info("Extracting legal description from PDF")
            legal_desc_text = self.extract_legal_description(pdf_path)

            matched = [p.pattern for p in _PRIOR_CONVEYANCE_PATTERNS if p.search(legal_desc_text)]
            if matched:
                processing_logger.warning(
                    "Extracted text may contain prior conveyance language",
                    matched_patterns=matched,
                )

            processing_logger.info("Normalizing text")
            normalized_text = self.normalize_legal_description(legal_desc_text)
            llm_stage_records = list(self._audit_stage_records or [])
        finally:
            self._audit_stage_records = None

        processing_logger.info("Extracting PLSS metadata")
        plss_data = TextParser.extract_plss_metadata(normalized_text)

        processing_logger.info("Extracting Point of Commencement and Point of Beginning")
        poc, pob = TextParser.extract_poc_and_pob(normalized_text)

        processing_logger.info("Extracting area statement")
        stated_area = TextParser.extract_area_statement(normalized_text)

        processing_logger.info("Inferring distance unit")
        inferred_unit = TextParser.infer_distance_unit(normalized_text)
        distance_unit: DistanceUnit = "feet"
        if inferred_unit is not None:
            try:
                ConversionFactors.convert_to_feet(1.0, inferred_unit)
                distance_unit = cast(DistanceUnit, inferred_unit)
            except ValueError:
                processing_logger.warning(
                    "Unsupported inferred distance unit; defaulting to feet",
                    inferred_unit=inferred_unit,
                )
        processing_logger.info("Distance unit resolved", distance_unit=distance_unit)

        # -- Build audit context early so it can be threaded through pipeline --
        ctx: AuditContext | None = None
        if audit:
            ctx = self._build_audit_context(
                pdf_path=pdf_path,
                legal_desc_text=legal_desc_text,
                normalized_text=normalized_text,
                distance_unit=distance_unit,
                llm_stages=llm_stage_records,
            )

        from mp_parse.tracts import split_into_tracts

        processing_logger.info("Extracting calls")
        segments = split_into_tracts(normalized_text)
        tracts: list[Tract] = []

        if len(segments) == 1 and segments[0][2].value == TractType.MAIN.value:
            calls = CallExtractor.extract_calls(
                normalized_text, distance_unit=distance_unit, audit_context=ctx
            )

            calls = CallExtractor.enrich_calls_with_azimuths(calls)

            processing_logger.info("Marking tie-in calls")
            calls = CallExtractor.mark_tie_in_calls(calls, poc_description=poc if poc else None)
        else:
            built_tracts: list[Tract] = []
            for segment_text, label, seg_type in segments:
                tract_type = TractType(seg_type.value)
                seg_calls = CallExtractor.extract_calls(
                    segment_text, distance_unit=distance_unit, audit_context=ctx
                )
                if not seg_calls:
                    processing_logger.warning(
                        "Empty tract after extraction - segment dropped",
                        tract_label=label,
                        tract_type=tract_type.value,
                    )
                    continue

                seg_calls = CallExtractor.enrich_calls_with_azimuths(seg_calls)
                seg_poc, seg_pob = TextParser.extract_poc_and_pob(segment_text)
                seg_calls = CallExtractor.mark_tie_in_calls(
                    seg_calls, poc_description=seg_poc if seg_poc else None
                )
                if tract_type == TractType.EXCEPTION:
                    seg_calls = [c.model_copy(update={"is_exception": True}) for c in seg_calls]

                seg_area = TextParser.extract_area_statement(segment_text)
                built_tracts.append(
                    Tract(
                        label=label,
                        tract_type=tract_type,
                        calls=seg_calls,
                        pob_description=seg_pob or None,
                        stated_area_sq_ft=seg_area["value_sq_ft"] if seg_area else None,
                    )
                )

            if len(built_tracts) > 1 or (
                len(built_tracts) == 1 and built_tracts[0].tract_type != TractType.MAIN
            ):
                tracts = built_tracts
                calls = [c for t in tracts for c in t.calls]
            elif len(built_tracts) == 1:
                calls = list(built_tracts[0].calls)
            else:
                calls = []

        processing_logger.info("Extracting deed clauses")
        clauses = TextParser.extract_deed_clauses(normalized_text)

        processing_logger.info("Extracting subdivision reference")
        subdivision_ref = TextParser.extract_subdivision_reference(normalized_text)

        processing_logger.info("Extracting witness trees")
        witness_trees = TextParser.extract_witness_trees(normalized_text)

        processing_logger.info("Extracting coordinate system")
        coordinate_system, fips_code = TextParser.extract_coordinate_system(normalized_text)

        legal_desc = LegalDescription(
            poc_description=poc or None,
            pob_description=pob or None,
            calls=calls,
            tracts=tracts,
            source_doc=Path(pdf_path).name,
            exhibit=None,
            page=None,
            survey_date=None,
            basis_of_bearing=TextParser.extract_basis_of_bearing(normalized_text),
            datum=None,
            distance_unit=distance_unit,
            section=plss_data.get("section"),
            township=plss_data.get("township"),
            range=plss_data.get("range"),
            principal_meridian=plss_data.get("principal_meridian"),
            aliquot=plss_data.get("aliquot"),
            surveyor_certification=TextParser.extract_surveyor_certification(normalized_text),
            prior_conveyance=TextParser.extract_prior_conveyance(normalized_text),
            clauses=clauses,
            subdivision_ref=subdivision_ref,
            witness_trees=witness_trees,
            coordinate_system=coordinate_system,
            fips_code=fips_code,
            stated_area_sq_ft=stated_area["value_sq_ft"] if stated_area else None,
            stated_area_approximate=stated_area["approximate"] if stated_area else False,
        )

        processing_logger.info("Extracted calls", count=legal_desc.num_calls())

        if not audit:
            return legal_desc

        assert ctx is not None  # guaranteed when audit=True
        return legal_desc, ctx

    # -- Audit helpers ----------------------------------------------------------

    def _build_audit_context(
        self,
        *,
        pdf_path: str,
        legal_desc_text: str,
        normalized_text: str,
        distance_unit: DistanceUnit,
        llm_stages: list[LLMStageRecord] | None = None,
    ) -> AuditContext:
        """Build an ``AuditContext`` populated with run metadata and extraction record."""
        import metesparser

        # Determine LLM provider name from client type
        inner = self._unwrap_client(self.client)
        if isinstance(inner, OpenAIClient):
            llm_provider = "openai"
        elif isinstance(inner, GeminiClient):
            llm_provider = "gemini"
        else:
            llm_provider = "unknown"

        llm_model = self._get_model_name()

        # Compute prompt hash from normalize_text prompt template content
        prompt_hash = self._compute_prompt_hash("normalize_text")

        log_level = os.getenv("METESPARSER_LOG_LEVEL", "INFO")

        run_metadata = RunMetadata(
            parser_version=metesparser.__version__,
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

        # Compute LLM confidence on the normalized text
        llm_confidence, confidence_signals = self._compute_llm_confidence(normalized_text)

        ctx.extraction_record = ExtractionRecord(
            raw_llm_response=legal_desc_text,
            normalized_text=normalized_text,
            llm_confidence=llm_confidence,
            confidence_signals=confidence_signals,
            llm_stages=llm_stages or [],
        )

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
    def _compute_llm_confidence(text: str) -> tuple[float, dict[str, bool]]:
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
        has_pob = bool(_POB_RE.search(text))
        has_bearing_calls = len(_BEARING_CALL_RE.findall(text)) >= 3
        has_closure_language = bool(_CLOSURE_RE.search(text))
        has_distances = bool(_DISTANCE_RE.search(text))
        text_length_reasonable = 50 < len(text) < 50_000
        has_plss = bool(_PLSS_RE.search(text))

        # Non-ASCII ratio excluding common surveying symbols
        non_ascii_count = sum(1 for ch in text if ord(ch) > 127 and ch not in _ALLOWED_NON_ASCII)
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

        confidence = sum(_CONFIDENCE_WEIGHTS[k] for k, v in signals.items() if v)
        # Clamp to [0.0, 1.0] to be safe with floating point
        confidence = max(0.0, min(1.0, confidence))

        return confidence, signals

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
