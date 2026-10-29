"""Deterministic heading constraints for straight, explicitly local traverses.

No heading is inferred from cardinal words or fitted to force positional closure.
Relations are solved as a graph of directed angular differences. The tolerance
of 1e-8 degrees accommodates floating arithmetic only, not survey uncertainty.
Translated points must retain local offsets and course vectors within 1e-6 ft
or one part per million of the shortest course, whichever is smaller.
This module neither calls the canonical verifier nor modifies recorded bearings.
"""

import math
from collections import deque
from itertools import pairwise

from mp_models import (
    Point,
    RelativeAnalysisResult,
    RelativeConstraint,
    RelativeCourseGeometry,
    RelativeDescription,
    RelativeIssue,
)

ANGLE_TOLERANCE_DEG = 1e-8
COORDINATE_TOLERANCE_FT = 1e-6


def _difference(constraint: RelativeConstraint, orientation: str) -> float | None:
    if constraint.kind in {"interior", "exterior"}:
        angle = constraint.angle_deg
        assert angle is not None  # Validated by RelativeConstraint.
        if constraint.kind == "exterior":
            if constraint.exterior_convention is None:
                return None
            angle = 360 - angle
        return (180 - angle) * (1 if orientation == "cw" else -1)
    if constraint.kind == "perpendicular":
        return None if constraint.turn is None else (90 if constraint.turn == "right" else -90)
    return (
        None
        if constraint.parallel_direction is None
        else (0 if constraint.parallel_direction == "same" else 180)
    )


def _angular_residual(first: float, second: float) -> float:
    return abs((first - second + 180) % 360 - 180)


def _headings(
    description: RelativeDescription,
) -> tuple[dict[str, float], tuple[RelativeIssue, ...]]:
    ids = [course.course_id for course in description.courses]
    graph: dict[str, list[tuple[str, float, str]]] = {key: [] for key in ids}
    issues: list[RelativeIssue] = []
    for constraint in description.constraints:
        delta = _difference(constraint, description.frame.orientation)
        if delta is None:
            choices = (
                (-90.0, 90.0)
                if constraint.kind == "perpendicular"
                else (0.0, 180.0)
                if constraint.kind == "parallel"
                else ()
            )
            issues.append(
                RelativeIssue(
                    code="ambiguous_constraint",
                    message=f"Constraint {constraint.constraint_id!r} needs an explicit "
                    f"{constraint.kind} interpretation; closure is not used to choose one.",
                    constraint_ids=(constraint.constraint_id,),
                    course_ids=(constraint.from_course, constraint.to_course),
                    alternatives_deg=choices,
                )
            )
            continue
        graph[constraint.from_course].append(
            (constraint.to_course, delta, constraint.constraint_id)
        )
        graph[constraint.to_course].append(
            (constraint.from_course, -delta, constraint.constraint_id)
        )

    headings: dict[str, float] = {}
    anchored: set[str] = set()
    conflicting: set[str] = set()
    # Also inspect unanchored components: contradiction is not hidden by missing
    # constraints elsewhere. Their arbitrary seeds never become output geometry.
    for seed in ids:
        if seed in headings:
            continue
        is_anchored = seed == ids[0]
        headings[seed] = description.frame.first_azimuth_deg % 360 if is_anchored else 0
        pending = deque([seed])
        while pending:
            current = pending.popleft()
            if is_anchored:
                anchored.add(current)
            for neighbor, delta, constraint_id in graph[current]:
                expected = (headings[current] + delta) % 360
                if neighbor not in headings:
                    headings[neighbor] = expected
                    pending.append(neighbor)
                elif _angular_residual(headings[neighbor], expected) > ANGLE_TOLERANCE_DEG:
                    conflicting.add(constraint_id)
    if conflicting:
        issues.append(
            RelativeIssue(
                code="contradictory_constraints",
                message="Sourced angular relations disagree beyond the 1e-8 degree "
                "arithmetic tolerance. No relation was discarded or adjusted.",
                constraint_ids=tuple(sorted(conflicting)),
            )
        )
    missing = tuple(key for key in ids if key not in anchored)
    if missing:
        issues.append(
            RelativeIssue(
                code="insufficient_constraints",
                message="These courses have no determined heading relative to the first course.",
                course_ids=missing,
            )
        )
    return headings, tuple(issues)


def _stated_angle_sum(description: RelativeDescription) -> float | None:
    angles: dict[str, float] = {}
    for constraint in description.constraints:
        if constraint.kind == "interior":
            assert constraint.angle_deg is not None
            angles[constraint.to_course] = constraint.angle_deg
        elif constraint.kind == "exterior" and constraint.exterior_convention is not None:
            assert constraint.angle_deg is not None
            angles[constraint.to_course] = 360 - constraint.angle_deg
    return math.fsum(angles.values()) if len(angles) == len(description.courses) else None


def _geometry(
    description: RelativeDescription, headings: dict[str, float]
) -> RelativeAnalysisResult:
    courses = tuple(
        RelativeCourseGeometry(
            course_id=course.course_id,
            local_azimuth_deg=headings[course.course_id],
            delta_x_ft=course.distance_ft * math.sin(math.radians(headings[course.course_id])),
            delta_y_ft=course.distance_ft * math.cos(math.radians(headings[course.course_id])),
        )
        for course in description.courses
    )
    # Work relative to the origin for closure and area: translating a local
    # frame must not introduce the cancellation error of global shoelace terms.
    offsets: list[tuple[float, float]] = [(0, 0)]
    x, y = 0.0, 0.0
    for course in courses:
        x += course.delta_x_ft
        y += course.delta_y_ft
        offsets.append((x, y))
    dx = math.fsum(course.delta_x_ft for course in courses)
    dy = math.fsum(course.delta_y_ft for course in courses)
    misclosure = math.hypot(dx, dy)
    perimeter = math.fsum(course.distance_ft for course in description.courses)
    area = abs(math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in pairwise(offsets))) / 2
    origin_x, origin_y = description.frame.origin
    coordinates = [(origin_x + x, origin_y + y) for x, y in offsets]
    if not all(
        math.isfinite(value)
        for value in (dx, dy, misclosure, perimeter, area, *(v for p in coordinates for v in p))
    ):
        raise ValueError("nonfinite local geometry")
    coordinate_tolerance = min(
        COORDINATE_TOLERANCE_FT,
        min(course.distance_ft for course in description.courses) * 1e-6,
    )
    for (x, y), (px, py) in zip(offsets, coordinates, strict=True):
        if max(abs((px - origin_x) - x), abs((py - origin_y) - y)) > coordinate_tolerance:
            raise ValueError("translation loses local coordinate precision")
    for (a, b), course in zip(pairwise(coordinates), courses, strict=True):
        if (
            max(
                abs((b[0] - a[0]) - course.delta_x_ft),
                abs((b[1] - a[1]) - course.delta_y_ft),
            )
            > coordinate_tolerance
        ):
            raise ValueError("translated points cannot represent the local course vectors")
    precision = perimeter / misclosure if misclosure else None
    if precision is not None and not math.isfinite(precision):
        precision = None
    sign = 1 if description.frame.orientation == "cw" else -1
    closing = (180 - sign * (courses[0].local_azimuth_deg - courses[-1].local_azimuth_deg)) % 360
    return RelativeAnalysisResult(
        description=description,
        status="analyzed",
        points=tuple(Point(x=x, y=y) for x, y in coordinates),
        courses=courses,
        misclosure_ft=misclosure,
        misclosure_x_ft=dx,
        misclosure_y_ft=dy,
        perimeter_ft=perimeter,
        area_sq_ft=area,
        precision_denominator=precision,
        stated_angle_sum_deg=_stated_angle_sum(description),
        expected_angle_sum_deg=(len(courses) - 2) * 180,
        computed_closing_angle_deg=closing,
    )


def analyze_relative(description: RelativeDescription) -> RelativeAnalysisResult:
    """Analyze validated relative constraints without changing canonical status.

    A heading requires connection to the explicit local first-course frame.
    Ambiguous interpretations remain unresolved even if other constraints could
    determine the same relation. No partial geometry is returned on unresolved
    or inconsistent input. Positional misclosure is reported, never corrected.
    """
    headings, issues = _headings(description)
    angle_sum = _stated_angle_sum(description)
    if (
        angle_sum is not None
        and abs(angle_sum - (len(description.courses) - 2) * 180) > ANGLE_TOLERANCE_DEG
    ):
        issues += (
            RelativeIssue(
                code="contradictory_constraints",
                message="The complete stated interior angle sum disagrees with "
                "(n - 2) * 180 degrees; modulo-360 headings cannot resolve this conflict.",
                constraint_ids=tuple(
                    constraint.constraint_id
                    for constraint in description.constraints
                    if constraint.kind in {"interior", "exterior"}
                ),
            ),
        )
    if issues:
        return RelativeAnalysisResult(
            description=description,
            status=(
                "inconsistent"
                if any(issue.code == "contradictory_constraints" for issue in issues)
                else "unresolved"
            ),
            issues=issues,
        )
    try:
        return _geometry(description, headings)
    except (OverflowError, ValueError):
        return RelativeAnalysisResult(
            description=description,
            status="unresolved",
            issues=(
                RelativeIssue(
                    code="numerical_range",
                    message="The distances or origin exceed finite numerical geometry range "
                    "or lose local point/vector precision. Choose a representable local "
                    "origin and review the supplied magnitudes; "
                    "the arithmetic limit is min(1e-6 ft, shortest course * 1e-6).",
                ),
            ),
        )
