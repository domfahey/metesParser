"""Distance unit types and conversion factors."""

from typing import ClassVar, Literal

DistanceUnit = Literal[
    "feet",
    "us_survey_feet",
    "poles",
    "rods",
    "perches",
    "perch",
    "chains",
    "links",
    "link",
    "varas",
    "arpents",
    "toises",
    "furlongs",
    "meters",
    "miles",
    "engineer_chains",
    "engineer_links",
]


class ConversionFactors:
    """Unit conversion factors."""

    POLE_TO_FEET: float = 16.5
    ROD_TO_FEET: float = 16.5
    PERCH_TO_FEET: float = 16.5
    CHAIN_TO_FEET: float = 66.0
    LINK_TO_FEET: float = 0.66
    VARA_TO_FEET: float = 2.778
    ARPENT_TO_FEET: float = 191.8
    TOISE_TO_FEET: float = 6.395
    FURLONG_TO_FEET: float = 660.0
    MILE_TO_FEET: float = 5280.0
    METER_TO_FEET: float = 3.28084
    ENGINEER_CHAIN_TO_FEET: float = 100.0
    ENGINEER_LINK_TO_FEET: float = 1.0
    ACRE_TO_SQ_FEET: float = 43560.0
    FOOT_TO_METERS: float = 0.3048
    US_SURVEY_FOOT_TO_METERS: float = 0.30480061
    US_SURVEY_FOOT_TO_FEET: float = US_SURVEY_FOOT_TO_METERS / FOOT_TO_METERS

    _UNIT_TO_FEET: ClassVar[dict[str, float]] = {
        "feet": 1.0,
        "us_survey_feet": US_SURVEY_FOOT_TO_FEET,
        "poles": POLE_TO_FEET,
        "rods": ROD_TO_FEET,
        "perch": PERCH_TO_FEET,
        "perches": PERCH_TO_FEET,
        "chains": CHAIN_TO_FEET,
        "link": LINK_TO_FEET,
        "links": LINK_TO_FEET,
        "varas": VARA_TO_FEET,
        "arpents": ARPENT_TO_FEET,
        "toises": TOISE_TO_FEET,
        "furlongs": FURLONG_TO_FEET,
        "meters": METER_TO_FEET,
        "miles": MILE_TO_FEET,
        "engineer_chains": ENGINEER_CHAIN_TO_FEET,
        "engineer_links": ENGINEER_LINK_TO_FEET,
    }

    @classmethod
    def convert_to_feet(cls, value: float, unit: str) -> float:
        """Convert a distance value to feet."""
        normalized_unit = unit.strip().lower()
        if normalized_unit not in cls._UNIT_TO_FEET:
            raise ValueError(f"Unsupported distance unit: {unit}")
        return value * cls._UNIT_TO_FEET[normalized_unit]
