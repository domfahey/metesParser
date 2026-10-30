"""DeedCall model and related types."""

from typing import Literal, Self

from pydantic import (
    Field,
    FiniteFloat,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .base import _Model

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
        ...,
        ge=1,
        strict=True,
        description="Sequential course number (1, 2, 3, ...)",
    )
    direction_text: str = Field(
        ...,
        min_length=1,
        description="Verbatim direction from deed (e.g., 'S 56\u00b040' W' or 'southwesterly')",
    )
    bearing_quadrant: str | None = Field(
        default=None,
        description="Quadrant bearing if specified (e.g., 'S 56\u00b040' W')",
    )
    bearing_azimuth_deg_from_north: FiniteFloat | None = Field(
        default=None,
        description="Azimuth in degrees clockwise from North (0-360)",
        ge=0,
        lt=360,
    )
    distance_ft: FiniteFloat | None = Field(
        ...,
        description=(
            "Distance in decimal feet; None only for a spiral whose length is not "
            "stated (not determinable without fabrication)"
        ),
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
        description="Central angle (\u0394) in degrees",
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
        description="Radial bearing for non-tangent curves (e.g., 'N 15\u00b022' E')",
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
        "is_exception",
        "is_meander",
        "is_tie_in",
        "is_indefinite",
        "non_tangent",
        mode="before",
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

        # Radius + chord (bearing and length) without a delta or arc is ambiguous
        # (minor vs major arc); it is accepted so the course can be positioned by
        # its chord, but verification never treats its arc as determined.
        has_full_chord = has_chord and self.chord_bearing is not None
        if not has_radius or not (has_delta or has_arc or has_full_chord):
            raise ValueError(
                "Curve geometry requires radius_ft and either delta_deg, arc_length_ft, "
                "or chord_bearing with chord_length_ft"
            )

        return self

    @model_validator(mode="after")
    def validate_undetermined_distance(self) -> Self:
        """Allow an undetermined distance only for a spiral with no stated length.

        A spiral's length is not R * delta, so a spiral stated by radius and delta
        alone has no determinable course distance; any other course states one or
        fixes it (arc, chord, or radius and delta of a circular arc).
        """
        if self.distance_ft is not None:
            return self
        if (
            self.curve_type != "spiral"
            or self.curve_dir is None
            or self.arc_length_ft is not None
            or self.chord_length_ft is not None
        ):
            raise ValueError(
                "distance_ft may be None only for a spiral curve with no stated arc or chord length"
            )
        return self

    def is_chord_only_curve(self) -> bool:
        """Return True for a curve stated by radius and chord without delta or arc."""
        return (
            self.curve_dir is not None
            and self.radius_ft is not None
            and self.delta_deg is None
            and self.arc_length_ft is None
            and self.chord_bearing is not None
            and self.chord_length_ft is not None
        )

    def is_curve(self) -> bool:
        """Check if this call represents a curve."""
        return self.curve_dir is not None or self.radius_ft is not None

    def is_complete_bearing(self) -> bool:
        """Check if bearing is fully specified (has azimuth)."""
        return self.bearing_azimuth_deg_from_north is not None
