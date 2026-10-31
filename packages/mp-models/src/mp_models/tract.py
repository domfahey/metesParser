"""Tract model for multi-tract deed support."""

from collections.abc import Sequence
from enum import Enum
from typing import Literal, Protocol

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


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def non_boundary_detail(label: str, tract_type: TractType | str) -> str:
    """The one wording for why an easement/exception tract is never verified or exported."""
    return (
        f"non_boundary_tract: {label} is {_article(tract_kind(tract_type))} {tract_kind(tract_type)} tract, not a parcel "
        "boundary, and is never eligible for verified export; its closure, area and "
        "perimeter are for review only"
    )


# Where a tract's role (its TractType) came from:
# * "heading": an explicit TRACT/PARCEL heading the parser recognises as a tract
#   marker, typed MAIN or ADDITION, with no role wording (easement, except, less,
#   reserving, subject to, ...) in it or before its opening (otherwise "inferred");
# * "single": the deed's one description, the parcel (MAIN); a sole EXCEPTION,
#   EASEMENT or ADDITION (an easement deed's easement) keeps "inferred";
# * "inferred": typed from wording heuristics (EXCEPT/ALSO leads, easement grants,
#   preamble rules, closed-boundary order, a default MAIN without a heading).
# None means the basis was not recorded (a stored artifact or caller-built tract
# predating the field); it is established only for a deed's sole tract.
RoleBasis = Literal["heading", "single", "inferred"]

DESCRIPTION_ROLES_CHECK = "description_roles_inferred"
DESCRIPTION_ROLES_PREFIX = "description roles need review: "


class _RoleBearing(Protocol):
    @property
    def label(self) -> str: ...

    @property
    def tract_type(self) -> TractType | str: ...


_INFERRED_WHY = {
    TractType.MAIN.value: "main role assumed from its position, without a tract heading",
    TractType.ADDITION.value: "addition role inferred from ALSO/INCLUDING wording",
    TractType.EXCEPTION.value: "exception role inferred from EXCEPT wording",
    TractType.EASEMENT.value: "easement role inferred from easement-grant wording",
}


def roles_need_review(tracts: Sequence[_RoleBearing]) -> list[str]:
    """Why a deed's description roles must be reviewed before any verified export.

    Fail closed: land whose role was guessed from wording is never exported. A tract
    whose ``role_basis`` is "inferred" always needs review (the parser infers roles
    only among several descriptions, so this holds when a caller passes that tract
    alone too). With more than one tract every tract needs a "heading" basis; a
    "single" or unrecorded (None) basis there needs review as well. A deed's sole
    tract with a "single", "heading" or unrecorded basis needs none.
    """
    several = len(tracts) > 1
    reasons: list[str] = []
    for tract in tracts:
        basis = getattr(tract, "role_basis", None)
        kind = tract_kind(tract.tract_type)
        if basis == "heading" or (not several and basis in ("single", None)):
            continue
        if basis == "inferred":
            why = _INFERRED_WHY.get(kind, "role inferred from wording")
        elif basis == "single":
            why = f"marked the sole description, but the deed has {len(tracts)} descriptions"
        else:
            why = "role basis not recorded, so no explicit tract heading is established"
        reasons.append(f"{tract.label} ({kind}): {why}")
    return reasons


def roles_review_detail(reasons: Sequence[str]) -> str:
    """The one wording of the deed-level block for inferred description roles."""
    return (
        DESCRIPTION_ROLES_PREFIX
        + "; ".join(reasons)
        + ". No description of this deed is eligible for verified export until its "
        "roles are reviewed"
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
    role_basis: RoleBasis | None = Field(
        default=None,
        description=(
            "Where tract_type came from: an explicit tract heading, the deed's single "
            "description, or wording heuristics (None: not recorded)"
        ),
    )
