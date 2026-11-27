"""Behavioral and invariant tests for scene, corridor, PLSS, plot, and comparison verification."""

from __future__ import annotations

import math
import sys
from types import SimpleNamespace

import pytest
from mp_models import (
    DeedCall,
    LocalFrame,
    PlotCall,
    PlotRequest,
    RelativeConstraint,
    RelativeCourse,
    RelativeDescription,
    RelativeSource,
)
from mp_models.comparison import (
    BearingBasis,
    ComparisonDescription,
    ComparisonPair,
    ComparisonRequest,
    ComparisonSelection,
    ComparisonTolerance,
)
from mp_models.corridor import (
    CorridorErrorBudget,
    CorridorRequest,
    CorridorStation,
    CorridorWidthInterval,
)
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    DiagnosticSourceRef,
    QuantizationAssumptions,
    diagnostic_input_hash,
)
from mp_models.plot import (
    MapSource,
    PlotPlacement,
    PlotPrimitive,
    PlotScene,
    PointCorrespondence,
)
from mp_models.plss import (
    PLSSCorner,
    PLSSDerivationRequest,
    PLSSReferenceDataset,
    PLSSSectionKey,
    PLSSSectionReference,
)
from mp_verify.comparison import compare_descriptions
from mp_verify.corridor import analyze_corridor
from mp_verify.diagnostics import diagnose_closure
from mp_verify.plot import (
    arc_point,
    compare_points,
    prepare_plot,
    unit_factor,
    validate_plot_placement,
)
from mp_verify.plss import derive_plss
from mp_verify.relative import analyze_relative
from mp_verify.scene import projected_crs_unit, validate_scene


class TestSceneValidationInvariants:
    def test_projected_crs_unit_rejects_nonfinite_and_unsupported_axis_factors(self):
        bad_factor_crs = SimpleNamespace(
            is_projected=True,
            axis_info=[
                SimpleNamespace(unit_conversion_factor=float("nan")),
                SimpleNamespace(unit_conversion_factor=1.0),
            ],
        )
        with pytest.raises(ValueError, match="unavailable or invalid linear units"):
            projected_crs_unit(bad_factor_crs)

        unsupported_crs = SimpleNamespace(
            is_projected=True,
            axis_info=[
                SimpleNamespace(unit_conversion_factor=2.5),
                SimpleNamespace(unit_conversion_factor=2.5),
            ],
        )
        with pytest.raises(ValueError, match="unsupported, ambiguous, or differing"):
            projected_crs_unit(unsupported_crs)

    def test_validate_scene_rejects_bad_axis_order_and_local_crs(self):
        bad_axis = PlotScene.model_construct(
            id="s", name="S", kind="local", crs=None, units="m", axis_order="yx", basis="local"
        )
        with pytest.raises(ValueError, match="XY axis order"):
            validate_scene(bad_axis)

        local_with_crs = PlotScene.model_construct(
            id="s",
            name="S",
            kind="local",
            crs="EPSG:3857",
            units="m",
            axis_order="xy",
            basis="local",
        )
        with pytest.raises(ValueError, match="Local scenes cannot declare"):
            validate_scene(local_with_crs)

    def test_validate_scene_rejects_projected_crs_unit_mismatch_and_geographic_crs(self):
        pytest.importorskip("pyproj")
        # EPSG:3857 (meters) conflicts with declared international_ft.
        projected_ft = PlotScene(
            id="s",
            name="S",
            kind="projected",
            crs="EPSG:3857",
            units="international_ft",
            basis="grid",
        )
        with pytest.raises(ValueError, match="conflict with CRS linear units"):
            validate_scene(projected_ft)

        # Geographic CRS (EPSG:4326) is not projected -> rejected.
        geo_scene = PlotScene(
            id="s",
            name="S",
            kind="projected",
            crs="EPSG:4326",
            units="m",
            basis="grid",
        )
        with pytest.raises(ValueError, match="Invalid projected scene CRS"):
            validate_scene(geo_scene)

    def test_validate_scene_reports_missing_pyproj_extra(self, monkeypatch):
        projected_m = PlotScene(
            id="s",
            name="S",
            kind="projected",
            crs="EPSG:3857",
            units="m",
            basis="grid",
        )
        monkeypatch.setitem(sys.modules, "pyproj", None)
        with pytest.raises(ValueError, match="mp-review\\[geo\\]"):
            validate_scene(projected_m)


class TestCorridorGeometryInvariants:
    def _src(self) -> DiagnosticSourceRef:
        return DiagnosticSourceRef(source_id="deed", quote="recorded width")

    def _line_call(self, cid: str, course: int, az: float, dist: float, **extra) -> PlotCall:
        return PlotCall(
            id=cid,
            source_reference="deed p.1",
            call=DeedCall(
                course=course,
                direction_text=f"az {az}",
                bearing_azimuth_deg_from_north=az,
                distance_ft=dist,
                **extra,
            ),
        )

    def _corridor_req(
        self,
        calls: tuple[PlotCall, ...],
        widths: tuple[CorridorWidthInterval, ...],
        *,
        foot_definition: str = "international_ft",
        join: str = "miter",
        cap: str = "butt",
        max_error: float = 0.01,
        max_segments: int = 2048,
        relative: RelativeDescription | None = None,
    ) -> CorridorRequest:
        return CorridorRequest(
            id="corr",
            centerline=PlotRequest(
                title="Road",
                foot_definition=foot_definition,
                calls=calls,
                relative=relative,
            ),
            widths=widths,
            width_unit="international_ft",
            join=join,
            cap=cap,
            construction_source_refs=(self._src(),),
            error_budget=CorridorErrorBudget(
                max_error=max_error, unit="international_ft", max_segments=max_segments
            ),
        )

    def test_corridor_rejects_unknown_ft_blank_source_tie_in_incomplete_closed_and_coverage_gap(
        self,
    ):
        c1 = self._line_call("c1", 1, 90.0, 100.0)
        w1 = CorridorWidthInterval(
            id="w1",
            start=CorridorStation(call_id="c1", fraction=0.0),
            end=CorridorStation(call_id="c1", fraction=1.0),
            left_start=10.0,
            left_end=10.0,
            right_start=10.0,
            right_end=10.0,
            rule="step",
            source_refs=(self._src(),),
        )
        # unknown_ft centerline.
        r_unk = analyze_corridor(self._corridor_req((c1,), (w1,), foot_definition="unknown_ft"))
        assert r_unk.availability == "unsupported"
        assert any("explicit foot definition" in lim for lim in r_unk.limitations)

        # Blank source_reference.
        blank_src = c1.model_copy(update={"source_reference": "   "})
        r_src = analyze_corridor(self._corridor_req((blank_src,), (w1,)))
        assert r_src.availability == "incomplete"

        # Tie-in call in centerline.
        tie_call = self._line_call("c1", 1, 90.0, 100.0, is_tie_in=True)
        r_tie = analyze_corridor(self._corridor_req((tie_call,), (w1,)))
        assert r_tie.availability == "unsupported"
        assert any("tie-ins" in lim for lim in r_tie.limitations)

        # Relative-only centerline unsupported.
        rel_src = RelativeSource(reference="p1", quote="straight")
        rel_calls = tuple(self._line_call(f"r{i}", i, (i - 1) * 90.0, 100.0) for i in (1, 2, 3))
        rel_desc = RelativeDescription(
            frame=LocalFrame(name="L", first_azimuth_deg=0.0, origin=(0.0, 0.0), orientation="cw"),
            courses=tuple(
                RelativeCourse(
                    course_id=f"r{i}",
                    distance_ft=100.0,
                    recorded_bearing_azimuth_deg_from_north=(i - 1) * 90.0,
                    source=rel_src,
                )
                for i in (1, 2, 3)
            ),
            constraints=(
                RelativeConstraint(
                    constraint_id="k1",
                    kind="interior",
                    from_course="r1",
                    to_course="r2",
                    angle_deg=90.0,
                    source=rel_src,
                ),
            ),
        )
        w_rel = w1.model_copy(
            update={
                "start": CorridorStation(call_id="r1", fraction=0.0),
                "end": CorridorStation(call_id="r3", fraction=1.0),
            }
        )
        r_rel = analyze_corridor(self._corridor_req(rel_calls, (w_rel,), relative=rel_desc))
        assert r_rel.availability == "unsupported"
        assert any("relative-only" in lim for lim in r_rel.limitations)

        # Incomplete centerline (chord-only curve).
        chord_only = PlotCall(
            id="c1",
            source_reference="deed p.1",
            call=DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=200.0,
                chord_bearing="N 90° E",
                chord_length_ft=100.0,
            ),
        )
        r_inc = analyze_corridor(self._corridor_req((chord_only,), (w1,)))
        assert r_inc.availability == "unsupported"

        # Closed centerline rejected.
        square = (
            self._line_call("c1", 1, 0.0, 100.0),
            self._line_call("c2", 2, 90.0, 100.0),
            self._line_call("c3", 3, 180.0, 100.0),
            self._line_call("c4", 4, 270.0, 100.0),
        )
        w_sq = w1.model_copy(update={"end": CorridorStation(call_id="c4", fraction=1.0)})
        r_closed = analyze_corridor(self._corridor_req(square, (w_sq,)))
        assert r_closed.availability == "unsupported"
        assert any("closed centerlines" in lim for lim in r_closed.limitations)

        # Missing width coverage to the end of the centerline.
        w_short = w1.model_copy(update={"end": CorridorStation(call_id="c1", fraction=0.5)})
        r_cov = analyze_corridor(self._corridor_req((c1,), (w_short,)))
        assert r_cov.availability == "incomplete"
        assert any("missing width coverage" in lim for lim in r_cov.limitations)

    def test_corridor_joins_limits_and_helper_guards(self):
        # Multi-call centerline with separate width rows exercises primitive skip (b <= a).
        c1 = self._line_call("c1", 1, 0.0, 100.0)
        c2 = self._line_call("c2", 2, 90.0, 100.0)
        w1 = CorridorWidthInterval(
            id="w1",
            start=CorridorStation(call_id="c1", fraction=0.0),
            end=CorridorStation(call_id="c1", fraction=1.0),
            left_start=10.0,
            left_end=10.0,
            right_start=10.0,
            right_end=10.0,
            rule="step",
            source_refs=(self._src(),),
        )
        w2 = CorridorWidthInterval(
            id="w2",
            start=CorridorStation(call_id="c2", fraction=0.0),
            end=CorridorStation(call_id="c2", fraction=1.0),
            left_start=20.0,
            left_end=20.0,
            right_start=10.0,
            right_end=10.0,
            rule="step",
            source_refs=(self._src(),),
        )
        # Round join with step width change at corner is unsupported.
        r_step_round = analyze_corridor(self._corridor_req((c1, c2), (w1, w2), join="round"))
        assert r_step_round.availability == "unsupported"
        assert any("step-radius join unsupported" in lim for lim in r_step_round.limitations)

        # 180-degree centerline reversal (open — does not return to origin) is unsupported.
        c_rev = self._line_call("c2", 2, 180.0, 50.0)
        w_rev = w1.model_copy(update={"end": CorridorStation(call_id="c2", fraction=1.0)})
        r_rev = analyze_corridor(self._corridor_req((c1, c_rev), (w_rev,)))
        assert r_rev.availability == "unsupported"
        assert any("180-degree centerline reversals" in lim for lim in r_rev.limitations)

        # Error budget smaller than floating-point resolution fails cleanly.
        r_tiny_budget = analyze_corridor(self._corridor_req((c1,), (w1,), max_error=1e-16))
        assert r_tiny_budget.availability == "unsupported"
        assert any(
            "floating point coordinate resolution" in lim for lim in r_tiny_budget.limitations
        )

        # Error budget underflowing tolerance / 2 to 0.0.
        r_subnormal = analyze_corridor(self._corridor_req((c1,), (w1,), max_error=1e-323))
        assert r_subnormal.availability == "unsupported"

        # Complete boundary exceeding max_segments=4 (2-course corridor with square caps has >4 vertices).
        r_max_seg = analyze_corridor(
            self._corridor_req((c1, c2), (w_rev,), cap="square", max_segments=4)
        )
        assert r_max_seg.availability == "unsupported"
        assert any("max_segments" in lim for lim in r_max_seg.limitations)

        # Public corridor arithmetic, budget, centerline precision, and parallel-taper join guards:
        # 1) Nonfinite corridor offset arithmetic (huge course + huge width overflows float).
        huge_call = self._line_call("c1", 1, 45.0, 1e308)
        w_huge = CorridorWidthInterval(
            id="wh",
            start=CorridorStation(call_id="c1", fraction=0.0),
            end=CorridorStation(call_id="c1", fraction=1.0),
            left_start=1.6e308,
            left_end=1.6e308,
            right_start=10.0,
            right_end=10.0,
            rule="step",
            source_refs=(self._src(),),
        )
        r_overflow = analyze_corridor(self._corridor_req((huge_call,), (w_huge,)))
        assert r_overflow.availability == "unsupported"
        assert any("nonfinite corridor arithmetic" in lim for lim in r_overflow.limitations)

        # 2) Nonfinite offset error bound on a circular arc with huge offset width (max(R+w) * angle^2 overflows).
        arc_call = PlotCall(
            id="c1",
            source_reference="deed p.1",
            call=DeedCall(
                course=1,
                direction_text="arc",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0 * (math.pi / 2),
                curve_dir="right",
                radius_ft=100.0,
                delta_deg=90.0,
            ),
        )
        w_huge_arc = w_huge.model_copy(update={"left_start": 1e308, "left_end": 1e308})
        r_arc_ov = analyze_corridor(self._corridor_req((arc_call,), (w_huge_arc,)))
        assert r_arc_ov.availability == "unsupported"
        assert any("nonfinite offset error bound" in lim for lim in r_arc_ov.limitations)

        # 3) Centerline precision loss causes partial prepared centerline -> incomplete corridor.
        prec_calls = (
            self._line_call("c1", 1, 90.0, 1e20),
            self._line_call("c2", 2, 90.0, 1.0),
        )
        r_prec = analyze_corridor(self._corridor_req(prec_calls, (w_rev,)))
        assert r_prec.availability == "incomplete"
        assert any("centerline geometry is incomplete" in lim for lim in r_prec.limitations)

        # 4) Converted error budget overflowing float (1e308 m -> ft).
        req_huge_budget = self._corridor_req((c1,), (w1,)).model_copy(
            update={"error_budget": CorridorErrorBudget(max_error=1e308, unit="m")}
        )
        r_budget_ov = analyze_corridor(req_huge_budget)
        assert r_budget_ov.availability == "unsupported"
        assert any(
            "outside representable positive arithmetic" in lim for lim in r_budget_ov.limitations
        )

        # 5) Self-crossing 90-degree hook centerline fails corridor boundary topology validation.
        hook_calls = (
            self._line_call("c1", 1, 90.0, 100.0),
            self._line_call("c2", 2, 0.0, 100.0),
            self._line_call("c3", 3, 270.0, 50.0),
            self._line_call("c4", 4, 180.0, 150.0),
        )
        w_hook = w1.model_copy(update={"end": CorridorStation(call_id="c4", fraction=1.0)})
        r_hook = analyze_corridor(self._corridor_req(hook_calls, (w_hook,), join="bevel"))
        assert r_hook.availability == "topology_failed"
        assert any("corridor boundary topology failed" in lim for lim in r_hook.limitations)

        # 6) Nearly-parallel tapered left offsets at a 90-degree corner exceed join conditioning:
        # Course 1 goes North (0..100) with left tapering 10->110 (offset vector (-100, 100));
        # Course 2 goes West (0..-100) with left tapering 110->10 (offset vector (-100, 100)).
        c_west = self._line_call("c2", 2, 270.0, 100.0)
        wt1 = CorridorWidthInterval(
            id="w1",
            start=CorridorStation(call_id="c1", fraction=0.0),
            end=CorridorStation(call_id="c1", fraction=1.0),
            left_start=10.0,
            left_end=110.0,
            right_start=10.0,
            right_end=10.0,
            rule="linear_taper",
            source_refs=(self._src(),),
        )
        wt2 = CorridorWidthInterval(
            id="w2",
            start=CorridorStation(call_id="c2", fraction=0.0),
            end=CorridorStation(call_id="c2", fraction=1.0),
            left_start=110.0,
            left_end=10.0,
            right_start=10.0,
            right_end=10.0,
            rule="linear_taper",
            source_refs=(self._src(),),
        )
        r_par_join = analyze_corridor(self._corridor_req((c1, c_west), (wt1, wt2), join="miter"))
        assert r_par_join.availability == "unsupported"
        assert any("offset join conditioning" in lim for lim in r_par_join.limitations)


class TestPLSSDerivationInvariants:
    def _plss_request(
        self,
        *,
        corners: tuple[PLSSCorner, ...] | None = None,
        selected_reference_id: str = "sec-1",
        scene_basis: str = "grid",
        scene_id: str = "grid-scene",
        source_id: str = "src-1",
        aliquot_steps: tuple[str, ...] = ("NE4",),
    ) -> PLSSDerivationRequest:
        sec = PLSSSectionKey(
            principal_meridian="Fifth Principal Meridian",
            township=1,
            township_direction="N",
            range=2,
            range_direction="W",
            section=12,
        )
        if corners is None:
            corners = (
                PLSSCorner(name="SW", xy=(0.0, 0.0), source_id=source_id),
                PLSSCorner(name="SE", xy=(1000.0, 0.0), source_id=source_id),
                PLSSCorner(name="NE", xy=(1000.0, 1000.0), source_id=source_id),
                PLSSCorner(name="NW", xy=(0.0, 1000.0), source_id=source_id),
            )
        scene = PlotScene(
            id=scene_id,
            name="Projected",
            kind="projected",
            crs="EPSG:3857",
            units="m",
            basis=scene_basis,
        )
        source = MapSource(
            id=source_id,
            label="County PLSS",
            sha256="a" * 64,
            native_crs="EPSG:3857",
            native_units="m",
        )
        dataset = PLSSReferenceDataset(
            id="ds-1",
            version="2026.1",
            authority_citation="County GIS",
            scene=scene,
            source=source,
            references=(
                PLSSSectionReference(
                    id="sec-1",
                    section=sec,
                    subdivision_class="rectangular",
                    corners=corners,
                ),
            ),
        )
        return PLSSDerivationRequest(
            dataset=dataset,
            selected_dataset_id="ds-1",
            selected_reference_id=selected_reference_id,
            section=sec,
            rule="rectangular_aliquot_v1",
            aliquot_steps=aliquot_steps,
        )

    def test_plss_unsupported_branches(self):
        pytest.importorskip("pyproj")

        # Absent reference ID.
        r_ref = derive_plss(self._plss_request(selected_reference_id="missing"))
        assert r_ref.availability == "unsupported"
        assert "absent or ambiguous" in r_ref.reason

        # Scene basis not grid.
        r_basis = derive_plss(self._plss_request(scene_basis="local"))
        assert r_basis.availability == "unsupported"
        assert "projected grid CRS" in r_basis.reason

        # Non-orthogonal axes (sheared parallelogram).
        sheared = (
            PLSSCorner(name="SW", xy=(0.0, 0.0), source_id="src-1"),
            PLSSCorner(name="SE", xy=(1000.0, 0.0), source_id="src-1"),
            PLSSCorner(name="NE", xy=(1100.0, 1000.0), source_id="src-1"),
            PLSSCorner(name="NW", xy=(100.0, 1000.0), source_id="src-1"),
        )
        r_shear = derive_plss(self._plss_request(corners=sheared))
        assert r_shear.availability == "unsupported"
        assert "not orthogonal" in r_shear.reason

        # Nonfinite arithmetic on huge coordinates (cross overflows to inf).
        huge = (
            PLSSCorner(name="SW", xy=(0.0, 0.0), source_id="src-1"),
            PLSSCorner(name="SE", xy=(1e200, 0.0), source_id="src-1"),
            PLSSCorner(name="NE", xy=(1e200, 1e200), source_id="src-1"),
            PLSSCorner(name="NW", xy=(0.0, 1e200), source_id="src-1"),
        )
        r_huge = derive_plss(self._plss_request(corners=huge))
        assert r_huge.availability == "unsupported"
        assert "nonfinite" in r_huge.reason

        # Derived aliquot dimensions below precision: width=100 passes section check
        # (> 1024 * tol ~ 8.0 at 1e12), but 8 halvings (100/256 ~ 0.39) fall below precision.
        tiny_at_large_offset = (
            PLSSCorner(name="SW", xy=(1e12, 1e12), source_id="src-1"),
            PLSSCorner(name="SE", xy=(1e12 + 100.0, 1e12), source_id="src-1"),
            PLSSCorner(name="NE", xy=(1e12 + 100.0, 1e12 + 100.0), source_id="src-1"),
            PLSSCorner(name="NW", xy=(1e12, 1e12 + 100.0), source_id="src-1"),
        )
        r_prec = derive_plss(
            self._plss_request(corners=tiny_at_large_offset, aliquot_steps=("NE4",) * 8)
        )
        assert r_prec.availability == "unsupported"
        assert "below supported coordinate precision" in r_prec.reason

        # Scene ID colliding with source ID.
        r_collide = derive_plss(self._plss_request(scene_id="same-id", source_id="same-id"))
        assert r_collide.availability == "unsupported"
        assert "globally unique" in r_collide.reason


class TestPlotAndComparisonInvariants:
    def test_plot_helpers_arc_analytic_area_units_and_placement_guards(self):
        # Unsupported zero-sweep circular arc stays unresolved via public prepare_plot.
        zero_sweep = DeedCall(
            course=1,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=10.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=0.0,
        )
        zero_geom = prepare_plot(
            PlotRequest(title="Zero sweep", calls=(PlotCall(id="c1", call=zero_sweep),))
        ).geometry
        assert zero_geom.completeness == "unresolved"
        assert zero_geom.primitives == ()
        assert "sweep unresolved or unsupported" in zero_geom.unresolved[0].reason

        # Huge line coordinates cause analytic area overflow via public prepare_plot.
        huge_area_req = PlotRequest(
            title="Huge area",
            calls=(
                PlotCall(
                    id="c1",
                    call=DeedCall(
                        course=1,
                        direction_text="N",
                        bearing_azimuth_deg_from_north=0.0,
                        distance_ft=1e200,
                    ),
                ),
                PlotCall(
                    id="c2",
                    call=DeedCall(
                        course=2,
                        direction_text="E",
                        bearing_azimuth_deg_from_north=90.0,
                        distance_ft=1e200,
                    ),
                ),
            ),
        )
        with pytest.raises(ValueError, match="nonfinite plot area"):
            prepare_plot(huge_area_req)

        # arc_point rejects line primitive and out-of-range fraction.
        line = PlotPrimitive(
            kind="line", call_id="c1", start=(0.0, 0.0), end=(10.0, 0.0), length_ft=10.0
        )
        with pytest.raises(ValueError, match="requires an arc"):
            arc_point(line, 0.5)
        arc_prim = PlotPrimitive(
            kind="arc",
            call_id="a1",
            start=(0.0, 0.0),
            end=(10.0, 10.0),
            center=(10.0, 0.0),
            radius_ft=10.0,
            sweep_deg=90.0,
            curve_dir="right",
            start_tangent_deg=0.0,
            length_ft=10.0 * math.pi / 2,
        )
        with pytest.raises(ValueError, match="fraction must be in"):
            arc_point(arc_prim, 1.5)

        # unit_factor rejects unsupported unit name.
        with pytest.raises(ValueError, match="unsupported linear units"):
            unit_factor("cubit", "m")  # type: ignore[arg-type]

        # prepare_plot with tie-in call excluded and relative description (analyzed & unresolved).
        tie_plot = prepare_plot(
            PlotRequest(
                title="With tie-in",
                calls=(
                    PlotCall(
                        id="tie",
                        call=DeedCall(
                            course=1,
                            direction_text="N",
                            bearing_azimuth_deg_from_north=0.0,
                            distance_ft=20.0,
                            is_tie_in=True,
                        ),
                    ),
                    PlotCall(
                        id="c1",
                        call=DeedCall(
                            course=2,
                            direction_text="E",
                            bearing_azimuth_deg_from_north=90.0,
                            distance_ft=100.0,
                        ),
                    ),
                ),
            )
        )
        assert any("tie-in excluded" in r for r in tie_plot.geometry.reasons)

        src = RelativeSource(reference="p1", quote="angle")
        rel_calls = tuple(
            PlotCall(
                id=f"c{i}",
                call=DeedCall(course=i, direction_text="straight", distance_ft=100.0),
            )
            for i in (1, 2, 3)
        )
        rel_unresolved = RelativeDescription(
            frame=LocalFrame(name="L", first_azimuth_deg=0.0, origin=(0.0, 0.0), orientation="cw"),
            courses=tuple(
                RelativeCourse(course_id=f"c{i}", distance_ft=100.0, source=src) for i in (1, 2, 3)
            ),
            constraints=(),
        )
        prep_rel = prepare_plot(PlotRequest(title="Rel", calls=rel_calls, relative=rel_unresolved))
        assert prep_rel.geometry.completeness == "unresolved"
        assert any(
            "relative constraints unresolved" in u.reason for u in prep_rel.geometry.unresolved
        )

        # validate_plot_placement: scenario_id, precision loss, referenced on local scene.
        scene = PlotScene(id="s", name="Local", kind="local", units="international_ft")
        base_pl = PlotPlacement(
            id="pl",
            calculation_id=tie_plot.geometry.calculation_id,
            geometry_hash=tie_plot.geometry.geometry_hash,
            scene_id="s",
            status="approximate",
            rationale="manual",
        )
        scen_pl = base_pl.model_copy(
            update={
                "scenario_id": "sc1",
                "baseline_geometry_hash": "a" * 64,
                "baseline_placement_id": "pl0",
            }
        )
        with pytest.raises(ValueError, match="scenario placements"):
            validate_plot_placement(
                tie_plot.geometry,
                scen_pl,
                scene,
                native_units="international_ft",
                orientation_supported=True,
            )

        ref_pl = base_pl.model_copy(
            update={
                "status": "referenced",
                "position_evidence": ("monument",),
                "orientation_evidence": ("basis",),
            }
        )
        with pytest.raises(ValueError, match="referenced placement requires supported projected"):
            validate_plot_placement(
                tie_plot.geometry,
                ref_pl,
                scene,
                native_units="international_ft",
                orientation_supported=True,
            )

        # compare_points: unplaced, duplicate IDs, and precision-loss exception -> not_comparable.
        unplaced = base_pl.model_copy(update={"status": "unplaced"})
        res_unplaced = compare_points(
            unplaced, (), native_units="international_ft", scene_units="international_ft"
        )
        assert res_unplaced.status == "not_comparable"

        corr = PointCorrespondence(id="pt1", deed_point=(0.0, 0.0), map_point=(1.0, 1.0))
        with pytest.raises(ValueError, match="must be unique"):
            compare_points(
                base_pl,
                (corr, corr),
                native_units="international_ft",
                scene_units="international_ft",
            )

        huge_pl = base_pl.model_copy(update={"translation": (1e18, 0.0)})
        res_loss = compare_points(
            huge_pl,
            (PointCorrespondence(id="pt1", deed_point=(1.0, 0.0), map_point=(1e18 + 1.0, 0.0)),),
            native_units="international_ft",
            scene_units="international_ft",
        )
        assert res_loss.status == "not_comparable"
        assert "precision" in res_loss.reason

    def test_comparison_edge_cases_and_position_guards(self):
        basis = BearingBasis(label="Grid", identity="NAD83", source_references=("deed p.1",))
        tol = ComparisonTolerance(
            length=0.5,
            displacement=0.5,
            position=0.5,
            linear_unit="international_ft",
            bearing_deg=0.5,
            source_references=("review",),
        )
        # Unit conversion scaling sys.float_info.max from us_survey_ft to international_ft overflows
        # to inf, exercising the nonfinite comparison arithmetic guard through public compare_descriptions.
        max_call = DeedCall(
            course=1,
            direction_text="N",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=sys.float_info.max,
        )
        comp_nonfinite = compare_descriptions(
            ComparisonRequest(
                left=ComparisonDescription(
                    id="max-l",
                    plot=PlotRequest(
                        title="Max L",
                        calculation_id="ml",
                        foot_definition="us_survey_ft",
                        calls=(PlotCall(id="c1", call=max_call),),
                    ),
                    bearing_basis=basis,
                ),
                right=ComparisonDescription(
                    id="max-r",
                    plot=PlotRequest(
                        title="Max R",
                        calculation_id="mr",
                        foot_definition="international_ft",
                        calls=(PlotCall(id="c2", call=max_call),),
                    ),
                    bearing_basis=basis,
                ),
                pairs=(
                    ComparisonPair(
                        id="p-ov",
                        left=ComparisonSelection(call_ids=("c1",), direction="forward"),
                        right=ComparisonSelection(call_ids=("c2",), direction="forward"),
                    ),
                ),
                tolerances=tol,
            )
        )
        assert comp_nonfinite.pairs[0].displacement.outcome == "not_comparable"
        assert "nonfinite comparison arithmetic" in comp_nonfinite.pairs[0].displacement.reason
        line1 = DeedCall(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        )
        meander_arc = DeedCall(
            course=2,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=50.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=30.0,
            arc_length_ft=100.0 * math.radians(30.0),
            is_meander=True,
        )
        left_req = PlotRequest(
            title="Left",
            calculation_id="lcalc",
            foot_definition="international_ft",
            calls=(
                PlotCall(id="l0", call=None, quote="illegible course"),
                PlotCall(id="l1", call=line1),
                PlotCall(id="l2", call=meander_arc),
            ),
        )
        right_req = PlotRequest(
            title="Right",
            calculation_id="rcalc",
            foot_definition="international_ft",
            calls=(
                PlotCall(id="r1", call=line1),
                PlotCall(id="r2", call=line1.model_copy(update={"course": 2})),
            ),
        )
        scene = PlotScene(id="sc", name="Local", kind="local", units="international_ft")
        l_prep = prepare_plot(left_req)
        r_prep = prepare_plot(right_req)
        unplaced = PlotPlacement(
            id="pl-u",
            calculation_id="lcalc",
            geometry_hash=l_prep.geometry.geometry_hash,
            scene_id="sc",
            status="unplaced",
            rationale="unplaced",
        )
        wrong_scene_pl = PlotPlacement(
            id="pl-r",
            calculation_id="rcalc",
            geometry_hash=r_prep.geometry.geometry_hash,
            scene_id="other-scene",
            status="approximate",
            rationale="wrong scene",
        )
        # Exercises: call=None in _group & _content, meander arc in _group, unplaced in _position.
        comp = compare_descriptions(
            ComparisonRequest(
                left=ComparisonDescription(
                    id="left", plot=left_req, bearing_basis=basis, placement=unplaced
                ),
                right=ComparisonDescription(
                    id="right", plot=right_req, bearing_basis=basis, placement=wrong_scene_pl
                ),
                pairs=(
                    ComparisonPair(
                        id="p-none",
                        left=ComparisonSelection(call_ids=("l0",), direction="forward"),
                        right=ComparisonSelection(call_ids=("r1",), direction="forward"),
                    ),
                    ComparisonPair(
                        id="p-arc",
                        left=ComparisonSelection(call_ids=("l2",), direction="forward"),
                        right=ComparisonSelection(call_ids=("r2",), direction="forward"),
                    ),
                    ComparisonPair(
                        id="p-pos",
                        left=ComparisonSelection(call_ids=("l1",), direction="forward"),
                        right=ComparisonSelection(call_ids=("r1",), direction="forward"),
                    ),
                ),
                tolerances=tol,
                scene=scene,
            )
        )
        by_id = {p.id: p for p in comp.pairs}
        assert by_id["p-none"].length.outcome == "not_comparable"
        assert by_id["p-arc"].length.outcome == "not_comparable"
        assert "meander" in by_id["p-arc"].length.reason
        assert by_id["p-pos"].position.outcome == "unavailable"
        assert "explicit placed geometry" in by_id["p-pos"].position.reason

        # Wrong scene ID on right placement while left is placed.
        ok_left_pl = PlotPlacement(
            id="pl-l",
            calculation_id="lcalc",
            geometry_hash=l_prep.geometry.geometry_hash,
            scene_id="sc",
            status="approximate",
            rationale="ok",
        )
        # First call l0 is unresolved -> l1 lacks fresh primitive.
        comp2 = compare_descriptions(
            ComparisonRequest(
                left=ComparisonDescription(
                    id="left", plot=left_req, bearing_basis=basis, placement=ok_left_pl
                ),
                right=ComparisonDescription(
                    id="right", plot=right_req, bearing_basis=basis, placement=wrong_scene_pl
                ),
                pairs=(
                    ComparisonPair(
                        id="p-pos",
                        left=ComparisonSelection(call_ids=("l1",), direction="forward"),
                        right=ComparisonSelection(call_ids=("r1",), direction="forward"),
                    ),
                ),
                tolerances=tol,
                scene=scene,
            )
        )
        assert comp2.pairs[0].position.outcome == "unavailable"
        assert "lacks complete fresh primitive" in comp2.pairs[0].position.reason

        # Left placed cleanly, right has wrong scene ID -> "placement calculation or scene identity differs".
        good_left = PlotRequest(
            title="L",
            calculation_id="lcalc",
            foot_definition="international_ft",
            calls=(PlotCall(id="l1", call=line1),),
        )
        gl_prep = prepare_plot(good_left)
        gl_pl = PlotPlacement(
            id="pl-gl",
            calculation_id="lcalc",
            geometry_hash=gl_prep.geometry.geometry_hash,
            scene_id="sc",
            status="approximate",
            rationale="ok",
        )
        comp3 = compare_descriptions(
            ComparisonRequest(
                left=ComparisonDescription(
                    id="left", plot=good_left, bearing_basis=basis, placement=gl_pl
                ),
                right=ComparisonDescription(
                    id="right", plot=right_req, bearing_basis=basis, placement=wrong_scene_pl
                ),
                pairs=(
                    ComparisonPair(
                        id="p-pos",
                        left=ComparisonSelection(call_ids=("l1",), direction="forward"),
                        right=ComparisonSelection(call_ids=("r1",), direction="forward"),
                    ),
                ),
                tolerances=tol,
                scene=scene,
            )
        )
        assert "scene identity differs" in comp3.pairs[0].position.reason

        # Overflow in structural split candidate summation (1e308 + 1e308 -> OverflowError caught).
        huge_call = DeedCall(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=1e308
        )
        huge_left = PlotRequest(
            title="H1",
            calculation_id="h1",
            foot_definition="international_ft",
            calls=(PlotCall(id="a", call=huge_call),),
        )
        huge_right = PlotRequest(
            title="H2",
            calculation_id="h2",
            foot_definition="international_ft",
            calls=(
                PlotCall(id="b1", call=huge_call),
                PlotCall(id="b2", call=huge_call.model_copy(update={"course": 2})),
            ),
        )
        comp_ov = compare_descriptions(
            ComparisonRequest(
                left=ComparisonDescription(id="h1", plot=huge_left, bearing_basis=basis),
                right=ComparisonDescription(id="h2", plot=huge_right, bearing_basis=basis),
                tolerances=tol,
            )
        )
        assert not any(s.kind == "split_candidate" for s in comp_ov.structural)

    def test_diagnostics_and_relative_numerical_limits_fail_closed(self):
        # 360-degree full-circle arc (derived from arc_length_ft without stated delta_deg) is unsupported.
        full_arc = DiagnosticCall(
            call_id="circle",
            call=DeedCall(
                course=1,
                direction_text="circle",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=2 * math.pi * 50.0,
                curve_dir="right",
                radius_ft=50.0,
                arc_length_ft=2 * math.pi * 50.0,
            ),
        )
        full_diag = diagnose_closure(
            ClosureDiagnosticRequest(
                request_id="req-circle",
                input_id="circle",
                input_sha256=diagnostic_input_hash((full_arc,)),
                calls=(full_arc,),
                frame=DiagnosticFrame(name="Rec"),
            )
        )
        assert full_diag.availability == "unsupported"
        assert any("full circles unsupported" in lim for lim in full_diag.limitations)

        # Overflowing quantization bound (single term 1e308 * 2 * sin(pi/2) = inf) and overflowing
        # residual fail closed without exposing partial diagnostic calculations.
        quant_calls = (
            DiagnosticCall(
                call_id="c1",
                call=DeedCall(
                    course=1,
                    direction_text="N",
                    bearing_azimuth_deg_from_north=0.0,
                    distance_ft=1e308,
                ),
            ),
            DiagnosticCall(
                call_id="c2",
                call=DeedCall(
                    course=2,
                    direction_text="E",
                    bearing_azimuth_deg_from_north=90.0,
                    distance_ft=10.0,
                ),
            ),
            DiagnosticCall(
                call_id="c3",
                call=DeedCall(
                    course=3,
                    direction_text="S",
                    bearing_azimuth_deg_from_north=180.0,
                    distance_ft=10.0,
                ),
            ),
        )
        diag_quant = diagnose_closure(
            ClosureDiagnosticRequest(
                request_id="req-quant",
                input_id="huge",
                input_sha256=diagnostic_input_hash(quant_calls),
                calls=quant_calls,
                frame=DiagnosticFrame(name="Rec"),
                precision=QuantizationAssumptions(
                    distance_increment_ft=0.01,
                    bearing_increment_arcsec=1296000.0,
                    evidence="stated",
                ),
            )
        )
        assert diag_quant.availability == "unsupported"
        assert any("finite arithmetic" in lim for lim in diag_quant.limitations)

        # Relative geometry: nonfinite area overflow (1e200^2) and unrepresentable translated origin fail closed.
        rel_src = RelativeSource(reference="p1", quote="right angle")
        huge_rel = RelativeDescription(
            frame=LocalFrame(name="L", first_azimuth_deg=0.0, origin=(0.0, 0.0), orientation="cw"),
            courses=tuple(
                RelativeCourse(course_id=f"c{i}", distance_ft=1e200, source=rel_src)
                for i in (1, 2, 3)
            ),
            constraints=(
                RelativeConstraint(
                    constraint_id="k1",
                    kind="interior",
                    from_course="c1",
                    to_course="c2",
                    angle_deg=90.0,
                    source=rel_src,
                ),
                RelativeConstraint(
                    constraint_id="k2",
                    kind="interior",
                    from_course="c2",
                    to_course="c3",
                    angle_deg=90.0,
                    source=rel_src,
                ),
            ),
        )
        rel_overflow = analyze_relative(huge_rel)
        assert rel_overflow.status == "unresolved"
        assert any(issue.code == "numerical_range" for issue in rel_overflow.issues)

        far_rel = huge_rel.model_copy(
            update={
                "frame": LocalFrame(
                    name="L", first_azimuth_deg=0.0, origin=(1e18, 0.0), orientation="cw"
                ),
                "courses": tuple(
                    RelativeCourse(course_id=f"c{i}", distance_ft=1.0, source=rel_src)
                    for i in (1, 2, 3)
                ),
            }
        )
        rel_prec = analyze_relative(far_rel)
        assert rel_prec.status == "unresolved"
        assert any(issue.code == "numerical_range" for issue in rel_prec.issues)
