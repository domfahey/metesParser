"""Machine-readable command line interface."""

import argparse
import contextlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from .api import review_file, verify_file
from .relative import review_relative_file
from .settings import SettingsError, read_settings
from .settings import output_path as _output_path

# Output directories handed out in this invocation, with the files present beforehand,
# so an internal failure can still report what was already written.
_OUTPUT_DIRS: list[tuple[Path, frozenset[Path]]] = []


def output_path(settings: dict[str, Any], explicit: Path | None) -> Path:
    path = _output_path(settings, explicit)
    before = frozenset(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else frozenset()
    _OUTPUT_DIRS.append((path, before))
    return path


def _written_artifacts() -> dict[str, str]:
    written: dict[str, str] = {}
    for root, before in _OUTPUT_DIRS:
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file() and p not in before):
            written[str(path.relative_to(root))] = str(path)
    return written


def _is_input_parse_recursion(exc: RecursionError) -> bool:
    """True only when recursion happened decoding JSON or validating the loaded input."""
    frames = traceback.extract_tb(exc.__traceback__)
    if any(f.filename.endswith(("json/decoder.py", "json/scanner.py")) for f in frames):
        return True
    return bool(frames) and frames[-1].filename.endswith("pydantic/main.py")


def main() -> None:
    parser = argparse.ArgumentParser(prog="metes-review")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("render-revision", "export-review", "inspect-delivery"):
        delivery = commands.add_parser(name, help="Revision-specific advisory views and delivery.")
        delivery.add_argument("input", type=Path, help="Original dashboard source bundle")
        delivery.add_argument("--revision-dir", type=Path, required=True)
        delivery.add_argument("--settings", type=Path)
        if name == "inspect-delivery":
            delivery.add_argument("--package-dir", type=Path, required=True)
        else:
            delivery.add_argument("--output-dir", type=Path)
        if name == "export-review":
            delivery.add_argument("--request", type=Path, required=True)
    for name in ("revision-template", "save-revision", "inspect-revision"):
        revision = commands.add_parser(
            name, help="Recoverable advisory revisions; no verification."
        )
        revision.add_argument("input", type=Path, help="Original dashboard source bundle")
        revision.add_argument("--settings", type=Path)
        if name == "revision-template":
            revision.add_argument("--output", type=Path, required=True)
            revision.add_argument("--revision-id", default="revision-1")
        elif name == "save-revision":
            revision.add_argument("--revision", type=Path, required=True)
            revision.add_argument("--output-dir", type=Path)
            revision.add_argument("--expected-revision-id")
            revision.add_argument("--expected-generation", type=int)
        else:
            revision.add_argument("--revision-dir", type=Path, required=True)
    for name in (
        "validate-source",
        "inspect-artifacts",
        "diagnose-closure",
        "compare-descriptions",
        "analyze-corridor",
        "derive-plss",
    ):
        advisory = commands.add_parser(
            name, help="Advisory analysis; completed results retain needs_review (exit 1)."
        )
        advisory.add_argument("input", type=Path)
        advisory.add_argument("--settings", type=Path)
        if name == "validate-source":
            advisory.add_argument("--acquisition", type=Path)
            advisory.add_argument("--selection", type=Path)
        elif name == "inspect-artifacts":
            advisory.add_argument(
                "--requested-stage",
                required=True,
                choices=(
                    "convert",
                    "extract",
                    "verify",
                    "review",
                    "plot",
                    "dashboard",
                    "render-map",
                    "compare-descriptions",
                ),
            )
        else:
            advisory.add_argument("--output-dir", type=Path)
    for name in ("review", "verify"):
        command = commands.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--output-dir", type=Path)
        command.add_argument("--area", type=float)
        command.add_argument("--settings", type=Path)
    relative = commands.add_parser(
        "analyze-relative",
        help="Analyze explicit relative constraints; valid analyses retain needs_review (exit 1).",
    )
    relative.add_argument("input", type=Path)
    relative.add_argument("--output-dir", type=Path)
    relative.add_argument("--settings", type=Path)
    plot = commands.add_parser(
        "plot", help="Plot structured calls, relative constraints, or explicitly selected text."
    )
    plot.add_argument("input", type=Path)
    plot.add_argument(
        "--input-format", choices=("auto", "calls", "relative", "plot", "text"), default="auto"
    )
    plot.add_argument("--output-dir", type=Path)
    plot.add_argument("--settings", type=Path)
    for name in ("compose-map", "compose-dashboard"):
        composition = commands.add_parser(
            name, help="Compose retained plot/map inputs without rendering or verification."
        )
        composition.add_argument("input", type=Path)
        composition.add_argument("--layer", type=Path, action="append", default=[])
        composition.add_argument("--output-dir", type=Path, required=True)
        composition.add_argument("--settings", type=Path)
    dashboard = commands.add_parser(
        "dashboard",
        help="Render a validated source bundle as an offline, non-verifying dashboard.",
    )
    dashboard.add_argument("input", type=Path)
    dashboard.add_argument("--output-dir", type=Path)
    dashboard.add_argument("--cache-dir", type=Path)
    dashboard.add_argument("--online-map-config", type=Path)
    dashboard.add_argument("--settings", type=Path)
    render_map = commands.add_parser(
        "render-map", help="Render existing standalone plots and overlays as an online map."
    )
    render_map.add_argument("input", type=Path)
    render_map.add_argument("--online-map-config", type=Path, required=True)
    render_map.add_argument("--output-dir", type=Path, required=True)
    render_map.add_argument("--settings", type=Path)
    preview = commands.add_parser("serve-map", help="Serve generated map views on localhost.")
    preview.add_argument("directory", type=Path)
    preview.add_argument("--port", type=int, default=8765)
    preview.add_argument("--settings", type=Path)
    mcp = commands.add_parser(
        "mapbox-mcp", help="Prepare vector tool arguments from an existing geographic map."
    )
    mcp.add_argument("directory", type=Path)
    mcp.add_argument("--output-dir", type=Path)
    mcp.add_argument("--style", choices=("standard", "standard-satellite"))
    mcp.add_argument("--settings", type=Path)
    overlay = commands.add_parser(
        "import-overlay", help="Import supplied polygons into an explicit projected scene."
    )
    overlay.add_argument("input", type=Path)
    overlay.add_argument("--format", choices=("geojson", "projected-layer"), required=True)
    overlay.add_argument("--target-crs", required=True)
    overlay.add_argument("--source-crs")
    overlay.add_argument("--output", type=Path, required=True)
    overlay.add_argument("--settings", type=Path)
    raster = commands.add_parser(
        "register-raster", help="Calibrate a supplied scan with explicit affine controls."
    )
    raster.add_argument("input", type=Path)
    raster.add_argument("--controls", type=Path, required=True)
    raster.add_argument("--output", type=Path, required=True)
    raster.add_argument("--settings", type=Path)
    picker = commands.add_parser(
        "pick-raster", help="Prepare an offline control-point picker without registration."
    )
    picker.add_argument("input", type=Path)
    picker.add_argument("--controls", type=Path, required=True)
    picker.add_argument("--output-dir", type=Path)
    picker.add_argument("--settings", type=Path)
    parcel = commands.add_parser(
        "fetch-parcel", help="Snapshot exact official NJGIN parcel identifiers."
    )
    parcel.add_argument("--municipality", required=True)
    parcel.add_argument("--block", required=True)
    parcel.add_argument("--lot", required=True)
    parcel.add_argument("--qualifier")
    parcel.add_argument("--feature-id")
    parcel.add_argument("--target-crs", required=True)
    parcel.add_argument("--output", type=Path, required=True)
    parcel.add_argument("--settings", type=Path)
    corpus = commands.add_parser("corpus")
    corpus.add_argument("manifest", type=Path)
    corpus.add_argument("--output", type=Path)
    corpus.add_argument("--settings", type=Path)
    args = parser.parse_args()
    result: dict[str, Any]
    with contextlib.redirect_stdout(sys.stderr):
        try:
            settings = read_settings(args.settings)
            if not settings["enabled"]:
                result = {
                    "schema_version": "1.0",
                    "status": "error",
                    "artifacts": {},
                    "errors": [
                        {"code": "plugin_disabled", "message": "Plugin disabled in local settings."}
                    ],
                }
            else:
                result = _execute(args, settings)
        except SettingsError as exc:
            result = {
                "schema_version": "1.0",
                "status": "error",
                "artifacts": {},
                "errors": [{"code": "invalid_settings", "message": str(exc)}],
            }
        except RecursionError as exc:
            if _is_input_parse_recursion(exc):
                # Deeply nested JSON exhausts the parser; report it as an invocation error.
                result = {
                    "schema_version": "1.0",
                    "status": "error",
                    "artifacts": {},
                    "errors": [
                        {
                            "code": "invalid_input_json",
                            "message": "Input JSON is nested too deeply to process.",
                        }
                    ],
                }
            else:
                # Later recursion (rendering, publishing) is an internal failure; files
                # may already be written, so report them rather than hide them.
                result = {
                    "schema_version": "1.0",
                    "status": "error",
                    "artifacts": _written_artifacts(),
                    "errors": [
                        {
                            "code": "internal_recursion_error",
                            "message": "Recursion limit exceeded while processing; "
                            "artifacts listed may be incomplete.",
                        }
                    ],
                }
    print(json.dumps(result, allow_nan=False))
    raise SystemExit(
        {"checks_passed": 0, "needs_review": 1, "passed": 0, "failed": 1, "error": 2}.get(
            str(result.get("status")), 2
        )
    )


def _execute(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    if args.command == "pick-raster":
        from .raster_picker import prepare_raster_picker_file

        return prepare_raster_picker_file(
            args.input, args.controls, output_path(settings, args.output_dir)
        )
    if args.command in ("render-revision", "export-review", "inspect-delivery"):
        return _execute_delivery(args, settings)
    if args.command == "analyze-corridor":
        from .corridor import analyze_corridor_file

        return analyze_corridor_file(args.input, output_path(settings, args.output_dir))
    if args.command == "derive-plss":
        from .plss import prepare_plss_file

        return prepare_plss_file(args.input, output_path(settings, args.output_dir))
    if args.command in ("revision-template", "save-revision", "inspect-revision"):
        return _execute_revision(args, settings)
    if args.command == "validate-source":
        from .source_handoff import validate_source_bundle

        return validate_source_bundle(
            args.input, acquisition=args.acquisition, selection=args.selection
        )
    if args.command == "inspect-artifacts":
        from .artifact_inspect import inspect_artifacts

        return inspect_artifacts(args.input, requested_stage=args.requested_stage)
    if args.command == "diagnose-closure":
        from .diagnostics import diagnose_closure_file

        return diagnose_closure_file(args.input, output_dir=output_path(settings, args.output_dir))
    if args.command == "compare-descriptions":
        from .comparison import compare_descriptions_file

        return compare_descriptions_file(
            args.input, output_dir=output_path(settings, args.output_dir)
        )
    if args.command in ("compose-map", "compose-dashboard"):
        from .compose import compose_dashboard_file, compose_map_file

        compose = compose_map_file if args.command == "compose-map" else compose_dashboard_file
        return compose(args.input, output_path(settings, args.output_dir), layers=args.layer)
    if args.command == "mapbox-mcp":
        from .mapbox_mcp import mapbox_mcp_file

        return mapbox_mcp_file(
            args.directory, output_path(settings, args.output_dir), style=args.style
        )
    if args.command == "serve-map":
        from .map_preview import serve_map_preview

        try:
            serve_map_preview(args.directory, port=args.port)
            return {"schema_version": "1.0", "status": "passed", "errors": [], "artifacts": {}}
        except (OSError, ValueError) as exc:
            return {
                "schema_version": "1.0",
                "status": "error",
                "artifacts": {},
                "errors": [{"code": "map_preview_unavailable", "message": str(exc)}],
            }
    if args.command in ("import-overlay", "register-raster", "fetch-parcel"):
        return _overlay_artifact(args)
    if args.command == "corpus":
        from .corpus import run_corpus

        try:
            result = run_corpus(args.manifest, output_path=args.output)
        except (OSError, ValueError) as exc:
            result = {
                "schema_version": "1.0",
                "status": "error",
                "errors": [{"code": "invalid_manifest", "message": str(exc)}],
            }
    elif args.command == "analyze-relative":
        result = review_relative_file(args.input, output_dir=output_path(settings, args.output_dir))
    elif args.command in ("dashboard", "render-map"):
        from mp_models.webmap import WebMapRequest

        from .dashboard import _load, dashboard_file

        request = None
        if args.online_map_config is not None:
            try:
                request = WebMapRequest.model_validate(_load(args.online_map_config))
            except (OSError, ValueError, TypeError):
                # Validation errors can contain rejected values, including pasted credentials.
                return {
                    "schema_version": "1.0",
                    "status": "error",
                    "artifacts": {},
                    "errors": [
                        {
                            "code": "invalid_online_map_config",
                            "message": "Invalid online map configuration. Supply a scene ID and supported display/view options; credentials are entered only in the viewer.",
                        }
                    ],
                }

        if args.command == "render-map":
            from .online_map import render_map_file

            assert request is not None
            result = render_map_file(
                args.input, output_path(settings, args.output_dir), online_map=request
            )
        else:
            result = dashboard_file(
                args.input,
                output_dir=output_path(settings, args.output_dir),
                cache_dir=args.cache_dir,
                online_map=request,
            )
    elif args.command == "plot":
        from .plot import plot_file

        result = plot_file(
            args.input,
            output_dir=output_path(settings, args.output_dir),
            input_format=args.input_format,
        )
    else:
        operation = review_file if args.command == "review" else verify_file
        result = operation(
            args.input,
            output_dir=output_path(settings, args.output_dir),
            stated_area_sq_ft=args.area,
        )
    return result


def _overlay_artifact(args: argparse.Namespace) -> dict[str, Any]:
    from .overlays import import_overlay, write_new_artifact

    try:
        if args.output.exists():
            raise ValueError("Output must be a new path; existing files are never overwritten")
        if args.command == "import-overlay":
            value = import_overlay(
                args.input.read_bytes(),
                input_format=args.format,
                target_crs=args.target_crs,
                source_crs=args.source_crs,
                filename=args.input.name,
            ).to_dict()
        elif args.command == "register-raster":
            from mp_models.plot import PlotScene
            from mp_models.raster import RasterControl

            from .raster_registration import fit_affine, image_layer, supplied_affine

            config = json.loads(args.controls.read_bytes())
            scene = PlotScene.model_validate(config["scene"])
            controls = tuple(RasterControl.model_validate(c) for c in config.get("controls", []))
            registration = (
                supplied_affine(config["matrix"], controls)
                if "matrix" in config
                else fit_affine(controls)
            )
            layer, source = image_layer(
                args.input.read_bytes(),
                scene=scene,
                registration=registration,
                filename=args.input.name,
            )
            value = {
                "schema_version": "1.1",
                "scenes": [scene.model_dump(mode="json")],
                "map_sources": [source.model_dump(mode="json")],
                "raster_layers": [layer.model_dump(mode="json")],
            }
        else:
            from .parcel_provider import fetch_njgin

            value = fetch_njgin(
                municipality=args.municipality,
                block=args.block,
                lot=args.lot,
                qualifier=args.qualifier,
                feature_id=args.feature_id,
                target_crs=args.target_crs,
            )
        write_new_artifact(args.output, value)
        return {
            "schema_version": "1.1",
            "status": "passed",
            "artifacts": {"map_artifact": str(args.output)},
            "errors": [],
            "acquisition_status": value.get("status"),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "schema_version": "1.1",
            "status": "error",
            "artifacts": {},
            "errors": [{"code": "invalid_overlay", "message": str(exc)}],
        }


def _execute_revision(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    from mp_models.dashboard import DashboardBundle
    from mp_models.revisions import revision_template

    from .dashboard import _load
    from .revisions import load_revision, publish_revision

    try:
        bundle = DashboardBundle.model_validate(_load(args.input))
        if args.command == "save-revision":
            return publish_revision(
                bundle,
                args.revision.read_bytes(),
                output_path(settings, args.output_dir),
                expected_revision_id=args.expected_revision_id,
                expected_generation=args.expected_generation,
            )
        if args.command == "inspect-revision":
            prepared = load_revision(bundle, args.revision_dir)
            return {
                "schema_version": "1.0",
                "status": "needs_review",
                "errors": [],
                "artifacts": {},
                "revision": prepared.model_dump(mode="json"),
            }
        payload = revision_template(bundle, revision_id=args.revision_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload.model_dump_json(indent=2) + "\n")
        return {
            "schema_version": "1.0",
            "status": "needs_review",
            "errors": [],
            "artifacts": {"revision": str(args.output)},
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "schema_version": "1.0",
            "status": "error",
            "artifacts": {},
            "errors": [{"code": "invalid_revision", "message": str(exc)}],
        }


def _execute_delivery(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    from mp_models.dashboard import DashboardBundle
    from mp_models.delivery import DeliveryRequest

    from .dashboard import _load
    from .delivery import publish_delivery, replay_delivery
    from .revision_view import render_revision_file

    if args.command == "render-revision":
        return render_revision_file(
            args.input, args.revision_dir, output_path(settings, args.output_dir)
        )
    try:
        bundle = DashboardBundle.model_validate(_load(args.input))
        if args.command == "export-review":
            request = DeliveryRequest.model_validate(_load(args.request))
            return publish_delivery(
                bundle, args.revision_dir, request, output_path(settings, args.output_dir)
            )
        replay = replay_delivery(bundle, args.revision_dir, args.package_dir)
        snapshot = replay.snapshot
        return {
            "schema_version": "1.0",
            "status": "needs_review",
            "errors": [],
            "artifacts": {},
            "omissions": [o.model_dump(mode="json") for o in snapshot.omissions],
            "replay_verification": {
                "geojson_coordinates": replay.geojson_coordinates,
                "findings": list(replay.findings),
            },
            "snapshot": snapshot.model_dump(mode="json"),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "schema_version": "1.0",
            "status": "error",
            "artifacts": {},
            "errors": [{"code": "invalid_delivery", "message": str(exc)}],
        }
