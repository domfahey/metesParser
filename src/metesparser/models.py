"""Pydantic models for metes and bounds deed parsing."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

CurveDirection = Literal["left", "right"]
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
    "pk_nail",
    "hub_and_tack",
    "monitoring_well",
    "capped_pin",
    "capped_rod",
    "txdot_monument",
    "tree",
    "rock",
    "natural_feature",
    "other",
]
MonumentStatus = Literal["found", "set"]
CurveType = Literal["simple", "compound", "reverse", "spiral"]
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


class _Model(BaseModel):
    """Project-wide Pydantic base configuration."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    @staticmethod
    def _coerce_bool_field(value: object) -> bool:
        """Normalize boolean-like values used by multiple models."""
        if isinstance(value, bool):
            return value

        if value is None:
            return False

        if isinstance(value, (int, float)):
            if value in (0, 1):
                return bool(value)
            raise ValueError("flag must be a boolean value")

        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"", "false", "0", "no", "n", "off"}:
                return False
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True

        raise ValueError("flag must be a boolean value")


class DeedClause(_Model):
    """A deed clause (reservation, subject-to, or together-with)."""

    clause_type: Literal["reservation", "subject_to", "together_with"]
    text: str = Field(..., min_length=1, description="Verbatim clause text from deed")


class SubdivisionReference(_Model):
    """Subdivision lot/block reference from a deed."""

    lot: str | None = None
    block: str | None = None
    subdivision_name: str | None = None
    plat_book: str | None = None
    plat_page: str | None = None


class DeedCall(_Model):
    """Represents a single metes and bounds call (course/line)."""

    course: int = Field(
        ..., ge=1, strict=True, description="Sequential course number (1, 2, 3, ...)"
    )
    direction_text: str = Field(
        ...,
        min_length=1,
        description="Verbatim direction from deed (e.g., 'S 56°40' W' or 'southwesterly')",
    )
    bearing_quadrant: str | None = Field(
        None, description="Quadrant bearing if specified (e.g., 'S 56°40' W')"
    )
    bearing_azimuth_deg_from_north: FiniteFloat | None = Field(
        None,
        description="Azimuth in degrees clockwise from North (0-360)",
        ge=0,
        lt=360,
    )
    distance_ft: FiniteFloat = Field(
        ...,
        description="Distance in decimal feet",
        gt=0,
    )

    curve_dir: CurveDirection | None = Field(None, description="Curve direction (left/right)")
    radius_ft: FiniteFloat | None = Field(
        None,
        description="Curve radius in feet",
    )
    delta_deg: FiniteFloat | None = Field(
        None,
        description="Central angle (Δ) in degrees",
        ge=0,
        le=360,
    )
    arc_length_ft: FiniteFloat | None = Field(
        None,
        description="Arc length in feet",
        ge=0,
    )
    chord_bearing: str | None = Field(None, description="Chord bearing")
    chord_length_ft: FiniteFloat | None = Field(
        None,
        description="Chord length in feet",
        ge=0,
    )

    along: str | None = Field(
        None,
        description="What the line runs along (e.g., 'Southerly line of Pennbrook Drive')",
    )
    to: str | None = Field(
        None,
        description="Ending point description (e.g., 'iron pin', 'corner to Lot 50')",
    )
    monument_status: MonumentStatus | None = Field(
        None,
        description="Whether monument text indicates found or set",
    )
    monument_type: MonumentType | None = Field(
        None,
        description="Type of survey monument at endpoint",
    )
    is_exception: bool = Field(
        False,
        description="True if this call is part of an exception/exclusion tract",
    )
    non_tangent: bool = Field(
        False,
        description="True if this curve is non-tangent (radial bearing provided)",
    )
    radial_bearing: str | None = Field(
        None,
        description="Radial bearing for non-tangent curves (e.g., 'N 15°22' E')",
    )
    is_meander: bool = Field(
        False,
        description="True if this call follows a water boundary (meander line)",
    )
    is_tie_in: bool = Field(
        False,
        description="True if this call is a tie-in call between POC and POB",
    )
    is_indefinite: bool = Field(
        False,
        description="True if this call has vague direction without precise bearing",
    )
    curve_type: CurveType | None = Field(
        None,
        description="Type of curve: simple, compound, or reverse (None for non-curves)",
    )
    notes: str | None = Field(None, description="Additional notes (meander flag, issues, etc.)")

    @field_validator("curve_dir", "monument_type", "curve_type", mode="before")
    @classmethod
    def _normalize_literals(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Curve/monument values must be strings")
        normalized = value.strip().lower()
        return normalized or None

    @field_validator("monument_status", mode="before")
    @classmethod
    def _normalize_monument_status(cls, value: str | None) -> MonumentStatus | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError("monument_status must be a string")

        normalized = value.strip().lower()
        if normalized in {"", "none"}:
            return None
        if normalized == "found":
            return "found"
        if normalized == "set":
            return "set"

        raise ValueError("monument_status must be one of: found, set")

    @field_validator("is_exception", "is_meander", "is_tie_in", "is_indefinite", mode="before")
    @classmethod
    def _normalize_is_exception(cls, value: object) -> bool:
        try:
            return cls._coerce_bool_field(value)
        except ValueError as exc:
            raise ValueError("flag field must be a boolean value") from exc

    @field_validator("bearing_azimuth_deg_from_north", mode="before")
    @classmethod
    def _normalize_bearing_azimuth(cls, value: float | int | str | None) -> float | None:
        if value is None:
            return None
        azimuth = float(value)
        return azimuth % 360.0

    @field_validator("radius_ft", mode="before")
    @classmethod
    def _normalize_radius(cls, value: float | int | str | None) -> float | None:
        """Ensure radius is numeric and non-zero."""
        if value is None:
            return None
        radius = float(value)
        if radius == 0:
            raise ValueError("radius_ft must be non-zero")
        return radius

    @model_validator(mode="after")
    def normalize_curve_radius_sign(self) -> "DeedCall":
        """Normalize negative radii based on curve direction."""
        if self.radius_ft is None or self.radius_ft >= 0:
            return self

        if self.curve_dir == "left":
            object.__setattr__(self, "radius_ft", abs(self.radius_ft))
            return self
        if self.curve_dir == "right":
            raise ValueError("radius_ft sign conflicts with curve_dir")

        return self

    @model_validator(mode="after")
    def validate_curve_geometry(self) -> "DeedCall":
        """Require consistent curve attributes when curve geometry is present."""
        has_curve_direction = self.curve_dir is not None
        has_radius = self.radius_ft is not None
        has_delta = self.delta_deg is not None
        has_arc = self.arc_length_ft is not None
        has_chord = self.chord_length_ft is not None
        has_curve_measure = has_radius or has_delta or has_arc or has_chord

        if not has_curve_measure and not has_curve_direction:
            return self

        if not has_curve_direction:
            raise ValueError("curve_dir is required when any curve field is provided")

        if not has_radius or not (has_delta or has_arc):
            raise ValueError(
                "Curve geometry requires radius_ft and either delta_deg or arc_length_ft"
            )

        return self

    def is_curve(self) -> bool:
        """Check if this call represents a curve."""
        return self.curve_dir is not None or self.radius_ft is not None

    def is_complete_bearing(self) -> bool:
        """Check if bearing is fully specified (has azimuth)."""
        return self.bearing_azimuth_deg_from_north is not None


class Point(_Model):
    """Represents a 2D coordinate point."""

    x: FiniteFloat = Field(..., description="X coordinate (feet)")
    y: FiniteFloat = Field(..., description="Y coordinate (feet)")

    def __str__(self) -> str:
        return f"({self.x:.2f}, {self.y:.2f})"


class LegalDescription(_Model):
    """Represents a complete legal description from a deed."""

    poc_description: str | None = Field(
        None,
        description="Point of Commencement - survey reference point (distinct from POB)",
    )
    pob_description: str | None = Field(
        None, description="Point of Beginning - where parcel boundary starts"
    )

    calls: list[DeedCall] = Field(
        default_factory=list, description="List of metes and bounds calls"
    )

    source_doc: str | None = Field(None, description="Source document (book/page, etc.)")
    exhibit: str | None = Field(None, description="Exhibit identifier (e.g., 'Exhibit A')")
    page: int | None = Field(None, ge=1, strict=True, description="Page number in document")
    survey_date: str | None = Field(None, description="Survey date if specified")
    basis_of_bearing: str | None = Field(
        None, description="Basis of bearing (e.g., 'True North', 'Magnetic North')"
    )
    datum: str | None = Field(None, description="Datum/ellipsoid if specified")

    section: str | None = Field(None, description="Section number (e.g., '12')")
    township: str | None = Field(None, description="Township designation (e.g., '15 N' or 'T15N')")
    range: str | None = Field(None, description="Range designation (e.g., '3 E' or 'R3E')")
    principal_meridian: str | None = Field(
        None, description="Principal Meridian (e.g., 'Willamette Principal Meridian')"
    )
    aliquot: str | None = Field(None, description="Aliquot subdivision (e.g., 'SW 1/4 of NE 1/4')")

    surveyor_certification: str | None = Field(None, description="Surveyor certification text")
    prior_conveyance: str | None = Field(
        None, description="Prior conveyance reference (e.g., Deed Book 1234, Page 567)"
    )

    stated_area_sq_ft: FiniteFloat | None = Field(
        None,
        description="Stated area from the legal description (square feet)",
    )
    stated_area_approximate: bool = Field(
        False,
        description="Whether the stated area is approximate",
    )

    clauses: list[DeedClause] = Field(
        default_factory=list,
        description="Deed clauses (reservations, subject-to, together-with)",
    )
    subdivision_ref: SubdivisionReference | None = Field(
        None, description="Subdivision lot/block reference"
    )
    witness_trees: list[str] = Field(
        default_factory=list,
        description="Witness tree/reference mark descriptions (verbatim)",
    )
    coordinate_system: str | None = Field(
        None, description="State Plane or other coordinate system reference"
    )
    fips_code: str | None = Field(None, description="FIPS zone code for State Plane coordinates")

    distance_unit: DistanceUnit = Field("feet", description="Primary distance unit in the deed")

    @field_validator("distance_unit", mode="before")
    @classmethod
    def _normalize_distance_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError("distance_unit must be a string")

        normalized = value.strip().lower()
        return normalized

    @model_validator(mode="after")
    def validate_stated_area_state(self) -> "LegalDescription":
        if self.stated_area_approximate and self.stated_area_sq_ft is None:
            raise ValueError("stated_area_sq_ft must be set when stated_area_approximate is true")
        return self

    def num_calls(self) -> int:
        """Return number of calls."""
        return len(self.calls)

    def has_incomplete_calls(self) -> bool:
        """Check if any calls have incomplete bearings."""
        return any(not call.is_complete_bearing() for call in self.calls)


class ClosureResult(_Model):
    """Results of traverse closure verification."""

    misclosure_x_ft: FiniteFloat = Field(..., description="Misclosure in X direction (feet)")
    misclosure_y_ft: FiniteFloat = Field(..., description="Misclosure in Y direction (feet)")
    misclosure_ft: FiniteFloat = Field(..., description="Total misclosure distance (feet)")

    area_sq_ft: FiniteFloat = Field(
        ...,
        description="Area in square feet (shoelace formula)",
    )
    area_acres: FiniteFloat = Field(..., description="Area in acres")
    perimeter_ft: FiniteFloat = Field(..., description="Total perimeter in feet")

    closure_passed: bool = Field(
        ...,
        description="True if misclosure is within tolerance (< 0.01 ft)",
    )
    angle_check_passed: bool = Field(
        ...,
        description="True if interior angles sum correctly ((n-2)*180°)",
    )
    curve_consistency_passed: bool = Field(
        ...,
        description="True if curve math is consistent",
    )

    precision_ratio: FiniteFloat | None = Field(
        None,
        description="Misclosure / perimeter (e.g., 0.00004 means 1:25,000)",
        ge=0,
    )

    warnings: list[str] = Field(default_factory=list, description="List of warnings or issues")

    points: list[Point] = Field(
        default_factory=list, description="Computed vertex points (x, y in feet)"
    )

    def is_fully_verified(self) -> bool:
        """Check if all verification checks passed."""
        return (
            self.closure_passed
            and self.angle_check_passed
            and self.curve_consistency_passed
            and len(self.warnings) == 0
        )

    def get_closure_status(self) -> str:
        """Get human-readable closure status."""
        if self.warnings:
            return "NEEDS REVIEW"
        if self.misclosure_ft < 0.01:
            return "EXCELLENT"
        if self.misclosure_ft < 0.1:
            return "GOOD"
        if self.misclosure_ft < 1.0:
            return "ACCEPTABLE"
        return "POOR"


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

    @classmethod
    def convert_to_feet(cls, value: float, unit: str) -> float:
        """Convert a distance value to feet."""
        conversions = {
            "feet": 1.0,
            "us_survey_feet": cls.US_SURVEY_FOOT_TO_FEET,
            "poles": cls.POLE_TO_FEET,
            "rods": cls.ROD_TO_FEET,
            "perch": cls.PERCH_TO_FEET,
            "perches": cls.PERCH_TO_FEET,
            "chains": cls.CHAIN_TO_FEET,
            "link": cls.LINK_TO_FEET,
            "links": cls.LINK_TO_FEET,
            "varas": cls.VARA_TO_FEET,
            "arpents": cls.ARPENT_TO_FEET,
            "toises": cls.TOISE_TO_FEET,
            "furlongs": cls.FURLONG_TO_FEET,
            "meters": cls.METER_TO_FEET,
            "miles": cls.MILE_TO_FEET,
            "engineer_chains": cls.ENGINEER_CHAIN_TO_FEET,
            "engineer_links": cls.ENGINEER_LINK_TO_FEET,
        }
        normalized_unit = unit.strip().lower()
        if normalized_unit not in conversions:
            raise ValueError(f"Unsupported distance unit: {unit}")
        factor = conversions[normalized_unit]
        return value * factor
