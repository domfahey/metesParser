"""Pydantic models for metes and bounds deed parsing."""

from datetime import datetime
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    ValidationInfo,
    field_validator,
    model_validator,
)

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
PERMANENT_MONUMENTS: frozenset[str] = frozenset(
    {
        "iron_rod",
        "iron_pin",
        "iron_pipe",
        "concrete",
        "brass_cap",
        "rebar",
        "capped_pin",
        "capped_rod",
        "railroad_spike",
    }
)
PRIOR_CONVEYANCE_SIGNALS: frozenset[str] = frozenset(
    {
        "BEING the same premises",
        "previously conveyed",
        "derived from",
        "by deed dated",
        "recorded in Book",
        "Instrument Number",
    }
)
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

    # frozen=True: models are immutable. The object.__setattr__() bypass in
    # normalize_curve_radius_sign() still works on frozen models.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
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

    lot: str | None = Field(default=None, description="Lot number or identifier")
    block: str | None = Field(default=None, description="Block number or identifier")
    subdivision_name: str | None = Field(default=None, description="Name of the subdivision")
    plat_book: str | None = Field(default=None, description="Plat book reference number")
    plat_page: str | None = Field(default=None, description="Plat page reference number")


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
        default=None, description="Quadrant bearing if specified (e.g., 'S 56°40' W')"
    )
    bearing_azimuth_deg_from_north: FiniteFloat | None = Field(
        default=None,
        description="Azimuth in degrees clockwise from North (0-360)",
        ge=0,
        lt=360,
    )
    distance_ft: FiniteFloat = Field(
        ...,
        description="Distance in decimal feet",
        gt=0,
    )

    curve_dir: CurveDirection | None = Field(
        default=None, description="Curve direction (left/right)"
    )
    radius_ft: FiniteFloat | None = Field(
        default=None,
        description="Curve radius in feet",
    )
    delta_deg: FiniteFloat | None = Field(
        default=None,
        description="Central angle (Δ) in degrees",
        ge=0,
        le=360,
    )
    arc_length_ft: FiniteFloat | None = Field(
        default=None,
        description="Arc length in feet",
        ge=0,
    )
    chord_bearing: str | None = Field(default=None, description="Chord bearing")
    chord_length_ft: FiniteFloat | None = Field(
        default=None,
        description="Chord length in feet",
        ge=0,
    )

    along: str | None = Field(
        default=None,
        description="What the line runs along (e.g., 'Southerly line of Pennbrook Drive')",
    )
    to: str | None = Field(
        default=None,
        description="Ending point description (e.g., 'iron pin', 'corner to Lot 50')",
    )
    monument_status: MonumentStatus | None = Field(
        default=None,
        description="Whether monument text indicates found or set",
    )
    monument_type: MonumentType | None = Field(
        default=None,
        description="Type of survey monument at endpoint",
    )
    is_exception: bool = Field(
        default=False,
        description="True if this call is part of an exception/exclusion tract",
    )
    non_tangent: bool = Field(
        default=False,
        description="True if this curve is non-tangent (radial bearing provided)",
    )
    radial_bearing: str | None = Field(
        default=None,
        description="Radial bearing for non-tangent curves (e.g., 'N 15°22' E')",
    )
    is_meander: bool = Field(
        default=False,
        description="True if this call follows a water boundary (meander line)",
    )
    is_tie_in: bool = Field(
        default=False,
        description="True if this call is a tie-in call between POC and POB",
    )
    is_indefinite: bool = Field(
        default=False,
        description="True if this call has vague direction without precise bearing",
    )
    curve_type: CurveType | None = Field(
        default=None,
        description="Type of curve: simple, compound, or reverse (None for non-curves)",
    )
    quality: Literal["high", "medium", "low"] | None = Field(
        default=None,
        description="Call quality rating based on bearing completeness and monument permanence",
    )
    notes: str | None = Field(
        default=None, description="Additional notes (meander flag, issues, etc.)"
    )

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

    @field_validator(
        "is_exception", "is_meander", "is_tie_in", "is_indefinite", "non_tangent", mode="before"
    )
    @classmethod
    def _coerce_bool_fields(cls, value: object, info: ValidationInfo) -> bool:
        try:
            return cls._coerce_bool_field(value)
        except ValueError as exc:
            field = info.field_name or "flag"
            raise ValueError(f"{field} must be a boolean value") from exc

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
    def normalize_curve_radius_sign(self) -> Self:
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
    def validate_curve_geometry(self) -> Self:
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
        default=None,
        description="Point of Commencement - survey reference point (distinct from POB)",
    )
    pob_description: str | None = Field(
        default=None, description="Point of Beginning - where parcel boundary starts"
    )

    calls: list[DeedCall] = Field(
        default_factory=list, description="List of metes and bounds calls"
    )

    source_doc: str | None = Field(default=None, description="Source document (book/page, etc.)")
    exhibit: str | None = Field(default=None, description="Exhibit identifier (e.g., 'Exhibit A')")
    page: int | None = Field(default=None, ge=1, strict=True, description="Page number in document")
    survey_date: str | None = Field(default=None, description="Survey date if specified")
    basis_of_bearing: str | None = Field(
        default=None, description="Basis of bearing (e.g., 'True North', 'Magnetic North')"
    )
    datum: str | None = Field(default=None, description="Datum/ellipsoid if specified")

    section: str | None = Field(default=None, description="Section number (e.g., '12')")
    township: str | None = Field(
        default=None, description="Township designation (e.g., '15 N' or 'T15N')"
    )
    range: str | None = Field(default=None, description="Range designation (e.g., '3 E' or 'R3E')")
    principal_meridian: str | None = Field(
        default=None, description="Principal Meridian (e.g., 'Willamette Principal Meridian')"
    )
    aliquot: str | None = Field(
        default=None, description="Aliquot subdivision (e.g., 'SW 1/4 of NE 1/4')"
    )

    surveyor_certification: str | None = Field(
        default=None, description="Surveyor certification text"
    )
    prior_conveyance: str | None = Field(
        default=None, description="Prior conveyance reference (e.g., Deed Book 1234, Page 567)"
    )

    stated_area_sq_ft: FiniteFloat | None = Field(
        default=None,
        description="Stated area from the legal description (square feet)",
    )
    stated_area_approximate: bool = Field(
        default=False,
        description="Whether the stated area is approximate",
    )

    clauses: list[DeedClause] = Field(
        default_factory=list,
        description="Deed clauses (reservations, subject-to, together-with)",
    )
    subdivision_ref: SubdivisionReference | None = Field(
        default=None, description="Subdivision lot/block reference"
    )
    witness_trees: list[str] = Field(
        default_factory=list,
        description="Witness tree/reference mark descriptions (verbatim)",
    )
    coordinate_system: str | None = Field(
        default=None, description="State Plane or other coordinate system reference"
    )
    fips_code: str | None = Field(
        default=None, description="FIPS zone code for State Plane coordinates"
    )

    distance_unit: DistanceUnit = Field(
        default="feet", description="Primary distance unit in the deed"
    )

    @field_validator("distance_unit", mode="before")
    @classmethod
    def _normalize_distance_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError("distance_unit must be a string")

        normalized = value.strip().lower()
        return normalized

    @field_validator("stated_area_approximate", mode="before")
    @classmethod
    def _coerce_bool_fields(cls, value: object, info: ValidationInfo) -> bool:
        try:
            return cls._coerce_bool_field(value)
        except ValueError as exc:
            field = info.field_name or "flag"
            raise ValueError(f"{field} must be a boolean value") from exc

    @model_validator(mode="after")
    def validate_stated_area_state(self) -> Self:
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
        default=None,
        description="Misclosure / perimeter (e.g., 0.00004 means 1:25,000)",
        ge=0,
    )
    confidence_score: FiniteFloat | None = Field(
        default=None,
        description="Overall confidence score (0.0–1.0) based on closure, bearings, monuments",
        ge=0.0,
        le=1.0,
    )

    warnings: list[str] = Field(default_factory=list, description="List of warnings or issues")

    points: list[Point] = Field(
        default_factory=list, description="Computed vertex points (x, y in feet)"
    )

    @field_validator(
        "closure_passed", "angle_check_passed", "curve_consistency_passed", mode="before"
    )
    @classmethod
    def _coerce_bool_fields(cls, value: object, info: ValidationInfo) -> bool:
        try:
            return cls._coerce_bool_field(value)
        except ValueError as exc:
            field = info.field_name or "flag"
            raise ValueError(f"{field} must be a boolean value") from exc

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


# ---------------------------------------------------------------------------
# Phase 6: Audit Sidecar Models
# ---------------------------------------------------------------------------


class Transformation(_Model):
    """A single transformation step in the audit trail."""

    step: str = Field(..., description="Pipeline step name")
    input: str = Field(..., description="Input value before transformation")
    output: str = Field(..., description="Output value after transformation")
    rule: str | None = Field(default=None, description="Regex pattern or method that matched")


class Decision(_Model):
    """A parsing decision with confidence and alternatives."""

    field: str = Field(..., description="Field name (e.g., 'monument_type')")
    value: str = Field(..., description="Chosen value")
    reason: str = Field(..., description="Why this value was chosen")
    alternatives: list[str] = Field(default_factory=list, description="Other values considered")
    confidence: FiniteFloat = Field(..., ge=0.0, le=1.0, description="Confidence 0.0-1.0")


class CallAudit(_Model):
    """Audit trail for a single deed call."""

    course: int = Field(
        ..., ge=1, strict=True, description="Course number (matches DeedCall.course)"
    )
    source_excerpt: str = Field(..., description="Verbatim text span this call was parsed from")
    transformations: list[Transformation] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class CheckResult(_Model):
    """Result of a single verification check."""

    name: str = Field(..., description="Check name")
    passed: bool = Field(..., description="Whether the check passed")
    detail: str = Field(..., description="Human-readable detail")
    inputs: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Values used in the check"
    )


class RunMetadata(_Model):
    """Metadata about a pipeline run."""

    parser_version: str = Field(..., description="Parser version")
    llm_provider: str = Field(..., description="LLM provider name")
    llm_model: str = Field(..., description="LLM model identifier")
    prompt_hash: str = Field(..., description="SHA256 hash of prompt template")
    timestamp_utc: datetime = Field(..., description="Run timestamp (UTC)")
    source_pdf: str = Field(..., description="Source PDF filename")
    cache_enabled: bool = Field(..., description="Whether LLM response caching is enabled")
    config: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Configuration snapshot"
    )


class ExtractionRecord(_Model):
    """Record of the LLM extraction step."""

    raw_llm_response: str = Field(..., description="Verbatim LLM output")
    normalized_text: str = Field(..., description="Text after normalization")
    llm_confidence: FiniteFloat | None = Field(
        default=None, ge=0.0, le=1.0, description="Heuristic extraction confidence"
    )
    confidence_signals: dict[str, bool] = Field(
        default_factory=dict, description="Individual confidence signal results"
    )


class VerificationAudit(_Model):
    """Audit trail for verification checks."""

    checks: list[CheckResult] = Field(default_factory=list)
    closure_summary: dict[str, float | str] = Field(default_factory=dict)


class AuditContext(BaseModel):
    """Complete audit trail for a pipeline run.

    NOT frozen — this is a mutable accumulator that gets populated
    as data flows through the pipeline. Other audit models are frozen.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", description="Audit schema version")
    run_metadata: RunMetadata
    extraction_record: ExtractionRecord | None = Field(default=None)
    call_audits: list[CallAudit] = Field(default_factory=list)
    verification_audit: VerificationAudit | None = Field(default=None)
