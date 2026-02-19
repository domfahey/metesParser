"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
Rule-based extraction -- no AI/LLM involved.
"""

from __future__ import annotations

import hashlib
import logging
import re

import structlog
from mp_bearing import (
    COMPASS_POINTS,
    QUADRANT_PATTERN,
    bearing_to_azimuth,
    calculate_curve_properties,
    degree_of_curvature_to_radius,
    parse_packed_dms,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)
from mp_models import (
    AuditContext,
    CallAudit,
    ConversionFactors,
    CurveDirection,
    CurveType,
    Decision,
    DeedCall,
    Tract,
    Transformation,
)
from pydantic import ValidationError

from .metadata import (
    detect_meander,
    extract_along_to_fields,
    extract_distance,
    is_closure_to_pob,
    is_indefinite_call,
    split_into_calls,
)
from .monuments import (
    MONUMENT_PATTERNS,
    classify_monument,
    classify_monument_status,
)
from .normalizer import normalize_legal_description, standardize_cardinal_directions
from .numbers import COMMA_NUMBER, parse_comma_number

logger = structlog.get_logger(__name__)

_CARDINAL_ONLY_PATTERN = re.compile(
    r"(north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?",
    re.IGNORECASE,
)

_UNIT_TOKEN = (
    r"(?:feet|foot|ft|poles?|rods?|perches?|chains?|links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
)

PACKED_DMS_PATTERN = re.compile(
    r"(N|S)\s+(\d{1,3}\.\d+)\u00b0\s*(E|W)",
    re.IGNORECASE,
)

CURVE_PATTERN = re.compile(
    rf"curve\s+to\s+the\s+(left|right).*?radius\s+of\s+({COMMA_NUMBER})\s*({_UNIT_TOKEN})?.*?"
    rf"(?:delta\s+(?:angle\s+)?of\s+)?({COMMA_NUMBER})(?:\u00b0|\s+degrees?)(?:\s*({COMMA_NUMBER})(?:'|\s+minutes?))?(?:\s*({COMMA_NUMBER})(?:\"|\s+seconds?))?",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_unit_token(token: str | None) -> str:
    """Normalize a captured unit token to a ConversionFactors-compatible key."""
    if token is None:
        return "feet"
    t = token.strip().lower()
    if t in ("ft", "feet", "foot", ""):
        return "feet"
    if t in ("pole", "poles"):
        return "poles"
    if t in ("rod", "rods"):
        return "rods"
    if t in ("perch", "perches"):
        return "perches"
    if t in ("chain", "chains"):
        return "chains"
    if t in ("link", "links"):
        return "links"
    if t in ("vara", "varas"):
        return "varas"
    if t in ("arpent", "arpents"):
        return "arpents"
    if t in ("toise", "toises"):
        return "toises"
    if t in ("furlong", "furlongs"):
        return "furlongs"
    if t in ("meter", "meters"):
        return "meters"
    if t in ("mile", "miles"):
        return "miles"
    return "feet"


def _call_preview(call_text: str, max_len: int = 120) -> str:
    """Return a compact single-line preview suitable for warning logs."""
    compact = " ".join(call_text.split())
    if len(compact) <= max_len:
        return compact
    return f"{compact[: max_len - 3]}..."


def _call_hash(call_text: str) -> str:
    """Stable short hash for correlating call text without logging full content."""
    return hashlib.sha256(call_text.encode("utf-8")).hexdigest()[:12]


def _is_debug_logging_enabled() -> bool:
    return logging.getLogger(__name__).isEnabledFor(logging.DEBUG)


def _extract_calls_from_text(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    course_start: int = 1,
) -> list[DeedCall]:
    """Extract calls from a single text segment (one tract).

    This is the inner extraction loop, factored out for reuse by
    both single-tract and multi-tract paths.
    """
    # Strip POB preamble -- everything before first THENCE is not a call.
    thence_match = re.search(r"\bTHENCE\b", text, re.IGNORECASE)
    if thence_match:
        text = text[thence_match.start() :]

    call_texts = split_into_calls(text)
    calls: list[DeedCall] = []
    course_num = course_start

    for call_text in call_texts:
        try:
            call = extract_single_call(call_text, course=course_num, distance_unit=distance_unit)
        except (ValidationError, ValueError, TypeError) as exc:
            payload = {
                "course": course_num,
                "call_preview": _call_preview(call_text),
                "call_hash": _call_hash(call_text),
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
            if _is_debug_logging_enabled():
                logger.warning(
                    "Skipping malformed call",
                    **payload,
                    call_text=call_text,
                    exc_info=exc,
                )
            else:
                logger.warning("Skipping malformed call", **payload)
            continue

        if call is None:
            continue

        calls.append(call)

        if audit_context is not None:
            transformations, decisions, flags = _audit_single_call(call_text, call)
            audit_context.call_audits.append(
                CallAudit(
                    course=course_num,
                    source_excerpt=call_text,
                    transformations=transformations,
                    decisions=decisions,
                    flags=flags,
                )
            )

        course_num += 1

    return calls


def extract_calls(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
) -> tuple[list[DeedCall], list[Tract]]:
    """Extract all calls from normalized legal description text.

    Handles multi-tract deeds (TRACT markers, multiple BEGINNINGs,
    EXCEPT/ALSO clauses) and marks calls accordingly.

    Args:
        text: Normalized legal description text (should already be normalized)
        distance_unit: Primary distance unit (feet, poles, etc.)
        audit_context: Optional audit context for recording parsing decisions

    Returns:
        Tuple of (flat_calls, tracts).
        - For single-tract deeds: flat_calls populated, tracts is empty list.
        - For multi-tract deeds: flat_calls is the merged list, tracts has
          per-tract Tract objects with independent call lists.
    """
    from mp_models import Tract, TractType

    from .tracts import split_into_tracts

    normalized = normalize_legal_description(text)
    segments = split_into_tracts(normalized)

    # Single-tract fast path: preserve backward-compatible behavior
    if len(segments) == 1 and segments[0][2] == TractType.MAIN:
        flat_calls = _extract_calls_from_text(
            normalized, distance_unit, audit_context=audit_context, course_start=1
        )
        return flat_calls, []

    # Multi-tract path
    all_calls: list[DeedCall] = []
    tract_objects: list[Tract] = []

    for segment_text, label, tract_type in segments:
        tract_calls = _extract_calls_from_text(
            segment_text, distance_unit, audit_context=audit_context, course_start=1
        )

        if not tract_calls:
            logger.warning(
                "Empty tract after extraction — segment dropped",
                tract_label=label,
                tract_type=tract_type.value,
                segment_length=len(segment_text),
                segment_preview=segment_text[:120],
            )
            continue

        if tract_type == TractType.EXCEPTION:
            tract_calls = [c.model_copy(update={"is_exception": True}) for c in tract_calls]

        tract = Tract(
            label=label,
            tract_type=tract_type,
            calls=tract_calls,
        )
        tract_objects.append(tract)
        all_calls.extend(tract_calls)

    return all_calls, tract_objects


def extract_single_call(
    call_text: str, course: int, distance_unit: str = "feet"
) -> DeedCall | None:
    """Extract a single call from text.

    Args:
        call_text: Text for one call
        course: Course number
        distance_unit: Primary distance unit

    Returns:
        DeedCall object or None if parsing fails
    """
    if re.match(r"^\s*(BEGINNING|COMMENCING|POB)\b", call_text, re.IGNORECASE):
        return None

    raw_direction = extract_direction(call_text)
    direction_text = raw_direction if raw_direction else call_text.strip()

    bearing_quadrant = None
    azimuth = None

    parsed_bearing = parse_quadrant_bearing(raw_direction) if raw_direction else None
    if parsed_bearing:
        cardinal1, degrees, cardinal2 = parsed_bearing
        deg_int = int(degrees)
        minutes = (degrees - deg_int) * 60

        rounded_minutes = round(minutes)
        if rounded_minutes >= 60:
            rounded_minutes = 0
            deg_int += 1

        bearing_quadrant = f"{cardinal1} {deg_int}\u00b0{rounded_minutes:02d}' {cardinal2}"
        azimuth = quadrant_to_azimuth(cardinal1, degrees, cardinal2)
    else:
        bearing_quadrant = None
        azimuth = None

    distance, unit = extract_distance(call_text)
    if distance == 0:
        distance = extract_distance_alternate(call_text)
        unit = distance_unit

    distance_ft = ConversionFactors.convert_to_feet(distance, unit)

    curve_info = extract_curve_info(call_text)

    arc_length_ft = curve_info.get("arc_length_ft")
    if isinstance(arc_length_ft, float) and arc_length_ft > 0.0:
        distance_ft = arc_length_ft
    elif curve_info.get("radius_ft") is not None and curve_info.get("delta_deg") is not None:
        radius_ft = curve_info.get("radius_ft")
        delta_deg = curve_info.get("delta_deg")
        if isinstance(radius_ft, float) and isinstance(delta_deg, float):
            props = calculate_curve_properties(radius_ft, delta_deg=delta_deg)
        else:
            raise ValueError("Curve info missing numeric radius/delta")
        arc_length_ft = props["arc_length_ft"]
        if arc_length_ft is None:
            raise ValueError("Curve props missing arc length")
        if arc_length_ft > 0.0:
            distance_ft = arc_length_ft
        curve_info.setdefault("arc_length_ft", props["arc_length_ft"])
        curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

    along, to = extract_along_to_fields(call_text)

    monument_type = classify_monument(to) if to else None
    monument_status = classify_monument_status(to or call_text)
    is_meander = detect_meander(call_text)

    notes = ""
    cardinal_only = False
    if raw_direction and not parsed_bearing:
        if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
            cardinal_only = True

    if is_meander or "approximate" in call_text.lower():
        notes = "meander / approximate"
    elif not parsed_bearing:
        notes = "incomplete bearing - cardinal only" if cardinal_only else "incomplete bearing"

    if distance_ft <= 0.0:
        return None

    has_curve = bool(curve_info.get("direction") or curve_info.get("radius_ft"))
    has_direction_intent = bool(
        raw_direction
        or parsed_bearing
        or has_curve
        or along
        or is_meander
        or re.search(r"\b[NS]\s+\d+\u00b0", call_text)
    )
    if not has_direction_intent:
        payload = {
            "course": course,
            "distance_ft": distance_ft,
            "call_preview": _call_preview(call_text),
            "call_hash": _call_hash(call_text),
        }
        if _is_debug_logging_enabled():
            logger.warning("Rejecting bearingless non-curve call", **payload, call_text=call_text)
        else:
            logger.warning("Rejecting bearingless non-curve call", **payload)
        return None

    curve_dir = curve_info.get("direction")
    curve_direction: CurveDirection | None
    if curve_dir == "left":
        curve_direction = "left"
    elif curve_dir == "right":
        curve_direction = "right"
    else:
        curve_direction = None

    radius_value = curve_info.get("radius_ft")
    radius_ft = radius_value if isinstance(radius_value, float) else None

    delta_value = curve_info.get("delta_deg")
    delta_deg = delta_value if isinstance(delta_value, float) else None

    arc_length_value = curve_info.get("arc_length_ft")
    arc_length_ft = arc_length_value if isinstance(arc_length_value, float) else None

    chord_bearing_value = curve_info.get("chord_bearing")
    chord_bearing = chord_bearing_value if isinstance(chord_bearing_value, str) else None

    chord_length_value = curve_info.get("chord_length_ft")
    chord_length_ft = chord_length_value if isinstance(chord_length_value, float) else None

    radial_bearing_value = curve_info.get("radial_bearing")

    is_indefinite = is_indefinite_call(direction_text, has_bearing=parsed_bearing is not None)

    curve_type_value = curve_info.get("curve_type")
    curve_type: CurveType | None = None
    if isinstance(curve_type_value, str):
        normalized_curve_type = curve_type_value.strip().lower()
        if normalized_curve_type == "simple":
            curve_type = "simple"
        elif normalized_curve_type == "compound":
            curve_type = "compound"
        elif normalized_curve_type == "reverse":
            curve_type = "reverse"
        elif normalized_curve_type == "spiral":
            curve_type = "spiral"
    if curve_direction is not None and curve_type is None:
        curve_type = "simple"

    call = DeedCall(
        course=course,
        direction_text=direction_text,
        bearing_quadrant=bearing_quadrant,
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance_ft,
        curve_dir=curve_direction,
        radius_ft=radius_ft,
        delta_deg=delta_deg,
        arc_length_ft=arc_length_ft,
        chord_bearing=chord_bearing,
        chord_length_ft=chord_length_ft,
        along=along if along else None,
        to=to if to else None,
        monument_type=monument_type,
        monument_status=monument_status,
        is_exception=False,
        non_tangent=bool(curve_info.get("non_tangent", False)),
        radial_bearing=(radial_bearing_value if isinstance(radial_bearing_value, str) else None),
        is_meander=is_meander,
        is_tie_in=False,
        is_indefinite=is_indefinite,
        curve_type=curve_type,
        notes=notes if notes else None,
    )

    return call


def _audit_single_call(
    call_text: str,
    call: DeedCall,
) -> tuple[list[Transformation], list[Decision], list[str]]:
    """Build audit data for a successfully parsed call.

    This is a pure function that inspects the parsed call and original text
    to construct transformation, decision, and flag lists for the audit trail.

    Args:
        call_text: Original text of the call
        call: The successfully parsed DeedCall

    Returns:
        Tuple of (transformations, decisions, flags)
    """
    transformations: list[Transformation] = []
    decisions: list[Decision] = []
    flags: list[str] = []

    # --- Bearing transformation ---
    raw_direction = extract_direction(call_text)
    if raw_direction:
        transformations.append(
            Transformation(
                step="extract_bearing",
                input=raw_direction,
                output=call.bearing_quadrant or "none",
            )
        )

    # --- Azimuth transformation ---
    if call.bearing_quadrant and call.bearing_azimuth_deg_from_north is not None:
        parsed = parse_quadrant_bearing(raw_direction)
        rule_str = None
        if parsed:
            cardinal1, degrees, cardinal2 = parsed
            rule_str = f"quadrant_to_azimuth: {cardinal1} {degrees} {cardinal2}"
        transformations.append(
            Transformation(
                step="compute_azimuth",
                input=call.bearing_quadrant,
                output=str(call.bearing_azimuth_deg_from_north),
                rule=rule_str,
            )
        )

    # --- Distance transformation ---
    distance, unit = extract_distance(call_text)
    distance_input = f"{distance} {unit}" if distance > 0 else call_text.strip()
    transformations.append(
        Transformation(
            step="extract_distance",
            input=distance_input,
            output=str(call.distance_ft),
        )
    )

    # --- Monument classification transformation ---
    if call.to and call.monument_type:
        # Find which pattern matched
        matched_rule = None
        to_lower = call.to.lower()
        for pattern, _mtype in MONUMENT_PATTERNS:
            if re.search(pattern, to_lower):
                matched_rule = pattern
                break
        transformations.append(
            Transformation(
                step="classify_monument",
                input=call.to,
                output=call.monument_type,
                rule=matched_rule,
            )
        )

    # --- Bearing decision ---
    if call.bearing_azimuth_deg_from_north is not None:
        decisions.append(
            Decision(
                field="bearing_azimuth_deg_from_north",
                value=str(call.bearing_azimuth_deg_from_north),
                reason="exact quadrant bearing parsed",
                confidence=0.95,
            )
        )

    # --- Monument type decision ---
    if call.monument_type:
        confidence = 0.60 if call.monument_type == "other" else 0.90
        decisions.append(
            Decision(
                field="monument_type",
                value=call.monument_type,
                reason="keyword pattern match",
                confidence=confidence,
            )
        )

    # --- Monument status decision ---
    if call.monument_status:
        decisions.append(
            Decision(
                field="monument_status",
                value=call.monument_status,
                reason="explicit found/set keyword",
                confidence=0.95,
            )
        )

    # --- Flags ---
    cardinal_only = False
    if raw_direction and not call.bearing_quadrant:
        if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
            cardinal_only = True

    if cardinal_only or (raw_direction and not call.bearing_quadrant):
        flags.append("incomplete_bearing")

    if call.is_indefinite:
        flags.append("indefinite")

    if call.is_meander:
        flags.append("meander")

    return transformations, decisions, flags


def extract_direction(text: str) -> str:
    """Extract direction/bearing from call text.

    Args:
        text: Call text

    Returns:
        Direction string (e.g., "S 56 deg 40' W" or "southwesterly")
    """
    quadrant_match = QUADRANT_PATTERN.search(text)
    if quadrant_match:
        return quadrant_match.group(0)

    packed_match = PACKED_DMS_PATTERN.search(text)
    if packed_match:
        cardinal1 = packed_match.group(1).upper()
        packed_value = float(packed_match.group(2))
        cardinal2 = packed_match.group(3).upper()
        decimal_degrees = parse_packed_dms(packed_value)
        deg = int(decimal_degrees)
        minutes = (decimal_degrees - deg) * 60
        rounded_minutes = round(minutes)
        if rounded_minutes >= 60:
            rounded_minutes = 0
            deg += 1
        return f"{cardinal1} {deg}\u00b0{rounded_minutes:02d}' {cardinal2}"

    # Compound compass point check (32-point system) -- must come before
    # simple cardinal check so "North by East" is not truncated to "North"
    compound_compass_names = sorted(
        [name for name in COMPASS_POINTS if " " in name or "-" in name],
        key=len,
        reverse=True,
    )
    compound_compass_regex = (
        r"\b(" + "|".join(re.escape(name) for name in compound_compass_names) + r")\b"
    )
    compound_compass_match = re.search(compound_compass_regex, text, re.IGNORECASE)
    if compound_compass_match:
        return compound_compass_match.group(0).lower()

    cardinal_pattern = (
        r"\b(north(?:erly|wardly)?|south(?:erly|wardly)?|east(?:erly|wardly)?|west(?:erly|wardly)?|"
        r"northeast(?:erly|wardly)?|northwest(?:erly|wardly)?|southeast(?:erly|wardly)?|southwest(?:erly|wardly)?)\b"
    )

    cardinal_match = re.search(cardinal_pattern, text, re.IGNORECASE)
    if cardinal_match:
        return cardinal_match.group(0).lower()

    # Abbreviated cardinal directions (NW, SW, NE, SE) from LLM normalization
    abbrev_match = re.search(r"\b(NE|NW|SE|SW)\b", text, re.IGNORECASE)
    if abbrev_match:
        return abbrev_match.group(0).lower()

    return ""


def extract_distance_alternate(text: str) -> float:
    """Extract distance using alternate patterns.

    Some deeds use formats like "125.26' along..." instead of "125.26 feet".

    Args:
        text: Call text

    Returns:
        Distance value (0.0 if not found)
    """
    feet_match = re.search(rf"({COMMA_NUMBER})\s*(?:feet|ft)\b", text, re.IGNORECASE)
    if feet_match:
        return parse_comma_number(feet_match.group(1))

    apostrophe_match = re.search(
        r"(?<!\u00b0)(\d+(?:\.\d+)?)\s*'(?=(?:\s+(?:along|to)\b|[.,;)]|$))",
        text,
        re.IGNORECASE,
    )
    if apostrophe_match:
        prefix = text[: apostrophe_match.end()]
        if re.search(
            r"\b(?:NORTH|SOUTH|N|S)\s+\d{1,3}\s+\d+(?:\.\d+)?\s*\x27\s*$",
            prefix,
            re.IGNORECASE,
        ):
            return 0.0
        if re.search(
            r"\d+\u00b0\s*\d+(?:\.\d+)?\s*\x27\s*$",
            prefix,
        ):
            return 0.0
        return float(apostrophe_match.group(1))

    return 0.0


def extract_curve_info(text: str) -> dict[str, float | str | None]:
    """Extract curve information from call text.

    Args:
        text: Call text

    Returns:
        Dict with curve properties (empty if no curve)
    """
    curve_info: dict[str, float | str | None] = {}

    if not re.search(r"\b(?:curve|spiral|transition)\b", text, re.IGNORECASE):
        return curve_info

    match = CURVE_PATTERN.search(text)
    if match:
        direction = match.group(1).lower()
        radius_raw = parse_comma_number(match.group(2))
        radius_unit = _normalize_unit_token(match.group(3))
        radius = ConversionFactors.convert_to_feet(radius_raw, radius_unit)
        delta_deg = parse_comma_number(match.group(4))

        if match.group(5):
            delta_deg += parse_comma_number(match.group(5)) / 60.0
        if match.group(6):
            delta_deg += parse_comma_number(match.group(6)) / 3600.0

        arc_length_match = re.search(
            rf"arc\s+(?:length|distance)\s+(?:of\s+)?({COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
            text,
            re.IGNORECASE,
        )
        arc_length: float | None = None
        if arc_length_match:
            arc_raw = parse_comma_number(arc_length_match.group(1))
            arc_unit = _normalize_unit_token(arc_length_match.group(2))
            arc_length = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

        props = calculate_curve_properties(radius, delta_deg=delta_deg)
        computed_arc_length = arc_length if arc_length is not None else props["arc_length_ft"]

        curve_info = {
            "direction": direction,
            "radius_ft": radius,
            "delta_deg": delta_deg,
            "arc_length_ft": computed_arc_length,
            "chord_length_ft": props["chord_length_ft"],
        }

    else:
        dir_match = re.search(r"curve\s+to\s+the\s+(left|right)", text, re.IGNORECASE)
        if dir_match:
            curve_info["direction"] = dir_match.group(1).lower()

        radius_match = re.search(
            rf"radius\s+(?:of\s+)?({COMMA_NUMBER})\s*({_UNIT_TOKEN})?", text, re.IGNORECASE
        )
        if radius_match:
            radius_raw = parse_comma_number(radius_match.group(1))
            radius_unit = _normalize_unit_token(radius_match.group(2))
            curve_info["radius_ft"] = ConversionFactors.convert_to_feet(radius_raw, radius_unit)

        delta_match = re.search(
            r"delta\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:\u00b0|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?(?:\s*(\d+(?:\.\d+)?)(?:\"|\s+seconds?))?",
            text,
            re.IGNORECASE,
        )
        if delta_match:
            delta = float(delta_match.group(1))
            if delta_match.group(2):
                delta += float(delta_match.group(2)) / 60.0
            if delta_match.group(3):
                delta += float(delta_match.group(3)) / 3600.0

            curve_info["delta_deg"] = delta

        arc_match = re.search(
            rf"arc\s+(?:length|distance)\s+(?:of\s+)?({COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
            text,
            re.IGNORECASE,
        )
        if arc_match:
            arc_raw = parse_comma_number(arc_match.group(1))
            arc_unit = _normalize_unit_token(arc_match.group(2))
            curve_info["arc_length_ft"] = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

        # Degree of curvature -> radius conversion
        doc_match = re.search(
            r"degree\s+of\s+(?:curve|curvature)\s+(?:of\s+)?"
            r"(\d+(?:\.\d+)?)(?:\u00b0|(?:\s+)?degrees?)"
            r"(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?"
            r'(?:\s*(\d+(?:\.\d+)?)(?:"|\s+seconds?))?',
            text,
            re.IGNORECASE,
        )
        if doc_match and curve_info.get("radius_ft") is None:
            doc_deg = float(doc_match.group(1))
            if doc_match.group(2):
                doc_deg += float(doc_match.group(2)) / 60.0
            if doc_match.group(3):
                doc_deg += float(doc_match.group(3)) / 3600.0
            if doc_deg > 0:
                curve_info["radius_ft"] = degree_of_curvature_to_radius(doc_deg)

    radius_ft = curve_info.get("radius_ft")
    curve_delta_deg = curve_info.get("delta_deg")
    if isinstance(radius_ft, float) and isinstance(curve_delta_deg, float):
        props = calculate_curve_properties(radius_ft, delta_deg=curve_delta_deg)
        if curve_info.get("arc_length_ft") is None:
            curve_info["arc_length_ft"] = props["arc_length_ft"]
        curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

    chord_bearing_match = re.search(
        r"(?:the\s+)?chord\s+(?:of\s+which\s+)?bears\s+(.+?)(?:,\s*(\d+(?:\.\d+)?)\s*(?:feet|ft))?(?:\s*$|\s*(?:to|along|;|\.))",
        text,
        re.IGNORECASE,
    )
    if chord_bearing_match:
        raw_chord_bearing = chord_bearing_match.group(1).strip().rstrip(",")
        normalized = standardize_cardinal_directions(raw_chord_bearing)
        bearing_match = QUADRANT_PATTERN.search(normalized)
        if bearing_match:
            curve_info["chord_bearing"] = bearing_match.group(0)
        if chord_bearing_match.group(2):
            curve_info["chord_length_ft"] = float(chord_bearing_match.group(2))

    if re.search(
        r"\b(?:point\s+of\s+compound\s+curvature|PCC|compound\s+curve)\b",
        text,
        re.IGNORECASE,
    ):
        curve_info["curve_type"] = "compound"
    elif re.search(
        r"\b(?:point\s+of\s+reverse\s+curvature|PRC|reverse\s+curve)\b",
        text,
        re.IGNORECASE,
    ):
        curve_info["curve_type"] = "reverse"
    elif re.search(
        r"\b(?:spiral\s+curve|transition\s+curve)\b",
        text,
        re.IGNORECASE,
    ):
        curve_info["curve_type"] = "spiral"

    if re.search(r"\bnon-?tangent\b", text, re.IGNORECASE):
        curve_info["non_tangent"] = True

    radial_match = re.search(
        r"radial\s+(?:line\s+)?bear(?:s|ing)\s+(?:of\s+)?(.+?)(?:,|\s*radius|\s*$)",
        text,
        re.IGNORECASE,
    )
    if radial_match:
        curve_info["non_tangent"] = True
        raw_radial = radial_match.group(1).strip()
        normalized_radial = standardize_cardinal_directions(raw_radial)
        radial_bearing_match = QUADRANT_PATTERN.search(normalized_radial)
        if radial_bearing_match:
            curve_info["radial_bearing"] = radial_bearing_match.group(0)

    return curve_info


def mark_tie_in_calls(calls: list[DeedCall], poc_description: str | None) -> list[DeedCall]:
    """Mark calls between POC and POB as tie-in calls.

    When a POC exists, calls before (and including) the first call whose
    'to' field references the Point of Beginning are marked as tie-in.

    Args:
        calls: List of DeedCall objects
        poc_description: POC description (None or empty means no POC)

    Returns:
        List of DeedCall objects with is_tie_in set appropriately
    """
    if not poc_description:
        return calls

    pob_index = None
    for i, call in enumerate(calls):
        if call.to and is_closure_to_pob("to " + call.to):
            pob_index = i
            break

    if pob_index is None:
        return calls

    result = []
    for i, call in enumerate(calls):
        if i <= pob_index:
            result.append(call.model_copy(update={"is_tie_in": True}))
        else:
            result.append(call)
    return result


def enrich_calls_with_azimuths(calls: list[DeedCall]) -> list[DeedCall]:
    """Add azimuths to calls that have quadrant bearings but missing azimuths.

    Args:
        calls: List of DeedCall objects

    Returns:
        List of enriched DeedCall objects
    """
    enriched = []
    for call in calls:
        if call.bearing_quadrant and call.bearing_azimuth_deg_from_north is None:
            azimuth = bearing_to_azimuth(call.bearing_quadrant)
            if azimuth is not None:
                enriched.append(call.model_copy(update={"bearing_azimuth_deg_from_north": azimuth}))
            else:
                enriched.append(call)
        else:
            enriched.append(call)
    return enriched
