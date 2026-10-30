"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
"""

import hashlib
import logging
import math
import re

import structlog
from pydantic import ValidationError

from .bearing_converter import BearingConverter
from .models import (
    AuditContext,
    CallAudit,
    ConversionFactors,
    CurveDirection,
    CurveType,
    Decision,
    DeedCall,
    MonumentStatus,
    MonumentType,
    Transformation,
)
from .text_parser import _COMMA_NUMBER, TextParser, parse_comma_number

logger = structlog.get_logger(__name__)

_CARDINAL_ONLY_PATTERN = re.compile(
    r"(north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?",
    re.IGNORECASE,
)

_WORD_SYMBOL_BEARING = re.compile(
    r"\b(North|South)\s+(\d{1,3})\s*\u00b0\s*(?:(\d{1,2})\s*'\s*)?"
    r"(?:(\d{1,2}(?:\.\d+)?)\s*\"\s*)?(East|West)\b",
    re.IGNORECASE,
)


def _abbreviate_word_bearing(text: str) -> str:
    """Abbreviate 'North 45\u00b0 East' style bearings (full words, degree symbol)."""

    def _repl(m: re.Match[str]) -> str:
        minutes = f"{m.group(3)}'" if m.group(3) else ""
        seconds = f'{m.group(4)}"' if m.group(4) else ""
        return (
            f"{m.group(1)[0].upper()} {m.group(2)}\u00b0{minutes}{seconds} {m.group(5)[0].upper()}"
        )

    return _WORD_SYMBOL_BEARING.sub(_repl, text)


_UNIT_TOKEN = (
    r"(?:US\s+survey\s+(?:feet|foot)|feet|foot|ft|poles?|rods?|perches?|chains?|links?"
    r"|engineer\s+chains?|engineer\s+links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
)


def _normalize_unit_token(token: str | None) -> str:
    """Normalize a captured unit token to a ConversionFactors-compatible key."""
    if token is None:
        return "feet"
    t = " ".join(token.strip().lower().split())
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
    if t in ("engineer chain", "engineer chains"):
        return "engineer_chains"
    if t in ("engineer link", "engineer links"):
        return "engineer_links"
    if t in ("us survey foot", "us survey feet"):
        return "us_survey_feet"
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


_PACKED_DMS_BEARING = re.compile(r"(N|S)\s+(\d{1,3}\.\d+)°\s*(E|W)", re.IGNORECASE)

_COMPACT_DMS_BEARING = re.compile(
    r"\b([NS])\s*(\d{1,3})\s*(?:-|d\b|d(?=\d)|deg\.?|degrees?)\s*"
    r"(?:(\d{1,2})\s*(?:-|m\b|m(?=\d)|min\.?|minutes?)\s*)?"
    r"(?:(\d{1,2}(?:\.\d+)?)\s*(?:s\b|sec\.?|seconds?)?\s*)?([EW])\b",
    re.IGNORECASE,
)


def _expand_compact_dms(text: str) -> str:
    """Rewrite dashed or d/m bearings (``N 45-30-00 E``, ``N 45d30m E``) with symbols."""

    def _repl(m: re.Match[str]) -> str:
        minutes = f"{m.group(3)}'" if m.group(3) else ""
        seconds = f'{m.group(4)}"' if m.group(4) else ""
        return f"{m.group(1).upper()} {m.group(2)}°{minutes}{seconds} {m.group(5).upper()}"

    return _COMPACT_DMS_BEARING.sub(_repl, text)


def _normalize_bearing_forms(text: str) -> str:
    """Rewrite every bearing form the parser accepts into abbreviated DMS."""
    return TextParser.standardize_cardinal_directions(
        _abbreviate_word_bearing(_expand_compact_dms(text))
    )


_CHORD_PREFIX_PATTERN = re.compile(
    r"(?:the\s+)?chord\s+(?:of\s+which\s+)?(?:bears|bearing)\s+(?:of\s+)?", re.IGNORECASE
)
_RADIAL_PREFIX_PATTERN = re.compile(
    r"(?:radius\s+point|radial(?:\s+line)?|(?:center|centre)(?:\s+point)?"
    r"|(?:center|centre)\s+of\s+which)"
    r"\s+(?:which\s+|that\s+)?(?:bears?|bearing)\s+(?:of\s+)?",
    re.IGNORECASE,
)


def _without_reference_bearings(text: str, prefix: re.Pattern[str]) -> str:
    """Remove every ``prefix`` clause together with the bearing it introduces.

    The bearing is searched only within the clause (up to the next comma or
    semicolon); if none is recognised the clause itself is dropped so its
    direction words cannot be read as the course bearing.
    """
    text = _normalize_bearing_forms(text)
    while True:
        match = prefix.search(text)
        if not match:
            return text
        rest = text[match.end() :]
        clause_end = re.search(r"[,;]", rest)
        clause = rest[: clause_end.start()] if clause_end else rest
        bearing = _PACKED_DMS_BEARING.search(clause) or BearingConverter.QUADRANT_PATTERN.search(
            clause
        )
        cut = bearing.end() if bearing else len(clause)
        text = text[: match.start()] + " " + rest[cut:]


def _without_chord_bearing(text: str) -> str:
    """Remove chord-bearing clauses; the chord is never the tangent."""
    return _without_reference_bearings(text, _CHORD_PREFIX_PATTERN)


def _without_radial_bearing(text: str) -> str:
    """Remove radius-point/radial/center bearing clauses; they are not the tangent."""
    return _without_reference_bearings(text, _RADIAL_PREFIX_PATTERN)


_BEARING_DEGREE_PREFIX = re.compile(
    r"(?:\b(?:N|S|north|south)\.?\s*|\b(?:bears?|bearing|azimuth)\s+(?:of\s+)?)$",
    re.IGNORECASE,
)


def _is_bearing_degree(text: str, start: int) -> bool:
    """Return True when the degree value at ``start`` is part of a bearing."""
    return bool(_BEARING_DEGREE_PREFIX.search(text[:start]))


def _boundary_course_text(call_text: str) -> str:
    """Remove bearing references that describe a corner instead of the course."""
    starts = [
        match.start()
        for match in re.finditer(
            r"\b(?:from\s+which|witness(?:\s+(?:tree|mark|corner))?|"
            r"reference\s+(?:tree|mark))\b",
            call_text,
            re.IGNORECASE,
        )
    ]
    lowered = call_text.lower()
    for witness in TextParser.extract_witness_trees(call_text):
        position = lowered.find(witness.lower())
        if position >= 0:
            starts.append(position)
    if not starts:
        return call_text
    return call_text[: min(starts)]


def _course_direction(call_text: str) -> str:
    """Return the course (tangent) direction stated in the boundary course text.

    Bearing forms are normalized, then corner witnesses, chord bearings and
    radial/radius-point/center bearings are removed *before* extraction, so only
    a bearing describing the course itself can be returned.
    """
    course_text = _without_radial_bearing(_without_chord_bearing(_boundary_course_text(call_text)))
    return CallExtractor.extract_direction(course_text)


class MonumentClassifier:
    """Classify survey monument types from text descriptions."""

    MONUMENT_PATTERNS: list[tuple[str, MonumentType]] = [
        (r"\btxdot\b.*\bmonument\b", "txdot_monument"),
        (r"\bcapped\s+(?:iron\s+)?rod\b", "capped_rod"),
        (r"\bcapped\s+(?:iron\s+)?pin\b", "capped_pin"),
        (r"\bcapped\s+rebar\b", "capped_rod"),
        (r"\biron\s+rod\b", "iron_rod"),
        (r"\biron\s+pin\b", "iron_pin"),
        (r"\biron\s+pipe\b", "iron_pipe"),
        (r"\biron\s+stake\b", "iron_rod"),
        (r"\biron\s+monument\b", "iron_rod"),
        (r"\brebar\b", "rebar"),
        (r"\bpk\s+nail\b", "pk_nail"),
        (r"\b(?:mag|magnetic)\s+nail\b", "nail"),
        (r"\bnail\b", "nail"),
        (r"\bhub\s+(?:and|&)\s+tack\b", "hub_and_tack"),
        (r"\bmonitoring\s+well\b", "monitoring_well"),
        (r"\brailroad\s+(?:spike|tie)\b", "railroad_spike"),
        (r"\bgin\s+(?:spike|pole)\b", "railroad_spike"),
        (r"\bstone\s+monument\b", "stone"),
        (r"\bstone\b", "stone"),
        (r"\bconcrete\s+monument\b", "concrete"),
        (r"\bconcrete\b", "concrete"),
        (r"\bbrass\s+(?:cap|marker|monument)\b", "brass_cap"),
        (r"\bwooden\s+(?:post|stake)\b", "wooden_post"),
        (r"\bhedge\s+post\b", "wooden_post"),
        (r"\bwood\s+stake\b", "wooden_post"),
        (r"\blandscap(?:e|ing)\s+(?:rod|pin)\b", "iron_rod"),
        # Natural monuments — trees
        (
            r"\b(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)\b",
            "tree",
        ),
        (r"\btree\b", "tree"),
        # Natural monuments — rocks
        (r"\bboulder\b", "rock"),
        (r"\brock\s+outcrop\b", "rock"),
        (r"\bstanding\s+rock\b", "rock"),
        (r"\blarge\s+rock\b", "rock"),
        # Natural features — water/terrain
        (r"\b(?:stream|creek|river|brook|branch|run)\b", "natural_feature"),
        (r"\b(?:ridge|bluff|cliff|shoreline|lakeshore|shore)\b", "natural_feature"),
    ]

    @classmethod
    def classify_monument(cls, text: str) -> MonumentType | None:
        """Classify monument type from text description.

        Args:
            text: Text description (typically from 'to' field)

        Returns:
            Monument type literal or None if not found
        """
        if not text:
            return None

        text_lower = text.lower()

        for pattern, monument_type in cls.MONUMENT_PATTERNS:
            if re.search(pattern, text_lower):
                return monument_type

        if re.search(r"\bmonument\b", text_lower):
            return "other"

        return None

    MONUMENT_STATUS_PATTERNS: list[tuple[str, MonumentStatus]] = [
        (r"\bfd\b", "found"),
        (r"\bfnd\b", "found"),
        (r"\bfound\b", "found"),
        (r"\bset\b", "set"),
        (r"\bplaced\b", "set"),
    ]

    @classmethod
    def classify_monument_status(cls, text: str | None) -> MonumentStatus | None:
        """Classify whether monument status indicates found or set."""
        if not text:
            return None

        text_lower = text.lower()
        for pattern, status in cls.MONUMENT_STATUS_PATTERNS:
            if re.search(pattern, text_lower):
                return status

        return None


class CallExtractor:
    """Extract and structure deed calls from legal description text."""

    CURVE_PATTERN = re.compile(
        rf"curve\s+to\s+the\s+(left|right).*?radius\s+of\s+({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?.*?"
        rf"(?:delta\s+(?:angle\s+)?of\s+)?({_COMMA_NUMBER})(?:°|\s+degrees?)(?:\s*({_COMMA_NUMBER})(?:'|\s+minutes?))?(?:\s*({_COMMA_NUMBER})(?:\"|\s+seconds?))?",
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def _is_initial_course_prefix(cls, prefix: str) -> bool:
        """Return whether text before THENCE starts with a supported bearing."""
        candidate = re.sub(r"^\s*(?:(?:\(\d+\)|\d+[.)])\s*)?", "", prefix)
        if cls.PACKED_DMS_PATTERN.match(candidate):
            return True

        try:
            direction = cls.extract_direction(candidate)
        except ValueError:
            return False
        if not direction or not candidate.lstrip().lower().startswith(direction.lower()):
            return False
        if _CARDINAL_ONLY_PATTERN.fullmatch(direction):
            remainder = candidate.lstrip()[len(direction) :]
            return bool(re.match(rf"\s+{_COMMA_NUMBER}(?:\s|$)", remainder))
        return bool(
            BearingConverter.parse_quadrant_bearing(direction)
            or BearingConverter.due_cardinal_to_azimuth(direction) is not None
        )

    @classmethod
    def extract_calls(
        cls,
        text: str,
        distance_unit: str = "feet",
        *,
        audit_context: AuditContext | None = None,
        strict: bool = True,
    ) -> list[DeedCall]:
        """Extract all calls from normalized legal description text.

        Handles exception clauses (EXCEPT, LESS AND EXCEPT, ALSO, INCLUDING)
        and marks calls accordingly.

        Args:
            text: Normalized legal description text (should already be normalized)
            distance_unit: Primary distance unit (feet, poles, etc.)
            audit_context: Optional audit context for recording parsing decisions
            strict: Raise with course context when a geometric course is malformed.

        Returns:
            List of DeedCall objects
        """
        normalized = TextParser.normalize_legal_description(text)

        tracts = TextParser.split_exception_clauses(normalized)

        calls: list[DeedCall] = []
        course_num = 1

        for tract_text, is_exception_tract in tracts:
            # Remove a recognized commencement/POB preamble. A description may
            # legitimately begin with its first course and introduce THENCE later.
            thence_match = re.search(r"\bTHENCE\b", tract_text, re.IGNORECASE)
            has_thence_marker = thence_match is not None
            prefix = tract_text[: thence_match.start()] if thence_match else ""
            has_beginning_preamble = re.match(
                r"\s*(?:BEGINNING|COMMENCING|POINT\s+OF\s+BEGINNING|POB|TPOB|RPOB)\b",
                prefix,
                re.IGNORECASE,
            )
            has_initial_course = bool(thence_match and cls._is_initial_course_prefix(prefix))
            if thence_match and (has_beginning_preamble or not has_initial_course):
                tract_text = tract_text[thence_match.start() :]

            has_numbered_course_markers = bool(
                re.search(
                    r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+",
                    tract_text,
                    re.MULTILINE,
                )
            )
            call_texts = TextParser.split_into_calls(tract_text)

            for source_course, call_text in enumerate(call_texts, start=1):
                try:
                    call = cls.extract_single_call(
                        call_text, course=course_num, distance_unit=distance_unit
                    )
                except (ValidationError, ValueError, TypeError) as exc:
                    if strict:
                        raise ValueError(
                            f"Malformed course {source_course}: {call_text.strip()!r}: {exc}"
                        ) from exc
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
                    standalone_thence = re.fullmatch(r"\s*THENCE\s*", call_text, re.I)
                    explicit_course = not standalone_thence and (
                        has_thence_marker or has_numbered_course_markers
                    )
                    if strict and (
                        explicit_course
                        or cls.extract_direction(call_text)
                        or re.search(r"\b(?:[NSEW])\s+\d", call_text, re.I)
                        or re.search(r"\b(?:curve|spiral|transition)\b", call_text, re.I)
                    ):
                        raise ValueError(f"Malformed course {source_course}: {call_text.strip()!r}")
                    continue

                if is_exception_tract:
                    call = call.model_copy(update={"is_exception": True})
                calls.append(call)

                if audit_context is not None:
                    transformations, decisions, flags = cls._audit_single_call(call_text, call)
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

    @classmethod
    def extract_single_call(
        cls, call_text: str, course: int, distance_unit: str = "feet"
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

        raw_direction = _course_direction(call_text)
        direction_text = raw_direction if raw_direction else call_text.strip()

        bearing_quadrant = None
        azimuth = None

        is_due_cardinal = False
        parsed_bearing = (
            BearingConverter.parse_quadrant_bearing(raw_direction) if raw_direction else None
        )
        if parsed_bearing:
            cardinal1, degrees, cardinal2 = parsed_bearing
            deg_int = int(degrees)
            minutes = (degrees - deg_int) * 60

            rounded_minutes = round(minutes)
            if rounded_minutes >= 60:
                rounded_minutes = 0
                deg_int += 1

            bearing_quadrant = f"{cardinal1} {deg_int}°{rounded_minutes:02d}' {cardinal2}"
            azimuth = BearingConverter.quadrant_to_azimuth(cardinal1, degrees, cardinal2)
        else:
            # Try "due {cardinal}" before giving up
            due_az = (
                BearingConverter.due_cardinal_to_azimuth(raw_direction) if raw_direction else None
            )
            if due_az is not None:
                azimuth = due_az
                is_due_cardinal = True
                bearing_quadrant = None
            else:
                bearing_quadrant = None
                azimuth = None

        course_text = _boundary_course_text(call_text)
        distance, unit = TextParser.extract_distance(course_text)
        if distance == 0:
            if re.search(
                rf"{_COMMA_NUMBER}\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+and\s+{_COMMA_NUMBER}\s+[A-Za-z]+",
                course_text,
                re.IGNORECASE,
            ):
                raise ValueError("Unsupported component in compound course distance")
            distance = cls.extract_distance_alternate(course_text)
            unit = distance_unit

        distance_ft = ConversionFactors.convert_to_feet(distance, unit)

        curve_info = cls.extract_curve_info(call_text)

        # The tangent azimuth is only what the course text states (chord and radial
        # clauses were removed before extraction). Without one, a stated chord bearing
        # plus curve direction and delta yields it deterministically (right: chord -
        # delta/2; left: chord + delta/2). Only an explicitly stated delta is stored as
        # delta_deg; otherwise the stated arc length and radius (delta = arc / R) or
        # chord length and radius (delta = 2 asin(c / 2R)) define it exactly. Such a
        # delta is used for the tangent only, and disclosed in the notes.
        has_stated_tangent = parsed_bearing is not None or is_due_cardinal
        chord_text = curve_info.get("chord_bearing")
        chord_only = isinstance(chord_text, str) and not has_stated_tangent
        curve_delta = curve_info.get("delta_deg")
        tangent_delta: float | None = curve_delta if isinstance(curve_delta, float) else None
        delta_source = ""
        arc_from_chord = False
        stated_radius = curve_info.get("radius_ft")
        stated_arc = curve_info.get("arc_length_ft")
        stated_chord = curve_info.get("chord_length_ft")
        if tangent_delta is None and isinstance(stated_radius, float) and stated_radius > 0.0:
            if isinstance(stated_arc, float) and stated_arc > 0.0:
                tangent_delta = math.degrees(stated_arc / stated_radius)
                delta_source = "arc length"
            elif isinstance(stated_chord, float) and stated_chord > 0.0:
                if stated_chord > 2.0 * stated_radius:
                    raise ValueError("Curve chord length exceeds twice the radius")
                delta_rad = 2.0 * math.asin(stated_chord / (2.0 * stated_radius))
                tangent_delta = math.degrees(delta_rad)
                delta_source = "chord length"
                # The arc follows exactly from the stated radius and chord length.
                curve_info["arc_length_ft"] = stated_radius * delta_rad
                arc_from_chord = True
        derived_tangent = False
        if (
            chord_only
            and isinstance(chord_text, str)
            and curve_info.get("direction") in ("left", "right")
            and tangent_delta is not None
        ):
            chord_az = BearingConverter.bearing_to_azimuth(chord_text)
            if chord_az is not None:
                half_delta = tangent_delta / 2.0
                sign = -1.0 if curve_info.get("direction") == "right" else 1.0
                azimuth = (chord_az + sign * half_delta) % 360.0
                bearing_quadrant = None
                derived_tangent = True

        has_abbreviated_cardinal = bool(
            re.match(r"^\s*(?:N|S|E|W|NE|NW|SE|SW)\b", call_text, re.IGNORECASE)
        )
        has_curve_geometry = any(
            curve_info.get(key) is not None
            for key in ("radius_ft", "delta_deg", "arc_length_ft", "chord_length_ft")
        )
        has_boundary_endpoint = bool(
            re.search(
                r"\bto\s+(?:(?:a|an|the)\s+)?(?:point|corner|pin|rod|monument|stone|stake)\b",
                call_text,
                re.IGNORECASE,
            )
        )
        if (
            not raw_direction
            and not has_abbreviated_cardinal
            and not has_curve_geometry
            and not has_boundary_endpoint
            and not TextParser.detect_meander(call_text)
        ):
            return None

        arc_length_ft = curve_info.get("arc_length_ft")
        if isinstance(arc_length_ft, float) and arc_length_ft > 0.0:
            distance_ft = arc_length_ft
        elif curve_info.get("radius_ft") is not None and curve_info.get("delta_deg") is not None:
            radius_ft = curve_info.get("radius_ft")
            delta_deg = curve_info.get("delta_deg")
            if isinstance(radius_ft, float) and isinstance(delta_deg, float):
                props = BearingConverter.calculate_curve_properties(radius_ft, delta_deg=delta_deg)
            else:
                raise ValueError("Curve info missing numeric radius/delta")
            arc_length_ft = props["arc_length_ft"]
            if arc_length_ft is None:
                raise ValueError("Curve props missing arc length")
            if arc_length_ft > 0.0:
                distance_ft = arc_length_ft
            curve_info.setdefault("arc_length_ft", props["arc_length_ft"])
            curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

        if distance_ft <= 0.0:
            raise ValueError("Missing boundary course distance")

        along, to = TextParser.extract_along_to_fields(call_text)

        monument_type = MonumentClassifier.classify_monument(to) if to else None
        monument_status = MonumentClassifier.classify_monument_status(to or call_text)
        is_meander = TextParser.detect_meander(call_text)

        notes = ""
        cardinal_only = False
        if raw_direction and not parsed_bearing and not is_due_cardinal:
            if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
                cardinal_only = True

        tangent_notes: list[str] = []
        if derived_tangent:
            note = "tangent bearing derived from chord bearing and delta"
            if delta_source:
                note += f" (delta computed from {delta_source} and radius)"
            tangent_notes.append(note)
        elif chord_only:
            tangent_notes.append("tangent bearing not stated - chord bearing only")
        if arc_from_chord:
            tangent_notes.append("arc length computed from chord length and radius")
        tangent_note = "; ".join(tangent_notes)

        if is_meander or "approximate" in call_text.lower():
            notes = "meander / approximate"
            if tangent_note:
                notes += f"; {tangent_note}"
        elif tangent_note:
            notes = tangent_note
        elif not parsed_bearing and not is_due_cardinal:
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
            or re.search(r"\b[NS]\s+\d+°", call_text)
        )
        if not has_direction_intent:
            payload = {
                "course": course,
                "distance_ft": distance_ft,
                "call_preview": _call_preview(call_text),
                "call_hash": _call_hash(call_text),
            }
            if _is_debug_logging_enabled():
                logger.warning(
                    "Rejecting bearingless non-curve call", **payload, call_text=call_text
                )
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

        # A chord-only curve whose tangent could not be derived has no stored bearing.
        chord_only_unresolved = chord_only and not derived_tangent
        is_indefinite = chord_only_unresolved or TextParser.is_indefinite_call(
            direction_text,
            has_bearing=has_stated_tangent or derived_tangent,
        )

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
            radial_bearing=(
                radial_bearing_value if isinstance(radial_bearing_value, str) else None
            ),
            is_meander=is_meander,
            is_tie_in=False,
            is_indefinite=is_indefinite,
            curve_type=curve_type,
            notes=notes if notes else None,
        )

        return call

    @classmethod
    def _audit_single_call(
        cls,
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
        raw_direction = _course_direction(call_text)
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
            parsed = BearingConverter.parse_quadrant_bearing(raw_direction)
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
        distance, unit = TextParser.extract_distance(call_text)
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
            for pattern, _mtype in MonumentClassifier.MONUMENT_PATTERNS:
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
        is_due = (
            BearingConverter.due_cardinal_to_azimuth(raw_direction) is not None
            if raw_direction
            else False
        )
        cardinal_only = False
        if raw_direction and not call.bearing_quadrant and not is_due:
            if _CARDINAL_ONLY_PATTERN.fullmatch(raw_direction.strip()):
                cardinal_only = True

        if not is_due and (cardinal_only or (raw_direction and not call.bearing_quadrant)):
            flags.append("incomplete_bearing")

        if call.is_indefinite:
            flags.append("indefinite")

        if call.is_meander:
            flags.append("meander")

        return transformations, decisions, flags

    PACKED_DMS_PATTERN = _PACKED_DMS_BEARING

    @classmethod
    def extract_direction(cls, text: str) -> str:
        """Extract direction/bearing from call text.

        Args:
            text: Call text

        Returns:
            Direction string (e.g., "S 56°40' W" or "southwesterly")
        """
        packed_match = cls.PACKED_DMS_PATTERN.search(text)
        quadrant_match = BearingConverter.QUADRANT_PATTERN.search(text)
        if quadrant_match and not packed_match:
            return quadrant_match.group(0)

        if packed_match:
            cardinal1 = packed_match.group(1).upper()
            packed_value = float(packed_match.group(2))
            cardinal2 = packed_match.group(3).upper()
            decimal_degrees = BearingConverter.parse_packed_dms(packed_value)
            total_seconds = round(decimal_degrees * 3600, 4)
            degree, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            seconds_text = f"{seconds:.4f}".rstrip("0").rstrip(".")
            if seconds < 10:
                seconds_text = f"0{seconds_text}"
            return f"{cardinal1} {int(degree)}°{int(minutes):02d}'{seconds_text}\" {cardinal2}"

        # "due {cardinal}" check -- must come before simple cardinal so "due North"
        # is captured as the full phrase, not truncated to "north".
        due_cardinal_match = re.search(
            r"\bdue\s+(north|south|east|west|N|S|E|W)\b",
            text,
            re.IGNORECASE,
        )
        if due_cardinal_match:
            return due_cardinal_match.group(0).lower()

        # "due {cardinal}" check -- must come before simple cardinal so "due North"
        # is captured as the full phrase, not truncated to "north".
        due_cardinal_match = re.search(
            r"\bdue\s+(north|south|east|west|N|S|E|W)\b",
            text,
            re.IGNORECASE,
        )
        if due_cardinal_match:
            return due_cardinal_match.group(0).lower()

        # Compound compass point check (32-point system) — must come before
        # simple cardinal check so "North by East" is not truncated to "North"
        compound_compass_names = sorted(
            [name for name in BearingConverter.COMPASS_POINTS if " " in name or "-" in name],
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

    @classmethod
    def extract_distance_alternate(cls, text: str) -> float:
        """Extract distance using alternate patterns.

        Some deeds use formats like "125.26' along..." instead of "125.26 feet".

        Args:
            text: Call text

        Returns:
            Distance value (0.0 if not found)
        """
        feet_match = re.search(rf"({_COMMA_NUMBER})\s*(?:feet|ft)\b", text, re.IGNORECASE)
        if feet_match:
            return parse_comma_number(feet_match.group(1))

        apostrophe_match = re.search(
            r"(?<!°)(\d+(?:\.\d+)?)\s*'(?=(?:\s+(?:along|to)\b|[.,;)]|$))",
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
                r"\d+°\s*\d+(?:\.\d+)?\s*\x27\s*$",
                prefix,
            ):
                return 0.0
            return float(apostrophe_match.group(1))

        return 0.0

    @classmethod
    def extract_curve_info(cls, text: str) -> dict[str, float | str | None]:
        """Extract curve information from call text.

        Args:
            text: Call text

        Returns:
            Dict with curve properties (empty if no curve)
        """
        curve_info: dict[str, float | str | None] = {}

        if not re.search(r"\b(?:curve|spiral|transition)\b", text, re.IGNORECASE):
            return curve_info

        match = cls.CURVE_PATTERN.search(text)
        if match and _is_bearing_degree(text, match.start(4)):
            # The first degree value belongs to a bearing (e.g. the chord's), not
            # the central angle; only an explicitly labelled delta may be used.
            match = None
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
                rf"arc\s+(?:length|distance)\s+(?:of\s+)?({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
                text,
                re.IGNORECASE,
            )
            arc_length: float | None = None
            if arc_length_match:
                arc_raw = parse_comma_number(arc_length_match.group(1))
                arc_unit = _normalize_unit_token(arc_length_match.group(2))
                arc_length = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

            props = BearingConverter.calculate_curve_properties(radius, delta_deg=delta_deg)
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
                rf"radius\s+(?:of\s+)?({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?", text, re.IGNORECASE
            )
            if radius_match:
                radius_raw = parse_comma_number(radius_match.group(1))
                radius_unit = _normalize_unit_token(radius_match.group(2))
                curve_info["radius_ft"] = ConversionFactors.convert_to_feet(radius_raw, radius_unit)

            delta_match = re.search(
                r"(?:delta|central\s+angle)\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:°|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?(?:\s*(\d+(?:\.\d+)?)(?:\"|\s+seconds?))?",
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
                rf"arc\s+(?:length|distance)\s+(?:of\s+)?({_COMMA_NUMBER})\s*({_UNIT_TOKEN})?",
                text,
                re.IGNORECASE,
            )
            if arc_match:
                arc_raw = parse_comma_number(arc_match.group(1))
                arc_unit = _normalize_unit_token(arc_match.group(2))
                curve_info["arc_length_ft"] = ConversionFactors.convert_to_feet(arc_raw, arc_unit)

            # Degree of curvature → radius conversion
            doc_match = re.search(
                r"degree\s+of\s+(?:curve|curvature)\s+(?:of\s+)?"
                r"(\d+(?:\.\d+)?)(?:°|(?:\s+)?degrees?)"
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
                    curve_info["radius_ft"] = BearingConverter.degree_of_curvature_to_radius(
                        doc_deg
                    )

        radius_ft = curve_info.get("radius_ft")
        curve_delta_deg = curve_info.get("delta_deg")
        if isinstance(radius_ft, float) and isinstance(curve_delta_deg, float):
            props = BearingConverter.calculate_curve_properties(
                radius_ft, delta_deg=curve_delta_deg
            )
            if curve_info.get("arc_length_ft") is None:
                curve_info["arc_length_ft"] = props["arc_length_ft"]
            curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

        chord_bearing_match = re.search(
            r"(?:the\s+)?chord\s+(?:of\s+which\s+)?(?:bears|bearing)\s+(.+?)(?:[,\s]\s*(\d+(?:\.\d+)?)\s*(?:feet|ft))?(?:\s*$|\s*(?:to|along|;|\.))",
            text,
            re.IGNORECASE,
        )
        if chord_bearing_match:
            raw_chord_bearing = chord_bearing_match.group(1).strip().rstrip(",")
            normalized = _normalize_bearing_forms(raw_chord_bearing)
            bearing_match = BearingConverter.QUADRANT_PATTERN.search(normalized)
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
            normalized_radial = _normalize_bearing_forms(raw_radial)
            radial_bearing_match = BearingConverter.QUADRANT_PATTERN.search(normalized_radial)
            if radial_bearing_match:
                curve_info["radial_bearing"] = radial_bearing_match.group(0)

        return curve_info

    @classmethod
    def mark_tie_in_calls(
        cls, calls: list[DeedCall], poc_description: str | None
    ) -> list[DeedCall]:
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
            if call.to and TextParser.is_closure_to_pob("to " + call.to):
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

    @classmethod
    def enrich_calls_with_azimuths(cls, calls: list[DeedCall]) -> list[DeedCall]:
        """Add azimuths to calls that have quadrant bearings but missing azimuths.

        Args:
            calls: List of DeedCall objects

        Returns:
            List of enriched DeedCall objects
        """
        enriched = []
        for call in calls:
            enriched.append(BearingConverter.enrich_call_with_azimuth(call))
        return enriched
