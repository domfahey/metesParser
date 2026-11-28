"""Command-line interface for metesparser."""

from __future__ import annotations

import math
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import structlog.contextvars
from mp_export import write_report
from mp_ocr import (
    VALID_ESCALATION_POLICIES,
    EscalationPolicy,
    validate_escalation_policy,
    validate_render_dpi,
)

from .logging_config import configure_logging, get_log_format

if TYPE_CHECKING:
    from mp_models import AuditContext as PkgAuditContext

logger = structlog.get_logger(__name__)

RUNS_DIR = Path("output/runs")

_PROVIDER_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _validate_escalation_args(
    escalate_policy: str,
    escalate_provider: str | None,
    escalate_dpi: int | None,
) -> tuple[EscalationPolicy, str | None, int]:
    """Validate and normalize CLI escalation flags."""
    validated_policy = validate_escalation_policy(escalate_policy)
    validated_dpi = (
        validate_render_dpi(escalate_dpi, name="--escalate-dpi")
        if escalate_dpi is not None
        else 300
    )
    normalized_provider: str | None = None
    if escalate_provider is not None:
        normalized_provider = escalate_provider.strip().lower()
        if normalized_provider not in _PROVIDER_API_KEY_ENV:
            raise ValueError(
                f"Invalid --escalate-provider {escalate_provider!r}; "
                f"expected one of: {', '.join(_PROVIDER_API_KEY_ENV)}"
            )
    if validated_policy == "never" and (escalate_provider is not None or escalate_dpi is not None):
        raise ValueError(
            "--escalate-provider and --escalate-dpi require --escalate-policy other than 'never'"
        )
    return validated_policy, normalized_provider, validated_dpi


def _write_unverified_audit(
    audit_ctx: PkgAuditContext,
    output_csv: str,
    command_logger: structlog.stdlib.BoundLogger,
) -> None:
    """Write unverified audit sidecars at ``<stem>.audit.json`` and ``<stem>.audit.html``."""
    output_file = Path(output_csv)
    base = output_file.with_stem(output_file.stem.removesuffix("_verified") or "unverified")
    audit_json_path = base.with_suffix(".audit.json")
    audit_json_path.parent.mkdir(parents=True, exist_ok=True)
    audit_json_path.write_text(audit_ctx.model_dump_json(indent=2), encoding="utf-8")
    command_logger.info("Audit trail written", path=str(audit_json_path))

    audit_html_path = base.with_suffix(".audit.html")
    write_report(audit_ctx, audit_html_path)
    command_logger.info("Audit HTML report written", path=str(audit_html_path))


def _unwrap_llm_model(processor: object) -> str:
    """Resolve the underlying model identifier, preferring public model_name properties."""
    model_name = getattr(processor, "model_name", None)
    if isinstance(model_name, str) and model_name:
        return model_name
    client: Any = getattr(processor, "client", None)
    seen: set[int] = set()
    while client is not None and id(client) not in seen:
        seen.add(id(client))
        for attr in ("model_name", "model"):
            model = getattr(client, attr, None)
            if isinstance(model, str) and model:
                return model
        client = getattr(client, "_client", None)
    return "unknown"


def aggregate_tract_closure(tract_results: list[tuple[Any, Any]]) -> Any:
    """Summarize per-tract ClosureResult objects into a single RunResults-compatible ClosureResult."""
    from mp_models import is_boundary_tract, tract_kind

    from .models import CheckResult, ClosureResult

    if not tract_results:
        return ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=0.0,
            area_acres=0.0,
            perimeter_ft=0.0,
            misclosure_available=False,
            area_available=False,
            perimeter_available=False,
            closure_passed=False,
            angle_check_passed=False,
            curve_consistency_passed=False,
            confidence_score=0.0,
            warnings=["No tracts verified"],
        )

    boundary_pairs = [(t, r) for t, r in tract_results if is_boundary_tract(t.tract_type)]
    exception_pairs = [(t, r) for t, r in tract_results if tract_kind(t.tract_type) == "exception"]
    boundary = [r for _, r in boundary_pairs]
    exceptions = [r for _, r in exception_pairs]
    selected = boundary or [r for _, r in tract_results]
    evaluated = [*boundary, *exceptions] if boundary else selected

    all_warnings = [w for _, r in tract_results for w in r.warnings]
    if not boundary:
        all_warnings.append("No boundary tracts (main or addition) present")
    else:
        for tract, res in exception_pairs:
            if not res.closure_passed:
                all_warnings.append(f"{tract.label}: exception tract closure failed")

    propagated_checks = [
        CheckResult(
            name=check.name,
            status=check.status,
            reason=check.reason,
            detail=f"[{tract.label}] {check.detail}",
            inputs=dict(check.inputs),
        )
        for tract, res in tract_results
        for check in getattr(res, "checks", ())
        if check.status in ("failed", "blocked")
    ]

    misclosure_avail = all(r.misclosure_available for r in evaluated)
    area_avail = bool(boundary) and not exceptions and all(r.area_available for r in boundary)
    perimeter_avail = all(r.perimeter_available for r in selected)
    closure_passed = bool(boundary) and all(r.closure_passed for r in evaluated)
    confidences = [r.confidence_score for r in evaluated if r.confidence_score is not None]
    return ClosureResult(
        misclosure_x_ft=(
            evaluated[0].misclosure_x_ft if misclosure_avail and len(evaluated) == 1 else 0.0
        ),
        misclosure_y_ft=(
            evaluated[0].misclosure_y_ft if misclosure_avail and len(evaluated) == 1 else 0.0
        ),
        misclosure_ft=(
            max((r.misclosure_ft for r in evaluated), default=0.0) if misclosure_avail else 0.0
        ),
        area_sq_ft=sum(r.area_sq_ft for r in boundary) if area_avail else 0.0,
        area_acres=sum(r.area_acres for r in boundary) if area_avail else 0.0,
        perimeter_ft=sum(r.perimeter_ft for r in selected) if perimeter_avail else 0.0,
        misclosure_available=misclosure_avail,
        area_available=area_avail,
        perimeter_available=perimeter_avail,
        closure_passed=closure_passed,
        angle_check_passed=all(r.angle_check_passed for r in evaluated),
        curve_consistency_passed=all(r.curve_consistency_passed for r in evaluated),
        confidence_score=min(confidences) if confidences else 0.0,
        warnings=all_warnings,
        checks=propagated_checks,
    )


def _emit_closure_summary(summary: str, command_logger: structlog.stdlib.BoundLogger) -> None:
    command_logger.info("Closure summary", summary=summary)
    if get_log_format() != "json":
        print()
        print(summary)
        print()


def extract_command(
    pdf_path: str,
    output: str | None = None,
    llm_provider: str | None = None,
    *,
    no_cache: bool = False,
    audit: bool = False,
    escalate_policy: EscalationPolicy = "never",
    escalate_provider: str | None = None,
    escalate_dpi: int | None = None,
) -> None:
    """Extract legal description from PDF and save to CSV.

    Args:
        pdf_path: Path to input PDF file
        output: Output CSV path (default: derived from input filename)
        llm_provider: Optional LLM provider override
        no_cache: Disable LLM response caching
        audit: Record full audit trail and write .audit.json/.audit.html sidecars
        escalate_policy: Blind high-DPI OCR escalation policy
        escalate_provider: Optional LLM provider override for escalation pass
        escalate_dpi: Optional render DPI for escalated OCR images (1-600)
    """
    from mp_models import (
        is_boundary_tract,
        mark_roles_review,
        roles_need_review,
        roles_review_detail,
    )

    from .closure_checker import ClosureChecker
    from .csv_builder import CSVBuilder
    from .package_bridge import (
        monolith_audit_context,
        monolith_legal_description,
        monolith_result,
    )
    from .pipeline import Pipeline

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.error("PDF file not found", path=pdf_path)
        sys.exit(1)

    if not output:
        output = str(pdf_file.with_suffix(".csv"))

    try:
        validated_policy, normalized_esc_provider, validated_dpi = _validate_escalation_args(
            escalate_policy, escalate_provider, escalate_dpi
        )
    except ValueError as exc:
        logger.error("Invalid escalation arguments", error=str(exc))
        sys.exit(1)

    if normalized_esc_provider is not None:
        required_env = _PROVIDER_API_KEY_ENV[normalized_esc_provider]
        if not (os.getenv(required_env) or "").strip():
            logger.error(
                "Missing API key for escalation provider",
                escalate_provider=normalized_esc_provider,
                required_env=required_env,
            )
            sys.exit(1)

    run_id = str(uuid.uuid4())
    ctx = {"command": "extract", "input_pdf": pdf_path, "output_csv": output, "run_id": run_id}
    structlog.contextvars.bind_contextvars(**ctx)
    command_logger = logger.bind(**ctx)
    command_logger.info("Processing deed PDF")

    try:
        effective_provider = (
            llm_provider or (os.getenv("METESPARSER_LLM_PROVIDER") or "").strip() or "openai"
        )
        pipe = Pipeline(
            provider=effective_provider,
            cache=not no_cache,
            audit=audit,
            escalation_policy=validated_policy,
            escalation_provider=normalized_esc_provider,
            escalation_dpi=validated_dpi,
        )
        detailed = pipe.run_detailed(pdf_file)

        esc_report = detailed.escalation_report
        if esc_report is not None and esc_report.triggered:
            command_logger.warning(
                "OCR escalation triggered",
                policy=esc_report.policy,
                selected=esc_report.selected,
                selection_reason=esc_report.selection_reason,
                agrees=esc_report.agrees,
                disagreements=len(esc_report.disagreements),
                legal_pages=list(esc_report.legal_pages),
                primary_model=esc_report.primary_model,
                escalation_model=esc_report.escalation_model,
            )

        legal_desc = monolith_legal_description(detailed.legal_description)
        monolith_audit_ctx = (
            monolith_audit_context(detailed.audit_context)
            if detailed.audit_context is not None
            else None
        )

        # Guessed description roles (several descriptions, a role inferred from
        # wording) are never verified or exported, whatever the flat geometry: the
        # calls carry the role-review mark, so the unverified CSV fails `verify` too.
        role_review = roles_need_review(legal_desc.tracts, legal_desc.calls)
        if role_review:
            command_logger.warning(roles_review_detail(role_review))
            legal_desc = legal_desc.model_copy(
                update={
                    "calls": mark_roles_review(legal_desc.calls),
                    "tracts": [
                        t.model_copy(update={"calls": mark_roles_review(t.calls)})
                        for t in legal_desc.tracts
                    ],
                }
            )

        calls_for_verify = legal_desc.all_calls if legal_desc.tracts else legal_desc.calls

        if isinstance(detailed.closure, tuple):
            closure_list = [monolith_result(r) for r in detailed.closure]
            tract_results = list(zip(legal_desc.tracts, closure_list, strict=True))
            summary = "\n\n".join(
                f"--- {tract.label} ---\n"
                + ClosureChecker.get_closure_summary(tract_res, calls=tract.calls)
                for tract, tract_res in tract_results
            )
            _emit_closure_summary(summary, command_logger)
            any_exportable = not role_review and any(
                is_boundary_tract(tract.tract_type) and tract_res.is_fully_verified()
                for tract, tract_res in tract_results
            )
            if any_exportable:
                command_logger.info("Exporting verified CSV")
                if monolith_audit_ctx is not None:
                    CSVBuilder.export_verified_csv(
                        calls_for_verify,
                        closure_list[0],
                        output,
                        legal_desc,
                        tract_results=tract_results,
                        audit_context=monolith_audit_ctx,
                    )
                else:
                    CSVBuilder.export_verified_csv(
                        calls_for_verify,
                        closure_list[0],
                        output,
                        legal_desc,
                        tract_results=tract_results,
                    )
            else:
                command_logger.warning(
                    "Verification did not pass completely; exporting unverified CSV"
                )
                CSVBuilder.legal_description_to_csv(legal_desc, output)
                command_logger.info("Exported unverified CSV")
                if detailed.audit_context is not None:
                    _write_unverified_audit(detailed.audit_context, output, command_logger)
            manifest_closure = aggregate_tract_closure(tract_results)
        else:
            closure_result = monolith_result(detailed.closure)
            summary = ClosureChecker.get_closure_summary(closure_result, calls=calls_for_verify)
            _emit_closure_summary(summary, command_logger)

            if closure_result.is_fully_verified() and not role_review:
                command_logger.info("Exporting verified CSV")
                if monolith_audit_ctx is not None:
                    CSVBuilder.export_verified_csv(
                        legal_desc.calls,
                        closure_result,
                        output,
                        legal_desc,
                        audit_context=monolith_audit_ctx,
                    )
                else:
                    CSVBuilder.export_verified_csv(
                        legal_desc.calls, closure_result, output, legal_desc
                    )
            else:
                command_logger.warning(
                    "Verification did not pass completely; exporting unverified CSV"
                )
                CSVBuilder.legal_description_to_csv(legal_desc, output)
                command_logger.info("Exported unverified CSV")
                if detailed.audit_context is not None:
                    _write_unverified_audit(detailed.audit_context, output, command_logger)
            manifest_closure = closure_result

        # Write run manifest (never fails the main extract flow)
        if detailed.prompts_dir is not None:
            try:
                import metesparser

                from .run_registry import (
                    RunManifest,
                    RunResults,
                    get_prompt_versions,
                    write_run_manifest,
                )

                prompt_versions = get_prompt_versions(detailed.prompts_dir)
                manifest = RunManifest(
                    run_id=run_id,
                    timestamp_utc=datetime.now(UTC),
                    source_pdf=pdf_file.name,
                    llm_provider=detailed.provider or effective_provider,
                    llm_model=detailed.primary_model or "unknown",
                    cache_enabled=not no_cache,
                    prompt_versions=prompt_versions,
                    results=RunResults.from_closure(manifest_closure, len(calls_for_verify)),
                    parser_version=metesparser.__version__,
                )
                write_run_manifest(manifest, RUNS_DIR)
            except Exception:
                command_logger.warning("Failed to write run manifest", exc_info=True)

    except Exception:
        command_logger.exception("Failed to process PDF")
        sys.exit(1)
    finally:
        structlog.contextvars.clear_contextvars()


def verify_command(csv_path: str, stated_area: float | None = None) -> None:
    """Verify a CSV file of calls.

    Args:
        csv_path: Path to CSV file
        stated_area: Optional stated area in sq ft for comparison
    """
    from .closure_checker import ClosureChecker
    from .csv_builder import CSVBuilder

    csv_file = Path(csv_path)
    if not csv_file.exists():
        logger.error("CSV file not found", path=csv_path)
        sys.exit(1)

    if stated_area is not None and (
        isinstance(stated_area, bool) or not math.isfinite(stated_area) or stated_area <= 0
    ):
        logger.error("Stated area must be finite and positive", stated_area=stated_area)
        sys.exit(1)

    command_logger = logger.bind(command="verify", input_csv=csv_path)
    command_logger.info("Verifying calls from CSV")

    try:
        calls = CSVBuilder.csv_to_calls(csv_path)
        command_logger.info("Loaded calls", count=len(calls))

        closure_result = ClosureChecker.verify_closure(
            calls,
            stated_area_sq_ft=stated_area or 0.0,
        )

        summary = ClosureChecker.get_closure_summary(closure_result, calls=calls)
        _emit_closure_summary(summary, command_logger)

        if closure_result.is_fully_verified():
            command_logger.info("All verification checks passed")
        else:
            command_logger.warning("Some verification checks did not pass")
            sys.exit(1)

    except Exception:
        command_logger.exception("Failed to verify CSV")
        sys.exit(1)


def export_command(csv_path: str, format: str = "geojson", output: str | None = None) -> None:
    """Export calls to GeoJSON or KML (currently not implemented).

    Args:
        csv_path: Path to CSV file
        format: Output format (geojson or kml)
        output: Output file path (default: derived from input)
    """
    logger.error("Export functionality not yet implemented")
    sys.exit(1)


def compare_runs_command(runs_dir: str | None = None, pdf_filter: str | None = None) -> None:
    """Compare extraction runs across prompt versions."""
    from .run_registry import format_comparison_table, load_run_manifests

    resolved_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    command_logger = logger.bind(command="compare-runs", runs_dir=str(resolved_dir))
    command_logger.info("Comparing runs")

    try:
        manifests = load_run_manifests(resolved_dir)
        command_logger.info("Loaded run manifests", count=len(manifests))
        output = format_comparison_table(manifests, pdf_filter=pdf_filter)
        print(output)
    except Exception:
        command_logger.exception("Failed to compare runs")
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Metes & Bounds Deed Parser - Extract and verify legal descriptions"
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("METESPARSER_LOG_LEVEL", "INFO"),
        help="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    parser.add_argument(
        "--log-format",
        choices=["console", "json"],
        default=os.getenv("METESPARSER_LOG_FORMAT", "console"),
        help="Log output format",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging with callsite metadata",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    extract_parser = subparsers.add_parser("extract", help="Extract legal description from PDF")
    extract_parser.add_argument("pdf", help="Path to PDF file")
    extract_parser.add_argument(
        "-o", "--output", help="Output CSV file path (default: derived from input)"
    )
    extract_parser.add_argument(
        "--llm-provider",
        choices=["openai", "gemini", "openrouter"],
        help="LLM provider to use (overrides METESPARSER_LLM_PROVIDER env var)",
    )
    extract_parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Disable LLM response caching (re-query the LLM for every call)",
    )
    extract_parser.add_argument(
        "--audit",
        action="store_true",
        default=False,
        help="Record full audit trail and write .audit.json and .audit.html sidecars",
    )
    extract_parser.add_argument(
        "--escalate-policy",
        choices=list(VALID_ESCALATION_POLICIES),
        default="never",
        help="Blind high-DPI OCR escalation policy (default: never)",
    )
    extract_parser.add_argument(
        "--escalate-provider",
        choices=list(_PROVIDER_API_KEY_ENV),
        default=None,
        help="LLM provider override for escalated OCR pass (requires --escalate-policy != never)",
    )
    extract_parser.add_argument(
        "--escalate-dpi",
        type=int,
        default=None,
        help="Render DPI for escalated OCR images (1-600; default 300 when escalating)",
    )

    verify_parser = subparsers.add_parser("verify", help="Verify a CSV file of calls")
    verify_parser.add_argument("csv", help="Path to CSV file")
    verify_parser.add_argument(
        "-a", "--area", type=float, help="Stated area in square feet (for comparison)"
    )

    compare_parser = subparsers.add_parser("compare-runs", help="Compare extraction runs")
    compare_parser.add_argument(
        "--runs-dir", help="Directory containing run manifests (default: output/runs/)"
    )
    compare_parser.add_argument("--pdf", help="Filter by PDF name (substring match)")

    args = parser.parse_args()

    try:
        configured_level = "DEBUG" if args.debug else args.log_level
        configure_logging(
            level=configured_level,
            log_format=args.log_format,
            debug=args.debug,
            take_over_root=True,
        )
        logger.debug(
            "Logging configured",
            level=configured_level,
            format=args.log_format,
            debug=args.debug,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "extract":
        try:
            validated_policy, normalized_esc_provider, _ = _validate_escalation_args(
                args.escalate_policy, args.escalate_provider, args.escalate_dpi
            )
        except ValueError as exc:
            parser.error(str(exc))

        extra_kwargs: dict[str, Any] = {}
        if args.audit:
            extra_kwargs["audit"] = True
        if validated_policy != "never":
            extra_kwargs["escalate_policy"] = validated_policy
        if normalized_esc_provider is not None:
            extra_kwargs["escalate_provider"] = normalized_esc_provider
        if args.escalate_dpi is not None:
            extra_kwargs["escalate_dpi"] = args.escalate_dpi

        if extra_kwargs:
            extract_command(
                args.pdf,
                args.output,
                args.llm_provider,
                no_cache=args.no_cache,
                **extra_kwargs,
            )
        else:
            extract_command(args.pdf, args.output, args.llm_provider, no_cache=args.no_cache)
    elif args.command == "verify":
        if args.area is not None and (not math.isfinite(args.area) or args.area <= 0):
            parser.error("--area must be a finite positive number")
        verify_command(args.csv, args.area)
    elif args.command == "compare-runs":
        compare_runs_command(args.runs_dir, args.pdf)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
