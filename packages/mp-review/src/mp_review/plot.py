"""Compose structured calls or isolated prose into a non-verifying offline plot."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mp_models import DeedCall, LegalDescription, RelativeDescription
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.plot import prepare_plot

from .dashboard import _atomic
from .relative import _invalid_number, _unique_object
from .text import prepare_text

REPLAY_VERSION = "plot-input-replay-1"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite JSON number")
    if isinstance(value, dict):
        for item in value.values():
            _finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item)


def _calls_request(calls: Sequence[DeedCall | None], title: str, reference: str) -> PlotRequest:
    return PlotRequest(
        title=title,
        calls=tuple(
            PlotCall(id=f"call-{i}", call=call, source_reference=f"{reference} {i}")
            for i, call in enumerate(calls, 1)
        ),
    )


def _relative_request(description: RelativeDescription, title: str) -> PlotRequest:
    return PlotRequest(
        title=title,
        relative=description,
        calls=tuple(
            PlotCall(
                id=f"call-{i}",
                call=DeedCall(
                    course=i,
                    direction_text=course.source.quote,
                    distance_ft=course.distance_ft,
                    bearing_azimuth_deg_from_north=course.recorded_bearing_azimuth_deg_from_north,
                ),
                source_reference=course.source.reference,
                quote=course.source.quote,
            )
            for i, course in enumerate(description.courses, 1)
        ),
    )


def _request(source: bytes, name: str, input_format: str) -> tuple[PlotRequest, str]:
    if input_format not in {"auto", "calls", "relative", "plot", "text"}:
        raise ValueError(
            "input_format must be auto, calls, relative or plot; text is also accepted explicitly"
        )
    is_csv = input_format in {"auto", "calls"} and Path(name).suffix.lower() == ".csv"
    text = source.decode("utf-8")
    if input_format == "text":
        prepared = prepare_text(text)
        if prepared.multiple_tracts:
            raise ValueError(
                "Multi-tract descriptions require selecting a boundary before plotting"
            )
        if prepared.unresolved_commencement:
            raise ValueError("Point of commencement could not be separated from boundary calls.")
        return PlotRequest(
            title=name,
            calls=tuple(
                PlotCall(
                    id=f"call-{i}",
                    call=call,
                    source_reference=f"{name}: isolated description, call {i}",
                    quote=quote,
                )
                for i, (call, quote) in enumerate(
                    zip(prepared.legal_description.calls, prepared.quotes, strict=True), 1
                )
            ),
        ), "txt"
    if is_csv:
        from mp_export.csv_writer import FIELDNAMES, _row_to_call  # type: ignore[import-untyped]

        reader = csv.reader(io.StringIO(text), strict=True)
        if next(reader, None) != FIELDNAMES:
            raise ValueError("CSV requires the exact ordered 21-field call schema")
        csv_calls = []
        for number, values in enumerate(reader, 2):
            if len(values) != len(FIELDNAMES):
                raise ValueError(f"Malformed CSV row {number}")
            call = _row_to_call(dict(zip(FIELDNAMES, values, strict=True)), row_number=number)
            if call is None:
                raise ValueError(f"Invalid CSV call at row {number}")
            csv_calls.append(call)
        request = _calls_request(csv_calls, name, f"{name}: data row")
        return request, "csv"
    data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
    _finite_json(data)
    if input_format == "auto":
        if isinstance(data, dict) and "title" in data:
            input_format = "plot"
        elif isinstance(data, dict) and "frame" in data:
            input_format = "relative"
        else:
            input_format = "calls"
    if input_format == "plot":
        return PlotRequest.model_validate(data), "json"
    if input_format == "relative":
        return _relative_request(RelativeDescription.model_validate(data), name), "json"
    calls: Sequence[DeedCall | None]
    if isinstance(data, list):
        calls = [DeedCall.model_validate(c) if c is not None else None for c in data]
    elif isinstance(data, dict):
        description = LegalDescription.model_validate(data)
        if description.tracts:
            raise ValueError(
                "Multi-tract descriptions require selecting a boundary before plotting"
            )
        calls = description.calls
    else:
        raise ValueError(
            "Expected a call list, LegalDescription, RelativeDescription or PlotRequest"
        )
    return _calls_request(calls, name, f"{name}: calls item"), "json"


def plot_file(
    path: Path | str, output_dir: Path | str, *, input_format: str = "auto"
) -> dict[str, Any]:
    """Save original bytes, canonical inputs, fresh geometry and a non-verifying HTML plot.

    A fresh output directory is required. Every valid plot retains ``needs_review``;
    closure alone cannot establish source completeness or authorize verified CSV.
    Dashboard bundles use the separate validated dashboard workflow.
    """
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "engine_verified": False,
        "verified_export_eligible": False,
        "source_review_complete": False,
        "errors": [],
        "artifacts": {},
    }
    try:
        directory = Path(output_dir)
        if directory.is_symlink() or directory.exists():
            raise ValueError("Output directory must not already exist or be a symlink")
        source_path = Path(path).resolve(strict=True)
        source = source_path.read_bytes()
        result["input"] = {"name": source_path.name, "sha256": _sha(source)}
        request, kind = _request(source, source_path.name, input_format)
        prepared = prepare_plot(request)
        from mp_export.plot_html import render_plot  # type: ignore[import-untyped]

        rendered = render_plot(prepared)
        canonical = _json(prepared.request.model_dump(mode="json"))
        geometry = _json(prepared.geometry.model_dump(mode="json"))
        manifest = {
            "schema_version": "1.0",
            "replay_version": REPLAY_VERSION,
            "source_name": source_path.name,
            "input_format": input_format,
            "source_sha256": _sha(source),
            "input_hash": prepared.input_hash,
            "plot_input_sha256": _sha(canonical),
            "geometry_hash": prepared.geometry.geometry_hash,
            "plot_geometry_sha256": _sha(geometry),
            "html_sha256": _sha(rendered),
            "engine_verified": False,
            "verified_export_eligible": False,
            "source_review_complete": False,
        }
        artifacts: dict[str, str | bytes] = {
            f"source.{kind}": source,
            "plot-input.json": canonical,
            "plot-geometry.json": geometry,
            "plot.html": rendered,
            "plot-manifest.json": _json(manifest),
        }
        directory.mkdir(parents=True, exist_ok=False)
        for name, content in artifacts.items():
            _atomic(directory / name, content)
            result["artifacts"][name] = str(directory / name)
        result["geometry"] = prepared.geometry.model_dump(mode="json")
        result["manifest"] = manifest
    except (ValueError, TypeError, OSError, ArithmeticError, csv.Error) as exc:
        result["status"] = "error"
        result["errors"].append({"code": "invalid_plot", "message": str(exc)})
    return result
