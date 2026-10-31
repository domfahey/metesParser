"""Tract model for multi-tract deed support."""

from enum import Enum

from pydantic import Field, FiniteFloat

from .audit import SkippedCourse
from .base import _Model
from .closure import ClosureResult
from .deed_call import DeedCall


class TractType(str, Enum):
    """Type of tract in a multi-tract deed."""

    MAIN = "main"
    EXCEPTION = "exception"
    ADDITION = "addition"
    EASEMENT = "easement"


# Only these tracts describe the conveyed parcel's boundary. An easement or an
# excepted parcel can close as a traverse, but is never the deed's parcel.
BOUNDARY_TRACT_TYPES: frozenset[str] = frozenset({TractType.MAIN.value, TractType.ADDITION.value})


def tract_kind(tract_type: TractType | str) -> str:
    """The tract type's string value (also for a different TractType enum, e.g. the monolith's)."""
    return str(getattr(tract_type, "value", tract_type))


def is_boundary_tract(tract_type: TractType | str) -> bool:
    """Whether a tract of this type is part of the conveyed parcel's boundary."""
    return tract_kind(tract_type) in BOUNDARY_TRACT_TYPES


def non_boundary_detail(label: str, tract_type: TractType | str) -> str:
    """The one wording for why an easement/exception tract is never verified or exported."""
    return (
        f"non_boundary_tract: {label} is a {tract_kind(tract_type)} tract, not a parcel "
        "boundary, and is never eligible for verified export; its closure, area and "
        "perimeter are for review only"
    )


class Tract(_Model):
    """A single tract within a multi-tract deed."""

    label: str = Field(
        ..., min_length=1, description="Tract label (e.g., 'Tract 1', 'Exception 1')"
    )
    tract_type: TractType = Field(..., description="Type of tract")
    calls: list[DeedCall] = Field(default_factory=list, description="Calls for this tract")
    skipped_courses: list[SkippedCourse] = Field(
        default_factory=list, description="Courses of this tract extraction could not parse"
    )
    pob_description: str | None = Field(default=None, description="POB for this tract")
    stated_area_sq_ft: FiniteFloat | None = Field(default=None, description="Stated area")
    closure_result: ClosureResult | None = Field(
        default=None, description="Closure result (populated by mp-verify)"
    )
