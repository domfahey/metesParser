"""Atomic dashboard staging and intact cache reuse, with no document-reading claims."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from mp_models.dashboard import (
    DashboardBundle,
    DashboardManifest,
    DashboardResult,
    PreparedDashboard,
)
from mp_verify.dashboard import (
    CALCULATOR_VERSION,
    _calculate,
    _hash,
    _json,
    _source_complete,
    _source_data,
)
from mp_verify.dashboard import (
    validate_prepared_dashboard as validate_prepared_dashboard,
)

from .relative import _invalid_number, _unique_object


def _atomic(path: Path, content: str | bytes) -> None:
    """Publish a complete stage without exposing a partial JSON or HTML file."""
    if path.is_symlink():
        raise ValueError(f"Refusing symlink output: {path.name}")
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content.encode("utf-8") if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_number,
    )


def prepare_dashboard(
    bundle: DashboardBundle, cache_dir: Path | str | None = None
) -> PreparedDashboard:
    """Validate source ledger and compute record-only results, optionally reusing intact stages.

    The input schema accepts no engine flags/results. A cache hit requires matching source,
    assumptions, calculator version and hashes of both persisted source and calculation stages.
    Cache reuse preserves source review and persisted payloads; geometry is freshly checked
    even for cache hits. It never reruns extraction or document reading. Hashing a source
    never means that somebody reviewed it.
    """
    bundle = DashboardBundle.model_validate(bundle.model_dump(mode="json"))
    source = _source_data(bundle)
    source_hash = _hash(source)
    input_hash = _hash(
        {
            "source_review_hash": source_hash,
            "calculations": [c.model_dump(mode="json") for c in bundle.calculations],
            "calculator_version": CALCULATOR_VERSION,
        }
    )
    presentation_hash = _hash(
        {
            "title": bundle.title,
            "presentation": bundle.presentation.model_dump(mode="json"),
            "scenarios": [s.model_dump(mode="json") for s in bundle.scenarios],
        }
    )
    directory = Path(cache_dir) if cache_dir is not None else None
    calculations = None
    fresh_calculations = tuple(_calculate(bundle, spec) for spec in bundle.calculations)
    if directory is not None:
        if directory.is_symlink():
            raise ValueError("Cache directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True)
        try:
            manifest = DashboardManifest.model_validate(_load(directory / "stage-manifest.json"))
            saved_source = _load(directory / "source-review.json")
            saved = _load(directory / "calculations.json")
            if (
                manifest.calculator_version == CALCULATOR_VERSION
                and manifest.calculation_input_hash == input_hash
                and manifest.source_review_hash == source_hash == _hash(saved_source)
                and manifest.calculation_output_hash == _hash(saved)
            ):
                candidate = tuple(DashboardResult.model_validate(item) for item in saved)
                if candidate == fresh_calculations:
                    calculations = candidate
        except (OSError, ValueError, TypeError):
            pass  # Incomplete/tampered/old stages are recomputed, never trusted.
    reused = calculations is not None
    if calculations is None:
        calculations = fresh_calculations
    manifest = DashboardManifest(
        calculator_version=CALCULATOR_VERSION,
        source_review_hash=source_hash,
        calculation_input_hash=input_hash,
        calculation_output_hash=_hash([r.model_dump(mode="json") for r in calculations]),
        presentation_hash=presentation_hash,
        source_review_complete=_source_complete(bundle),
        cache_reused=reused,
    )
    if directory is not None:
        _atomic(directory / "source-review.json", _json(source))
        _atomic(
            directory / "calculations.json",
            _json([r.model_dump(mode="json") for r in calculations]),
        )
        _atomic(directory / "stage-manifest.json", _json(manifest.model_dump(mode="json")))
    return PreparedDashboard(bundle=bundle, calculations=calculations, manifest=manifest)


def dashboard_file(
    path: Path | str, output_dir: Path | str, *, cache_dir: Path | str | None = None
) -> dict[str, Any]:
    """Render a validated offline bundle and atomically save inspectable stage artifacts."""
    from mp_export.dashboard_html import (  # type: ignore[import-untyped]
        render_dashboard,
        renderer_fingerprint,
    )

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "errors": [],
        "artifacts": {},
    }
    try:
        source_path = Path(path)
        directory = Path(output_dir)
        if directory.is_symlink() or directory.exists():
            raise ValueError("Output directory must not already exist or be a symlink")
        source_path = source_path.resolve(strict=True)
        directory = directory.resolve()
        artifact_names = (
            "source.json",
            "dashboard.html",
            "source-review.json",
            "calculations.json",
            "stage-manifest.json",
            "render-manifest.json",
        )
        if any((directory / name).resolve() == source_path for name in artifact_names):
            raise ValueError("Output must not overwrite the original input bundle")
        source = source_path.read_bytes()
        result["input"] = {"name": source_path.name, "sha256": hashlib.sha256(source).hexdigest()}
        bundle = DashboardBundle.model_validate(
            json.loads(
                source.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_number,
            )
        )
        directory.mkdir(parents=True, exist_ok=False)
        prepared = prepare_dashboard(bundle, cache_dir=cache_dir)
        output = render_dashboard(prepared)
        render_manifest = {
            "renderer_sha256": renderer_fingerprint(),
            "html_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "presentation_hash": prepared.manifest.presentation_hash,
        }
        artifacts: dict[str, str | bytes] = {
            "source.json": source,
            "dashboard.html": output,
            "source-review.json": _json(_source_data(bundle)),
            "calculations.json": _json([r.model_dump(mode="json") for r in prepared.calculations]),
            "stage-manifest.json": _json(prepared.manifest.model_dump(mode="json")),
            "render-manifest.json": _json(render_manifest),
        }
        for name, content in artifacts.items():
            if (directory / name).resolve() == Path(path).resolve():
                raise ValueError("Output must not overwrite the original input bundle")
            _atomic(directory / name, content)
            result["artifacts"][name] = str(directory / name)
        result.update(
            source_review_complete=prepared.manifest.source_review_complete,
            cache_reused=prepared.manifest.cache_reused,
            engine_verified=all(r.engine_verified for r in prepared.calculations),
            verified_export_eligible=False,
            manifest=prepared.manifest.model_dump(mode="json"),
            render_manifest=render_manifest,
        )
    except (ValueError, TypeError, OSError, ArithmeticError) as exc:
        result["status"] = "error"
        result["errors"].append({"code": "invalid_dashboard", "message": str(exc)})
    return result
