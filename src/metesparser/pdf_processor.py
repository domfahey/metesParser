"""PDF processing using pluggable LLM providers for OCR and extraction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any, cast

import structlog
import yaml

from .llm_clients import (
    BaseLLMClient,
    GeminiClient,
    LLMClientError,
    OpenAIClient,
    OpenRouterClient,
)
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
    stated_areas_match,
)

logger = structlog.get_logger(__name__)


_PRIOR_CONVEYANCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(signal, re.IGNORECASE) for signal in PRIOR_CONVEYANCE_SIGNALS
]


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
            provider: LLM provider name ("openai", "gemini", or "openrouter")
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
            from .llm_cache import CachedLLMClient

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
            Path(__file__).parent.parent / "prompts" / prompt_file,
            Path(__file__).parent.parent.parent / "prompts" / prompt_file,
        ]

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
            f"{system_prompt}\n\n{user_prompt}"
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
        from mp_ocr import verify_normalization_integrity

        ok, reasons = verify_normalization_integrity(legal_desc_text, response)
        if not ok:
            logger.warning(
                "Stage 3 normalization failed measurement integrity check; "
                "preserving Stage 2 legal description text",
                reasons=reasons,
            )
            return legal_desc_text
        return response

    def _generate_text_with_images(
        self,
        prompt: str,
        image_paths: Sequence[str | Path],
        *,
        response_mime_type: str | None = None,
    ) -> str:
        image_method = getattr(self.client, "generate_text_with_images", None)
        if not callable(image_method):
            raise NotImplementedError(
                f"{type(self.client).__name__} does not support generate_text_with_images"
            )
        return cast(
            str,
            image_method(prompt, image_paths, response_mime_type=response_mime_type),
        )

    def locate_legal_description_pages(
        self,
        pdf_path: str,
        *,
        thumbnail_dpi: int = 100,
        thumbnail_max_dim: int = 900,
        max_pages_per_batch: int = 16,
        audit: bool = False,
    ) -> list[int]:
        """Identify 1-based page numbers in *pdf_path* containing legal descriptions."""
        from mp_ocr import count_pdf_pages, parse_located_pages, preprocess_pdf_pages_for_ocr

        total_pages = count_pdf_pages(pdf_path)
        if total_pages == 0:
            raise ValueError(f"PDF has no pages: {pdf_path}")

        self._audit_stage_records = [] if audit else None
        if total_pages <= 2:
            return list(range(1, total_pages + 1))

        batch_size = max(1, int(max_pages_per_batch))
        prompt_config = self._load_prompt("locate_legal_pages")
        system_prompt = prompt_config.get("system_prompt")
        response_mime_type = prompt_config.get("response_mime_type")

        try:
            located: list[int] = []
            with tempfile.TemporaryDirectory(prefix="mp_ocr_locate_") as tmpdir:
                thumbs = preprocess_pdf_pages_for_ocr(
                    pdf_path,
                    Path(tmpdir),
                    dpi=thumbnail_dpi,
                    strip_watermark=False,
                    crop_margins=False,
                    max_dim=thumbnail_max_dim,
                )
                for batch_start in range(0, len(thumbs), batch_size):
                    batch = thumbs[batch_start : batch_start + batch_size]
                    batch_len = (
                        total_pages
                        if batch_start == 0 and total_pages <= batch_size
                        else len(batch)
                    )
                    user_prompt = prompt_config["user_prompt_template"].replace(
                        "{total_pages}", str(batch_len)
                    )
                    combined_prompt = (
                        f"{system_prompt}\n\n{user_prompt}"
                        if isinstance(system_prompt, str) and system_prompt.strip()
                        else user_prompt
                    )
                    response = self._generate_text_with_images(
                        combined_prompt, batch, response_mime_type=response_mime_type
                    )
                    if audit:
                        self._record_llm_stage("locate_legal_pages", combined_prompt, response)
                    local_pages = parse_located_pages(response, batch_len, allow_empty=True)
                    located.extend(batch_start + p for p in local_pages)
        except Exception:
            if audit:
                self._audit_stage_records = None
            raise

        deduped = sorted(dict.fromkeys(located))
        if not deduped:
            logger.warning(
                "locate_legal_pages returned no pages across all batches; falling back to all pages",
                total_pages=total_pages,
            )
            return list(range(1, total_pages + 1))
        return deduped

    def extract_text_from_images(
        self,
        image_paths: Sequence[str | Path],
        *,
        audit: bool = False,
        stage_name: str = "extract_text_from_images",
        max_images_per_call: int = 16,
    ) -> str:
        """Extract all text from preprocessed deed page images using Stage 1 prompt."""
        if not audit:
            self._audit_stage_records = None
        elif self._audit_stage_records is None:
            self._audit_stage_records = []

        prompt_config = self._load_prompt("extract_text_from_pdf")
        system_prompt = prompt_config.get("system_prompt")
        user_prompt = prompt_config["user_prompt_template"]
        prompt_text = (
            f"{system_prompt}\n\n{user_prompt}"
            if isinstance(system_prompt, str) and system_prompt.strip()
            else user_prompt
        )
        response_mime_type = prompt_config.get("response_mime_type")
        items = list(image_paths)
        batch_size = max(1, int(max_images_per_call))

        try:
            if len(items) <= batch_size:
                response = self._generate_text_with_images(
                    prompt_text, items, response_mime_type=response_mime_type
                )
                if audit:
                    self._record_llm_stage(stage_name, prompt_text, response)
                return response

            chunks: list[str] = []
            for start in range(0, len(items), batch_size):
                batch = items[start : start + batch_size]
                chunk = self._generate_text_with_images(
                    prompt_text, batch, response_mime_type=response_mime_type
                )
                if audit:
                    self._record_llm_stage(stage_name, prompt_text, chunk)
                if chunk:
                    chunks.append(chunk)
            return "\n\n".join(chunks)
        except Exception:
            if audit:
                self._audit_stage_records = None
            raise

    def pop_audit_stage_records(self) -> list[LLMStageRecord]:
        """Return and clear collected audit stage records on this processor."""
        stages = list(self._audit_stage_records or [])
        self._audit_stage_records = None
        return stages

    def extract_legal_description_from_images(
        self,
        pdf_path: str,
        *,
        pages: Sequence[int] | None = None,
        dpi: int = 300,
        strip_watermark: bool = True,
        crop_margins: bool = True,
        max_dim: int = 2200,
        audit: bool = False,
        stage_prefix: str = "escalation_",
        locator_processor: PDFProcessor | None = None,
    ) -> tuple[str, str, list[int]]:
        """Run a blind 3-stage extraction on preprocessed high-DPI legal-page PNGs.

        Returns ``(legal_desc_text, normalized_text, resolved_pages)``. When
        ``audit=True``, call :meth:`pop_audit_stage_records` to retrieve the
        collected stage records.
        """
        from mp_ocr import (
            count_pdf_pages,
            has_legal_measurement_signals,
            preprocess_pdf_pages_for_ocr,
            validate_pdf_pages,
            verify_normalization_integrity,
        )

        collected_stages: list[LLMStageRecord] | None = [] if audit else None
        self._audit_stage_records = None

        try:
            total_pages = count_pdf_pages(pdf_path)
            if total_pages == 0:
                raise ValueError(f"PDF has no pages: {pdf_path}")

            if pages is not None:
                resolved_pages = validate_pdf_pages(pages, total_pages)
            else:
                locator = locator_processor or self
                prev_locator_records = locator._audit_stage_records
                try:
                    resolved_pages = locator.locate_legal_description_pages(pdf_path, audit=audit)
                    if audit and collected_stages is not None and locator._audit_stage_records:
                        collected_stages.extend(locator._audit_stage_records)
                finally:
                    locator._audit_stage_records = prev_locator_records

            self._audit_stage_records = collected_stages

            with tempfile.TemporaryDirectory(prefix="mp_ocr_escalate_") as tmpdir:
                rendered_by_page: dict[int, Path] = {}

                def _get_page_pngs(target_pages: list[int]) -> list[Path]:
                    missing = [p for p in target_pages if p not in rendered_by_page]
                    if missing:
                        new_pngs = preprocess_pdf_pages_for_ocr(
                            pdf_path,
                            Path(tmpdir),
                            pages=missing,
                            dpi=dpi,
                            strip_watermark=strip_watermark,
                            crop_margins=crop_margins,
                            max_dim=max_dim,
                        )
                        if len(new_pngs) == len(missing):
                            for page_num, png_path in zip(missing, new_pngs, strict=True):
                                rendered_by_page[page_num] = png_path
                        else:
                            return new_pngs
                    return [rendered_by_page[p] for p in target_pages]

                def _run_on_pages(
                    target_pages: list[int],
                    prefix: str,
                    *,
                    skip_norm_if_no_signals: bool = False,
                ) -> tuple[str, str]:
                    clean_pngs = _get_page_pngs(target_pages)
                    raw_text = self.extract_text_from_images(
                        clean_pngs,
                        audit=audit,
                        stage_name=f"{prefix}extract_text_from_images",
                    )

                    s2_config = self._load_prompt("extract_legal_description")
                    s2_user = s2_config["user_prompt_template"].replace("{document_text}", raw_text)
                    s2_prompt = f"{s2_config['system_prompt']}\n\n{s2_user}"
                    legal_text = self.client.generate_text(s2_prompt)
                    if audit:
                        self._record_llm_stage(
                            f"{prefix}extract_legal_description", s2_prompt, legal_text
                        )

                    if skip_norm_if_no_signals and not has_legal_measurement_signals(legal_text):
                        return legal_text, legal_text

                    s3_config = self._load_prompt("normalize_text")
                    s3_user = s3_config["user_prompt_template"].replace(
                        "{legal_description_text}", legal_text
                    )
                    s3_prompt = f"{s3_config['system_prompt']}\n\n{s3_user}"
                    raw_norm = self.client.generate_text(s3_prompt)
                    if audit:
                        self._record_llm_stage(f"{prefix}normalize_text", s3_prompt, raw_norm)

                    ok, reasons = verify_normalization_integrity(legal_text, raw_norm)
                    if not ok:
                        logger.warning(
                            "Escalation Stage 3 normalization failed measurement integrity check; "
                            "preserving Stage 2 legal description text",
                            reasons=reasons,
                        )
                        return legal_text, legal_text
                    return legal_text, raw_norm

                can_fallback = pages is None and len(resolved_pages) < total_pages
                legal_desc_text, normalized_text = _run_on_pages(
                    resolved_pages,
                    stage_prefix,
                    skip_norm_if_no_signals=can_fallback,
                )
                if can_fallback and not has_legal_measurement_signals(legal_desc_text):
                    all_pages = list(range(1, total_pages + 1))
                    logger.warning(
                        "Escalation on located pages produced no legal measurements; "
                        "retrying across all PDF pages",
                        located_pages=resolved_pages,
                        total_pages=total_pages,
                    )
                    legal_desc_text, normalized_text = _run_on_pages(
                        all_pages, f"{stage_prefix}fallback_"
                    )
                    resolved_pages = all_pages
        except Exception:
            if audit:
                self._audit_stage_records = None
            raise

        return legal_desc_text, normalized_text, resolved_pages

    def _record_llm_stage(self, stage: str, prompt: str, response: str) -> None:
        """Capture rendered LLM evidence only during an audited pipeline run."""
        if self._audit_stage_records is None:
            return
        inner = self._unwrap_client(self.client)
        if isinstance(inner, OpenAIClient):
            provider = "openai"
        elif isinstance(inner, GeminiClient):
            provider = "gemini"
        elif isinstance(inner, OpenRouterClient):
            provider = "openrouter"
        else:
            provider = "unknown"
        model = self._get_model_name()
        self._audit_stage_records.append(
            LLMStageRecord(
                stage=stage,
                prompt=prompt,
                prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                response=response,
                response_sha256=hashlib.sha256(response.encode("utf-8")).hexdigest(),
                provider=provider,
                model=model,
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
        processing_logger = logger.bind(pdf_path=pdf_path)

        self._audit_stage_records = [] if audit else None
        try:
            processing_logger.info("Extracting legal description from PDF")
            legal_desc_text = self.extract_legal_description(pdf_path)

            processing_logger.info("Normalizing text")
            normalized_text = self.normalize_legal_description(legal_desc_text)
            llm_stage_records = list(self._audit_stage_records or [])
        finally:
            self._audit_stage_records = None

        return self.process_legal_text(
            pdf_path,
            legal_desc_text=legal_desc_text,
            normalized_text=normalized_text,
            llm_stage_records=llm_stage_records,
            audit=audit,
        )

    def process_legal_text(
        self,
        pdf_path: str,
        *,
        legal_desc_text: str,
        normalized_text: str,
        llm_stage_records: list[LLMStageRecord] | None = None,
        audit: bool = False,
    ) -> LegalDescription | tuple[LegalDescription, AuditContext]:
        """Parse already-extracted legal description text into structured output."""
        from .call_extractor import CallExtractor
        from .text_parser import TextParser

        processing_logger = logger.bind(pdf_path=pdf_path)

        matched = [p.pattern for p in _PRIOR_CONVEYANCE_PATTERNS if p.search(legal_desc_text)]
        if matched:
            processing_logger.warning(
                "Extracted text may contain prior conveyance language",
                matched_patterns=matched,
            )

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

        from mp_models import invalid_stated_area_notes, is_boundary_tract

        processing_logger.info("Extracting calls")
        # One extraction gives the flat calls and the tracts (with role bases) the
        # role gate reads (``mp_models.roles_need_review``); a blocked deed's flat
        # calls carry the role-review mark, so they never verify on their own.
        tracts: list[Tract] = []
        calls = CallExtractor.extract_calls(
            normalized_text, distance_unit=distance_unit, audit_context=ctx, tracts=tracts
        )

        processing_logger.info("Marking tie-in calls")
        legal_poc_description: str | None
        if tracts:
            tracts = [
                tract.model_copy(
                    update={"calls": CallExtractor.enrich_calls_with_azimuths(tract.calls)}
                )
                for tract in tracts
            ]
            if (
                len(tracts) == 1
                and tracts[0].poc_description is None
                and poc
                and not tracts[0].skipped_courses
            ):
                marked = CallExtractor.mark_tie_in_calls(tracts[0].calls, poc_description=poc)
                if marked and not all(c.is_tie_in for c in marked):
                    tracts[0] = tracts[0].model_copy(update={"calls": marked})
            non_empty_boundary = [
                tract for tract in tracts if is_boundary_tract(tract.tract_type) and tract.calls
            ]
            if non_empty_boundary:
                active_tracts = [
                    tract for tract in tracts if tract.tract_type != TractType.EASEMENT
                ]
                calls = [call for tract in active_tracts for call in tract.calls]
            else:
                active_tracts = tracts
                calls = [call for tract in tracts for call in tract.calls]
            legal_poc_description = next(
                (tract.poc_description for tract in active_tracts if tract.poc_description),
                None,
            )
            if (
                legal_poc_description is None
                and len(tracts) == 1
                and tracts[0].poc_description is None
            ):
                legal_poc_description = poc or None
        else:
            calls = CallExtractor.enrich_calls_with_azimuths(calls)
            calls = CallExtractor.mark_tie_in_calls(calls, poc_description=poc if poc else None)
            legal_poc_description = poc or None

        area_notes = list(
            dict.fromkeys(
                detail
                for call in (*calls, *(c for tract in tracts for c in tract.calls))
                for detail in invalid_stated_area_notes(call.notes)
            )
        )
        has_invalid_stated_area = bool(area_notes) or (
            not calls
            and not any(tract.calls for tract in tracts)
            and stated_area is not None
            and stated_area["value_sq_ft"] <= 0
        )
        if has_invalid_stated_area:
            processing_logger.warning(
                "Ignoring non-positive stated area",
                stated_area_sq_ft=(
                    stated_area["value_sq_ft"]
                    if stated_area is not None and stated_area["value_sq_ft"] <= 0
                    else area_notes
                ),
            )
            if ctx is not None and ctx.extraction_record is not None:
                ctx.extraction_record = ctx.extraction_record.model_copy(
                    update={
                        "confidence_signals": {
                            **ctx.extraction_record.confidence_signals,
                            "valid_stated_area": False,
                        }
                    }
                )

        processing_logger.info("Extracting deed clauses")
        clauses = TextParser.extract_deed_clauses(normalized_text)

        processing_logger.info("Extracting subdivision reference")
        subdivision_ref = TextParser.extract_subdivision_reference(normalized_text)

        processing_logger.info("Extracting witness trees")
        witness_trees = TextParser.extract_witness_trees(normalized_text)

        processing_logger.info("Extracting coordinate system")
        coordinate_system, fips_code = TextParser.extract_coordinate_system(normalized_text)

        valid_stated_area = stated_area if stated_area and stated_area["value_sq_ft"] > 0 else None
        boundary_tracts = [tract for tract in tracts if is_boundary_tract(tract.tract_type)]
        legal_stated_area_sq_ft: float | None
        if tracts:
            boundary_area = (
                boundary_tracts[0].stated_area_sq_ft
                if len(boundary_tracts) == 1
                and not any(invalid_stated_area_notes(c.notes) for c in boundary_tracts[0].calls)
                else None
            )
            if boundary_area is not None:
                legal_stated_area_sq_ft = boundary_area
                legal_stated_area_approx = (
                    bool(valid_stated_area["approximate"])
                    if valid_stated_area is not None
                    and stated_areas_match(valid_stated_area["value_sq_ft"], boundary_area)
                    else False
                )
            else:
                legal_stated_area_sq_ft = None
                legal_stated_area_approx = False
        else:
            legal_stated_area_sq_ft = (
                valid_stated_area["value_sq_ft"] if valid_stated_area else None
            )
            legal_stated_area_approx = (
                bool(valid_stated_area["approximate"]) if valid_stated_area else False
            )

        legal_desc = LegalDescription(
            poc_description=legal_poc_description,
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
            stated_area_sq_ft=legal_stated_area_sq_ft,
            stated_area_approximate=legal_stated_area_approx,
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
        import metesparser  # noqa: PLW0406 – local import to read __version__

        from .llm_cache import CachedLLMClient

        # Determine LLM provider name from client type
        inner = self._unwrap_client(self.client)
        if isinstance(inner, OpenAIClient):
            llm_provider = "openai"
        elif isinstance(inner, GeminiClient):
            llm_provider = "gemini"
        elif isinstance(inner, OpenRouterClient):
            llm_provider = "openrouter"
        else:
            llm_provider = "unknown"

        llm_model = self._get_model_name()

        # Compute prompt hash from normalize_text prompt template content
        prompt_hash = self._compute_prompt_hash("normalize_text")

        log_level = os.getenv("METESPARSER_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO"

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

    @property
    def model_name(self) -> str | None:
        """Return the LLM model name from the underlying client, if available."""
        inner = self._unwrap_client(self.client)
        for candidate in (self.client, inner):
            model: object = getattr(candidate, "model", None)
            if isinstance(model, str) and model:
                return model
            wrapped: object = getattr(candidate, "model_name", None)
            if isinstance(wrapped, str) and wrapped:
                return wrapped
        return None

    def _get_model_name(self) -> str:
        """Return the LLM model name from the underlying client."""
        return self.model_name or "unknown"

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
        has_pob = bool(
            re.search(r"(?:POINT\s+OF\s+BEGINNING|BEGINNING\s+at|POB)\b", text, re.IGNORECASE)
        )

        bearing_matches = re.findall(
            r"\b(?:North|South|[NS])\s*\d{1,2}\s*(?:°|º|degrees?|deg\.?)",
            text,
            re.IGNORECASE,
        )
        has_bearing_calls = len(bearing_matches) >= 3

        has_closure_language = bool(
            re.search(
                r"(?:POINT\s+OF\s+BEGINNING|place\s+of\s+beginning)\s*(?:[.;]|\s*$)",
                text,
                re.IGNORECASE,
            )
        )

        has_distances = bool(
            re.search(
                r"\b\d+(?:\.\d+)?\s*(?:feet|foot|ft\.?|poles?|rods?|perch(?:es)?|chains?|links?|varas?|arpents?|toises?|furlongs?|meters?|miles?)\b",
                text,
                re.IGNORECASE,
            )
        )

        text_length_reasonable = 50 < len(text) < 50_000

        has_plss = bool(re.search(r"\b(?:Section|Township|Range)\b", text, re.IGNORECASE))

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

    @staticmethod
    def _unwrap_client(client: BaseLLMClient) -> BaseLLMClient:
        """Unwrap already-cached client layers to avoid double-wrapping."""
        from .llm_cache import _unwrap_client_chain

        return _unwrap_client_chain(client)

    def _create_client(self, provider: str | None) -> BaseLLMClient:
        provider_name = (provider or os.getenv("METESPARSER_LLM_PROVIDER") or "openai").lower()

        try:
            if provider_name == "openai":
                return OpenAIClient(api_key=self._configured_api_key)
            if provider_name == "gemini":
                return GeminiClient(api_key=self._configured_api_key)
            if provider_name == "openrouter":
                openrouter_kwargs: dict[str, Any] = {"api_key": self._configured_api_key}
                if or_model := (os.getenv("OPENROUTER_MODEL") or "").strip():
                    openrouter_kwargs["model"] = or_model
                if "OPENROUTER_FALLBACK_MODEL" in os.environ:
                    or_fallback = os.environ["OPENROUTER_FALLBACK_MODEL"].strip()
                    if not or_fallback or or_fallback.lower() in {"none", "off", "disabled"}:
                        openrouter_kwargs["fallback_model"] = None
                    else:
                        openrouter_kwargs["fallback_model"] = or_fallback
                if or_pdf_engine := (os.getenv("OPENROUTER_PDF_ENGINE") or "").strip():
                    openrouter_kwargs["pdf_engine"] = or_pdf_engine
                if "OPENROUTER_REASONING_EFFORT" in os.environ:
                    or_effort = os.environ["OPENROUTER_REASONING_EFFORT"].strip()
                    if not or_effort or or_effort.lower() in {"off", "disabled"}:
                        openrouter_kwargs["reasoning_effort"] = None
                    else:
                        openrouter_kwargs["reasoning_effort"] = or_effort
                return OpenRouterClient(**openrouter_kwargs)
        except LLMClientError as exc:
            raise ValueError(str(exc)) from exc

        raise ValueError(
            f"Unsupported LLM provider '{provider_name}'. Choose from: openai, gemini, openrouter."
        )
