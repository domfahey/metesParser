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
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import structlog
import yaml
from mp_models import LLMStageRecord

from .cache import CachedLLMClient, _unwrap_client_chain
from .clients import BaseLLMClient, GeminiClient, LLMClientError, OpenAIClient, OpenRouterClient
from .preprocessing import count_pdf_pages, preprocess_pdf_pages_for_ocr

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


# ---------------------------------------------------------------------------
# Stage 3 normalization integrity guard
# ---------------------------------------------------------------------------

_NORM_GUARD_DEG = r"(?:°|º|deg(?:rees?)?\.?|decr(?:ees?)?\.?)"
_NORM_GUARD_MIN = r"(?:'|\u2018|\u2019|\u2032|`|min(?:utes?)?\.?)"
_NORM_GUARD_SEC = r'(?:"|\u201c|\u201d|\u2033|\'\'|sec(?:onds?)?\.?)'
_NORM_GUARD_BEARING_RE = re.compile(
    rf"\b(?:(?P<ns_word>[5S][oO0]uth|N[oO0]rth)\s+|(?P<ns_abbr>[NS])\s*)"
    rf"(?P<deg>\d{{1,2}})\s*{_NORM_GUARD_DEG}\s*,?\s*"
    rf"(?:"
    rf"(?P<min1>\d{{1,2}})\s*{_NORM_GUARD_MIN}\s*,?\s*"
    rf"(?:(?:and\s+)?(?P<sec1>\d{{1,2}}(?:\.\d+)?)\s*{_NORM_GUARD_SEC}?\s*,?\s*)?"
    rf"|(?P<min2>\d{{1,2}})\s+(?P<sec2>\d{{1,2}}(?:\.\d+)?)\s*,?\s*"
    rf")?\s*(?P<ew>East|West|[EW])\b",
    re.IGNORECASE,
)

_NORM_GUARD_ANGLE_RE = re.compile(
    rf"(?<![A-Za-z0-9.])(?P<deg>\d{{1,3}})\s*{_NORM_GUARD_DEG}\s*,?\s*"
    rf"(?P<min>\d{{1,2}})\s*{_NORM_GUARD_MIN}\s*,?\s*"
    rf"(?:(?:and\s+)?(?P<sec>\d{{1,2}}(?:\.\d+)?)\s*{_NORM_GUARD_SEC}?)?",
    re.IGNORECASE,
)

_NORM_GUARD_DISTANCE_RE = re.compile(
    r"(?<![A-Za-z0-9./,])"
    r"(?:(?:(?P<whole>\d+)\s+)?(?P<num>\d+)/(?P<den>\d+)"
    r"|(?P<val>\d+(?:,\d{3})*(?:\.\d+)?|\.\d+))"
    r"\.?[\s-]*"
    r"(?P<unit>(?:u\.?s\.?\s+)?survey\s+(?:feet|foot|ft)|"
    r"engineer(?:'s)?\s+(?:chains?|links?)|"
    r"feet|foot|ft|poles?|rods?|perch(?:es)?|chains?|links?|varas?|"
    r"arpents?|toises?|furlongs?|met(?:er|re)s?|miles?)"
    r"(?:\.(?!\w))?(?!\w|\.\w)",
    re.IGNORECASE,
)

_LEGAL_COURSE_CUE_RE = re.compile(r"\b(?:BEGINNING|COMMENCING|THENCE)\b", re.IGNORECASE)

_NORM_GUARD_UNIT_CANONICAL: dict[str, str] = {
    "foot": "feet",
    "ft": "feet",
    "feet": "feet",
    "pole": "poles",
    "poles": "poles",
    "rod": "rods",
    "rods": "rods",
    "perch": "perches",
    "perches": "perches",
    "chain": "chains",
    "chains": "chains",
    "link": "links",
    "links": "links",
    "vara": "varas",
    "varas": "varas",
    "arpent": "arpents",
    "arpents": "arpents",
    "toise": "toises",
    "toises": "toises",
    "furlong": "furlongs",
    "furlongs": "furlongs",
    "meter": "meters",
    "meters": "meters",
    "metre": "meters",
    "metres": "meters",
    "mile": "miles",
    "miles": "miles",
}


def _canonicalize_unit(raw_unit: str) -> str:
    cleaned = " ".join(raw_unit.lower().replace(".", "").split())
    if cleaned.endswith(("feet", "foot", "ft")):
        return "feet"
    if cleaned.endswith(("chains", "chain")):
        return "chains"
    if cleaned.endswith(("links", "link")):
        return "links"
    return _NORM_GUARD_UNIT_CANONICAL.get(cleaned, cleaned)


def _extract_bearing_signature(
    text: str,
) -> tuple[list[tuple[str, int, int, float, str]], list[tuple[int, int]]]:
    """Return ordered canonical DMS bearings and their character spans."""
    out: list[tuple[str, int, int, float, str]] = []
    spans: list[tuple[int, int]] = []
    for match in _NORM_GUARD_BEARING_RE.finditer(text):
        ns_raw = match.group("ns_word") or match.group("ns_abbr") or ""
        ns = "N" if ns_raw[0].upper() == "N" else "S"
        ew = "E" if match.group("ew")[0].upper() == "E" else "W"
        deg = int(match.group("deg"))
        if match.group("min1") is not None:
            mins = int(match.group("min1"))
            secs = float(match.group("sec1")) if match.group("sec1") is not None else 0.0
        elif match.group("min2") is not None:
            mins = int(match.group("min2"))
            secs = float(match.group("sec2"))
        else:
            mins = 0
            secs = 0.0
        out.append((ns, deg, mins, round(secs, 4), ew))
        spans.append(match.span())
    return out, spans


def _extract_standalone_angle_signature(
    text: str, excluded_spans: Sequence[tuple[int, int]]
) -> list[tuple[int, int, float]]:
    """Return ordered standalone DMS angles (deltas, interior/exterior angles)."""
    out: list[tuple[int, int, float]] = []
    for match in _NORM_GUARD_ANGLE_RE.finditer(text):
        start, end = match.span()
        if any(start < b_end and end > b_start for b_start, b_end in excluded_spans):
            continue
        deg = int(match.group("deg"))
        mins = int(match.group("min"))
        secs = float(match.group("sec")) if match.group("sec") is not None else 0.0
        out.append((deg, mins, round(secs, 4)))
    return out


def _extract_distance_signature(text: str) -> list[tuple[float, str]]:
    """Return ordered canonical ``(value, unit)`` distance measurement tuples."""
    out: list[tuple[float, str]] = []
    for match in _NORM_GUARD_DISTANCE_RE.finditer(text):
        if match.group("num") is not None:
            den = int(match.group("den"))
            if den == 0:
                continue
            whole = float(match.group("whole")) if match.group("whole") is not None else 0.0
            val = whole + (float(match.group("num")) / den)
        else:
            val = float(match.group("val").replace(",", ""))
        unit = _canonicalize_unit(match.group("unit"))
        out.append((round(val, 6), unit))
    return out


def verify_normalization_integrity(
    source_text: str, normalized_text: str
) -> tuple[bool, list[str]]:
    """Verify Stage 3 normalization preserved every bearing, angle, and distance in order.

    Stage 3 is a format-only rewrite (symbols, abbreviations, line unwrapping).
    Any reordering, omission, duplication, or numeric change in bearings,
    standalone DMS angles, or distance measurements indicates LLM copy drift
    and fails this check.
    """
    reasons: list[str] = []
    if source_text.strip() and not normalized_text.strip():
        return False, ["empty_normalized_output"]

    src_bearings, src_b_spans = _extract_bearing_signature(source_text)
    norm_bearings, norm_b_spans = _extract_bearing_signature(normalized_text)
    if src_bearings != norm_bearings:
        reasons.append(
            f"bearing_sequence_mismatch (source={len(src_bearings)}, "
            f"normalized={len(norm_bearings)})"
        )

    src_angles = _extract_standalone_angle_signature(source_text, src_b_spans)
    norm_angles = _extract_standalone_angle_signature(normalized_text, norm_b_spans)
    if src_angles != norm_angles:
        reasons.append(
            f"angle_sequence_mismatch (source={len(src_angles)}, normalized={len(norm_angles)})"
        )

    src_distances = _extract_distance_signature(source_text)
    norm_distances = _extract_distance_signature(normalized_text)
    if src_distances != norm_distances:
        reasons.append(
            f"distance_sequence_mismatch (source={len(src_distances)}, "
            f"normalized={len(norm_distances)})"
        )

    return not reasons, reasons


def has_legal_measurement_signals(text: str) -> bool:
    """Return True if *text* contains bearings or metes-and-bounds course distances.

    Requires at least one DMS bearing OR a legal course cue
    (``BEGINNING`` / ``COMMENCING`` / ``THENCE``) with at least two distance
    measurements so a stray boilerplate distance on a cover page does not
    suppress all-page fallback.
    """
    bearings, _ = _extract_bearing_signature(text)
    if bearings:
        return True
    return bool(_LEGAL_COURSE_CUE_RE.search(text)) and len(_extract_distance_signature(text)) >= 2


def parse_located_pages(raw_response: str, total_pages: int) -> list[int]:
    """Parse 1-based legal-description page numbers from JSON LLM output.

    Falls back to all pages ``1..total_pages`` whenever the response is empty,
    malformed, or contains no valid page numbers so legal text is never dropped.
    """
    all_pages = list(range(1, total_pages + 1))
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(
            "Could not parse locate_legal_pages JSON; falling back to all pages",
            total_pages=total_pages,
        )
        return all_pages

    raw_pages: object = parsed.get("pages") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_pages, list):
        logger.warning(
            "locate_legal_pages returned unexpected payload; falling back to all pages",
            total_pages=total_pages,
        )
        return all_pages

    valid = sorted(
        {
            p
            for p in raw_pages
            if isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= total_pages
        }
    )
    if not valid:
        logger.warning(
            "locate_legal_pages returned no valid page numbers; falling back to all pages",
            total_pages=total_pages,
        )
        return all_pages
    return valid


_has_legal_measurement_signals = has_legal_measurement_signals
_parse_located_pages = parse_located_pages


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
            provider: LLM provider name ("openai", "gemini", or "openrouter")
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
                prompt_text = prompt_path.read_text(encoding="utf-8")
                break

        if prompt_text is None:
            try:
                from importlib import resources

                packaged_prompt = resources.files("mp_ocr").joinpath("prompts", prompt_file)
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

    def extract_text_from_pdf(self, pdf_path: str, *, audit: bool = False) -> str:
        """Extract all text from a PDF using the configured LLM provider."""
        self._audit_stage_records = [] if audit else None
        try:
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
        elif (
            not self._audit_stage_records
            or self._audit_stage_records[-1].stage != "extract_legal_description"
        ):
            # Keep an active extract_legal_description -> normalize_legal_description
            # audited chain intact while resetting on repeated standalone calls.
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
        """Identify 1-based page numbers in *pdf_path* containing legal descriptions.

        Returns all pages without an LLM call when the PDF has two or fewer pages.
        Batches thumbnail requests when ``total_pages > max_pages_per_batch``.
        """
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
                    local_pages = parse_located_pages(response, batch_len)
                    located.extend(batch_start + p for p in local_pages)
        except Exception:
            if audit:
                self._audit_stage_records = None
            raise

        return sorted(dict.fromkeys(located))

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

        Returns ``(legal_desc_text, normalized_text, resolved_pages)``. Never
        receives closure errors or prior extraction guesses, and preserves any
        pre-existing audit records on *locator_processor* without stealing them.
        """
        collected_stages: list[LLMStageRecord] | None = [] if audit else None
        self._audit_stage_records = None

        try:
            total_pages = count_pdf_pages(pdf_path)
            if total_pages == 0:
                raise ValueError(f"PDF has no pages: {pdf_path}")

            if pages is not None:
                resolved_pages = sorted(dict.fromkeys(int(p) for p in pages))
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

            def _run_on_pages(target_pages: list[int], prefix: str) -> tuple[str, str]:
                with tempfile.TemporaryDirectory(prefix="mp_ocr_escalate_") as tmpdir:
                    clean_pngs = preprocess_pdf_pages_for_ocr(
                        pdf_path,
                        Path(tmpdir),
                        pages=target_pages,
                        dpi=dpi,
                        strip_watermark=strip_watermark,
                        crop_margins=crop_margins,
                        max_dim=max_dim,
                    )
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

            legal_desc_text, normalized_text = _run_on_pages(resolved_pages, stage_prefix)
            if (
                pages is None
                and len(resolved_pages) < total_pages
                and not has_legal_measurement_signals(legal_desc_text)
            ):
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
        """Capture provenance only while an audited caller has enabled collection."""
        if self._audit_stage_records is None:
            return
        inner = self._unwrap_client(self.client)
        provider = (
            "openai"
            if isinstance(inner, OpenAIClient)
            else "gemini"
            if isinstance(inner, GeminiClient)
            else "openrouter"
            if isinstance(inner, OpenRouterClient)
            else "unknown"
        )
        model = self._get_model_name()
        self._audit_stage_records.append(
            LLMStageRecord(
                stage=stage,
                prompt=prompt,
                prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
                response=response,
                response_sha256=sha256(response.encode("utf-8")).hexdigest(),
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
        elif isinstance(inner, OpenRouterClient):
            llm_provider = "openrouter"
        else:
            llm_provider = "unknown"

        llm_model = self._get_model_name()
        prompt_hash = self._compute_prompt_hash("normalize_text")
        log_level = os.getenv("METESPARSER_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO"

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
    def _unwrap_client(client: BaseLLMClient) -> BaseLLMClient:
        """Unwrap already-cached client layers to avoid double-wrapping."""
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

    def check_prior_conveyance(self, text: str) -> list[str]:
        """Return matched prior conveyance patterns in the given text."""
        return [p.pattern for p in _PRIOR_CONVEYANCE_PATTERNS if p.search(text)]
