"""Tract model for multi-tract deed support."""

from collections.abc import Sequence
from enum import Enum
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, Field, FiniteFloat

from .audit import SkippedCourse
from .base import _Model
from .closure import ClosureResult
from .deed_call import (
    DESCRIPTION_ROLES_NOTE,
    EASEMENT_TRACT_NOTE,
    EXCEPTION_TRACT_NOTE,
    DeedCall,
    split_notes,
)


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


NON_BOUNDARY_CHECK = "non_boundary_tract"


def non_boundary_detail(label: str, tract_type: TractType | str) -> str:
    """The one wording for why an easement/exception tract is never verified or exported."""
    return (
        f"{NON_BOUNDARY_CHECK}: {label} is {_article(tract_kind(tract_type))} {tract_kind(tract_type)} tract, not a parcel "
        "boundary, and is never eligible for verified export; its closure, area and "
        "perimeter are for review only"
    )


# The note each non-boundary tract kind's calls carry (``mark_non_boundary``).
_NON_BOUNDARY_NOTE_BY_KIND = {
    TractType.EASEMENT.value: EASEMENT_TRACT_NOTE,
    TractType.EXCEPTION.value: EXCEPTION_TRACT_NOTE,
}


# Where a tract's role (its TractType) came from:
# * "heading": an explicit TRACT/PARCEL heading the parser recognises as a tract
#   marker, typed MAIN or ADDITION, whose plain label is followed by nothing or the
#   parcel's own intro, with only harmless recitals before it and no role statement
#   after the last description (r59: an allow-list; otherwise "inferred");
# * "single": the deed's one description, the parcel (MAIN), when no easement,
#   exception or reservation wording introduces, titles or follows it outside harmless
#   recitals (r59); otherwise, and for a sole EXCEPTION, EASEMENT or ADDITION (an
#   easement deed's easement), "inferred";
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


# r59: a deed's only description whose parcel role its wording does not establish.
_SOLE_INFERRED_WHY = (
    "the sole description's parcel role is not established: easement, exception or "
    "reservation wording introduces, labels or follows it"
)


_Call = TypeVar("_Call", bound=BaseModel)


def _has_note(call: BaseModel, note: str) -> bool:
    return note in split_notes(getattr(call, "notes", None))


def _has_roles_mark(call: BaseModel) -> bool:
    return _has_note(call, DESCRIPTION_ROLES_NOTE)


def _with_note(calls: Sequence[_Call], note: str) -> list[_Call]:
    """Each call with ``note`` appended to its notes (idempotent; any DeedCall model)."""
    return [
        call
        if _has_note(call, note)
        else call.model_copy(
            update={"notes": "; ".join(filter(None, (getattr(call, "notes", None), note)))}
        )
        for call in calls
    ]


def mark_roles_review(calls: Sequence[_Call]) -> list[_Call]:
    """Mark each call with ``DESCRIPTION_ROLES_NOTE`` (idempotent; any DeedCall model).

    Applied to every call of a deed whose description roles need review (its flat calls
    and each tract's own), so no subset of them verifies, and every artifact written
    from them stays blocked from verified export when re-imported without the deed's
    tracts (notes survive CSV and JSON round trips).
    """
    return _with_note(calls, DESCRIPTION_ROLES_NOTE)


def mark_non_boundary(calls: Sequence[_Call], tract_type: TractType | str) -> list[_Call]:
    """Mark each call of an easement/exception tract with its kind's non-boundary note.

    The calls then never verify as a parcel boundary, with or without their tract,
    including once written and re-imported. Calls of a boundary tract (main, addition)
    are returned unchanged. Idempotent; any DeedCall model.
    """
    note = _NON_BOUNDARY_NOTE_BY_KIND.get(tract_kind(tract_type))
    return list(calls) if note is None else _with_note(calls, note)


def non_boundary_marks(calls: Sequence[BaseModel]) -> list[str]:
    """The non-boundary tract kinds whose note any of ``calls`` bears (easement first)."""
    return [
        kind
        for kind, note in _NON_BOUNDARY_NOTE_BY_KIND.items()
        if any(_has_note(call, note) for call in calls)
    ]


def non_boundary_marks_detail(kinds: Sequence[str]) -> str:
    """Why calls bearing a non-boundary note (``non_boundary_marks``) are never verified."""
    tracts = " and ".join(f"{_article(kind)} {kind} tract" for kind in kinds)
    return (
        f"{NON_BOUNDARY_CHECK}: calls marked as land of {tracts} are not a parcel boundary "
        "and are never eligible for verified export; their closure, area and perimeter "
        "are for review only"
    )


def roles_need_review(tracts: Sequence[_RoleBearing], calls: Sequence[BaseModel] = ()) -> list[str]:
    """Why a deed's description roles must be reviewed before any verified export.

    The one role gate: verification, verified export, review and the monolith
    pipeline/CLI all consult it. Fail closed: land whose role was guessed from wording
    is never exported. A tract whose ``role_basis`` is "inferred" always needs review,
    a deed's sole description too (r59: easement, exception or reservation wording
    introduces, labels or follows it), and so does a tract taken from a deed of several
    passed alone. With more than one tract every tract needs a
    "heading" basis; a "single" or unrecorded (None) basis there needs review as
    well. A deed's sole tract with a "single", "heading" or unrecorded basis needs
    none. Calls carried without their tracts (``calls``, or a tract's own) that bear
    the role-review mark (``mark_roles_review``) need review too.
    """
    several = len(tracts) > 1
    reasons: list[str] = []
    for tract in tracts:
        basis = getattr(tract, "role_basis", None)
        kind = tract_kind(tract.tract_type)
        if basis == "heading" or (not several and basis in ("single", None)):
            continue
        if basis == "inferred" and not several and kind == TractType.MAIN.value:
            why = _SOLE_INFERRED_WHY
        elif basis == "inferred":
            why = _INFERRED_WHY.get(kind, "role inferred from wording")
        elif basis == "single":
            why = f"marked the sole description, but the deed has {len(tracts)} descriptions"
        else:
            why = "role basis not recorded, so no explicit tract heading is established"
        reasons.append(f"{tract.label} ({kind}): {why}")
    marked = [*calls, *(c for t in tracts for c in getattr(t, "calls", ()))]
    if not reasons and any(_has_roles_mark(call) for call in marked):
        reasons.append(
            f"calls marked {DESCRIPTION_ROLES_NOTE!r} come from a deed whose description "
            "roles were not established"
        )
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
