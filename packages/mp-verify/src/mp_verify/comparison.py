"""Deterministic advisory comparisons; no fitting, correction, or legal inference."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal

from mp_models.comparison import (
    CircularArcComparison,
    ComparedPair,
    ComparisonComponent,
    ComparisonDescription,
    ComparisonPair,
    ComparisonRequest,
    ComparisonSelection,
    DescriptionComparison,
    StructuralDifference,
)
from mp_models.deed_call import DeedCall
from mp_models.plot import XY, LinearUnit
from mp_models.plot_request import PlotCall

from .diagnostics import _curve_evidence, _supported_circular_arc
from .plot import prepare_plot, transform_point, unit_factor, validate_plot_placement

COMPARISON_VERSION = "comparison-1.1.0"


def comparison_input_hash(request: ComparisonRequest) -> str:
    return hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _finite(*values: float) -> None:
    if not all(math.isfinite(v) for v in values):
        raise ValueError("nonfinite comparison arithmetic")


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _excluded_boundary(call: DeedCall) -> bool:
    return call.is_tie_in or call.is_exception or call.is_meander or call.is_indefinite


@dataclass(frozen=True)
class _Group:
    length: float
    vector: XY
    bearing: float
    radius: float | None = None
    sweep: float | None = None
    turn: str | None = None


def _group(
    description: ComparisonDescription,
    selection: ComparisonSelection,
    output_unit: LinearUnit,
) -> _Group:
    if description.plot.relative is not None:
        raise ValueError("relative-only geometry is unsupported")
    records = description.plot.calls
    index = {r.id: i for i, r in enumerate(records)}
    positions = [index[id] for id in selection.call_ids]
    step = 1 if selection.direction == "forward" else -1
    if any(b != a + step for a, b in zip(positions, positions[1:], strict=False)):
        raise ValueError(
            "group must be contiguous, connected and ordered in explicit traversal direction"
        )
    if description.plot.foot_definition == "unknown_ft":
        raise ValueError("unknown foot definition cannot establish unit compatibility")
    factor = unit_factor(description.plot.foot_definition, output_unit)
    if any(
        call is not None and _curve_evidence(call) for call in (records[i].call for i in positions)
    ):
        if len(positions) != 1:
            raise ValueError(
                "grouped arcs or mixed line/arc groups unsupported; select individual circular arcs"
            )
        record = records[positions[0]]
        call = record.call
        assert call is not None
        if _excluded_boundary(call):
            raise ValueError("tie-in, exception, meander or indefinite boundary unsupported")
        arc = _supported_circular_arc(call, record.id)
        assert arc.radius_ft is not None and arc.sweep_deg is not None
        assert arc.start_tangent_deg is not None
        sign = 1 if arc.curve_dir == "right" else -1
        bearing = (arc.start_tangent_deg + (sign * arc.sweep_deg + 180 if step == -1 else 0)) % 360
        vector = (step * arc.end[0] * factor, step * arc.end[1] * factor)
        length, radius = arc.length_ft * factor, arc.radius_ft * factor
        _finite(length, radius, *vector)
        turn = arc.curve_dir if step == 1 else "left" if arc.curve_dir == "right" else "right"
        return _Group(length, vector, bearing, radius, arc.sweep_deg, turn)
    vectors = []
    lengths = []
    bearings = []
    for i in positions:
        call = records[i].call
        if call is None or _curve_evidence(call):
            raise ValueError(
                "unresolved or curved course unsupported; chord is not a straight boundary"
            )
        if _excluded_boundary(call):
            raise ValueError("tie-in, exception, meander or indefinite boundary unsupported")
        if call.bearing_azimuth_deg_from_north is None:
            raise ValueError("unresolved bearing; no invented orientation")
        length = call.distance_ft * factor
        bearing = (call.bearing_azimuth_deg_from_north + (180 if step == -1 else 0)) % 360
        angle = math.radians(bearing)
        vector = (length * math.sin(angle), length * math.cos(angle))
        _finite(length, *vector)
        lengths.append(length)
        bearings.append(bearing)
        vectors.append(vector)
    # Group eligibility requires the same recorded numeric heading. A user's
    # comparison tolerance cannot turn a bent chain into a straight boundary.
    if any(bearing != bearings[0] for bearing in bearings[1:]):
        raise ValueError("group members must be collinear and have the same traversal direction")
    length = math.fsum(lengths)
    vector = (math.fsum(v[0] for v in vectors), math.fsum(v[1] for v in vectors))
    _finite(length, *vector)
    return _Group(length, vector, math.degrees(math.atan2(*vector)) % 360)


def _unavailable(reason: str, *, position: bool = False) -> ComparisonComponent:
    return ComparisonComponent(
        outcome="unavailable" if position else "not_comparable", reason=reason
    )


def _component(difference: float, tolerance: float, units: str, reason: str) -> ComparisonComponent:
    _finite(difference)
    # Only compensate for subtraction roundoff at a declared inclusive boundary.
    agree = difference <= tolerance or math.isclose(difference, tolerance, rel_tol=1e-12, abs_tol=0)
    return ComparisonComponent(
        outcome="agree" if agree else "differ", reason=reason, difference=difference, units=units
    )


def _basis(request: ComparisonRequest) -> bool:
    a, b = request.left.bearing_basis, request.right.bearing_basis
    return request.right_to_left_transform is not None or (
        a.identity is not None
        and a.identity == b.identity
        and bool(a.source_references)
        and bool(b.source_references)
    )


def _position(
    request: ComparisonRequest, left: ComparisonSelection, right: ComparisonSelection
) -> ComparisonComponent:
    scene = request.scene
    if scene is None or not _basis(request):
        return _unavailable(
            "position requires a validated common scene, placements and documented orientation",
            position=True,
        )
    if scene.units == "unknown_ft":
        return _unavailable(
            "unknown scene foot definition blocks positional compatibility", position=True
        )
    endpoint_sets = []
    try:
        for description, selection in ((request.left, left), (request.right, right)):
            placement = description.placement
            if placement is None or placement.status == "unplaced":
                raise ValueError("position requires explicit placed geometry for both descriptions")
            if description.plot.foot_definition == "unknown_ft":
                raise ValueError("unknown native foot definition blocks positional compatibility")
            prepared = prepare_plot(description.plot)
            if (
                placement.calculation_id != prepared.geometry.calculation_id
                or placement.scene_id != scene.id
            ):
                raise ValueError("placement calculation or scene identity differs")
            validate_plot_placement(
                prepared.geometry,
                placement,
                scene,
                native_units=description.plot.foot_definition,
                orientation_supported=description.bearing_basis.identity is not None,
            )
            primitives = {p.call_id: p for p in prepared.geometry.primitives}
            if not set(selection.call_ids) <= set(primitives):
                raise ValueError("selected course lacks complete fresh primitive")
            # An unresolved preceding course prevents meaningful absolute native position.
            first_index = min(
                i for i, r in enumerate(description.plot.calls) if r.id in selection.call_ids
            )
            preceding = {
                r.id
                for r in description.plot.calls[:first_index]
                if not (r.call and r.call.is_tie_in)
            }
            for record in description.plot.calls[:first_index]:
                if (
                    record.call is not None
                    and not record.call.is_tie_in
                    and _curve_evidence(record.call)
                ):
                    _supported_circular_arc(record.call, record.id)
            if not preceding <= set(primitives):
                raise ValueError("unresolved preceding geometry prevents position")
            first, last = primitives[selection.call_ids[0]], primitives[selection.call_ids[-1]]
            points = (
                (first.start, last.end)
                if selection.direction == "forward"
                else (first.end, last.start)
            )
            endpoint_sets.append(
                tuple(
                    transform_point(
                        p,
                        placement,
                        native_units=description.plot.foot_definition,
                        scene_units=scene.units,
                    )
                    for p in points
                )
            )
        factor = unit_factor(scene.units, request.tolerances.linear_unit)
        differences = [
            math.hypot(a[0] - b[0], a[1] - b[1]) * factor
            for a, b in zip(*endpoint_sets, strict=True)
        ]
        return _component(
            max(differences),
            request.tolerances.position,
            request.tolerances.linear_unit,
            "maximum corresponding endpoint separation in validated shared scene; placement status retained in request",
        )
    except (ValueError, OverflowError, ArithmeticError) as exc:
        return _unavailable(str(exc), position=True)


def _pair(request: ComparisonRequest, pair: ComparisonPair) -> ComparedPair:
    left_records = {r.id: r for r in request.left.plot.calls}
    right_records = {r.id: r for r in request.right.plot.calls}
    base: dict[str, Any] = {
        "id": pair.id,
        "left_call_ids": pair.left.call_ids,
        "right_call_ids": pair.right.call_ids,
        "left_sources": tuple(left_records[id] for id in pair.left.call_ids),
        "right_sources": tuple(right_records[id] for id in pair.right.call_ids),
    }
    try:
        a = _group(request.left, pair.left, request.tolerances.linear_unit)
        b = _group(
            request.right,
            pair.right,
            request.tolerances.linear_unit,
        )
        if (a.radius is None) != (b.radius is None):
            raise ValueError(
                "circular arc and straight boundary are not comparable; no chord substitution"
            )
        curve = None
        if a.radius is not None and b.radius is not None:
            assert a.sweep is not None and b.sweep is not None
            curve = CircularArcComparison(
                radius=_component(
                    abs(b.radius - a.radius),
                    request.tolerances.radius,
                    request.tolerances.linear_unit,
                    "absolute circular radius difference after declared unit conversion",
                )
                if request.tolerances.radius is not None
                else _unavailable("explicit radius tolerance required"),
                sweep=_component(
                    abs(b.sweep - a.sweep),
                    request.tolerances.sweep_deg,
                    "degree",
                    "absolute circular sweep difference; major arc branch retained",
                )
                if request.tolerances.sweep_deg is not None
                else _unavailable("explicit sweep tolerance required"),
                turn=ComparisonComponent(
                    outcome="agree" if a.turn == b.turn else "differ",
                    reason=f"traversal turn after explicit reversal: left={a.turn}, right={b.turn}",
                ),
            )
        base["curve"] = curve
        length = _component(
            abs(b.length - a.length),
            request.tolerances.length,
            request.tolerances.linear_unit,
            "absolute analytic arc length difference after declared unit conversion"
            if curve is not None
            else "absolute aggregate length difference after declared unit conversion",
        )
        if not _basis(request):
            unavailable = _unavailable(
                "bearing bases unknown or incompatible; equal display labels do not establish compatibility"
            )
            return ComparedPair(
                **base,
                length=length,
                bearing=unavailable,
                displacement=unavailable,
                position=_unavailable(
                    "orientation/common placement evidence unavailable", position=True
                ),
            )
        rotation = (
            request.right_to_left_transform.rotation_deg if request.right_to_left_transform else 0
        )
        theta = math.radians(rotation % 360)
        bv = (
            b.vector[0] * math.cos(theta) + b.vector[1] * math.sin(theta),
            -b.vector[0] * math.sin(theta) + b.vector[1] * math.cos(theta),
        )
        bearing = _component(
            _angle(a.bearing, (b.bearing + rotation) % 360),
            request.tolerances.bearing_deg,
            "degree",
            "shortest unsigned start-tangent difference; explicit reversal and sourced rotation applied"
            if curve is not None
            else "shortest unsigned angular difference; explicit reversal and sourced rotation applied",
        )
        displacement = _component(
            math.hypot(bv[0] - a.vector[0], bv[1] - a.vector[1]),
            request.tolerances.displacement,
            request.tolerances.linear_unit,
            "norm of right-minus-left displacement; translation does not affect vectors",
        )
        return ComparedPair(
            **base,
            length=length,
            bearing=bearing,
            displacement=displacement,
            position=_position(request, pair.left, pair.right),
            left_displacement=a.vector,
            right_displacement=bv,
        )
    except (ValueError, ArithmeticError) as exc:
        unavailable = _unavailable(str(exc))
        return ComparedPair(
            **base,
            length=unavailable,
            bearing=unavailable,
            displacement=unavailable,
            position=_unavailable(
                "selected group lacks supported geometric evidence: " + str(exc), position=True
            ),
        )


def _content(record: PlotCall) -> dict[str, Any]:
    if record.call is None:
        return {"unresolved_quote": record.quote}
    return record.call.model_dump(mode="json", exclude={"course", "quality"})


def _structural(request: ComparisonRequest) -> tuple[StructuralDifference, ...]:
    left, right = request.left.plot.calls, request.right.plot.calls
    signatures = [
        [json.dumps(_content(r), sort_keys=True, allow_nan=False) for r in records]
        for records in (left, right)
    ]
    ls, rs = signatures
    results = []
    anchors = [(i, rs.index(s)) for i, s in enumerate(ls) if ls.count(s) == rs.count(s) == 1]

    def add(
        kind: Literal[
            "anchor",
            "ambiguous",
            "changed",
            "unmatched_left",
            "unmatched_right",
            "reordered",
            "split_candidate",
            "merge_candidate",
        ],
        li: tuple[int, ...],
        ri: tuple[int, ...],
        reason: str,
        fields: tuple[str, ...] = (),
        tentative: bool = True,
    ) -> None:
        results.append(
            StructuralDifference(
                kind=kind,
                left_call_ids=tuple(left[i].id for i in li),
                right_call_ids=tuple(right[i].id for i in ri),
                reason=reason,
                changed_fields=fields,
                tentative=tentative,
                left_sources=tuple(left[i] for i in li),
                right_sources=tuple(right[i] for i in ri),
            )
        )

    for i, s in enumerate(ls):
        matches = [j for j, other in enumerate(rs) if s == other]
        for j in matches:
            if ls.count(s) == len(matches) == 1:
                reordered = any((i - k) * (j - other) < 0 for k, other in anchors)
                add(
                    "reordered" if reordered else "anchor",
                    (i,),
                    (j,),
                    "unique exact call-content match reverses anchor order"
                    if reordered
                    else "unique exact call-content match; course ordinal/source identity excluded",
                    tentative=reordered,
                )
            else:
                add(
                    "ambiguous",
                    (i,),
                    (j,),
                    "repeated exact content has multiple possible correspondences; no occurrence selected",
                )
        if not matches:
            add(
                "unmatched_left",
                (i,),
                (),
                "no exact content counterpart; not evidence of a definitive omission",
            )
    for j, s in enumerate(rs):
        if s not in ls:
            add(
                "unmatched_right",
                (),
                (j,),
                "no exact content counterpart; not evidence of a definitive insertion",
            )
    # Same ordinal unmatched calls yield a transparent textual suggestion, not an alignment cost.
    for i in range(min(len(left), len(right))):
        if ls[i] not in rs and rs[i] not in ls:
            a, b = _content(left[i]), _content(right[i])
            fields = tuple(sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k)))
            add(
                "changed",
                (i,),
                (i,),
                "unmatched calls at same ordinal; tentative textual correspondence",
                fields,
            )
    # Candidate splits use only recorded numeric content in the SAME declared native unit.
    # They remain structural notation suggestions even with unknown bearing basis.
    if request.left.plot.foot_definition == request.right.plot.foot_definition != "unknown_ft":
        for single_side, singles, groups in (("left", left, right), ("right", right, left)):
            for i, single in enumerate(singles):
                call = single.call
                if (
                    call is None
                    or _curve_evidence(call)
                    or _excluded_boundary(call)
                    or call.bearing_azimuth_deg_from_north is None
                ):
                    continue
                for start in range(len(groups)):
                    members = []
                    for end in range(start, len(groups)):
                        part = groups[end].call
                        if (
                            part is None
                            or _curve_evidence(part)
                            or part.bearing_azimuth_deg_from_north
                            != call.bearing_azimuth_deg_from_north
                            or _excluded_boundary(part)
                        ):
                            break
                        members.append(part.distance_ft)
                        try:
                            total = math.fsum(members)
                        except OverflowError:
                            break
                        if end > start and math.isclose(
                            total, call.distance_ft, rel_tol=1e-12, abs_tol=0
                        ):
                            indexes = tuple(range(start, end + 1))
                            add(
                                "split_candidate" if single_side == "left" else "merge_candidate",
                                (i,) if single_side == "left" else indexes,
                                indexes if single_side == "left" else (i,),
                                "contiguous same recorded azimuth and exact summed native distance; tentative notation pattern, no geographic agreement implied",
                            )
                        if total > call.distance_ft:
                            break
    return tuple(results)


def compare_descriptions(request: ComparisonRequest) -> DescriptionComparison:
    """Compare immutable explicit selections; retain structural differences independently."""
    request = ComparisonRequest.model_validate(request.model_dump(mode="json"))
    return DescriptionComparison(
        input_hash=comparison_input_hash(request),
        left_id=request.left.id,
        right_id=request.right.id,
        pairs=tuple(_pair(request, p) for p in request.pairs),
        structural=_structural(request),
        tolerances=request.tolerances,
    )
