"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
"""

import hashlib
import logging
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
from .text_parser import (
    _COMMA_NUMBER,
    _UNSUPPORTED_COMPOUND_PATTERN,
    TextParser,
    parse_comma_number,
)

logger = structlog.get_logger(__name__)

_CARDINAL_ONLY_PATTERN = re.compile(
    r"(north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?",
    re.IGNORECASE,
)

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


# "...to a point corner to X, which last mentioned point is the place of beginning":
# the course ends at the true POB, so it and the courses before it (back to the
# previous closing course) are tie lines.
_RESTATED_POB_PATTERN = re.compile(
    r"\blast\s+mentioned\s+point\s+is\s+the\s+(?:place|point)\s+of\s+beginning\b",
    re.IGNORECASE,
)
_CLOSES_TO_POB_PATTERN = re.compile(
    r"\b(?:to|for)\s+(?:the\s+|a\s+)?(?:(?:point|place)\s+(?:and\s+place\s+)?of\s+)?beginning\b",
    re.IGNORECASE,
)


def _mark_restated_pob_tie_lines(calls: list[DeedCall], call_texts: list[str]) -> list[DeedCall]:
    """Mark courses leading to a restated place of beginning as tie lines."""
    segment_start = 0
    tie_end: tuple[int, int] | None = None
    for i, call_text in enumerate(call_texts):
        if _CLOSES_TO_POB_PATTERN.search(call_text):
            segment_start = i + 1
        elif _RESTATED_POB_PATTERN.search(call_text):
            tie_end = (segment_start, i)
    if tie_end is None:
        return calls
    start, end = tie_end
    return [
        call.model_copy(update={"is_tie_in": True}) if start <= i <= end else call
        for i, call in enumerate(calls)
    ]


# "said point being the following two courses and distances from the intersection":
# the first courses run from the reference point to the POB, so they are tie lines.
_PREAMBLE_TIE_COURSES_PATTERN = re.compile(
    r"\bbeing\s+the\s+following\s+(?:(\w+)(?:\s+\(\d+\))?\s+)?courses?\s+and\s+distances?\s+from\b",
    re.IGNORECASE,
)
_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

# "Commencing at the corner of Lot 15; thence ... for the point of beginning; thence ...":
# the courses from the commencement point to the POB are tie lines.
_COMMENCEMENT_PATTERN = re.compile(r"\b(?:COMMENCING|STARTING)\s+at\b", re.IGNORECASE)


def _preamble_tie_course_count(preamble: str, call_texts: list[str]) -> int:
    """Return how many leading courses the preamble says lead to the POB.

    Without a count ("the following courses and distances from", or a commencement
    point), the tie courses end at the first course reaching the place of beginning while
    more courses follow.
    """
    match = _PREAMBLE_TIE_COURSES_PATTERN.search(preamble)
    if not match and not _COMMENCEMENT_PATTERN.search(preamble):
        return 0
    if match is None or match.group(1) is None:
        return next(
            (
                i + 1
                for i, text in enumerate(call_texts[:-1])
                if _CLOSES_TO_POB_PATTERN.search(text)
            ),
            0,
        )
    count = match.group(1).lower()
    return int(count) if count.isdigit() else _COUNT_WORDS.get(count, 0)


def _mark_preamble_tie_courses(calls: list[DeedCall], count: int) -> list[DeedCall]:
    """Mark the leading courses the preamble counts as tie lines."""
    if not count or count >= len(calls):
        return calls
    return [
        call.model_copy(update={"is_tie_in": True}) if i < count else call
        for i, call in enumerate(calls)
    ]


# SCHEDULE A-1: one property per schedule in a multi-property deed (mirrors
# mp_parse.tracts._SCHEDULE_MARKER; a lone "Schedule A" names the attachment).
_SCHEDULE_MARKER = re.compile(
    # "Parcel 2:" / "PARCEL A:" / "TRACT #2:" / "Tract #2" headings also end the clauses before
    # them, so an EXCEPT in Parcel 1 does not extend into Parcel 2.
    r"\bSCHEDULE\s+[A-Z]-?\d+\b"
    r"|\b(?:PARCEL|TRACT)\s+(?:#\s*|NO\.?\s*)?(?:\d+[A-Z]?|[A-Z])\s*:"
    r"|\b(?:PARCEL|TRACT)\s*(?:#\s*|NO\.?\s*)\d+[A-Z]?\b",
    re.IGNORECASE,
)

# "the boundary line of Tract #1 of Haddonfield Estates": a reference, not a heading
# (mirrors mp_parse.tracts._REFERENCE_BEFORE)
_MARKER_REFERENCE_BEFORE = re.compile(r"(?:\b(?:of|to|said|with|from|by)|,)\s*$", re.IGNORECASE)


def _split_schedules(text: str) -> list[str]:
    """Split a multi-property description so each schedule's courses split on their own."""
    # A title or preamble before the first marker carries no courses; it stays with the first.
    starts = [
        match.start()
        for match in _SCHEDULE_MARKER.finditer(text)
        if not _MARKER_REFERENCE_BEFORE.search(text, 0, match.start())
    ]
    if starts and not re.search(r"\bTHENCE\b", text[: starts[0]], re.IGNORECASE):
        starts = starts[1:]
    bounds = [0, *starts, len(text)]
    return [
        description
        for a, b in zip(bounds, bounds[1:], strict=False)
        if text[a:b].strip()
        for description in _split_complete_descriptions(text[a:b])
    ]


# A description opens at its commencement or point of beginning and closes at its point of
# beginning (mirrors mp_parse.tracts.split_complete_descriptions)
_DESCRIPTION_OPENING = re.compile(r"\b(?:COMMENCING|BEGINNING)\s+at\b", re.IGNORECASE)
_CLAUSE_KEYWORD = re.compile(
    r"\b(?:(?:LESS\s+AND\s+)?EXCEPT(?:ING)?|EXCLUDING|ALSO|INCLUDING|EASEMENT)\b", re.IGNORECASE
)
_DESCRIPTION_CLOSE = re.compile(
    r"(?:POINT\s+(?:AND\s+PLACE\s+)?OF\s+BEGINNING|place\s+of\s+BEGINNING|POB)\b",
    re.IGNORECASE,
)


def _find_description_close(text: str, start: int) -> re.Match[str] | None:
    """Find the closure after start, skipping references and a POB reached by a tie course."""
    for match in _DESCRIPTION_CLOSE.finditer(text, start):
        if re.search(r"(?<!\bto\s)\bsaid\s+$", text[: match.start()], re.IGNORECASE):
            continue
        if re.match(r"\s*[,;]?\s*thence\b", text[match.end() :], re.IGNORECASE):
            continue
        return match
    return None


def _split_complete_descriptions(text: str) -> list[str]:
    """Split text holding complete descriptions in sequence.

    "...to the point of beginning. Combined Legal Description: ... Commencing at ..." opens
    another description once the previous one has closed at its point of beginning. An
    excepted, added or easement parcel ("..., EXCEPT ... beginning at ...") stays with its
    description.
    """
    parts: list[str] = []
    start = search_from = 0
    while opening := _DESCRIPTION_OPENING.search(text, search_from):
        close = _find_description_close(text, opening.end())
        if close is None:
            break
        following = _DESCRIPTION_OPENING.search(text, close.end())
        if following is None:
            break
        between = text[close.end() : following.start()]
        if re.search(r"\bTHENCE\b", between, re.IGNORECASE):
            break
        if not _CLAUSE_KEYWORD.search(between):
            parts.append(text[start : close.end()])
            start = close.end()
        search_from = close.end()
    parts.append(text[start:])
    return [part for part in parts if part.strip()]


# "thence", "thence:" or "thence from the beginning point;" before the first numbered course
_STANDALONE_THENCE = (
    r"\s*THENCE(?:\s+from\s+the\s+(?:beginning\s+point|point\s+of\s+beginning))?\s*[:;]?\s*"
)

# "thence along the line of lands of X, the following two courses and distances;" introduces
# the next courses and carries none itself
_COURSE_INTRO_PATTERN = re.compile(
    r"\bthe\s+following\s+(?:\w+\s+)?(?:\(\d+\)\s+)?courses?(?:\s+and\s+distances?)?\s*[:;,.]?\s*$",
    re.IGNORECASE,
)


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


# "...551.39 feet to a point on the Westerly line, said point also being a point on a
# non-tangential curve to the left": the endpoint lies on the next course's curve.
_ENDPOINT_ON_CURVE = re.compile(
    r",?\s*said\s+point\s+(?:also\s+)?being\s+(?:a\s+point\s+)?on\s+(?:a|the)\s+[^;]*?\bcurve\b.*",
    re.IGNORECASE | re.DOTALL,
)


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
    def _trailing_thence_course(cls, prefix: str) -> str:
        """Return the course ending the preamble when courses end with "thence".

        "...Burnt Mill Road. N 40°41'31\" E a distance of 483.13 feet to a point thence;"
        """
        boundaries = list(re.finditer(r"[.;:]\s+|\n", prefix))
        tail = prefix[boundaries[-1].end() :] if boundaries else ""
        if not tail.strip():
            return ""
        return (
            tail
            if cls._is_initial_course_prefix(tail) or cls._is_marked_bearing_course(tail)
            else ""
        )

    @classmethod
    def _is_marked_bearing_course(cls, text: str) -> bool:
        """Return whether text is a lettered/numbered course stating a bearing ("(A) Along X, N 73° W")."""
        if not re.match(r"\s*(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s", text):
            return False
        try:
            direction = cls.extract_direction(text)
        except ValueError:
            return False
        return bool(direction and BearingConverter.parse_quadrant_bearing(direction))

    @classmethod
    def _is_initial_course_prefix(cls, prefix: str) -> bool:
        """Return whether text before THENCE starts with a supported bearing."""
        candidate = re.sub(r"^\s*(?:(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s*)?", "", prefix)
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

        tracts = [
            clause
            for schedule_text in _split_schedules(normalized)
            for clause in TextParser.split_exception_clauses(schedule_text)
        ]

        calls: list[DeedCall] = []
        course_num = 1

        for tract_text, is_exception_tract in tracts:
            tract_calls: list[DeedCall] = []
            tract_call_texts: list[str] = []
            # Remove a recognized commencement/POB preamble. A description may
            # legitimately begin with its first course and introduce THENCE later.
            thence_match = re.search(r"\bTHENCE\b", tract_text, re.IGNORECASE)
            has_thence_marker = thence_match is not None
            prefix = tract_text[: thence_match.start()] if thence_match else ""
            # "(1) Along ..., N 32°22'34\" W, 41.23 feet to a point in same;" may come before the
            # first THENCE: the courses then start at the first numbered course.
            first_marker = re.search(
                r"(?:^|\n)\s*(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s+", tract_text, re.MULTILINE
            )
            numbered_before_thence = bool(
                thence_match and first_marker and first_marker.start() < thence_match.start()
            )
            if numbered_before_thence and first_marker:
                prefix = tract_text[: first_marker.start()]
            has_beginning_preamble = re.match(
                r"\s*(?:BEGINNING|COMMENCING|POINT\s+OF\s+BEGINNING|POB|TPOB|RPOB)\b",
                prefix,
                re.IGNORECASE,
            )
            has_initial_course = bool(thence_match and cls._is_initial_course_prefix(prefix))
            if (
                thence_match
                and not numbered_before_thence
                and (has_beginning_preamble or not has_initial_course)
            ):
                tract_text = (
                    cls._trailing_thence_course(prefix) + tract_text[thence_match.start() :]
                )

            has_numbered_course_markers = bool(
                re.search(
                    r"(?:^|\n)\s*(?:\(\d+\)|\([A-Za-z]\)|\d+[.)])\s+",
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
                    standalone_thence = re.fullmatch(
                        _STANDALONE_THENCE, call_text, re.I
                    ) or _COURSE_INTRO_PATTERN.search(call_text)
                    explicit_course = not standalone_thence and (
                        has_thence_marker or has_numbered_course_markers
                    )
                    if strict and (
                        explicit_course
                        or cls.extract_direction(call_text)
                        or re.search(r"\b(?:[NSEW])\s+\d", call_text, re.I)
                        or re.search(r"\b(?:curv(?:e|ed|ing)|spiral|transition)\b", call_text, re.I)
                    ):
                        raise ValueError(f"Malformed course {source_course}: {call_text.strip()!r}")
                    continue

                if is_exception_tract:
                    call = call.model_copy(update={"is_exception": True})
                tract_calls.append(call)
                tract_call_texts.append(call_text)

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

            tract_calls = _mark_preamble_tie_courses(
                tract_calls, _preamble_tie_course_count(prefix, tract_call_texts)
            )
            calls.extend(_mark_restated_pob_tie_lines(tract_calls, tract_call_texts))

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

        raw_direction = cls.extract_direction(_boundary_course_text(call_text))
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
            if _UNSUPPORTED_COMPOUND_PATTERN.search(course_text):
                raise ValueError("Unsupported component in compound course distance")
            distance = cls.extract_distance_alternate(course_text)
            unit = distance_unit

        distance_ft = ConversionFactors.convert_to_feet(distance, unit)

        curve_info = cls.extract_curve_info(_ENDPOINT_ON_CURVE.sub("", call_text))

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

        if is_meander or "approximate" in call_text.lower():
            notes = "meander / approximate"
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

        is_indefinite = TextParser.is_indefinite_call(
            direction_text, has_bearing=parsed_bearing is not None or is_due_cardinal
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
        raw_direction = cls.extract_direction(_boundary_course_text(call_text))
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

    PACKED_DMS_PATTERN = re.compile(
        r"(N|S)\s+(\d{1,3}\.\d+)°\s*(E|W)",
        re.IGNORECASE,
    )

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

        if not re.search(r"\b(?:curv(?:e|ed|ing)|spiral|transition)\b", text, re.IGNORECASE):
            return curve_info

        match = cls.CURVE_PATTERN.search(text)
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
            # "curve to the left", "curving to the right", "turning towards the left"
            dir_match = re.search(
                r"\b(?:curve|curving|turning)\s+(?:to|towards?)\s+the\s+(left|right)\b",
                text,
                re.IGNORECASE,
            )
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
                r"delta\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:°|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?(?:\s*(\d+(?:\.\d+)?)(?:\"|\s+seconds?))?",
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
            r"(?:the\s+)?chord\s+(?:of\s+which\s+)?bears\s+(.+?)(?:,\s*(\d+(?:\.\d+)?)\s*(?:feet|ft))?(?:\s*$|\s*(?:to|along|;|\.))",
            text,
            re.IGNORECASE,
        )
        if chord_bearing_match:
            raw_chord_bearing = chord_bearing_match.group(1).strip().rstrip(",")
            normalized = TextParser.standardize_cardinal_directions(raw_chord_bearing)
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
            normalized_radial = TextParser.standardize_cardinal_directions(raw_radial)
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

        Calls already marked from their course text are kept, and a closing course is not a
        tie line: marking across the flat calls would otherwise reach into another tract.

        Returns:
            List of DeedCall objects with is_tie_in set appropriately
        """
        if not poc_description or any(call.is_tie_in for call in calls):
            return calls

        pob_index = None
        for i, call in enumerate(calls):
            if call.to and TextParser.is_closure_to_pob("to " + call.to):
                pob_index = i
                break

        if pob_index is None or pob_index == len(calls) - 1:
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
