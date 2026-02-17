"""LegalDescription model."""

from typing import Self

from pydantic import (
    Field,
    FiniteFloat,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .base import _Model
from .deed_call import DeedCall, DeedClause, SubdivisionReference
from .units import DistanceUnit


class LegalDescription(_Model):
    """Represents a complete legal description from a deed."""

    poc_description: str | None = Field(
        default=None,
        description="Point of Commencement - survey reference point (distinct from POB)",
    )
    pob_description: str | None = Field(
        default=None,
        description="Point of Beginning - where parcel boundary starts",
    )

    calls: list[DeedCall] = Field(
        default_factory=list, description="List of metes and bounds calls"
    )

    source_doc: str | None = Field(default=None, description="Source document (book/page, etc.)")
    exhibit: str | None = Field(default=None, description="Exhibit identifier (e.g., 'Exhibit A')")
    page: int | None = Field(default=None, ge=1, strict=True, description="Page number in document")
    survey_date: str | None = Field(default=None, description="Survey date if specified")
    basis_of_bearing: str | None = Field(
        default=None,
        description="Basis of bearing (e.g., 'True North', 'Magnetic North')",
    )
    datum: str | None = Field(default=None, description="Datum/ellipsoid if specified")

    section: str | None = Field(default=None, description="Section number (e.g., '12')")
    township: str | None = Field(
        default=None,
        description="Township designation (e.g., '15 N' or 'T15N')",
    )
    range: str | None = Field(default=None, description="Range designation (e.g., '3 E' or 'R3E')")
    principal_meridian: str | None = Field(
        default=None,
        description="Principal Meridian (e.g., 'Willamette Principal Meridian')",
    )
    aliquot: str | None = Field(
        default=None,
        description="Aliquot subdivision (e.g., 'SW 1/4 of NE 1/4')",
    )

    surveyor_certification: str | None = Field(
        default=None, description="Surveyor certification text"
    )
    prior_conveyance: str | None = Field(
        default=None,
        description="Prior conveyance reference (e.g., Deed Book 1234, Page 567)",
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
        default=None,
        description="State Plane or other coordinate system reference",
    )
    fips_code: str | None = Field(
        default=None,
        description="FIPS zone code for State Plane coordinates",
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
