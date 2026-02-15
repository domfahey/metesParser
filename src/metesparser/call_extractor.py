"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
"""

import re
from typing import Literal

from .bearing_converter import BearingConverter
from .models import ConversionFactors, DeedCall
from .text_parser import TextParser

MonumentType = Literal[
    "iron_rod",
    "iron_pin",
    "iron_pipe",
    "stone",
    "concrete",
    "wooden_post",
    "brass_cap",
    "rebar",
    "railroad_spike",
    "nail",
    "other",
]


class MonumentClassifier:
    """Classify survey monument types from text descriptions."""

    # Monument type patterns (order matters - more specific first)
    MONUMENT_PATTERNS: list[tuple[str, MonumentType]] = [
        # Iron monuments
        (r"\biron\s+rod\b", "iron_rod"),
        (r"\biron\s+pin\b", "iron_pin"),
        (r"\biron\s+pipe\b", "iron_pipe"),
        (r"\biron\s+stake\b", "iron_rod"),
        (r"\biron\s+monument\b", "iron_rod"),
        (r"\brebar\b", "rebar"),
        (r"\b(?:mag|magnetic)\s+nail\b", "nail"),
        (r"\bnail\b", "nail"),
        # Railroad markers
        (r"\brailroad\s+(?:spike|tie)\b", "railroad_spike"),
        (r"\bgin\s+(?:spike|pole)\b", "railroad_spike"),
        # Stone/concrete
        (r"\bstone\s+monument\b", "stone"),
        (r"\bstone\b", "stone"),
        (r"\bconcrete\s+monument\b", "concrete"),
        (r"\bconcrete\b", "concrete"),
        # Brass
        (r"\bbrass\s+(?:cap|marker|monument)\b", "brass_cap"),
        # Wood
        (r"\bwooden\s+(?:post|stake)\b", "wooden_post"),
        (r"\bhedge\s+post\b", "wooden_post"),
        (r"\bwood\s+stake\b", "wooden_post"),
        # Landscape markers
        (r"\blandscap(?:e|ing)\s+(?:rod|pin)\b", "iron_rod"),
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

        # Check for generic monument keywords
        if re.search(r"\bmonument\b", text_lower):
            return "other"

        return None


class CallExtractor:
    """Extract and structure deed calls from legal description text."""

    # Pattern for curve information
    CURVE_PATTERN = re.compile(
        r"curve\s+to\s+the\s+(left|right).*?radius\s+of\s+(\d+(?:\.\d+)?)\s*(?:feet|ft)?.*?"
        r"(?:delta\s+(?:angle\s+)?of\s+)?(\d+(?:\.\d+)?)(?:°|\s+degrees?)(?:\s*(\d+)')?(?:\s*(\d+(?:\.\d+)?)\")?",
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def extract_calls(cls, text: str, distance_unit: str = "feet") -> list[DeedCall]:
        """Extract all calls from normalized legal description text.

        Handles exception clauses (EXCEPT, LESS AND EXCEPT, ALSO, INCLUDING)
        and marks calls accordingly.

        Args:
            text: Normalized legal description text (should already be normalized)
            distance_unit: Primary distance unit (feet, poles, etc.)

        Returns:
            List of DeedCall objects
        """
        # Normalize legal description text (idempotent if already cleaned)
        normalized = TextParser.normalize_legal_description(text)

        # Split into main tract and exception/inclusion tracts
        tracts = TextParser.split_exception_clauses(normalized)

        calls: list[DeedCall] = []
        course_num = 1

        for tract_text, is_exception_tract in tracts:
            # Split tract into individual calls
            call_texts = TextParser.split_into_calls(tract_text)

            for call_text in call_texts:
                call = cls.extract_single_call(
                    call_text, course=course_num, distance_unit=distance_unit
                )
                if call:
                    # Mark as exception if this is an exception tract
                    if is_exception_tract:
                        call = call.model_copy(update={"is_exception": True})
                    calls.append(call)
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
        # Skip POB lines (BEGINNING, COMMENCING, etc.)
        if re.match(r"^\s*(BEGINNING|COMMENCING|POB)\b", call_text, re.IGNORECASE):
            return None

        # Extract direction (bearing)
        raw_direction = cls.extract_direction(call_text)
        direction_text = raw_direction if raw_direction else call_text.strip()

        # Try to parse quadrant bearing
        bearing_quadrant = None
        azimuth = None

        parsed_bearing = (
            BearingConverter.parse_quadrant_bearing(raw_direction) if raw_direction else None
        )
        if parsed_bearing:
            cardinal1, degrees, cardinal2 = parsed_bearing
            deg_int = int(degrees)
            minutes = (degrees - deg_int) * 60

            # Handle rounding edge case: if minutes rounds to 60, carry to degrees
            rounded_minutes = round(minutes)
            if rounded_minutes >= 60:
                rounded_minutes = 0
                deg_int += 1

            bearing_quadrant = f"{cardinal1} {deg_int}°{rounded_minutes:02d}' {cardinal2}"
            azimuth = BearingConverter.quadrant_to_azimuth(cardinal1, degrees, cardinal2)
        else:
            # Could be a meander/cardinal-only (e.g., "southwesterly")
            bearing_quadrant = None
            azimuth = None

        # Extract distance
        distance, unit = TextParser.extract_distance(call_text)
        if distance == 0:
            # Try alternate pattern
            distance = cls.extract_distance_alternate(call_text)
            unit = distance_unit

        # Convert to feet
        distance_ft = ConversionFactors.convert_to_feet(distance, unit)

        # Extract curve information if present
        curve_info = cls.extract_curve_info(call_text)

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

        # Extract along/to fields
        along, to = TextParser.extract_along_to_fields(call_text)

        # Classify monument type from 'to' field
        monument_type = MonumentClassifier.classify_monument(to) if to else None

        # Check for meander/incomplete flags
        notes = ""
        cardinal_only = False
        if raw_direction and not parsed_bearing:
            if re.fullmatch(
                r"(north|south|east|west|northeast|northwest|southeast|southwest)(?:erly)?",
                raw_direction.strip(),
                flags=re.IGNORECASE,
            ):
                cardinal_only = True

        if "meander" in call_text.lower() or "approximate" in call_text.lower():
            notes = "meander / approximate"
        elif not parsed_bearing:
            notes = "incomplete bearing - cardinal only" if cardinal_only else "incomplete bearing"

        # Skip if no valid distance found (not a real call, just descriptive text)
        if distance_ft <= 0.0:
            return None

        # Build DeedCall
        curve_dir = curve_info.get("direction")
        curve_direction: Literal["left", "right"] | None
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
            is_exception=False,  # Will be set later when parsing EXCEPT clauses
            notes=notes if notes else None,
        )

        return call

    @classmethod
    def extract_direction(cls, text: str) -> str:
        """Extract direction/bearing from call text.

        Args:
            text: Call text

        Returns:
            Direction string (e.g., "S 56°40' W" or "southwesterly")
        """
        # Try quadrant bearing first
        quadrant_match = BearingConverter.QUADRANT_PATTERN.search(text)
        if quadrant_match:
            return quadrant_match.group(0)

        # Try cardinal-only directions
        cardinal_pattern = (
            r"\b(north(?:erly)?|south(?:erly)?|east(?:erly)?|west(?:erly)?|"
            r"northeast(?:erly)?|northwest(?:erly)?|southeast(?:erly)?|southwest(?:erly)?)\b"
        )

        cardinal_match = re.search(cardinal_pattern, text, re.IGNORECASE)
        if cardinal_match:
            return cardinal_match.group(0).lower()

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
        feet_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:feet|ft)\b", text, re.IGNORECASE)
        if feet_match:
            return float(feet_match.group(1))

        apostrophe_match = re.search(
            r"(?<!°)(\d+(?:\.\d+)?)\s*'(?=(?:\s+(?:along|to)\b|[.,;)]|$))",
            text,
            re.IGNORECASE,
        )
        if apostrophe_match:
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

        # Check if it's a curve
        if "curve" not in text.lower():
            return curve_info

        # Try to match full curve pattern
        match = cls.CURVE_PATTERN.search(text)
        if match:
            direction = match.group(1).lower()  # left or right
            radius = float(match.group(2))
            delta_deg = float(match.group(3))

            # Add minutes/seconds if present
            if match.group(4):
                delta_deg += float(match.group(4)) / 60.0
            if match.group(5):
                delta_deg += float(match.group(5)) / 3600.0

            arc_length_match = re.search(
                r"arc\s+length\s+of\s+(\d+(?:\.\d+)?)", text, re.IGNORECASE
            )
            arc_length = float(arc_length_match.group(1)) if arc_length_match else None

            # Calculate properties
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
            # Try simpler patterns
            # "curve to the right/left"
            dir_match = re.search(r"curve\s+to\s+the\s+(left|right)", text, re.IGNORECASE)
            if dir_match:
                curve_info["direction"] = dir_match.group(1).lower()

            # "radius of X" or "radius X"
            radius_match = re.search(r"radius\s+(?:of\s+)?(\d+(?:\.\d+)?)", text, re.IGNORECASE)
            if radius_match:
                curve_info["radius_ft"] = float(radius_match.group(1))

            # "delta X°Y'" or "delta X degrees"
            delta_match = re.search(
                r"delta\s+(?:angle\s+)?(?:of\s+)?(\d+(?:\.\d+)?)(?:°|(?:\s+)?degrees?)(?:\s*(\d+(?:\.\d+)?)')?",
                text,
                re.IGNORECASE,
            )
            if delta_match:
                delta = float(delta_match.group(1))
                if delta_match.group(2):
                    delta += float(delta_match.group(2)) / 60.0
                curve_info["delta_deg"] = delta

            # "arc length of X"
            arc_match = re.search(r"arc\s+length\s+of\s+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
            if arc_match:
                curve_info["arc_length_ft"] = float(arc_match.group(1))

        radius_ft = curve_info.get("radius_ft")
        curve_delta_deg = curve_info.get("delta_deg")
        if isinstance(radius_ft, float) and isinstance(curve_delta_deg, float):
            props = BearingConverter.calculate_curve_properties(
                radius_ft, delta_deg=curve_delta_deg
            )
            if curve_info.get("arc_length_ft") is None:
                curve_info["arc_length_ft"] = props["arc_length_ft"]
            curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

        return curve_info

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
