"""Sourced constraints and separate results for straight, local-angle analysis.

These models do not replace DeedCall or ClosureResult. A local heading is never
a recorded bearing, and a computed local traverse cannot authorize export.
"""

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, field_validator, model_validator

from .base import _Model
from .closure import Point

Number = Annotated[FiniteFloat, Field(strict=True)]
PositiveNumber = Annotated[FiniteFloat, Field(strict=True, gt=0)]
Angle = Annotated[FiniteFloat, Field(strict=True, gt=0, lt=360)]
RecordedAzimuth = Annotated[FiniteFloat, Field(strict=True, ge=0, lt=360)]


class _RelativeModel(_Model):
    # Source quotes and references are evidence, including their whitespace.
    model_config = ConfigDict(str_strip_whitespace=False)


class RelativeSource(_RelativeModel):
    """Verbatim evidence plus a document/page/occurrence reference."""

    reference: str
    quote: str

    @field_validator("reference", "quote")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source reference and quote must not be blank")
        return value


class LocalFrame(_RelativeModel):
    """Explicit arbitrary frame, in feet; azimuth is clockwise from local +Y.

    Orientation sets the interior/exterior-angle interpretation convention and
    computed closing angle. It does not certify the winding of the resulting
    boundary. Explicit perpendicular/parallel directions are independent of it.
    """

    name: str
    first_azimuth_deg: Number
    origin: tuple[Number, Number]
    orientation: Literal["cw", "ccw"]

    @field_validator("name")
    @classmethod
    def _named_frame(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the local frame must be named")
        return value


class RelativeCourse(_RelativeModel):
    """One straight course; recorded bearings are retained but never inferred."""

    course_id: str
    distance_ft: PositiveNumber
    source: RelativeSource
    recorded_bearing_azimuth_deg_from_north: RecordedAzimuth | None = None

    @field_validator("course_id")
    @classmethod
    def _course_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("course_id must not be blank")
        return value


class RelativeConstraint(_RelativeModel):
    """Relation from one directed course to another.

    Interior/exterior angles connect successive boundary courses (last to first
    is the closing angle). Exterior values require an explicit convention that
    interior = 360 - exterior; an unspecified convention stays unresolved.
    Perpendicular turns and parallel direction refer to the directed from_course,
    so they also work for nonadjacent courses. Unspecified choices stay unresolved.
    """

    constraint_id: str
    kind: Literal["interior", "exterior", "perpendicular", "parallel"]
    from_course: str
    to_course: str
    source: RelativeSource
    angle_deg: Angle | None = None
    turn: Literal["left", "right"] | None = None
    parallel_direction: Literal["same", "opposite"] | None = None
    exterior_convention: Literal["interior_complement"] | None = None
    interpretation: str | None = None

    @field_validator("constraint_id", "from_course", "to_course")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("constraint and course identifiers must not be blank")
        return value

    @model_validator(mode="after")
    def _fields_match_kind(self) -> Self:
        if self.from_course == self.to_course:
            raise ValueError("a constraint must connect distinct courses")
        if self.kind in {"interior", "exterior"}:
            if self.angle_deg is None:
                raise ValueError("interior/exterior constraints require angle_deg")
            if self.turn is not None or self.parallel_direction is not None:
                raise ValueError("angle constraints cannot include turn or parallel_direction")
            if self.kind == "interior" and self.exterior_convention is not None:
                raise ValueError("exterior_convention is only valid for exterior constraints")
        else:
            if self.angle_deg is not None or self.exterior_convention is not None:
                raise ValueError("only interior/exterior constraints accept angle fields")
            if self.kind == "parallel" and self.turn is not None:
                raise ValueError("parallel constraints use parallel_direction, not turn")
            if self.kind == "perpendicular" and self.parallel_direction is not None:
                raise ValueError("perpendicular constraints use turn, not parallel_direction")
        return self


class RelativeDescription(_RelativeModel):
    """A source-linked straight boundary plus explicit local interpretation."""

    schema_version: Literal["1.0"] = "1.0"
    frame: LocalFrame
    courses: tuple[RelativeCourse, ...] = Field(min_length=3)
    constraints: tuple[RelativeConstraint, ...]

    @model_validator(mode="after")
    def _validate_references(self) -> Self:
        ids = [course.course_id for course in self.courses]
        if len(set(ids)) != len(ids):
            raise ValueError("course_id values must be unique")
        constraint_ids = [constraint.constraint_id for constraint in self.constraints]
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ValueError("constraint_id values must be unique")
        successors = dict(zip(ids, ids[1:] + ids[:1], strict=True))
        for constraint in self.constraints:
            if constraint.from_course not in successors or constraint.to_course not in successors:
                raise ValueError(f"constraint {constraint.constraint_id!r} has an unknown course")
            if (
                constraint.kind in {"interior", "exterior"}
                and successors[constraint.from_course] != constraint.to_course
            ):
                raise ValueError(
                    "interior/exterior angles must connect successive boundary courses"
                )
        return self


class RelativeIssue(_RelativeModel):
    """An unresolved interpretation or contradictory sourced relation."""

    code: Literal[
        "ambiguous_constraint",
        "insufficient_constraints",
        "contradictory_constraints",
        "numerical_range",
    ]
    message: str
    constraint_ids: tuple[str, ...] = ()
    course_ids: tuple[str, ...] = ()
    alternatives_deg: tuple[Number, ...] = ()


class RelativeCourseGeometry(_RelativeModel):
    """Derived coordinates reference their input course, never its recorded bearing."""

    course_id: str
    local_azimuth_deg: Number
    delta_x_ft: Number
    delta_y_ft: Number


class RelativeAnalysisResult(_RelativeModel):
    """Unadjusted local geometry, deliberately distinct from engine verification.

    Analyzed means constraints determine the headings, not that the boundary
    closes, is simple, or represents surveyed/title boundaries. Area is the
    absolute algebraic shoelace area with an implicit endpoint-to-start segment.
    """

    description: RelativeDescription
    method: Literal["local_angle_analysis"] = "local_angle_analysis"
    engine_verified: Literal[False] = False
    verified_export_eligible: Literal[False] = False
    status: Literal["analyzed", "unresolved", "inconsistent"]
    issues: tuple[RelativeIssue, ...] = ()
    points: tuple[Point, ...] = ()
    courses: tuple[RelativeCourseGeometry, ...] = ()
    misclosure_ft: Number | None = None
    misclosure_x_ft: Number | None = None
    misclosure_y_ft: Number | None = None
    perimeter_ft: Number | None = None
    area_sq_ft: Number | None = None
    precision_denominator: Number | None = Field(
        default=None,
        description="Perimeter/misclosure (1:N); null for exact zero or unrepresentable ratio.",
    )
    stated_angle_sum_deg: Number | None = None
    expected_angle_sum_deg: Number | None = None
    computed_closing_angle_deg: Number | None = None
    area_basis: Literal["implicit_closing_segment"] = "implicit_closing_segment"
