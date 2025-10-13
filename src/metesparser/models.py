"""Pydantic models for metes and bounds deed parsing."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DeedCall(BaseModel):
    """Represents a single metes and bounds call (course/line)."""

    course: int = Field(..., description="Sequential course number (1, 2, 3, ...)")
    direction_text: str = Field(
        ..., description="Verbatim direction from deed (e.g., 'S 56°40' W' or 'southwesterly')"
    )
    bearing_quadrant: str | None = Field(
        None, description="Quadrant bearing if specified (e.g., 'S 56°40' W')"
    )
    bearing_azimuth_deg_from_north: float | None = Field(
        None,
        description="Azimuth in degrees clockwise from North (0-360)",
        ge=0,
        lt=360,
    )
    distance_ft: float = Field(..., description="Distance in decimal feet", gt=0)

    # Curve fields (optional)
    curve_dir: Literal["left", "right"] | None = Field(
        None, description="Curve direction (left/right)"
    )
    radius_ft: float | None = Field(None, description="Curve radius in feet", gt=0)
    delta_deg: float | None = Field(None, description="Central angle (Δ) in degrees", gt=0, le=360)
    arc_length_ft: float | None = Field(None, description="Arc length in feet", gt=0)
    chord_bearing: str | None = Field(None, description="Chord bearing")
    chord_length_ft: float | None = Field(None, description="Chord length in feet", gt=0)

    # Descriptive fields
    along: str | None = Field(
        None, description="What the line runs along (e.g., 'Southerly line of Pennbrook Drive')"
    )
    to: str | None = Field(
        None, description="Ending point description (e.g., 'iron pin', 'corner to Lot 50')"
    )
    notes: str | None = Field(None, description="Additional notes (meander flag, issues, etc.)")

    @field_validator("bearing_azimuth_deg_from_north")
    @classmethod
    def validate_azimuth(cls, v: float | None) -> float | None:
        """Ensure azimuth is in valid range."""
        if v is not None and (v < 0 or v >= 360):
            raise ValueError("Azimuth must be in range [0, 360)")
        return v

    @field_validator("distance_ft", "radius_ft", "arc_length_ft", "chord_length_ft")
    @classmethod
    def validate_positive(cls, v: float | None) -> float | None:
        """Ensure distance values are positive."""
        if v is not None and v <= 0:
            raise ValueError("Distance/radius/length must be positive")
        return v

    def is_curve(self) -> bool:
        """Check if this call represents a curve."""
        return self.curve_dir is not None or self.radius_ft is not None

    def is_complete_bearing(self) -> bool:
        """Check if bearing is fully specified (has azimuth)."""
        return self.bearing_azimuth_deg_from_north is not None


class Point(BaseModel):
    """Represents a 2D coordinate point."""

    x: float = Field(..., description="X coordinate (feet)")
    y: float = Field(..., description="Y coordinate (feet)")

    def __str__(self) -> str:
        return f"({self.x:.2f}, {self.y:.2f})"


class LegalDescription(BaseModel):
    """Represents a complete legal description from a deed."""

    # Point of Beginning
    pob_description: str | None = Field(None, description="Description of Point of Beginning")

    # List of calls/courses
    calls: list[DeedCall] = Field(
        default_factory=list, description="List of metes and bounds calls"
    )

    # Metadata
    source_doc: str | None = Field(None, description="Source document (book/page, etc.)")
    exhibit: str | None = Field(None, description="Exhibit identifier (e.g., 'Exhibit A')")
    page: int | None = Field(None, description="Page number in document")
    survey_date: str | None = Field(None, description="Survey date if specified")
    basis_of_bearing: str | None = Field(
        None, description="Basis of bearing (e.g., 'True North', 'Magnetic North')"
    )
    datum: str | None = Field(None, description="Datum/ellipsoid if specified")

    # Units
    distance_unit: Literal["feet", "us_survey_feet", "poles", "rods", "chains"] = Field(
        "feet", description="Primary distance unit in the deed"
    )

    def num_calls(self) -> int:
        """Return number of calls."""
        return len(self.calls)

    def has_incomplete_calls(self) -> bool:
        """Check if any calls have incomplete bearings."""
        return any(not call.is_complete_bearing() for call in self.calls)


class ClosureResult(BaseModel):
    """Results of traverse closure verification."""

    # Closure errors
    misclosure_x_ft: float = Field(..., description="Misclosure in X direction (feet)")
    misclosure_y_ft: float = Field(..., description="Misclosure in Y direction (feet)")
    misclosure_ft: float = Field(..., description="Total misclosure distance (feet)")

    # Computed values
    area_sq_ft: float = Field(..., description="Area in square feet (shoelace formula)")
    area_acres: float = Field(..., description="Area in acres")
    perimeter_ft: float = Field(..., description="Total perimeter in feet")

    # Validation flags
    closure_passed: bool = Field(
        ..., description="True if misclosure is within tolerance (< 0.01 ft)"
    )
    angle_check_passed: bool = Field(
        ..., description="True if interior angles sum correctly ((n-2)*180°)"
    )
    curve_consistency_passed: bool = Field(..., description="True if curve math is consistent")

    # Warnings/issues
    warnings: list[str] = Field(default_factory=list, description="List of warnings or issues")

    # Computed points (for plotting)
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
        if self.misclosure_ft < 0.01:
            return "EXCELLENT"
        elif self.misclosure_ft < 0.1:
            return "GOOD"
        elif self.misclosure_ft < 1.0:
            return "ACCEPTABLE"
        else:
            return "POOR"


class ConversionFactors:
    """Unit conversion factors."""

    POLE_TO_FEET: float = 16.5
    ROD_TO_FEET: float = 16.5  # Same as pole
    PERCH_TO_FEET: float = 16.5  # Same as pole/rod
    CHAIN_TO_FEET: float = 66.0
    LINK_TO_FEET: float = 0.66
    ACRE_TO_SQ_FEET: float = 43560.0
    FOOT_TO_METERS: float = 0.3048
    US_SURVEY_FOOT_TO_METERS: float = 0.30480061

    @classmethod
    def convert_to_feet(cls, value: float, unit: str) -> float:
        """Convert a distance value to feet."""
        conversions = {
            "feet": 1.0,
            "us_survey_feet": 1.0,  # Functionally same for most purposes
            "poles": cls.POLE_TO_FEET,
            "rods": cls.ROD_TO_FEET,
            "perches": cls.PERCH_TO_FEET,
            "chains": cls.CHAIN_TO_FEET,
            "links": cls.LINK_TO_FEET,
        }
        factor = conversions.get(unit.lower(), 1.0)
        return value * factor
