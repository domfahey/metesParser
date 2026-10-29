"""Materialize synthetic skill-evaluation inputs and validate observed run evidence.

This module validates evidence structure only. It does not score model truthfulness or
launch model/provider sessions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "plugins/metesparser/evals/cases.json"
RUBRICS = ROOT / "plugins/metesparser/evals/rubrics.json"
SCHEMA_VERSION = "1.0"


# The case catalog is authoritative for candidate request/input; evaluator-only
# criterion IDs live in a separate file that materialize writes outside the bundle.
def _load_fixture_catalog() -> dict[str, dict[str, Any]]:
    cases = json.loads(CATALOG.read_text())
    rubrics = json.loads(RUBRICS.read_text())["rubrics"]
    indexed = {case["id"]: case for case in cases}
    combined: dict[str, dict[str, Any]] = {}
    for case_id, rubric in rubrics.items():
        if case_id not in indexed:
            raise ValueError(f"Rubric has no catalog case: {case_id}")
        case = indexed[case_id]
        if not case.get("synthetic") or not case.get("fixture_artifacts"):
            raise ValueError(f"Fixture case is not marked synthetic with artifacts: {case_id}")
        combined[case_id] = {
            "family": case["fixture_family"],
            "request": case["request"],
            "input": case["input"],
            "artifacts": case["fixture_artifacts"],
            "criteria": rubric["criteria"],
            "actions": rubric["required_actions"],
        }
    return combined


FIXTURES = _load_fixture_catalog()
MATERIALIZABLE_CASES = set(FIXTURES)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _page_lines(case_id: str) -> list[tuple[str, ...]]:
    """Return synthetic source-page content for the requested observation."""
    pages: dict[str, list[tuple[str, ...]]] = {
        "source-reading-obscured-digits": [
            (
                "SYNTHETIC DEED - EXHIBIT A",
                "BEGINNING at an iron pin",
                "thence N 56 deg 40 min 37 sec W, 100 feet",
                "thence southwesterly 50 feet to a fence",
            )
        ],
        "source-reading-missing-exhibit": [
            (
                "SYNTHETIC WARRANTY DEED",
                "The tract conveyed is described in",
                "the attached Exhibit A, incorporated herein.",
                "END OF SUPPLIED DEED - NO EXHIBIT A ATTACHED",
            )
        ],
        "source-reading-repeated-occurrences": [
            (
                "SYNTHETIC TITLE REPORT - PAGE 2",
                "BACKGROUND: EXHIBIT A, OCCURRENCE 1",
                "N 45 deg 00 min E, 100 feet to the old pin",
            ),
            (
                "SYNTHETIC TITLE REPORT - PAGE 7",
                "OPERATIVE: EXHIBIT A, OCCURRENCE 2",
                "N 45 deg 00 min W, 100 feet to the new pin",
            ),
        ],
        "selection-only": [
            (
                "SYNTHETIC SURVEY REPORT - PAGE 1",
                "BACKGROUND - PRIOR DEED DESCRIPTION",
                "N 10 deg E, 400 feet; then E 200 feet.",
                "NEW DESCRIPTION - BEGINNING AT THE IRON PIN",
                "thence N 90 deg E, 100 feet to a set pin;",
                "thence S 90 deg E, 100 feet to the POINT OF BEGINNING.",
                "LESS AND EXCEPT: the north 10 feet conveyed to the town.",
            )
        ],
        "end-to-end-review": [
            (
                "SYNTHETIC DEED - PAGE 1",
                "EXHIBIT B - OPERATIVE DESCRIPTION",
                "BEGINNING at a found iron pin;",
                "thence N 00 deg 00 min 00 sec E, 100 feet;",
                "thence N 90 deg 00 min 0? sec E, 100 feet;",
                "thence S 00 deg 00 min 00 sec W, 100 feet;",
                "thence W 100 feet to the BEGINNING.",
                "EXCEPT the recorded 10-foot utility easement.",
            )
        ],
    }
    return pages.get(
        case_id,
        [
            (
                f"SYNTHETIC INPUT - {case_id}",
                "All values and references in this fixture are invented.",
            )
        ],
    )


def _selection_text() -> bytes:
    return (
        b"SYNTHETIC SURVEY REPORT - PAGE 1\n"
        b"BACKGROUND - PRIOR DEED DESCRIPTION\n"
        b"N 10 deg E, 400 feet; then E 200 feet.\n"
        b"NEW DESCRIPTION - BEGINNING AT THE IRON PIN\n"
        b"thence N 90 deg E, 100 feet to a set pin;\n"
        b"thence S 90 deg E, 100 feet to the POINT OF BEGINNING.\n"
        b"LESS AND EXCEPT: the north 10 feet conveyed to the town.\n"
    )


def _render_page(lines: tuple[str, ...], *, obscure_digit: bool = False) -> Any:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError(
            "Fixture materialization requires Pillow (install the web-map extra)"
        ) from exc
    image = Image.new("RGB", (1200, max(600, 110 + 62 * len(lines))), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.line((70, 55, 1130, 55), fill="#333333", width=2)
    for index, line in enumerate(lines):
        y = 100 + 62 * index
        draw.text((75, y), line, fill="#171717", font=font)
        if obscure_digit and "37 sec" in line:
            prefix = line.split("37 sec")[0] + "3"
            bounds = draw.textbbox((75, y), prefix, font=font)
            draw.rectangle((bounds[2] + 1, y, bounds[2] + 33, y + 38), fill="#333333")
    draw.text(
        (75, image.height - 50),
        "SYNTHETIC TRAINING EXHIBIT - NOT A REAL PROPERTY RECORD",
        fill="#555555",
        font=font,
    )
    return image


def _pdf(case_id: str) -> bytes:
    """Build a scanned, image-only PDF with case-specific synthetic page content."""
    from io import BytesIO

    pages = [
        _render_page(lines, obscure_digit=case_id == "source-reading-obscured-digits" and i == 0)
        for i, lines in enumerate(_page_lines(case_id))
    ]
    output = BytesIO()
    pages[0].save(output, format="PDF", save_all=True, append_images=pages[1:], resolution=120)
    return output.getvalue()


def _write_json(path: Path, value: Any) -> bytes:
    content = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _materialize_restart_bundle(directory: Path, *, changed_transcript: bool) -> None:
    """Create schema-valid source records and real replayable review/plot outputs."""
    import hashlib

    from mp_models.source_handoff import (
        DescriptionCandidate,
        DescriptionSelectionRecord,
        SelectionSpan,
        SourceAcquisitionRecord,
        SourcePage,
        SourceReference,
        TranscriptReference,
    )
    from mp_review.api import review_file  # type: ignore[import-untyped]
    from mp_review.plot import plot_file  # type: ignore[import-untyped]

    original = b"SYNTHETIC DEED SOURCE - all matter is invented.\n"
    description = (
        "POINT OF BEGINNING at a synthetic pin; thence N 45° E, 100 feet to a corner; "
        "thence S 45° W, 100 feet to the POINT OF BEGINNING."
    )
    transcript = f"SYNTHETIC DEED - PAGE 1\n{description}\n".encode()
    selected = description.encode("utf-8")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "original.bin").write_bytes(original)
    (directory / "source-text.txt").write_bytes(transcript)
    (directory / "description-a.txt").write_bytes(selected)

    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    span_start = len(b"SYNTHETIC DEED - PAGE 1\n")
    acquisition = SourceAcquisitionRecord(
        id="acquisition-1",
        method="synthetic fixture transcription",
        request="Retain this synthetic source text.",
        conversion_instructions="Do not infer or repair any source values.",
        sources=(
            SourceReference(
                id="source-1", path="original.bin", sha256=digest(original), page_count=1
            ),
        ),
        transcript=TranscriptReference(path="source-text.txt", sha256=digest(transcript)),
        page_map=(SourcePage(id="page-1", source_id="source-1", page=1, start_line=1, end_line=2),),
        supplied_pages=("page-1",),
        read_pages=("page-1",),
        unreadable_pages=(),
        missing_pages=(),
        uncertainties=(),
    )
    acquisition_bytes = _write_json(
        directory / "source-acquisition.json", acquisition.model_dump(mode="json")
    )
    selection = DescriptionSelectionRecord(
        id="selection-1",
        acquisition_id=acquisition.id,
        acquisition_sha256=digest(acquisition_bytes),
        transcript_sha256=digest(transcript),
        request="Select the synthetic operative description.",
        selection_instructions="Retain the selected text verbatim.",
        candidates=(
            DescriptionCandidate(
                id="candidate-a",
                label="Synthetic parcel A",
                role="operative",
                selected_text=TranscriptReference(
                    path="description-a.txt", sha256=digest(selected)
                ),
                spans=(
                    SelectionSpan(
                        page_id="page-1",
                        start_byte=span_start,
                        end_byte=span_start + len(selected),
                        start_line=2,
                        end_line=2,
                    ),
                ),
                separators=(),
                opening_words=description[: len("POINT OF BEGINNING at a synthetic pin")],
                closing_words=description[-len("the POINT OF BEGINNING.") :],
                rationale="Synthetic operative description on the supplied page.",
                unresolved_references=(),
                carried_uncertainty_ids=(),
            ),
        ),
    )
    _write_json(directory / "description-selection.json", selection.model_dump(mode="json"))
    reviewed = review_file(directory / "description-a.txt", output_dir=directory / "review")
    plotted = plot_file(directory / "description-a.txt", directory / "plot", input_format="text")
    if reviewed["status"] == "error" or plotted["status"] == "error":
        raise ValueError("could not produce a real replayable review/plot fixture")
    if changed_transcript:
        changed = transcript.replace(b"100 feet to a corner", b"101 feet to a corner")
        (directory / "source-text.txt").write_bytes(changed)


def _fixture_json(case_id: str) -> dict[str, Any]:
    """Structured, concrete evaluation inputs; values and assets are synthetic."""
    if case_id == "reuse-restart":
        return {
            "schema_version": "1.0",
            "synthetic": True,
            "unchanged_bundle": "artifacts/unchanged",
            "changed_transcript_bundle": "artifacts/changed",
            "inspection_command": "metes-review inspect-artifacts BUNDLE --requested-stage plot",
            "note": "The changed bundle retains old downstream producer outputs to expose invalidation.",
        }
    if case_id in {"map-presentation-routing", "map-interaction-optional"}:
        from mp_models.plot import PlotScene
        from mp_models.raster import RasterRegistration
        from mp_models.webmap import StandaloneWebMapInput
        from mp_review.raster_registration import image_layer  # type: ignore[import-untyped]

        scene = PlotScene(
            id="synthetic-scene",
            name="Synthetic projected frame",
            kind="projected",
            crs="EPSG:3857",
            units="m",
        )
        layers_and_sources = []
        for suffix in ("a", "b"):
            image_bytes = _artifact_bytes(f"map-png-{suffix}", case_id)
            layer, source = image_layer(
                image_bytes,
                scene=scene,
                registration=RasterRegistration(
                    matrix=(1, 0, 0, 0, -1, 300), method="supplied_affine"
                ),
                filename=f"synthetic-scan-{suffix}.png",
            )
            layers_and_sources.append((layer, source))
        bundle = StandaloneWebMapInput(
            title="Synthetic paired scan view",
            scenes=(scene,),
            map_sources=tuple(item[1] for item in layers_and_sources),
            raster_layers=tuple(item[0] for item in layers_and_sources),
        )
        return {
            "schema_version": "1.0",
            "synthetic": True,
            "bundle": bundle.model_dump(mode="json"),
            "raster_layer_paths": ["artifacts/source-2.png", "artifacts/source-3.png"],
            "controls": ["visibility", "order"],
        }
    if case_id == "map-evidence-checkpoints":
        from mp_models.raster import RasterControl
        from mp_review.raster_registration import fit_affine

        controls = (
            RasterControl(id="fit-1", pixel=(0, 0), scene=(0, 0), role="fit"),
            RasterControl(id="fit-2", pixel=(100, 0), scene=(100, 0), role="fit"),
            RasterControl(id="fit-3", pixel=(0, 100), scene=(0, 100), role="fit"),
            RasterControl(id="fit-4", pixel=(100, 100), scene=(100.4, 100), role="fit"),
            RasterControl(id="check-1", pixel=(50, 50), scene=(70, 50), role="checkpoint"),
            RasterControl(id="check-2", pixel=(25, 75), scene=(25, 75), role="checkpoint"),
        )
        registration = fit_affine(controls)
        return {
            "schema_version": "1.0",
            "registration": registration.model_dump(mode="json"),
            "checkpoint_limit_px": 5.0,
            "status": "needs_review",
            "scene": {"crs": "EPSG:3857", "units": "m"},
        }
    if case_id == "comparison-reversed-lines":
        return {
            "left": {
                "id": "left",
                "plot": {
                    "title": "Synthetic prior description",
                    "calculation_id": "left-calc",
                    "foot_definition": "international_ft",
                    "calls": [
                        {
                            "id": "L1",
                            "quote": "N 45 E, 100 feet",
                            "source_reference": "synthetic page 1",
                            "occurrence_id": "left-occurrence",
                            "call": {
                                "course": 1,
                                "direction_text": "N 45 E, 100 feet",
                                "bearing_azimuth_deg_from_north": 45,
                                "distance_ft": 100,
                            },
                        }
                    ],
                },
                "bearing_basis": {
                    "label": "Recorded bearing basis",
                    "identity": "basis-synthetic-1",
                    "source_references": ["synthetic recital"],
                },
            },
            "right": {
                "id": "right",
                "plot": {
                    "title": "Synthetic revised description",
                    "calculation_id": "right-calc",
                    "foot_definition": "international_ft",
                    "calls": [
                        {
                            "id": "R1",
                            "quote": "S 45 W, 100 feet",
                            "source_reference": "synthetic page 2",
                            "occurrence_id": "right-occurrence",
                            "call": {
                                "course": 1,
                                "direction_text": "S 45 W, 100 feet",
                                "bearing_azimuth_deg_from_north": 225,
                                "distance_ft": 100,
                            },
                        }
                    ],
                },
                "bearing_basis": {
                    "label": "Recorded bearing basis",
                    "identity": "basis-synthetic-1",
                    "source_references": ["synthetic recital"],
                },
            },
            "pairs": [
                {
                    "id": "paired-line",
                    "left": {"call_ids": ["L1"], "direction": "forward"},
                    "right": {"call_ids": ["R1"], "direction": "reverse"},
                }
            ],
            "tolerances": {
                "length": 0.01,
                "displacement": 0.01,
                "position": 0.01,
                "linear_unit": "international_ft",
                "bearing_deg": 0.01,
                "source_references": ["synthetic review criterion"],
            },
        }
    if case_id == "comparison-incompatible-basis":
        return {
            "left": {
                "id": "record-a",
                "plot": {
                    "title": "Synthetic old record",
                    "calculation_id": "old-calc",
                    "foot_definition": "international_ft",
                    "calls": [
                        {
                            "id": "A1",
                            "quote": "N 45 E 100 feet to the iron pipe",
                            "source_reference": "synthetic page 1",
                            "occurrence_id": "old-occurrence",
                            "call": {
                                "course": 1,
                                "direction_text": "N 45 E, 100 feet",
                                "bearing_azimuth_deg_from_north": 45,
                                "distance_ft": 100,
                                "to": "original iron pipe",
                            },
                        }
                    ],
                },
                "bearing_basis": {
                    "label": "Unspecified recorded basis",
                    "identity": None,
                    "source_references": ["synthetic page 1"],
                },
            },
            "right": {
                "id": "record-b",
                "plot": {
                    "title": "Synthetic revised record",
                    "calculation_id": "new-calc",
                    "foot_definition": "international_ft",
                    "calls": [
                        {
                            "id": "B1",
                            "quote": "N 45 E 100 feet to the iron pin",
                            "source_reference": "synthetic page 2",
                            "occurrence_id": "new-occurrence",
                            "call": {
                                "course": 1,
                                "direction_text": "N 45 E, 100 feet",
                                "bearing_azimuth_deg_from_north": 45,
                                "distance_ft": 100,
                                "to": "replacement iron pin",
                            },
                        }
                    ],
                },
                "bearing_basis": {
                    "label": "Unspecified recorded basis",
                    "identity": None,
                    "source_references": ["synthetic page 2"],
                },
            },
            "pairs": [
                {
                    "id": "paired-recorded-call",
                    "left": {"call_ids": ["A1"], "direction": "forward"},
                    "right": {"call_ids": ["B1"], "direction": "forward"},
                }
            ],
            "tolerances": {
                "length": 0.1,
                "displacement": 0.1,
                "position": 0.1,
                "linear_unit": "international_ft",
                "bearing_deg": 0.01,
                "source_references": ["synthetic review criterion"],
            },
        }
    if case_id == "comparison-structural-tentative":
        return {
            "left": {
                "id": "version-a",
                "plot": {
                    "title": "Synthetic prior sequence",
                    "calculation_id": "sequence-a",
                    "foot_definition": "international_ft",
                    "calls": [
                        {
                            "id": "A1",
                            "quote": "N 45 E, 100 feet",
                            "source_reference": "synthetic exhibit A",
                            "occurrence_id": "a1",
                            "call": {
                                "course": 1,
                                "direction_text": "N 45 E, 100 feet",
                                "bearing_azimuth_deg_from_north": 45,
                                "distance_ft": 100,
                            },
                        },
                        {
                            "id": "A2",
                            "quote": "E 50 feet along fence",
                            "source_reference": "synthetic exhibit A",
                            "occurrence_id": "a2",
                            "call": {
                                "course": 2,
                                "direction_text": "E 50 feet",
                                "bearing_azimuth_deg_from_north": 90,
                                "distance_ft": 50,
                                "along": "fence",
                            },
                        },
                        {
                            "id": "A3",
                            "quote": "N 45 E, 100 feet",
                            "source_reference": "synthetic exhibit A",
                            "occurrence_id": "a3",
                            "call": {
                                "course": 3,
                                "direction_text": "N 45 E, 100 feet",
                                "bearing_azimuth_deg_from_north": 45,
                                "distance_ft": 100,
                            },
                        },
                    ],
                },
                "bearing_basis": {
                    "label": "Unspecified basis",
                    "identity": None,
                    "source_references": ["synthetic exhibit A"],
                },
            },
            "right": {
                "id": "version-b",
                "plot": {
                    "title": "Synthetic revised sequence",
                    "calculation_id": "sequence-b",
                    "foot_definition": "international_ft",
                    "calls": [
                        {
                            "id": "B1",
                            "quote": "N 45 E, 100 feet",
                            "source_reference": "synthetic exhibit B",
                            "occurrence_id": "b1",
                            "call": {
                                "course": 1,
                                "direction_text": "N 45 E, 100 feet",
                                "bearing_azimuth_deg_from_north": 45,
                                "distance_ft": 100,
                            },
                        },
                        {
                            "id": "B2",
                            "quote": "E 20 feet along fence",
                            "source_reference": "synthetic exhibit B",
                            "occurrence_id": "b2",
                            "call": {
                                "course": 2,
                                "direction_text": "E 20 feet",
                                "bearing_azimuth_deg_from_north": 90,
                                "distance_ft": 20,
                                "along": "fence",
                            },
                        },
                        {
                            "id": "B3",
                            "quote": "E 30 feet along fence",
                            "source_reference": "synthetic exhibit B",
                            "occurrence_id": "b3",
                            "call": {
                                "course": 3,
                                "direction_text": "E 30 feet",
                                "bearing_azimuth_deg_from_north": 90,
                                "distance_ft": 30,
                                "along": "fence",
                            },
                        },
                        {
                            "id": "B4",
                            "quote": "N 45 E, 100 feet",
                            "source_reference": "synthetic exhibit B",
                            "occurrence_id": "b4",
                            "call": {
                                "course": 4,
                                "direction_text": "N 45 E, 100 feet",
                                "bearing_azimuth_deg_from_north": 45,
                                "distance_ft": 100,
                            },
                        },
                    ],
                },
                "bearing_basis": {
                    "label": "Unspecified basis",
                    "identity": None,
                    "source_references": ["synthetic exhibit B"],
                },
            },
            "pairs": [],
            "tolerances": {
                "length": 0.1,
                "displacement": 0.1,
                "position": 0.1,
                "linear_unit": "international_ft",
                "bearing_deg": 0.01,
                "source_references": ["synthetic review criterion"],
            },
        }
    if case_id == "closure-diagnosis":
        from mp_models.deed_call import DeedCall
        from mp_models.diagnostics import (
            ClosureDiagnosticRequest,
            DiagnosticCall,
            DiagnosticFrame,
            diagnostic_input_hash,
        )

        calls = tuple(
            DiagnosticCall(
                call_id=f"c{index}",
                call=DeedCall(
                    course=index,
                    direction_text=direction,
                    bearing_azimuth_deg_from_north=azimuth,
                    distance_ft=distance,
                ),
            )
            for index, (direction, azimuth, distance) in enumerate(
                (
                    ("east", 90.0, 100.5),
                    ("south", 180.0, 100.0),
                    ("west", 270.0, 100.0),
                    ("north", 0.0, 100.0),
                ),
                start=1,
            )
        )
        request = ClosureDiagnosticRequest(
            request_id="synthetic-diagnosis-1",
            input_id="synthetic-parcel",
            calls=calls,
            input_sha256=diagnostic_input_hash(calls),
            frame=DiagnosticFrame(name="Recorded"),
        )
        return request.model_dump(mode="json")
    return {"schema_version": "1.0", "synthetic": True, "case_id": case_id}


def _artifact_bytes(kind: str, case_id: str) -> bytes:
    if kind == "pdf":
        return _pdf(case_id)
    if kind == "text":
        return _selection_text()
    if kind == "png":
        from io import BytesIO

        output = BytesIO()
        _render_page(
            _page_lines(case_id)[0], obscure_digit=case_id == "source-reading-obscured-digits"
        ).save(output, format="PNG")
        return output.getvalue()
    if kind in {"map-png-a", "map-png-b"}:
        from io import BytesIO

        output = BytesIO()
        label = (
            "SYNTHETIC RASTER LAYER A - north survey scan"
            if kind == "map-png-a"
            else "SYNTHETIC RASTER LAYER B - east survey scan"
        )
        _render_page((label, "Grid pixels are fixture content only.")).save(output, format="PNG")
        return output.getvalue()
    if kind == "manifest":
        return json.dumps(_fixture_json(case_id), indent=2).encode()
    if kind == "restart-bundles":
        return json.dumps(_fixture_json(case_id), indent=2).encode()
    if kind == "json":
        return json.dumps(_fixture_json(case_id), indent=2).encode()
    raise ValueError(f"Unsupported fixture artifact kind: {kind}")


def materialize(case_id: str, output_dir: Path, evaluator_dir: Path) -> dict[str, Any]:
    """Write candidate files and evaluator rubric to separate new directories."""
    if case_id not in MATERIALIZABLE_CASES:
        raise ValueError(f"Unknown evaluation fixture: {case_id}")
    candidate = Path(output_dir)
    evaluator = Path(evaluator_dir)
    candidate_root = candidate.resolve()
    evaluator_root = evaluator.resolve()
    if (
        candidate_root == evaluator_root
        or candidate_root in evaluator_root.parents
        or evaluator_root in candidate_root.parents
    ):
        raise ValueError("candidate and evaluator must be separate, non-overlapping directories")
    if candidate.exists() or evaluator.exists():
        raise FileExistsError("candidate and evaluator output directories must be new")
    if any(
        kind in {"pdf", "png", "map-png-a", "map-png-b"} for kind in FIXTURES[case_id]["artifacts"]
    ):
        try:
            import PIL  # noqa: F401
        except ImportError as exc:
            raise ValueError(
                "Fixture materialization requires Pillow (install the web-map extra)"
            ) from exc
    candidate.mkdir(parents=True)
    evaluator.mkdir(parents=True)
    spec = FIXTURES[case_id]
    artifacts: list[dict[str, str]] = []
    for index, kind in enumerate(spec["artifacts"], start=1):
        suffix = {
            "pdf": ".pdf",
            "png": ".png",
            "map-png-a": ".png",
            "map-png-b": ".png",
            "manifest": ".json",
            "json": ".json",
            "selection-json": ".json",
            "plot-json": ".json",
            "transcript-before": ".txt",
            "transcript-after": ".txt",
            "source-document": ".txt",
            "text": ".txt",
            "restart-bundles": ".json",
        }[kind]
        relpath = f"artifacts/source-{index}{suffix}"
        path = candidate / relpath
        path.parent.mkdir(exist_ok=True)
        content = _artifact_bytes(kind, case_id)
        path.write_bytes(content)
        artifacts.append({"path": relpath, "kind": kind, "sha256": _sha256(content)})
    if case_id == "reuse-restart":
        _materialize_restart_bundle(candidate / "artifacts/unchanged", changed_transcript=False)
        _materialize_restart_bundle(candidate / "artifacts/changed", changed_transcript=True)
        known = {entry["path"] for entry in artifacts}
        for path in sorted((candidate / "artifacts").rglob("*")):
            if path.is_file():
                relpath = path.relative_to(candidate).as_posix()
                if relpath not in known:
                    artifacts.append(
                        {
                            "path": relpath,
                            "kind": "producer_artifact",
                            "sha256": _sha256(path.read_bytes()),
                        }
                    )
    request = {
        "request": spec["request"],
        "input": spec["input"],
        "input_artifact_paths": [item["path"] for item in artifacts],
    }
    (candidate / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "family": spec["family"],
        "synthetic": True,
        "materialized_at_utc": datetime.now(UTC).isoformat(),
        "request_path": "request.json",
        "request_sha256": _sha256((candidate / "request.json").read_bytes()),
        "artifacts": artifacts,
    }
    manifest_path = candidate / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    rubric = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "criteria": [
            {"id": criterion, "description": criterion.replace("_", " ")}
            for criterion in spec["criteria"]
        ],
        "required_actions": spec["actions"],
    }
    (evaluator / "rubric.json").write_text(json.dumps(rubric, indent=2) + "\n")
    return {
        "candidate_dir": str(candidate),
        "evaluator_dir": str(evaluator),
        "manifest_sha256": _sha256(manifest_path.read_bytes()),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON record {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _transcript_observations(data: bytes) -> tuple[bool, bool]:
    """Recognize observed turns and explicit client failures, without judging truth.

    Accept JSON ``turns`` arrays, JSON arrays, and JSONL client events. A startup
    record or a client's synthetic authentication message is not model behavior.
    Unknown/plain-text formats cannot establish a scored observation here.
    """
    try:
        text = data.decode("utf-8-sig")
        try:
            value = json.loads(text)
            entries = value.get("turns", [value]) if isinstance(value, dict) else value
        except json.JSONDecodeError:
            entries = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, False
    if not isinstance(entries, list):
        return False, False
    observed = False
    failed = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind == "error" or kind == "result" and entry.get("is_error") is True:
            failed = True
        if kind == "assistant" and entry.get("error"):
            failed = True
            continue
        message = entry.get("message", entry)
        if not isinstance(message, dict) or message.get("model") == "<synthetic>":
            continue
        if kind == "assistant" or message.get("role") == "assistant":
            content = message.get("content", message.get("text"))
            if (
                isinstance(content, str)
                and content.strip()
                or isinstance(content, list)
                and content
            ):
                observed = True
        if (
            kind == "result"
            and entry.get("is_error") is not True
            and isinstance(entry.get("result"), str)
            and entry["result"].strip()
        ):
            observed = True
    return observed, failed


def validate_run(run_path: Path | dict[str, Any]) -> list[str]:
    """Return structural evidence errors; never infer behavior from prose."""
    errors: list[str] = []
    if isinstance(run_path, dict):
        run = run_path
        path = Path(str(run.get("_source_path", "."))).resolve()
    else:
        path = Path(run_path).resolve()
        try:
            run = _load_json(path)
        except ValueError as exc:
            return [str(exc)]
    record_dir = path.parent
    for field in (
        "run_id",
        "case_id",
        "pair_id",
        "model_provider",
        "model_name_version",
        "client_surface",
        "started_at_utc",
        "case_source_commit",
        "case_source_sha256",
        "input_manifest_path",
        "input_manifest_sha256",
        "transcript_path",
        "transcript_sha256",
    ):
        if not run.get(field):
            errors.append(f"missing required field: {field}")
    for field in (
        "skill_files_and_hashes",
        "available_tools_and_schema_evidence",
        "artifact_paths",
    ):
        if field not in run:
            errors.append(f"missing required field: {field}")
    condition = run.get("condition")
    if not isinstance(condition, str) or condition not in {
        "baseline",
        "with_skill",
        "non_equivalent",
    }:
        errors.append("condition must be baseline, with_skill, or non_equivalent")
    overall_result = run.get("overall_result")
    if not isinstance(overall_result, str) or overall_result not in {"pass", "fail", "not_run"}:
        errors.append("overall_result must be pass, fail, or not_run")
    if run.get("fresh_session") is not True:
        errors.append("run must record a fresh session")
    if run.get("case_source_sha256") and not _is_sha256(run["case_source_sha256"]):
        errors.append("case_source_sha256 must be a lowercase SHA-256 digest")
    if condition != "non_equivalent" and run.get("isolation_status") != "equivalent":
        errors.append("paired-equivalent condition requires verified equivalent isolation")
    if condition == "with_skill" and not run.get("skill_files_and_hashes"):
        errors.append("with-skill run must retain hashes for exposed skill resources")
    skill_files = run.get("skill_files_and_hashes")
    tool_evidence = run.get("available_tools_and_schema_evidence")
    artifact_paths = run.get("artifact_paths")
    if not isinstance(skill_files, list) or not isinstance(tool_evidence, list):
        errors.append("skill hashes and available tool/schema evidence must be arrays")
    if not isinstance(artifact_paths, list) or any(
        not isinstance(item, str) for item in artifact_paths
    ):
        errors.append("artifact_paths must be an array of paths")
        artifact_paths = []
    if not isinstance(skill_files, list):
        skill_files = []
    if not isinstance(tool_evidence, list):
        tool_evidence = []
    for skill in skill_files:
        if (
            not isinstance(skill, dict)
            or not isinstance(skill.get("path"), str)
            or not skill.get("path")
            or not _is_sha256(skill.get("sha256"))
        ):
            errors.append("skill resource entry requires path and SHA-256")
            continue
        try:
            skill_path = Path(skill["path"])
        except (TypeError, ValueError):
            errors.append("skill resource path must be a valid filesystem path")
            continue
        if not skill_path.is_absolute():
            skill_path = record_dir / skill_path
        try:
            if skill_path.is_symlink() or not skill_path.is_file():
                errors.append(f"skill resource is missing or not a regular file: {skill['path']}")
            elif _sha256(skill_path.read_bytes()) != skill["sha256"]:
                errors.append(f"skill resource hash mismatch: {skill['path']}")
        except OSError:
            errors.append(f"skill resource is unavailable: {skill['path']}")

    candidate_dir = (record_dir / str(run.get("candidate_bundle_path", ""))).resolve()
    rubric_path = (record_dir / str(run.get("rubric_path", ""))).resolve()
    evaluator_dir = rubric_path.parent
    if not run.get("candidate_bundle_path"):
        errors.append("candidate bundle path is missing")
    if (
        candidate_dir == evaluator_dir
        or candidate_dir in evaluator_dir.parents
        or evaluator_dir in candidate_dir.parents
        or candidate_dir in rubric_path.parents
    ):
        errors.append(
            "rubric path must be outside the candidate bundle in a separate evaluator directory"
        )
    try:
        rubric = _load_json(rubric_path)
    except ValueError as exc:
        errors.append(f"rubric unavailable: {exc}")
        rubric = {}
    if rubric and rubric.get("case_id") != run.get("case_id"):
        errors.append("rubric case_id does not match run")
    case_id = run.get("case_id")
    if not isinstance(case_id, str) or case_id not in FIXTURES:
        errors.append("case_id is absent from the authoritative evaluation catalog")
    else:
        authoritative = FIXTURES[run["case_id"]]
        expected_rubric = [
            {"id": criterion, "description": criterion.replace("_", " ")}
            for criterion in authoritative["criteria"]
        ]
        if (
            rubric.get("criteria") != expected_rubric
            or rubric.get("required_actions") != authoritative["actions"]
        ):
            errors.append("run rubric does not match the authoritative rubric for this case")
    rubric_digest = _sha256(rubric_path.read_bytes()) if rubric_path.is_file() else None
    if candidate_dir.is_dir() and rubric_digest:
        rubric_tokens = FIXTURES.get(str(run.get("case_id")), {}).get(
            "criteria", []
        ) + FIXTURES.get(str(run.get("case_id")), {}).get("actions", [])
        for candidate_file in candidate_dir.rglob("*"):
            if candidate_file.is_file():
                content = candidate_file.read_bytes()
                if (
                    candidate_file.name.lower().startswith("rubric")
                    or _sha256(content) == rubric_digest
                ):
                    errors.append("candidate bundle includes evaluator-only rubric")
                    break
                if any(token.encode("utf-8") in content for token in rubric_tokens):
                    errors.append("candidate bundle includes evaluator-only rubric criteria")
                    break
    try:
        manifest_path = (record_dir / str(run.get("input_manifest_path", ""))).resolve()
        if candidate_dir not in manifest_path.parents:
            errors.append("input manifest escapes candidate bundle")
        manifest_bytes = manifest_path.read_bytes()
        if _sha256(manifest_bytes) != run.get("input_manifest_sha256"):
            errors.append("stale or incorrect input manifest hash")
        manifest = json.loads(manifest_bytes)
        if manifest.get("case_id") != run.get("case_id"):
            errors.append("input manifest case_id does not match run")
        request_path = (candidate_dir / manifest["request_path"]).resolve()
        if (
            candidate_dir not in request_path.parents
            or not request_path.is_file()
            or _sha256(request_path.read_bytes()) != manifest.get("request_sha256")
        ):
            errors.append("missing or stale candidate request file")
        declared_paths = {item["path"] for item in manifest.get("artifacts", [])}
        if set(artifact_paths) != declared_paths:
            errors.append("run artifact paths do not match candidate manifest")
        for artifact in manifest.get("artifacts", []):
            artifact_path = (candidate_dir / artifact["path"]).resolve()
            if (
                candidate_dir not in artifact_path.parents
                or not artifact_path.is_file()
                or _sha256(artifact_path.read_bytes()) != artifact.get("sha256")
            ):
                errors.append(f"missing or stale input artifact: {artifact.get('path')}")
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        errors.append("input manifest is missing or invalid")

    transcript_path = (record_dir / str(run.get("transcript_path", ""))).resolve()
    transcript_observed = False
    transcript_client_failure = False
    try:
        if not transcript_path.is_file():
            errors.append("transcript file is missing")
        else:
            transcript_bytes = transcript_path.read_bytes()
            if not transcript_bytes:
                errors.append("transcript is empty")
            elif _sha256(transcript_bytes) != run.get("transcript_sha256"):
                errors.append("transcript hash mismatch")
            else:
                transcript_observed, transcript_client_failure = _transcript_observations(
                    transcript_bytes
                )
    except OSError:
        errors.append("transcript file is missing")

    rubric_criteria = rubric.get("criteria", [])
    if not isinstance(rubric_criteria, list) or any(
        not isinstance(item, dict) for item in rubric_criteria
    ):
        errors.append("rubric criteria must be an array of objects")
        rubric_criteria = []
    expected: set[str] = set()
    for item in rubric_criteria:
        criterion_id = item.get("id")
        if not isinstance(criterion_id, str) or not criterion_id:
            errors.append("rubric criterion IDs must be nonempty strings")
        else:
            expected.add(criterion_id)
    criteria = run.get("criteria")
    if not isinstance(criteria, list) or any(not isinstance(item, dict) for item in criteria):
        errors.append("criteria must be an array of objects")
        criteria = []
    actual: set[str] = set()
    for item in criteria:
        criterion_id = item.get("criterion_id")
        if not isinstance(criterion_id, str) or not criterion_id:
            errors.append("criterion IDs must be nonempty strings")
        else:
            actual.add(criterion_id)
    if len(actual) != len(criteria):
        errors.append("duplicate criterion IDs")
    if expected != actual:
        errors.append(
            f"criterion coverage mismatch: expected {sorted(expected)}, got {sorted(actual)}"
        )
    for item in criteria:
        result = item.get("result")
        if not isinstance(result, str) or result not in {"pass", "fail", "not_run"}:
            errors.append(f"invalid criterion result: {item.get('criterion_id')}")
        if not item.get("evidence"):
            errors.append(f"criterion evidence missing: {item.get('criterion_id')}")
    actions = run.get("required_actions")
    required_actions = rubric.get("required_actions", [])
    if not isinstance(required_actions, list) or any(
        not isinstance(item, str) for item in required_actions
    ):
        errors.append("rubric required_actions must be an array of action IDs")
        required_actions = []
    required = set(required_actions)
    if not isinstance(actions, list) or any(not isinstance(item, dict) for item in actions):
        errors.append("required_actions must be an array of objects")
        actions = []
    action_ids: set[str] = set()
    for item in actions:
        action_id = item.get("action")
        if not isinstance(action_id, str) or not action_id:
            errors.append("required action IDs must be nonempty strings")
        else:
            action_ids.add(action_id)
    if len(action_ids) != len(actions):
        errors.append("duplicate required action IDs")
    if action_ids != required:
        errors.append(
            f"required action coverage mismatch: expected {sorted(required)}, got {sorted(action_ids)}"
        )
    for item in actions:
        result = item.get("result")
        if not isinstance(result, str) or result not in {"pass", "fail", "not_run"}:
            errors.append(f"invalid required action result: {item.get('action')}")
        if not item.get("evidence"):
            errors.append(f"required action evidence missing: {item.get('action')}")
        if item.get("result") == "not_run" and not item.get("reason"):
            errors.append(f"not-run action reason missing: {item.get('action')}")
    observed = [item.get("result") for item in criteria]
    observed += [item.get("result") for item in actions]
    overall = run.get("overall_result")
    if transcript_client_failure and overall != "not_run":
        errors.append(
            "transcript records a client/session failure; unavailable behavior must be not_run"
        )
    if not transcript_observed and (
        isinstance(overall, str)
        and overall in {"pass", "fail"}
        or any(result in {"pass", "fail"} for result in observed if isinstance(result, str))
    ):
        errors.append("transcript has no observed model behavior for criterion/action scores")
    if overall == "not_run" and not run.get("overall_reason"):
        errors.append("not-run overall result requires a reason")
    if overall == "pass" and (errors or any(result != "pass" for result in observed)):
        errors.append("overall pass contradicts incomplete, failed, or unrun evidence")
    if overall == "fail" and not any(result == "fail" for result in observed):
        errors.append("overall fail has no failed criterion or required action")
    return errors


def _load_runs(paths: list[Path]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in paths:
        if path.suffix == ".jsonl":
            for line_number, line in enumerate(path.read_text().splitlines(), start=1):
                if line.strip():
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError(f"Expected an object on {path}:{line_number}")
                    record["_source_path"] = str(path)
                    record["_line"] = line_number
                    runs.append(record)
        else:
            record = _load_json(path)
            record["_source_path"] = str(path)
            runs.append(record)
    return runs


def summarize(run_paths: list[Path]) -> dict[str, Any]:
    """Summarize per-case/model/client outcomes and verify A/B pairing identity."""
    runs = _load_runs([Path(item) for item in run_paths])
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        run["validation_errors"] = validate_run(run)
        key = (
            str(run.get("case_id", "")),
            str(run.get("model_provider", "")) + "/" + str(run.get("model_name_version", "")),
            str(run.get("client_surface", "")),
        )
        groups[key].append(run)
        pairs[str(run.get("pair_id", ""))].append(run)
    group_rows = []
    for (case_id, model, client), records in sorted(groups.items()):
        valid_records = [record for record in records if not record["validation_errors"]]
        group_rows.append(
            {
                "case_id": case_id,
                "model": model,
                "client_surface": client,
                "runs": len(records),
                "valid_runs": len(valid_records),
                "invalid_runs": len(records) - len(valid_records),
                "recorded_result_counts": {
                    key: sum(record.get("overall_result") == key for record in records)
                    for key in ("pass", "fail", "not_run")
                },
                "validated_result_counts": {
                    key: sum(record.get("overall_result") == key for record in valid_records)
                    for key in ("pass", "fail", "not_run")
                },
            }
        )
    pair_rows = []
    for pair_id, records in sorted(pairs.items()):
        conditions = {str(record.get("condition")): record for record in records}
        status = "paired" if {"baseline", "with_skill"} <= conditions.keys() else "incomplete_pair"
        reasons: list[str] = []
        if "non_equivalent" in conditions:
            status = "non_equivalent"
            reasons.append("run condition is explicitly non_equivalent")
        if len(records) != 2 or len(conditions) != len(records):
            reasons.append("pair must contain exactly one baseline and one with-skill run")
            status = "non_equivalent"
        if status == "paired":
            baseline, skill = conditions["baseline"], conditions["with_skill"]
            for field in (
                "case_id",
                "model_provider",
                "model_name_version",
                "client_surface",
                "input_manifest_sha256",
            ):
                if baseline.get(field) != skill.get(field):
                    reasons.append(f"mismatched {field}")
            if baseline.get("available_tools_and_schema_evidence") != skill.get(
                "available_tools_and_schema_evidence"
            ):
                reasons.append("mismatched available tools or tool schemas")
            if baseline.get("validation_errors") or skill.get("validation_errors"):
                reasons.append("run evidence failed validation")
            if (
                baseline.get("isolation_status") != "equivalent"
                or skill.get("isolation_status") != "equivalent"
            ):
                reasons.append("isolation not verified")
            if reasons:
                status = "non_equivalent"
            elif (
                baseline.get("overall_result") == "not_run"
                or skill.get("overall_result") == "not_run"
            ):
                status = "incomplete_pair"
                reasons.append(
                    "one or both sessions are not_run; no observed paired comparison exists"
                )
        pair_rows.append(
            {
                "pair_id": pair_id,
                "status": status,
                "reasons": reasons,
                "conditions": sorted(conditions),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "groups": group_rows,
        "pairs": pair_rows,
        "runs": [
            {
                "run_id": record.get("run_id"),
                "case_id": record.get("case_id"),
                "model_provider": record.get("model_provider"),
                "model_name_version": record.get("model_name_version"),
                "client_surface": record.get("client_surface"),
                "condition": record.get("condition"),
                "overall_result": record.get("overall_result"),
                "transcript_sha256": record.get("transcript_sha256"),
                "valid": not record["validation_errors"],
                "validation_errors": record["validation_errors"],
            }
            for record in runs
        ],
        "run_count": len(runs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    materialize_parser = commands.add_parser(
        "materialize", help="write a synthetic candidate bundle and separate evaluator rubric"
    )
    materialize_parser.add_argument("case_id", choices=sorted(MATERIALIZABLE_CASES))
    materialize_parser.add_argument("--output-dir", type=Path, required=True)
    materialize_parser.add_argument("--evaluator-dir", type=Path, required=True)
    validate_parser = commands.add_parser(
        "validate-run", help="validate a run record and its referenced evidence"
    )
    validate_parser.add_argument("run_json", type=Path)
    summarize_parser = commands.add_parser(
        "summarize", help="summarize JSON/JSONL run records without cross-client scoring"
    )
    summarize_parser.add_argument("run_files", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "materialize":
            result = materialize(args.case_id, args.output_dir, args.evaluator_dir)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "validate-run":
            errors = validate_run(args.run_json)
            print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
            return 0 if not errors else 1
        result = summarize(args.run_files)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
