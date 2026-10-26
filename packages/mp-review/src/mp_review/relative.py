"""Review explicit relative constraints without issuing canonical verification."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from mp_models import RelativeDescription
from mp_verify import analyze_relative

from .api import _base, _error

RELATIVE_LIMITATIONS = [
    "Local headings use the declared frame; they are not recorded compass bearings.",
    "Relative analysis does not run canonical verification or authorize verified exports.",
    "Only explicit straight-line constraints are analyzed; source completeness requires separate review.",
    "Area includes an implicit closing segment and is provisional when the traverse is open.",
]


def _relative_base(source: bytes, name: str) -> dict[str, Any]:
    result = _base(source, name, "relative_json")
    result.update(
        method="deterministic_relative",
        engine_verified=False,
        verified_export_eligible=False,
        analysis=None,
        limitations=list(RELATIVE_LIMITATIONS),
    )
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_number(value: str) -> None:
    raise ValueError(f"Invalid JSON number: {value}")


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, allow_nan=False)


def _report(result: dict[str, Any], source_text: str | None) -> str:
    """Render source and local computations with no active user-provided markup."""
    analysis = result["analysis"] or {}
    summary = {
        "Canonical status": result["status"],
        "Local geometry": analysis.get("status", "unavailable"),
        "Misclosure (ft)": analysis.get("misclosure_ft"),
        "Area with implicit closing segment (sq ft)": analysis.get("area_sq_ft"),
        "Perimeter (ft)": analysis.get("perimeter_ft"),
        "Verified export eligible": False,
    }
    summary_html = "".join(
        f"<dt>{html.escape(key)}</dt><dd>{html.escape(str(value))}</dd>"
        for key, value in summary.items()
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in result["limitations"])
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Relative-angle review</title>"
        "<style>body{max-width:70rem;margin:2rem auto;padding:0 1rem;font:16px/1.5 system-ui}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f4;padding:1rem}"
        "dt{font-weight:bold}dd{margin:0 0 .6rem}details{margin:1rem 0}</style></head><body>"
        "<h1>Relative-angle review</h1><p>"
        + html.escape(str(result["input"]["name"]))
        + "</p><dl>"
        + summary_html
        + "</dl><h2>Limits of this analysis</h2><ul>"
        + limitations
        + "</ul><h2>Source input</h2><pre>"
        + html.escape(source_text if source_text is not None else "Input is not valid UTF-8.")
        + "</pre><h2>Local geometry, constraints and diagnostics</h2><pre>"
        + html.escape(_json(analysis))
        + "</pre><h2>Errors</h2><pre>"
        + html.escape(_json(result["errors"]))
        + "</pre></body></html>"
    )


def review_relative_file(path: Path | str, *, output_dir: Path | None = None) -> dict[str, Any]:
    """Analyze a RelativeDescription JSON file in an explicitly declared local frame.

    Valid descriptions always retain the canonical ``needs_review`` status. The
    separate ``analysis.status`` says whether relative geometry was determined.
    No calls are converted to canonical bearings, and no CSV is exported.
    """
    path = Path(path)
    try:
        source = path.read_bytes()
    except OSError as exc:
        return _error(_relative_base(b"", path.name), "input_error", str(exc))
    result = _relative_base(source, path.name)
    directory = Path(output_dir) if output_dir is not None else None
    if directory is not None:
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return _error(result, "output_exists", "Output directory must not already exist.")
        except OSError as exc:
            return _error(result, "output_error", str(exc))

    text = None
    description = None
    try:
        text = source.decode("utf-8")
        if path.suffix.lower() != ".json":
            raise ValueError("Relative analysis requires a RelativeDescription JSON file.")
        data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
        description = RelativeDescription.model_validate(data)
        result["analysis"] = analyze_relative(description).model_dump(mode="json")
    except (ValueError, TypeError, ArithmeticError) as exc:
        _error(result, "invalid_input", str(exc))

    if directory is not None:
        try:

            def write(name: str, value: str | bytes) -> None:
                target = directory / name
                target.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)
                result["artifacts"][name] = str(target)

            write("source.json", source)
            write("analysis.json", _json(result["analysis"]))
            write(
                "audit.json",
                _json(
                    {
                        "schema_version": "1.0",
                        "engine_version": result["engine_version"],
                        "provider": None,
                        "model": None,
                        "method": "deterministic_relative",
                        "input": result["input"],
                        "original_source": text,
                        "source_encoding": "utf-8" if text is not None else "unavailable",
                        "description": description.model_dump(mode="json") if description else None,
                        "analysis": result["analysis"],
                        "status": result["status"],
                        "engine_verified": False,
                        "verified_export_eligible": False,
                        "limitations": result["limitations"],
                        "errors": result["errors"],
                    }
                ),
            )
            write("review.html", _report(result, text))
        except (ValueError, OSError) as exc:
            _error(result, "artifact_error", str(exc))
    return result
