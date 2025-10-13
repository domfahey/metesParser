"""Extract individual deed calls from legal descriptions.

Parses normalized text to create structured DeedCall objects.
"""

import re

from .bearing_converter import BearingConverter
from .models import ConversionFactors, DeedCall
from .text_parser import TextParser


class CallExtractor:
    """Extract and structure deed calls from legal description text."""

    # Pattern for curve information
    CURVE_PATTERN = re.compile(
        r"curve\s+to\s+the\s+(left|right).*?radius\s+of\s+(\d+(?:\.\d+)?)\s*(?:feet|ft)?.*?"
        r"(?:delta\s+(?:angle\s+)?of\s+)?(\d+)°(?:\s*(\d+)')?\s*(?:(\d+(?:\.\d+)?)\")?"
        r".*?(?:arc\s+length\s+of\s+)?(\d+(?:\.\d+)?)\s*(?:feet|ft)?",
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def extract_calls(cls, text: str, distance_unit: str = "feet") -> list[DeedCall]:
        """Extract all calls from normalized legal description text.

        Args:
            text: Normalized legal description text
            distance_unit: Primary distance unit (feet, poles, etc.)

        Returns:
            List of DeedCall objects
        """
        # First normalize the text
        normalized = TextParser.normalize_legal_description(text)

        # Split into individual calls
        call_texts = TextParser.split_into_calls(normalized)

        calls = []
        course_num = 1
        for call_text in call_texts:
            call = cls.extract_single_call(
                call_text, course=course_num, distance_unit=distance_unit
            )
            if call:
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
            bearing_quadrant = f"{cardinal1} {deg_int}°{round(minutes):02d}' {cardinal2}"
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

        if curve_info.get("arc_length_ft"):
            distance_ft = curve_info["arc_length_ft"]
        elif curve_info.get("radius_ft") and curve_info.get("delta_deg"):
            props = BearingConverter.calculate_curve_properties(
                curve_info["radius_ft"], delta_deg=curve_info["delta_deg"]
            )
            distance_ft = props["arc_length_ft"]
            curve_info.setdefault("arc_length_ft", props["arc_length_ft"])
            curve_info.setdefault("chord_length_ft", props["chord_length_ft"])

        # Extract along/to fields
        along, to = TextParser.extract_along_to_fields(call_text)

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

        # Build DeedCall
        call = DeedCall(
            course=course,
            direction_text=direction_text,
            bearing_quadrant=bearing_quadrant,
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=distance_ft,
            curve_dir=curve_info.get("direction"),
            radius_ft=curve_info.get("radius_ft"),
            delta_deg=curve_info.get("delta_deg"),
            arc_length_ft=curve_info.get("arc_length_ft"),
            chord_bearing=curve_info.get("chord_bearing"),
            chord_length_ft=curve_info.get("chord_length_ft"),
            along=along if along else None,
            to=to if to else None,
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

        Some deeds use formats like "125.26' along..." instead of "125.26 feet"

        Args:
            text: Call text

        Returns:
            Distance value (0.0 if not found)
        """
        # Pattern: number followed by ' or "
        pattern = r"(\d+(?:\.\d+)?)\s*(?:'|feet|ft)\b"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return 0.0

    @classmethod
    def extract_curve_info(cls, text: str) -> dict:
        """Extract curve information from call text.

        Args:
            text: Call text

        Returns:
            Dict with curve properties (empty if no curve)
        """
        curve_info: dict = {}

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

            arc_length_str = match.group(6)

            # Calculate properties
            props = BearingConverter.calculate_curve_properties(radius, delta_deg=delta_deg)
            arc_length = (
                float(arc_length_str) if arc_length_str is not None else props["arc_length_ft"]
            )

            curve_info = {
                "direction": direction,
                "radius_ft": radius,
                "delta_deg": delta_deg,
                "arc_length_ft": arc_length,
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
                r"delta\s+(?:angle\s+)?(?:of\s+)?(\d+)(?:°|(?:\s+)?degrees?)(?:\s*(\d+)')?",
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

        if curve_info.get("radius_ft") and curve_info.get("delta_deg"):
            props = BearingConverter.calculate_curve_properties(
                curve_info["radius_ft"], delta_deg=curve_info["delta_deg"]
            )
            if not curve_info.get("arc_length_ft"):
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
