"""Bounded, read-only inventory and conditional resume guidance.

No workflow executor lives here. Hashes establish declared lineage; pure engine
replay establishes deterministic usability. Neither establishes source accuracy.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mp_models.artifact_inspection import ArtifactInspection

from .source_handoff import _json_object, _Validator, validate_source_bundle

STAGES = (
    "convert",
    "extract",
    "verify",
    "review",
    "plot",
    "dashboard",
    "render-map",
    "compare-descriptions",
)
KNOWN = (
    "source-acquisition.json",
    "description-selection.json",
    "review-manifest.json",
    "audit.json",
    "plot-manifest.json",
    "stage-manifest.json",
    "web-map-manifest.json",
    "composition-manifest.json",
    "diagnostics-manifest.json",
    "comparison-manifest.json",
)
LIMITATIONS = (
    "Artifact usability and identity do not establish source-reading accuracy, legal validity, or canonical verification.",
    "Discovery is limited to known root files and recognized manifests in immediate child directories; unrelated folders and sibling bundles are not adopted.",
    "Declared IDs and hashes establish dependencies; filenames and timestamps do not. Same-byte occurrences may remain ambiguous.",
    "Pure replay does not write outputs, invoke providers, reproject maps, or grant verified-export eligibility.",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class _Issue(Exception):
    def __init__(
        self, code: str, message: str, status: str = "invalid", path: str | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.path = code, message, status, path


class _Inspector:
    def __init__(self, root: Path, requested: str) -> None:
        self.root, self.requested = root, requested
        self.artifacts: list[dict[str, Any]] = []
        self.contexts: dict[str, Any] = {}

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def reference(self, directory: Path, reference: Any) -> Path:
        if (
            not isinstance(reference, str)
            or not reference
            or "\\" in reference
            or ":" in reference
            or "\x00" in reference
        ):
            raise _Issue(
                "unsafe_path",
                "Declared reference is not a confined relative path.",
                path=str(reference),
            )
        value = Path(reference)
        if value.is_absolute() or any(part in {"", ".", ".."} for part in reference.split("/")):
            raise _Issue(
                "unsafe_path",
                "Absolute, traversal, and ambiguous references are unsupported.",
                path=reference,
            )
        return directory / value

    def read(self, path: Path) -> bytes:
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            raise _Issue(
                "unsafe_path", "Reference escapes the explicit bundle root.", path=str(path)
            ) from None
        current = self.root
        for part in parts:
            current /= part
            if part in {".", ".."} or current.is_symlink():
                raise _Issue(
                    "unsafe_path",
                    "Symlink or traversal components below the root are unsupported.",
                    path=self.relative(path),
                )
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise _Issue(
                "missing_artifact", "Declared artifact is missing.", "missing", self.relative(path)
            ) from None
        except OSError:
            raise _Issue(
                "unreadable_artifact",
                "Declared artifact could not be read.",
                "unverifiable",
                self.relative(path),
            ) from None

    def load(self, path: Path) -> Any:
        from .plot import _finite_json

        try:
            value = json.loads(
                self.read(path).decode("utf-8-sig"),
                object_pairs_hook=_json_object,
                parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
            )
            _finite_json(value)
            return value
        except (ValueError, UnicodeDecodeError):
            raise _Issue(
                "invalid_json",
                "Artifact must contain strict UTF-8 JSON without duplicate keys.",
                path=self.relative(path),
            ) from None

    def node(self, kind: str, stage: str, path: Path, *, suffix: str = "") -> dict[str, Any]:
        node: dict[str, Any] = {
            "id": f"{kind}:{self.relative(path)}{suffix}",
            "kind": kind,
            "stage": stage,
            "path": self.relative(path),
            "status": "present_valid",
            "local_status": "present_valid",
            "dependency_ids": [],
            "reasons": [],
            "identities": {},
            "recorded_canonical_status": None,
            "limitations": [],
        }
        self.artifacts.append(node)
        return node

    def issue(
        self,
        node: dict[str, Any],
        code: str,
        message: str,
        status: str = "invalid",
        path: str | None = None,
        dependency_id: str | None = None,
    ) -> None:
        node["reasons"].append(
            {"code": code, "message": message, "path": path, "dependency_id": dependency_id}
        )
        rank = {
            "present_valid": 0,
            "unverifiable": 1,
            "missing": 2,
            "stale": 3,
            "blocked": 4,
            "invalid": 5,
        }
        if rank[status] > rank[node["local_status"]]:
            node["local_status"] = node["status"] = status

    def run(self, node: dict[str, Any], operation: Callable[[], None]) -> None:
        try:
            operation()
        except _Issue as exc:
            self.issue(node, exc.code, exc.message, exc.status, exc.path)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            self.issue(
                node,
                "invalid_provenance",
                "Schema, deterministic calculation, or provenance validation failed.",
            )

    def manifest(self, path: Path) -> dict[str, Any]:
        value = self.load(path)
        if not isinstance(value, dict):
            raise _Issue(
                "invalid_manifest", "Manifest must be an object.", path=self.relative(path)
            )
        if value.get("schema_version") != "1.0":
            raise _Issue(
                "unknown_schema_version",
                "Manifest schema version is unsupported.",
                path=self.relative(path),
            )
        return value

    def check_hash(
        self,
        node: dict[str, Any],
        path: Path,
        expected: Any,
        *,
        code: str = "artifact_hash_mismatch",
    ) -> bytes:
        raw = self.read(path)
        if expected is None:
            self.issue(
                node,
                "hash_unavailable",
                "Identity was not recorded.",
                "unverifiable",
                self.relative(path),
            )
        elif not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
            self.issue(
                node, "invalid_hash", "Declared SHA-256 is malformed.", path=self.relative(path)
            )
        elif _sha(raw) != expected:
            self.issue(
                node,
                code,
                "Retained bytes differ from their declared identity.",
                "stale",
                self.relative(path),
            )
        return raw

    def source_records(self, directories: list[Path]) -> None:
        acquisitions: list[tuple[dict[str, Any], Any, bytes]] = []
        for directory in directories:
            path = directory / "source-acquisition.json"
            if not path.exists() and not path.is_symlink():
                continue
            node = self.node("acquisition", "convert", path)
            validator = _Validator(self.root)
            record, raw = validator.record(Path(self.relative(path)), "acquisition")
            if record is not None:
                assert raw is not None
                validator.acquisition(record)
                node["identities"].update(
                    source_id=record.id,
                    acquisition_sha256=_sha(raw),
                    source_sha256s={s.id: s.sha256 for s in record.sources},
                )
                acquisitions.append((node, record, raw))
            self.source_findings(node, validator.result)
        for directory in directories:
            path = directory / "description-selection.json"
            if not path.exists() and not path.is_symlink():
                continue
            validator = _Validator(self.root)
            selection, _ = validator.record(Path(self.relative(path)), "selection")
            if selection is None:
                node = self.node("selection", "extract", path)
                self.source_findings(node, validator.result)
                continue
            matches = [
                (n, r, raw)
                for n, r, raw in acquisitions
                if r.id == selection.acquisition_id
                and (
                    selection.acquisition_sha256 is None
                    or _sha(raw) == selection.acquisition_sha256
                )
            ]
            # A changed acquisition record is still identified by its declared stable ID;
            # its mismatched recorded hash is surfaced by the source validator.
            if not matches:
                matches = [
                    (n, r, raw) for n, r, raw in acquisitions if r.id == selection.acquisition_id
                ]
            for candidate in selection.candidates:
                node = self.node("selection", "extract", path, suffix="#" + candidate.id)
                node["identities"].update(
                    candidate_id=candidate.id,
                    selection_id=selection.id,
                    source_id=selection.acquisition_id,
                    selected_sha256=candidate.selected_text.sha256,
                    selected_text_path=candidate.selected_text.path,
                    role=candidate.role,
                )
                if len(matches) == 1:
                    parent, _, _ = matches[0]
                    node["dependency_ids"] = [parent["id"]]
                    result = validate_source_bundle(
                        self.root,
                        acquisition=Path(parent["path"]),
                        selection=Path(self.relative(path)),
                    )
                    # Other candidates remain separate; do not apply their failures here.
                    result = {
                        **result,
                        "findings": [
                            f
                            for f in result["findings"]
                            if f.get("id") in {candidate.id, selection.id, None}
                            or f.get("path") == self.relative(path)
                        ],
                    }
                    self.source_findings(node, result)
                else:
                    local = _Validator(self.root)
                    local.candidate(candidate, None, None)
                    self.source_findings(node, local.result)
                    self.issue(
                        node,
                        "ambiguous_acquisition" if matches else "missing_acquisition",
                        "Selection prerequisite identity is ambiguous or unavailable.",
                        "unverifiable",
                    )

    def source_findings(self, node: dict[str, Any], result: dict[str, Any]) -> None:
        changed_identity = any(
            f["category"] == "identity" and f["code"].endswith("mismatch")
            for f in result["findings"]
        )
        for finding in result["findings"]:
            category = finding["category"]
            if category == "source_uncertainties":
                if finding["code"] == "uncertainty_dropped":
                    self.issue(node, finding["code"], finding["message"], path=finding.get("path"))
                    continue
                node["limitations"].append(finding["message"])
                continue
            code = finding["code"]
            state = (
                "stale"
                if code.endswith("mismatch")
                and code
                not in {
                    "selected_bytes_mismatch",
                    "opening_words_mismatch",
                    "closing_words_mismatch",
                    "span_line_mismatch",
                    "span_page_mismatch",
                }
                else "unverifiable"
                if category == "identity"
                else "invalid"
            )
            if (
                changed_identity
                and category == "structure"
                and code
                in {
                    "selected_bytes_mismatch",
                    "opening_words_mismatch",
                    "closing_words_mismatch",
                    "span_line_mismatch",
                    "span_page_mismatch",
                    "span_out_of_bounds",
                    "span_character_boundary",
                    "invalid_utf8",
                    "page_lines_out_of_bounds",
                }
            ):
                state = "stale"
            self.issue(node, code, finding["message"], state, finding.get("path"))
        if result["structure"]["status"] == "legacy":
            self.issue(
                node,
                "legacy_source_schema",
                "Legacy records cannot establish a validated source chain.",
                "unverifiable",
            )
        if result["source_uncertainties"]["status"] == "declared":
            node["limitations"].append(
                "Declared source uncertainties remain unresolved and do not invalidate deterministic identity alone."
            )

    def review(self, directory: Path) -> None:
        from . import api

        path = directory / "review-manifest.json"
        node = self.node("review", "review", path)

        def operation() -> None:
            if not path.exists() and not path.is_symlink():
                self.issue(
                    node,
                    "legacy_review_manifest",
                    "Saved audit hashes alone do not establish replayable calls or verification; original input kind and parameters are unavailable.",
                    "unverifiable",
                )
                return
            manifest = self.manifest(path)
            display = self.node("review_display", "review", directory / "review.html")
            if manifest.get("kind") != "review" or manifest.get("recorded_status") not in {
                "checks_passed",
                "needs_review",
                "error",
            }:
                raise _Issue(
                    "invalid_manifest",
                    "Review kind and separately recorded canonical status must be valid declared values.",
                )
            node["recorded_canonical_status"] = manifest["recorded_status"]
            source = manifest.get("input")
            parameters = manifest.get("parameters")
            if (
                not isinstance(source, dict)
                or source.get("kind") not in {"text", "json", "csv"}
                or not isinstance(parameters, dict)
                or "stated_area_sq_ft" not in parameters
                or not manifest.get("replay_version")
            ):
                self.issue(
                    node,
                    "replay_parameters_unavailable",
                    "Original input kind, options, and replay version are required; retained source.txt does not establish its kind.",
                    "unverifiable",
                )
                return
            if (
                manifest.get("engine_version") != api.ENGINE_VERSION
                or manifest.get("replay_version") != api.REPLAY_VERSION
            ):
                self.issue(
                    node,
                    "algorithm_version_mismatch",
                    "Review was produced by an incompatible algorithm version.",
                    "stale",
                )
                return
            source_path = self.reference(directory, source.get("path"))
            raw = self.check_hash(
                node, source_path, source.get("sha256"), code="source_hash_mismatch"
            )
            node["identities"].update(
                input_sha256=source.get("sha256"),
                input_kind=source["kind"],
                input_path=self.relative(source_path),
            )
            declared_artifacts = manifest.get("artifacts")
            if not isinstance(declared_artifacts, dict) or not {
                "calls.json",
                "verification.json",
                "audit.json",
                source.get("path"),
            }.issubset(declared_artifacts):
                raise _Issue(
                    "missing_review_artifacts",
                    "Replay requires declared source, calls, verification, and audit artifacts.",
                    "unverifiable",
                )
            for name, expected in declared_artifacts.items():
                target = self.reference(directory, name)
                if name == "review.html":
                    self.run(
                        display,
                        lambda target=target, expected=expected: self.check_hash(
                            display, target, expected
                        ),
                    )
                    continue
                self.check_hash(node, target, expected)
            if "review.html" not in declared_artifacts:
                self.issue(
                    display,
                    "hash_unavailable",
                    "Review display output has no declared SHA-256 identity.",
                    "unverifiable",
                    self.relative(directory / "review.html"),
                )
            saved_calls = self.load(directory / "calls.json")
            saved_verification = self.load(directory / "verification.json")
            saved_audit = self.load(directory / "audit.json")
            fresh = api.replay_review(
                raw,
                input_kind=source["kind"],
                source_name=source.get("name", "source.txt"),
                stated_area_sq_ft=parameters["stated_area_sq_ft"],
            )
            if fresh["status"] == "error":
                self.issue(
                    node,
                    "replay_input_error",
                    "Retained source cannot be replayed with the recorded parameters.",
                )
            if (
                saved_calls != fresh["calls"]
                or saved_verification != fresh["verification"]
                or saved_audit != fresh["audit"]
                or manifest.get("recorded_status") != fresh["status"]
            ):
                self.issue(
                    node,
                    "replay_mismatch",
                    "Saved calls, verification, audit, or recorded status differ from deterministic replay.",
                )
            node["identities"]["calls_sha256"] = _sha(self.read(directory / "calls.json"))
            self.contexts[node["id"]] = {
                "calls": fresh["calls"],
                "verification": fresh["verification"],
            }

        self.run(node, operation)

    def plot(self, directory: Path) -> None:
        from mp_models.plot_request import PlotRequest, PreparedPlot
        from mp_verify.plot import validate_prepared_plot

        from .plot import _request

        path = directory / "plot-manifest.json"
        node = self.node("plot", "plot", path)

        def operation() -> None:
            manifest = self.manifest(path)
            request_path = directory / "plot-input.json"
            geometry_path = directory / "plot-geometry.json"
            display = self.node("plot_display", "plot", directory / "plot.html")
            self.run(
                display,
                lambda: self.check_hash(
                    display, directory / "plot.html", manifest.get("html_sha256")
                ),
            )
            self.check_hash(node, request_path, manifest.get("plot_input_sha256"))
            self.check_hash(node, geometry_path, manifest.get("plot_geometry_sha256"))
            request = PlotRequest.model_validate(self.load(request_path))
            prepared = validate_prepared_plot(
                PreparedPlot.model_validate(
                    {
                        "request": request,
                        "geometry": self.load(geometry_path),
                        "input_hash": manifest.get("input_hash"),
                    }
                )
            )
            if manifest.get("geometry_hash") != prepared.geometry.geometry_hash:
                self.issue(
                    node,
                    "geometry_hash_mismatch",
                    "Plot manifest geometry identity is stale.",
                    "stale",
                )
            candidates = [
                directory / name
                for name in ("source.txt", "source.json", "source.csv")
                if (directory / name).exists() or (directory / name).is_symlink()
            ]
            if len(candidates) != 1:
                raise _Issue(
                    "ambiguous_plot_source",
                    "Plot requires exactly one retained source file.",
                    "unverifiable",
                )
            raw = self.check_hash(
                node, candidates[0], manifest.get("source_sha256"), code="source_hash_mismatch"
            )
            node["identities"].update(
                input_sha256=manifest.get("source_sha256"),
                input_path=self.relative(candidates[0]),
                geometry_hash=prepared.geometry.geometry_hash,
                calculation_id=request.calculation_id,
                plot_input_hash=prepared.input_hash,
            )
            self.contexts[node["id"]] = prepared
            if (
                not manifest.get("source_name")
                or not manifest.get("input_format")
                or not manifest.get("replay_version")
            ):
                self.issue(
                    node,
                    "plot_replay_parameters_unavailable",
                    "Original source name, input format, and replay version are unavailable; geometry is individually valid but derivation from retained bytes is unproven.",
                    "unverifiable",
                )
            elif manifest["replay_version"] != "plot-input-replay-1":
                self.issue(
                    node,
                    "algorithm_version_mismatch",
                    "Plot input replay version is incompatible.",
                    "stale",
                )
            else:
                replayed, _ = _request(raw, manifest["source_name"], manifest["input_format"])
                if replayed != request:
                    self.issue(
                        node,
                        "replay_mismatch",
                        "Plot request differs from deterministic source dispatch.",
                    )

        self.run(node, operation)

    def diagnostics(self, directory: Path) -> None:
        from mp_models.diagnostics import ClosureDiagnosticRequest
        from mp_verify.diagnostics import diagnose_closure

        path = directory / "diagnostics-manifest.json"
        node = self.node("diagnostics", "verify", path)

        def operation() -> None:
            manifest = self.manifest(path)
            source_path = self.reference(directory, manifest.get("source_file"))
            result_path = self.reference(directory, manifest.get("diagnostics_file"))
            self.check_hash(
                node, source_path, manifest.get("source_sha256"), code="source_hash_mismatch"
            )
            self.check_hash(node, result_path, manifest.get("diagnostics_sha256"))
            request = ClosureDiagnosticRequest.model_validate(self.load(source_path))
            fresh = diagnose_closure(request)
            node["identities"].update(
                input_id=request.input_id,
                input_sha256=request.input_sha256,
                request_sha256=fresh.request_sha256,
                source_refs=[
                    r.model_dump(mode="json") for call in request.calls for r in call.source_refs
                ],
            )
            if manifest.get("algorithm_version") != fresh.algorithm_version:
                self.issue(
                    node,
                    "algorithm_version_mismatch",
                    "Diagnosis algorithm version is incompatible.",
                    "stale",
                )
            elif (
                self.load(result_path) != fresh.model_dump(mode="json")
                or manifest.get("request_sha256") != fresh.request_sha256
                or manifest.get("input_sha256") != fresh.input_sha256
            ):
                self.issue(node, "replay_mismatch", "Diagnosis differs from deterministic replay.")

        self.run(node, operation)

    def dashboard(self, directory: Path) -> None:
        from mp_export.dashboard_html import renderer_fingerprint  # type: ignore[import-untyped]
        from mp_models.dashboard import (
            DashboardBundle,
            DashboardDescriptionComparisonSpec,
            DashboardManifest,
        )
        from mp_verify.dashboard import _hash, _source_data, calculate_dashboard, map_stage

        path = directory / "stage-manifest.json"
        calculation = self.node("dashboard_calculations", "verify", path)
        plot = self.node("dashboard_plot", "plot", directory / "plot-geometry.json")
        maps = self.node("prepared_map", "render-map", directory / "map-layers.json")
        placement = self.node("placement", "render-map", directory / "placements.json")
        display = self.node("dashboard", "dashboard", directory / "render-manifest.json")
        plot["dependency_ids"] = [calculation["id"]]
        placement["dependency_ids"] = [plot["id"], maps["id"]]
        display["dependency_ids"] = [calculation["id"], plot["id"], maps["id"], placement["id"]]
        state: dict[str, Any] = {}

        def operation() -> None:
            raw = self.load(directory / "source.json")
            saved = DashboardManifest.model_validate(self.manifest(path))
            # Existing calculation hashes explicitly exclude optional maps and
            # presentation. Reuse that pure producer with those independent
            # inputs absent, so malformed maps cannot invalidate saved math.
            core = DashboardBundle.model_validate(
                {
                    **raw,
                    "scenes": [],
                    "map_sources": [],
                    "vector_layers": [],
                    "raster_layers": [],
                    "placements": [],
                    "comparison_specs": [],
                    "description_comparison_specs": [],
                    "presentation": {},
                    "scenarios": [],
                    "plot_view": None,
                }
            )
            fresh = calculate_dashboard(core)
            state.update(raw=raw, saved=saved, core=fresh)
            calculation["identities"].update(
                calculation_input_hash=saved.calculation_input_hash,
                calculation_output_hash=saved.calculation_output_hash,
                source_review_hash=saved.source_review_hash,
                source_refs=[
                    {"source_id": doc.id, "source_sha256": doc.sha256} for doc in core.documents
                ],
            )
            if saved.calculator_version != fresh.manifest.calculator_version:
                self.issue(
                    calculation,
                    "algorithm_version_mismatch",
                    "Dashboard calculator version is incompatible.",
                    "stale",
                )
            if saved.source_review_hash != fresh.manifest.source_review_hash or self.load(
                directory / "source-review.json"
            ) != _source_data(core):
                self.issue(
                    calculation,
                    "source_review_mismatch",
                    "Source ledger changed from its saved calculation dependency.",
                    "stale",
                )
            if saved.calculation_input_hash != fresh.manifest.calculation_input_hash:
                self.issue(
                    calculation,
                    "calculation_input_mismatch",
                    "Calculation input identity changed.",
                    "stale",
                )
            outputs = self.load(directory / "calculations.json")
            if isinstance(outputs, list) and all(
                isinstance(item, dict) and isinstance(item.get("engine_status"), str)
                for item in outputs
            ):
                calculation["recorded_canonical_status"] = ",".join(
                    item["engine_status"] for item in outputs
                )
            if (
                outputs != [c.model_dump(mode="json") for c in fresh.calculations]
                or _hash(outputs) != saved.calculation_output_hash
            ):
                self.issue(
                    calculation,
                    "replay_mismatch",
                    "Dashboard calculations differ from deterministic replay.",
                )
            if saved.diagnostics_output_hash is not None:
                saved_diagnostics = self.load(directory / "diagnostics.json")
                if (
                    saved_diagnostics != [d.model_dump(mode="json") for d in fresh.diagnostics]
                    or _hash(saved_diagnostics) != saved.diagnostics_output_hash
                ):
                    self.issue(
                        calculation,
                        "diagnostics_replay_mismatch",
                        "Saved dashboard diagnoses differ from deterministic replay.",
                    )

        self.run(calculation, operation)
        if not state:
            for node in (plot, maps, placement, display):
                self.issue(
                    node,
                    "dashboard_prerequisite_unavailable",
                    "Valid source bundle and manifest are required.",
                    "unverifiable",
                )
            return
        saved = state["saved"]
        core = state["core"]

        def plot_operation() -> None:
            expected = [g.model_dump(mode="json") for g in core.plots.geometries]
            if (
                self.load(directory / "plot-geometry.json") != expected
                or saved.plot_output_hash != core.manifest.plot_output_hash
            ):
                self.issue(
                    plot, "geometry_hash_mismatch", "Dashboard plot geometry is stale.", "stale"
                )

        self.run(plot, plot_operation)

        def map_operation() -> None:
            from mp_verify.scene import validate_scene

            bundle = DashboardBundle.model_validate(state["raw"])
            for scene in bundle.scenes:
                validate_scene(scene)
            if bundle.raster_layers:
                from .raster_registration import validate_raster_layer

                scenes = {scene.id: scene for scene in bundle.scenes}
                for raster in bundle.raster_layers:
                    validate_raster_layer(raster, scenes[raster.scene_id])
            state["bundle"] = bundle
            expected = map_stage(bundle)
            if self.load(
                directory / "map-layers.json"
            ) != expected or saved.map_input_hash != _hash(expected):
                self.issue(
                    maps,
                    "map_input_mismatch",
                    "Map bytes, CRS, controls, or prepared map evidence changed.",
                    "stale",
                )

        self.run(maps, map_operation)

        def placement_operation() -> None:
            if "bundle" not in state:
                raise _Issue(
                    "map_prerequisite_unavailable",
                    "Valid map inputs are required to validate placement.",
                    "unverifiable",
                )
            fresh = calculate_dashboard(state["bundle"])
            self.contexts[str(directory)] = fresh
            expected = {
                "placements": [p.model_dump(mode="json") for p in fresh.plots.placements],
                "comparisons": [c.model_dump(mode="json") for c in fresh.plots.comparisons],
            }
            if (
                self.load(directory / "placements.json") != expected
                or saved.placement_input_hash != fresh.manifest.placement_input_hash
            ):
                self.issue(
                    placement,
                    "placement_input_mismatch",
                    "Placement or its geometry/map dependency changed.",
                    "stale",
                )

        self.run(placement, placement_operation)

        # Description comparisons are a distinct advisory stage. Vector-only
        # comparisons depend on source calculations, not optional map evidence.
        raw_specs = state["raw"].get("description_comparison_specs", [])
        if raw_specs or saved.description_comparisons_output_hash not in {None, _hash([])}:
            comparison_node = self.node(
                "comparison", "compare-descriptions", directory / "description-comparisons.json"
            )
            comparison_node["dependency_ids"] = [calculation["id"]]
            comparison_node["identities"]["dashboard_input_path"] = self.relative(
                directory / "source.json"
            )
            display["dependency_ids"].append(comparison_node["id"])

            def comparison_operation() -> None:
                specs = tuple(
                    DashboardDescriptionComparisonSpec.model_validate(spec) for spec in raw_specs
                )
                scene_ids = {spec.scene_id for spec in specs} - {None}
                placement_ids = {
                    identifier
                    for spec in specs
                    for identifier in (spec.left_placement_id, spec.right_placement_id)
                } - {None}
                if placement_ids:
                    comparison_node["dependency_ids"].extend(
                        (plot["id"], maps["id"], placement["id"])
                    )
                # Keep only explicitly used positioning inputs. Unrelated map
                # layers or their unavailable files cannot invalidate vectors.
                comparison_bundle = DashboardBundle.model_validate(
                    {
                        **state["raw"],
                        "scenes": [
                            scene
                            for scene in state["raw"].get("scenes", [])
                            if isinstance(scene, dict) and scene.get("id") in scene_ids
                        ]
                        if scene_ids
                        else [],
                        "placements": [
                            item
                            for item in state["raw"].get("placements", [])
                            if isinstance(item, dict) and item.get("id") in placement_ids
                        ]
                        if placement_ids
                        else [],
                        "map_sources": [],
                        "vector_layers": [],
                        "raster_layers": [],
                        "comparison_specs": [],
                        "presentation": {},
                        "scenarios": [],
                        "plot_view": None,
                    }
                )
                compared = calculate_dashboard(comparison_bundle)
                comparison_node["identities"].update(
                    calculation_input_hash=saved.calculation_input_hash,
                    comparison_input_hash=saved.description_comparisons_input_hash,
                    comparison_output_hash=saved.description_comparisons_output_hash,
                )
                if (
                    saved.description_comparisons_input_hash is None
                    or saved.description_comparisons_output_hash is None
                ):
                    self.issue(
                        comparison_node,
                        "comparison_identity_unavailable",
                        "Dashboard comparison input/output identities are unavailable.",
                        "unverifiable",
                    )
                    return
                if (
                    saved.description_comparisons_input_hash
                    != compared.manifest.description_comparisons_input_hash
                ):
                    self.issue(
                        comparison_node,
                        "comparison_input_mismatch",
                        "Description comparison source, criteria or positioning inputs changed.",
                        "stale",
                    )
                    return
                saved_comparisons = self.load(directory / "description-comparisons.json")
                if _hash(saved_comparisons) != saved.description_comparisons_output_hash:
                    self.issue(
                        comparison_node,
                        "comparison_output_hash_mismatch",
                        "Saved dashboard comparison differs from its recorded output identity.",
                        "stale",
                    )
                elif (
                    saved_comparisons
                    != [item.model_dump(mode="json") for item in compared.description_comparisons]
                    or saved.description_comparisons_output_hash
                    != compared.manifest.description_comparisons_output_hash
                ):
                    self.issue(
                        comparison_node,
                        "comparison_replay_mismatch",
                        "Saved dashboard comparisons differ from deterministic replay of source-owned calls and explicit comparison specifications.",
                    )

            self.run(comparison_node, comparison_operation)

        def display_operation() -> None:
            if str(directory) not in self.contexts:
                raise _Issue(
                    "placement_prerequisite_unavailable",
                    "Current placements and map inputs are required for dashboard rendering.",
                    "unverifiable",
                )
            fresh = self.contexts[str(directory)]
            render = self.load(directory / "render-manifest.json")
            if (
                render.get("presentation_hash") != fresh.manifest.presentation_hash
                or render.get("renderer_sha256") != renderer_fingerprint()
            ):
                self.issue(
                    display,
                    "presentation_changed",
                    "Presentation inputs or renderer changed; source and geometry remain separately assessed.",
                    "stale",
                )
            self.check_hash(display, directory / "dashboard.html", render.get("html_sha256"))

        self.run(display, display_operation)

    def direct_inputs(self) -> None:
        from .api import replay_review

        for name, kind in (
            ("calls.json", "json"),
            ("calls.csv", "csv"),
            ("description.txt", "text"),
        ):
            path = self.root / name
            if not path.exists() and not path.is_symlink():
                continue
            if (self.root / "review-manifest.json").exists() or (self.root / "audit.json").exists():
                continue
            node = self.node("direct_input", "verify" if kind != "text" else "review", path)

            def operation(
                path: Path = path,
                kind: str = kind,
                name: str = name,
                node: dict[str, Any] = node,
            ) -> None:
                raw = self.read(path)
                result = replay_review(raw, input_kind=kind, source_name=name)
                if result["status"] == "error":
                    raise _Issue(
                        "invalid_direct_input",
                        "Supplied direct input does not match its declared structured/text route.",
                    )
                node["identities"].update(
                    input_sha256=_sha(raw), input_kind=kind, input_path=self.relative(path)
                )
                node["limitations"].append(
                    "Input is individually usable; this inventory does not produce a saved verification result."
                )

            self.run(node, operation)

    def online_map(self, directory: Path) -> None:
        from mp_export.online_map_html import (  # type: ignore[import-untyped]
            online_renderer_fingerprint,
        )
        from mp_models.webmap import StandaloneWebMapInput, WebMapArtifact, WebMapRequest
        from mp_verify.dashboard import _hash
        from mp_verify.webmap import normalize_web_map_context, validate_web_map_artifact

        path = directory / "web-map-manifest.json"
        node = self.node("online_map", "render-map", path)

        def operation() -> None:
            manifest = self.manifest(path)
            request_data = self.load(directory / "web-map-request.json")
            artifact_data = self.load(directory / "web-map.json")
            request = WebMapRequest.model_validate(request_data)
            artifact = WebMapArtifact.model_validate(artifact_data)
            kind = manifest.get("source_kind", "dashboard")
            if kind == "standalone":
                source_path = directory / "source-map.json"
                self.check_hash(
                    node, source_path, manifest.get("source_sha256"), code="source_hash_mismatch"
                )
                prepared = StandaloneWebMapInput.model_validate(self.load(source_path))
            elif kind == "dashboard" and str(directory) in self.contexts:
                prepared = self.contexts[str(directory)]
                node["dependency_ids"] = [
                    n["id"]
                    for n in self.artifacts
                    if n["kind"] in {"dashboard_plot", "prepared_map", "placement"}
                    and Path(n["path"]).parent == Path(self.relative(directory))
                ]
            else:
                raise _Issue(
                    "map_source_unavailable",
                    "Online map source kind or validated dashboard prerequisite is unavailable.",
                    "unverifiable",
                )
            context = normalize_web_map_context(prepared)
            validate_web_map_artifact(prepared, artifact)
            if isinstance(prepared, StandaloneWebMapInput):
                node["identities"]["plot_dependencies"] = [
                    {
                        "calculation_id": p.request.calculation_id,
                        "plot_input_hash": p.input_hash,
                        "geometry_hash": p.geometry.geometry_hash,
                    }
                    for p in prepared.plots
                ]
            if dict(context.input_hashes) != manifest.get("input_hashes") or dict(
                artifact.input_hashes
            ) != dict(context.input_hashes):
                self.issue(
                    node, "map_input_mismatch", "Online map input dependencies changed.", "stale"
                )
            if (
                manifest.get("request_sha256") != _hash(request_data)
                or manifest.get("artifact_sha256") != _hash(artifact_data)
                or request.scene_id != artifact.scene_id
                or request.display != artifact.options
            ):
                self.issue(
                    node,
                    "map_stage_mismatch",
                    "Online map request or geographic artifact changed.",
                    "stale",
                )
            if manifest.get("renderer_sha256") != online_renderer_fingerprint():
                self.issue(
                    node,
                    "presentation_changed",
                    "Online renderer changed; source and geometry remain separately assessed.",
                    "stale",
                )
            files = manifest.get("files")
            if not isinstance(files, dict):
                raise _Issue(
                    "missing_display_files",
                    "Display-file identity manifest is unavailable.",
                    "unverifiable",
                )
            expected_files = {
                "online-map.html",
                "map-evidence.html" if kind == "standalone" else "dashboard.html",
                *(raster.path for raster in artifact.rasters),
            }
            if set(files) != expected_files:
                self.issue(
                    node,
                    "display_file_inventory_mismatch",
                    "Display-file inventory differs from the promised local views and raster assets.",
                )
            for name, expected in files.items():
                self.check_hash(node, self.reference(directory, name), expected)
            for raster in artifact.rasters:
                self.check_hash(node, self.reference(directory, raster.path), raster.sha256)
            node["identities"].update(
                input_hashes=dict(context.input_hashes),
                input_sha256=manifest.get("source_sha256"),
                source_kind=kind,
                source_input_path=self.relative(
                    directory / ("source-map.json" if kind == "standalone" else "source.json")
                ),
                request_path=self.relative(directory / "web-map-request.json"),
            )
            node["limitations"].append(
                "Geographic coordinates are reused under existing pure provenance validation; no reprojection, raster warp, or live-provider acceptance was performed."
            )

        self.run(node, operation)

    def composition(self, directory: Path) -> None:
        from mp_models.dashboard import DashboardBundle
        from mp_models.webmap import StandaloneWebMapInput
        from mp_verify.dashboard import calculate_dashboard
        from mp_verify.webmap import normalize_web_map_context

        path = directory / "composition-manifest.json"
        node = self.node("composition", "render-map", path)

        def operation() -> None:
            manifest = self.manifest(path)
            inputs = manifest.get("inputs")
            if not isinstance(inputs, dict):
                raise _Issue(
                    "missing_composition_inputs",
                    "Composition requires retained declared input identities.",
                    "unverifiable",
                )
            for name, expected in inputs.items():
                self.check_hash(node, self.reference(directory, name), expected)
            source: StandaloneWebMapInput | DashboardBundle
            if manifest.get("kind") == "standalone-map":
                source = StandaloneWebMapInput.model_validate(
                    self.load(directory / "map-input.json")
                )
                context = normalize_web_map_context(source)
                geometries = context.geometries
                required_plot_files = {
                    "inputs/plot/plot-manifest.json",
                    "inputs/plot/plot-input.json",
                    "inputs/plot/plot-geometry.json",
                }
                retained_sources = [
                    name
                    for name in (
                        "inputs/plot/source.json",
                        "inputs/plot/source.csv",
                        "inputs/plot/source.txt",
                    )
                    if name in inputs
                ]
                if not required_plot_files.issubset(inputs) or len(retained_sources) != 1:
                    raise _Issue(
                        "missing_composition_inputs",
                        "Standalone composition requires its declared retained plot and exactly one source.",
                        "unverifiable",
                    )
                retained_directory = directory / "inputs/plot"
                self.plot(retained_directory)
                retained_id = "plot:" + self.relative(retained_directory / "plot-manifest.json")
                node["dependency_ids"] = [retained_id]
                retained = self.contexts.get(retained_id)
                if retained is None:
                    raise _Issue(
                        "plot_prerequisite_unavailable",
                        "Composition retained plot failed deterministic validation.",
                        "unverifiable",
                    )
                expected = {
                    "schema_version": "1.0",
                    "title": retained.request.title,
                    "plots": [retained.model_dump(mode="json")],
                }
            elif manifest.get("kind") == "dashboard":
                source = DashboardBundle.model_validate(self.load(directory / "bundle.json"))
                geometries = calculate_dashboard(source).plots.geometries
                if "inputs/base-bundle.json" not in inputs:
                    raise _Issue(
                        "missing_composition_inputs",
                        "Dashboard composition requires its retained base bundle.",
                        "unverifiable",
                    )
                expected = self.load(directory / "inputs/base-bundle.json")
                DashboardBundle.model_validate(expected)
                expected["schema_version"] = "1.1"
            else:
                raise _Issue("unknown_composition_kind", "Composition source kind is unsupported.")
            layers = sorted(
                (name for name in inputs if re.fullmatch(r"inputs/layer-[1-9][0-9]*\.json", name)),
                key=lambda name: int(name.removeprefix("inputs/layer-").removesuffix(".json")),
            )
            for name in layers:
                layer = self.load(self.reference(directory, name))
                if not isinstance(layer, dict):
                    raise _Issue(
                        "invalid_composition_layer", "Retained map layer must be an object."
                    )
                for field in ("scenes", "map_sources", "vector_layers", "raster_layers"):
                    additions = layer.get(field, [])
                    if not isinstance(additions, list):
                        raise _Issue(
                            "invalid_composition_layer", "Retained map arrays must be lists."
                        )
                    expected[field] = expected.get(field, []) + additions
            replayed = (
                StandaloneWebMapInput.model_validate(expected)
                if manifest["kind"] == "standalone-map"
                else DashboardBundle.model_validate(expected)
            )
            if source != replayed:
                self.issue(
                    node,
                    "composition_replay_mismatch",
                    "Composed output differs from its declared retained inputs.",
                )
            if {g.calculation_id: g.geometry_hash for g in geometries} != manifest.get(
                "geometry_hashes"
            ):
                self.issue(
                    node,
                    "geometry_hash_mismatch",
                    "Composition geometry identity is stale.",
                    "stale",
                )
            node["identities"].update(
                input_path=self.relative(
                    directory
                    / ("map-input.json" if manifest["kind"] == "standalone-map" else "bundle.json")
                ),
                composition_kind=manifest["kind"],
                output_sha256=_sha(
                    self.read(
                        directory
                        / (
                            "map-input.json"
                            if manifest["kind"] == "standalone-map"
                            else "bundle.json"
                        )
                    )
                ),
            )
            node["limitations"].append(
                "Validated component identities do not establish source-reading or map-placement accuracy."
            )

        self.run(node, operation)

    def comparison(self, directory: Path) -> None:
        from mp_models.comparison import ComparisonManifest, ComparisonRequest
        from mp_verify.comparison import COMPARISON_VERSION, compare_descriptions

        path = directory / "comparison-manifest.json"
        node = self.node("comparison", "compare-descriptions", path)

        def operation() -> None:
            manifest = self.manifest(path)
            if manifest.get("algorithm_version") != COMPARISON_VERSION:
                self.issue(
                    node,
                    "algorithm_version_mismatch",
                    "Comparison algorithm version is incompatible.",
                    "stale",
                )
                return
            validated = ComparisonManifest.model_validate(manifest)
            request_path = self.reference(directory, validated.request_file)
            result_path = self.reference(directory, validated.result_file)
            self.check_hash(
                node, request_path, validated.request_sha256, code="source_hash_mismatch"
            )
            self.check_hash(node, result_path, validated.result_sha256)
            request = ComparisonRequest.model_validate(self.load(request_path))
            fresh = compare_descriptions(request)
            if (
                self.load(result_path) != fresh.model_dump(mode="json")
                or validated.input_hash != fresh.input_hash
                or (validated.left_id, validated.right_id) != (fresh.left_id, fresh.right_id)
            ):
                self.issue(
                    node,
                    "replay_mismatch",
                    "Saved comparison differs from deterministic replay of its retained immutable request.",
                )
            node["identities"].update(
                input_hash=fresh.input_hash,
                left_id=fresh.left_id,
                right_id=fresh.right_id,
                request_path=self.relative(request_path),
            )
            from mp_verify.plot import prepare_plot

            node["identities"]["plot_dependencies"] = [
                {
                    "calculation_id": p.request.calculation_id,
                    "plot_input_hash": p.input_hash,
                    "geometry_hash": p.geometry.geometry_hash,
                }
                for p in (prepare_plot(request.left.plot), prepare_plot(request.right.plot))
            ]
            node["limitations"].extend(fresh.limitations)

        self.run(node, operation)

    def link(self) -> None:
        selections = [
            a
            for a in self.artifacts
            if a["kind"] == "selection" and a["identities"].get("selected_sha256") is not None
        ]
        reviews = [a for a in self.artifacts if a["kind"] == "review"]
        acquisitions = [a for a in self.artifacts if a["kind"] == "acquisition"]
        for node in self.artifacts:
            refs = node["identities"].get("source_refs", [])
            for reference in refs:
                source_id = reference.get("source_id")
                source_hash = reference.get("source_sha256")
                if source_hash is None:
                    node["limitations"].append(
                        "An explicit source reference has no byte identity; its full document lineage remains unproven."
                    )
                    continue
                matches = [
                    a
                    for a in acquisitions
                    if a["identities"].get("source_sha256s", {}).get(source_id) == source_hash
                ]
                if len(matches) == 1:
                    parent = matches[0]
                    node["dependency_ids"] = list(
                        dict.fromkeys((*node["dependency_ids"], parent["id"]))
                    )
                    occurrence = reference.get("occurrence_id")
                    occurrences = (
                        [
                            s
                            for s in selections
                            if s["identities"].get("candidate_id") == occurrence
                            and parent["id"] in s["dependency_ids"]
                        ]
                        if occurrence is not None
                        else []
                    )
                    if len(occurrences) == 1:
                        node["dependency_ids"] = list(
                            dict.fromkeys((*node["dependency_ids"], occurrences[0]["id"]))
                        )
                elif len(matches) > 1:
                    node["status"] = "unverifiable"
                    node["reasons"].append(
                        {
                            "code": "ambiguous_source_occurrence",
                            "message": "Source ID/hash matches multiple acquisitions; no occurrence was guessed.",
                            "path": None,
                            "dependency_id": None,
                        }
                    )
                elif acquisitions:
                    node["status"] = "unverifiable"
                    node["reasons"].append(
                        {
                            "code": "unlinked_source_identity",
                            "message": "Explicit source reference has no matching acquisition identity.",
                            "path": None,
                            "dependency_id": None,
                        }
                    )
        for node in self.artifacts:
            if node["kind"] not in {"review", "plot"}:
                continue
            identity = node["identities"].get("input_sha256")
            if identity is None:
                continue
            matches = [a for a in selections if a["identities"]["selected_sha256"] == identity]
            if not matches and node["kind"] == "plot":
                matches = [a for a in reviews if a["identities"].get("calls_sha256") == identity]
            if len(matches) == 1:
                node["dependency_ids"] = [matches[0]["id"]]
            elif len(matches) > 1:
                # Keep local usability intact while refusing an occurrence assignment.
                node["status"] = "unverifiable"
                node["reasons"].append(
                    {
                        "code": "ambiguous_source_occurrence",
                        "message": "Declared byte identity matches multiple occurrences; no source was selected by filename or timestamp.",
                        "path": None,
                        "dependency_id": None,
                    }
                )
            elif selections and node["identities"].get("input_kind") == "text":
                node["status"] = "unverifiable"
                node["reasons"].append(
                    {
                        "code": "unlinked_source_occurrence",
                        "message": "Retained text is individually usable, but no current selection identity establishes its document lineage.",
                        "path": None,
                        "dependency_id": None,
                    }
                )
        plots = [a for a in self.artifacts if a["kind"] == "plot"]
        for node in self.artifacts:
            if node["kind"] == "online_map" and node["identities"].get("input_sha256") is not None:
                compositions = [
                    a
                    for a in self.artifacts
                    if a["kind"] == "composition"
                    and a["identities"].get("output_sha256") == node["identities"]["input_sha256"]
                ]
                if len(compositions) == 1:
                    node["dependency_ids"] = list(
                        dict.fromkeys((*node["dependency_ids"], compositions[0]["id"]))
                    )
                    continue
            for dependency in node["identities"].get("plot_dependencies", []):
                matches = [
                    a
                    for a in plots
                    if all(a["identities"].get(key) == value for key, value in dependency.items())
                ]
                if len(matches) == 1:
                    node["dependency_ids"] = list(
                        dict.fromkeys((*node["dependency_ids"], matches[0]["id"]))
                    )
                elif len(matches) > 1:
                    node["status"] = "unverifiable"
                    node["reasons"].append(
                        {
                            "code": "ambiguous_plot_identity",
                            "message": "More than one retained plot matches the declared geometry/input identity; no occurrence was selected.",
                            "path": None,
                            "dependency_id": None,
                        }
                    )
        by_id = {a["id"]: a for a in self.artifacts}
        for _ in range(len(self.artifacts)):
            changed = False
            for node in self.artifacts:
                for dependency_id in node["dependency_ids"]:
                    dependency = by_id[dependency_id]
                    if dependency["status"] in {"stale", "invalid", "missing", "blocked"} and node[
                        "status"
                    ] in {"present_valid", "unverifiable"}:
                        node["status"] = "blocked"
                        node["reasons"].append(
                            {
                                "code": "upstream_invalid",
                                "message": "A declared dependency is unavailable or changed; local artifact replay does not validate the full chain.",
                                "path": dependency["path"],
                                "dependency_id": dependency_id,
                            }
                        )
                        changed = True
                    elif (
                        dependency["status"] == "unverifiable" and node["status"] == "present_valid"
                    ):
                        node["status"] = "unverifiable"
                        node["reasons"].append(
                            {
                                "code": "upstream_unverifiable",
                                "message": "Local artifact is usable, but a declared dependency has unavailable identity.",
                                "path": dependency["path"],
                                "dependency_id": dependency_id,
                            }
                        )
                        changed = True
            if not changed:
                break

    def finish(self) -> dict[str, Any]:
        self.link()
        destination_kinds = {
            "convert": {"acquisition"},
            "extract": {"selection"},
            "verify": {"review", "dashboard_calculations"},
            "review": {"review", "review_display"},
            "plot": {"plot", "plot_display", "dashboard_plot"},
            "dashboard": {"dashboard"},
            "render-map": {"online_map"},
            "compare-descriptions": {"comparison"},
        }
        seeds = [n for n in self.artifacts if n["kind"] in destination_kinds[self.requested]]
        reachable = {n["id"] for n in seeds}
        by_id = {n["id"]: n for n in self.artifacts}
        frontier = list(reachable)
        while frontier:
            for parent in by_id[frontier.pop()]["dependency_ids"]:
                if parent not in reachable:
                    reachable.add(parent)
                    frontier.append(parent)
        if not seeds and self.requested in {"verify", "review", "plot", "extract"}:
            alternatives = [n for n in self.artifacts if n["kind"] == "selection"] or [
                n for n in self.artifacts if n["kind"] == "acquisition"
            ]
            for node in alternatives:
                reachable.add(node["id"])
                reachable.update(node["dependency_ids"])
        stages: list[dict[str, Any]] = []
        for stage in STAGES:
            members = [
                n
                for n in self.artifacts
                if n["id"] in reachable
                and (
                    n["stage"] == stage
                    or stage == "verify"
                    and self.requested == "verify"
                    and n["kind"] == "review"
                )
            ]
            if not members:
                status = "missing" if stage == self.requested else "not_requested"
            else:
                status = next(
                    (
                        state
                        for state in ("invalid", "stale", "blocked", "unverifiable", "missing")
                        if any(n["status"] == state for n in members)
                    ),
                    "present_valid",
                )
            dependency_ids = list(
                dict.fromkeys(
                    dependency for node in members for dependency in node["dependency_ids"]
                )
            )
            reasons = []
            seen_reasons = set()
            for node in members:
                for reason in node["reasons"]:
                    attributed = {**reason, "artifact_id": node["id"]}
                    identity = json.dumps(attributed, sort_keys=True)
                    if identity not in seen_reasons:
                        reasons.append(attributed)
                        seen_reasons.add(identity)
            if not members and status == "missing":
                reasons.append(
                    {
                        "code": "requested_stage_missing",
                        "message": "No recognized artifact is available for the requested destination.",
                        "path": None,
                        "dependency_id": None,
                        "artifact_id": None,
                    }
                )
            stages.append(
                {
                    "stage": stage,
                    "status": status,
                    "artifact_ids": [n["id"] for n in members],
                    "dependency_ids": dependency_ids,
                    "reasons": reasons,
                }
            )
        relevant_bad = [s for s in stages if s["status"] not in {"present_valid", "not_requested"}]
        # Choose an actual failing prerequisite before its blocked descendants.
        # Enum order is only a stable tie-break between independent root causes.
        bad_artifact_ids = {
            node["id"]
            for node in self.artifacts
            if node["id"] in reachable and node["status"] != "present_valid"
        }
        causal_artifact_ids = {
            node["id"]
            for node in self.artifacts
            if node["id"] in bad_artifact_ids
            and not any(dependency in bad_artifact_ids for dependency in node["dependency_ids"])
        }
        earliest = next(
            (
                stage["stage"]
                for stage in relevant_bad
                if causal_artifact_ids.intersection(stage["artifact_ids"])
            ),
            relevant_bad[0]["stage"] if relevant_bad else None,
        )
        required = []
        recommendations = []
        if earliest is not None:
            command = self.command(earliest)
            descriptions = {
                "convert": "Original source and actual native-reading request, transcript, page declarations, and uncertainties.",
                "extract": "A uniquely identified acquisition/transcript and verbatim selected spans with uncertainty carry-forward.",
                "verify": "Unambiguous structured calls or a replayable review input and its recorded options.",
                "review": "A uniquely identified current isolated description or supplied structured-call input.",
                "plot": "Explicit supported plot input or isolated text, with current source identity.",
                "dashboard": "A validated DashboardBundle with explicit source ledger, calculations, and optional map evidence.",
                "render-map": "Validated standalone map or dashboard geometry, explicit scene/placement, and token-free WebMapRequest.",
                "compare-descriptions": "An explicit identity-bound comparison request for the two intended descriptions.",
            }
            required = [descriptions[earliest]]
            if earliest == "compare-descriptions":
                dashboard_inputs = list(
                    dict.fromkeys(
                        node["identities"]["dashboard_input_path"]
                        for node in self.artifacts
                        if node["id"] in reachable
                        and node["kind"] == "comparison"
                        and node["identities"].get("dashboard_input_path")
                    )
                )
                if dashboard_inputs:
                    required = [
                        f"Retained DashboardBundle {path} with valid source-owned description_comparison_specs; regenerate using the dashboard producer into a new output directory. This integrated stage retains no standalone ComparisonRequest."
                        for path in dashboard_inputs
                    ]
            recommendations.append(
                {
                    "stage": earliest,
                    "reason": "Resume at the earliest unavailable or invalid declared dependency for the requested destination.",
                    "command": command,
                }
            )
        return ArtifactInspection.model_validate(
            {
                "bundle_root": str(self.root),
                "requested_stage": self.requested,
                "artifacts": self.artifacts,
                "stages": stages,
                "earliest_invalid_stage": earliest,
                "required_inputs": required,
                "recommendations": recommendations,
                "limitations": LIMITATIONS,
            }
        ).model_dump(mode="json")

    def command(self, stage: str) -> dict[str, Any] | None:
        if any(
            n["status"] == "unverifiable"
            and any(r["code"].startswith("ambiguous_") for r in n["reasons"])
            for n in self.artifacts
            if n["kind"] in {"review", "plot", "comparison", "online_map"}
        ):
            return None
        available = [
            a for a in self.artifacts if a["kind"] == "selection" and a["status"] == "present_valid"
        ]
        if len(available) > 1:
            return None
        inputs = [
            self.root / a["identities"]["selected_text_path"]
            for a in available
            if a["identities"].get("selected_text_path")
        ]
        if not inputs:
            inputs = [
                self.root / a["identities"]["input_path"]
                for a in self.artifacts
                if a["kind"] == "direct_input" and a["status"] == "present_valid"
            ]
        if not inputs:
            inputs = [
                self.root / a["identities"]["input_path"]
                for a in self.artifacts
                if a["kind"] == "review"
                and a["identities"].get("input_path")
                and a["local_status"] in {"present_valid", "stale", "invalid"}
                and Path(a["identities"]["input_path"]).suffix.lower()
                in (
                    {"text": {".txt", ".md"}, "json": {".json"}, "csv": {".csv"}}.get(
                        a["identities"].get("input_kind"), set()
                    )
                )
            ]
        if stage not in {"review", "verify", "plot"} or len(set(inputs)) != 1:
            return None
        source = inputs[0]
        actual_stage = (
            "review"
            if stage == "verify" and source.suffix.lower() not in {".csv", ".json"}
            else stage
        )
        output = self.root / f"{actual_stage}-next"
        suffix = 2
        while output.exists() or output.is_symlink():
            output = self.root / f"{actual_stage}-next-{suffix}"
            suffix += 1
        arguments = [actual_stage, str(source), "--output-dir", str(output)]
        if stage == "plot" and source.suffix.lower() in {".txt", ".md"}:
            arguments.extend(("--input-format", "text"))
        return {"program": "metes-review", "arguments": arguments}


def inspect_artifacts(root: Path, *, requested_stage: str) -> dict[str, Any]:
    """Inspect a bounded explicit bundle without writes, execution, or provider calls."""
    error_base: dict[str, Any] = {
        "schema_version": "1.0",
        "operation": "inspect-artifacts",
        "status": "error",
        "bundle_root": str(root),
        "requested_stage": requested_stage,
        "artifacts": [],
        "stages": [],
        "earliest_invalid_stage": None,
        "required_inputs": [],
        "recommendations": [],
        "limitations": list(LIMITATIONS),
        "errors": [],
    }
    if requested_stage not in STAGES:
        error_base["errors"] = [
            {
                "code": "invalid_requested_stage",
                "message": "Requested stage is unsupported.",
                "path": None,
                "dependency_id": None,
            }
        ]
        return error_base
    try:
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Bundle root is not a directory")
        children = sorted(root.iterdir())
    except (OSError, ValueError, RuntimeError):
        error_base["errors"] = [
            {
                "code": "invalid_bundle_root",
                "message": "Bundle root must be an existing readable directory.",
                "path": str(root),
                "dependency_id": None,
            }
        ]
        return error_base
    inspector = _Inspector(root, requested_stage)
    directories = [root]
    for child in children:
        if (
            not child.is_symlink()
            and child.is_dir()
            and any((child / name).exists() or (child / name).is_symlink() for name in KNOWN)
        ):
            directories.append(child)
    inspector.source_records(directories)
    inspector.direct_inputs()
    for directory in directories:

        def present(name: str, directory: Path = directory) -> bool:
            return (directory / name).exists() or (directory / name).is_symlink()

        if present("review-manifest.json") or present("audit.json"):
            inspector.review(directory)
        if present("plot-manifest.json"):
            inspector.plot(directory)
        if present("stage-manifest.json"):
            inspector.dashboard(directory)
        if present("diagnostics-manifest.json"):
            inspector.diagnostics(directory)
        if present("composition-manifest.json"):
            inspector.composition(directory)
        if present("web-map-manifest.json"):
            inspector.online_map(directory)
        if present("comparison-manifest.json"):
            inspector.comparison(directory)
    return inspector.finish()
