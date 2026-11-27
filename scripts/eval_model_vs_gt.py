#!/usr/bin/env python3
"""Evaluate a single LLM model across all sample deeds and compare against ground truths.

Runs the production 3-stage OCR pipeline (`extract_text_from_pdf` ->
`extract_legal_description` -> `normalize_legal_description`) followed by
deterministic `mp_parse.extract_calls`, then compares extracted courses
verbatim against each deed's `sample_deeds/*.ground_truth.json`.

By default, fallback models are disabled (`fallback_model=None`) so the score
reflects the single model under test without silent failover.

Examples:
    # Offline self-check of the scoring harness against all ground truths (0 API calls)
    uv run python scripts/eval_model_vs_gt.py --self-check

    # Evaluate default OpenRouter model (anthropic/claude-haiku-5.5) across all deeds
    uv run python scripts/eval_model_vs_gt.py --provider openrouter --model anthropic/claude-haiku-5.5

    # Evaluate Gemini 3.6 Flash on a filtered subset
    uv run python scripts/eval_model_vs_gt.py --provider gemini --model gemini-3.6-flash --filter "219 Berlin"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mp_ocr import (
    MAX_RENDER_DPI,
    VALID_ESCALATION_POLICIES,
    BaseLLMClient,
    EscalationPolicy,
    GeminiClient,
    OpenAIClient,
    OpenRouterClient,
    PDFProcessor,
    compare_call_readings,
    count_pdf_pages,
    select_escalation_outcome,
    should_escalate_closure,
    validate_escalation_policy,
    validate_render_dpi,
)
from mp_parse import extract_calls
from mp_verify import verify_closure

DEFAULT_SAMPLE_DIR = Path("sample_deeds")
DEFAULT_OUTPUT_ROOT = Path("output/model_eval")
_MARKDOWN_RE = re.compile(r"\*\*|```|^#{1,6}\s", re.MULTILINE)
_DEFAULT_MODELS: dict[str, str] = {
    "openrouter": "anthropic/claude-haiku-5.5",
    "gemini": "gemini-3.6-flash",
    "openai": "gpt-5.2",
}


def sanitize_slug(value: str) -> str:
    """Convert a provider/model identifier into a filesystem-safe directory slug."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._-") or "model"


def extract_all_calls(text: str) -> tuple[list[Any], list[Any], list[Any]]:
    """Parse calls from deed text, flattening all tracts in order when multi-tract."""
    skips: list[Any] = []
    if not text or not text.strip():
        return [], [], skips
    calls, tracts = extract_calls(text, strict=False, skipped_courses=skips)
    if tracts:
        return [c for t in tracts for c in t.calls], tracts, skips
    return list(calls), tracts, skips


def angle_diff_deg(a: float, b: float) -> float:
    """Shortest angular difference in degrees between two azimuths (0-360)."""
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def compare_calls(
    extracted: list[Any],
    expected: list[dict[str, Any]],
    *,
    distance_tol_ft: float = 0.05,
    azimuth_tol_deg: float = 0.05,
) -> dict[str, Any]:
    """Compare extracted calls against ground-truth `expected_calls` verbatim."""
    n_ext = len(extracted)
    n_exp = len(expected)
    mismatches: list[dict[str, Any]] = []

    if n_exp == 0:
        if n_ext == 0:
            return {"exact": True, "n_exp": 0, "n_ext": 0, "matched": 0, "mismatches": []}
        return {
            "exact": False,
            "n_exp": 0,
            "n_ext": n_ext,
            "matched": 0,
            "mismatches": [{"type": "spurious_calls_on_zero_call_deed", "n_ext": n_ext}],
        }

    matched = 0
    for idx in range(min(n_ext, n_exp)):
        ext = extracted[idx]
        exp = expected[idx]
        course_num = exp.get("course", idx + 1)
        issues: list[str] = []

        exp_dist = exp.get("distance_ft")
        ext_dist = ext.distance_ft
        if exp_dist is not None:
            if ext_dist is None or abs(ext_dist - exp_dist) > distance_tol_ft:
                issues.append(f"dist: got={ext_dist} exp={exp_dist}")

        exp_az = exp.get("bearing_azimuth_deg_from_north")
        ext_az = ext.bearing_azimuth_deg_from_north
        if exp_az is not None:
            if ext_az is None or angle_diff_deg(ext_az, exp_az) > azimuth_tol_deg:
                issues.append(
                    f"az: got={None if ext_az is None else round(ext_az, 4)} exp={round(exp_az, 4)}"
                )
        elif ext_az is not None:
            issues.append(f"az: got={round(ext_az, 4)} exp=None (cardinal-only)")

        exp_curve = exp.get("curve_dir")
        ext_curve = getattr(ext.curve_dir, "value", ext.curve_dir)
        if exp_curve != ext_curve:
            issues.append(f"curve_dir: got={ext_curve} exp={exp_curve}")
        if exp.get("radius_ft") is not None:
            if ext.radius_ft is None or abs(ext.radius_ft - exp["radius_ft"]) > distance_tol_ft:
                issues.append(f"radius: got={ext.radius_ft} exp={exp['radius_ft']}")
        if exp.get("arc_length_ft") is not None:
            if (
                ext.arc_length_ft is None
                or abs(ext.arc_length_ft - exp["arc_length_ft"]) > distance_tol_ft
            ):
                issues.append(f"arc: got={ext.arc_length_ft} exp={exp['arc_length_ft']}")

        if not issues:
            matched += 1
        else:
            mismatches.append(
                {
                    "course": course_num,
                    "issues": issues,
                    "got_dir": ext.direction_text,
                    "exp_dir": exp.get("direction_text"),
                    "got_dist": ext_dist,
                    "exp_dist": exp_dist,
                }
            )

    if n_ext != n_exp:
        mismatches.insert(0, {"type": "call_count", "got": n_ext, "exp": n_exp})

    return {
        "exact": (n_ext == n_exp and matched == n_exp),
        "n_exp": n_exp,
        "n_ext": n_ext,
        "matched": matched,
        "mismatches": mismatches,
    }


def classify_result(rec: dict[str, Any]) -> str:
    """Classify a deed evaluation result into a clear failure bucket or 'exact'."""
    if rec.get("status") != "ok":
        return "api_error"
    norm = rec["norm"]
    if norm["exact"]:
        return "exact"
    if rec.get("legal", {}).get("exact"):
        return "normalization_regression"
    if norm["n_exp"] == 0 and norm["n_ext"] > 0:
        return "zero_call_false_positive"
    if norm["n_ext"] != norm["n_exp"]:
        return "call_count_mismatch"
    return "value_mismatch"


def _parse_optional_setting(raw: str | None, *, disable_tokens: set[str]) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() in disable_tokens:
        return None
    return cleaned


def build_client(
    *,
    provider: str,
    model: str | None = None,
    fallback_model: str | None = None,
    reasoning_effort: str | None = "low",
    pdf_engine: str | None = None,
    thinking_level: str | None = "LOW",
    timeout_s: float = 180.0,
    max_retries: int = 3,
    retry_backoff_s: float = 1.5,
) -> tuple[BaseLLMClient, str]:
    """Build a single-model LLM client for the requested provider (fallback disabled by default)."""
    prov = provider.strip().lower()
    resolved_model = (model or "").strip() or _DEFAULT_MODELS.get(prov, "")
    resolved_fallback = _parse_optional_setting(
        fallback_model, disable_tokens={"none", "off", "disabled"}
    )

    if prov == "openrouter":
        effort = _parse_optional_setting(reasoning_effort, disable_tokens={"off", "disabled"})
        engine = _parse_optional_setting(pdf_engine, disable_tokens={"none", "off", "disabled"})
        client: BaseLLMClient = OpenRouterClient(
            model=resolved_model,
            fallback_model=resolved_fallback,
            reasoning_effort=effort,
            pdf_engine=engine,
            timeout_s=timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
        )
        return client, resolved_model

    if prov == "gemini":
        level = _parse_optional_setting(thinking_level, disable_tokens={"none", "off", "disabled"})
        client = GeminiClient(
            model=resolved_model,
            fallback_model=resolved_fallback,
            thinking_level=level,
            timeout_ms=int(timeout_s * 1000),
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
        )
        return client, resolved_model

    if prov == "openai":
        client = OpenAIClient(model=resolved_model)
        return client, resolved_model

    raise ValueError(f"Unsupported provider '{provider}'. Choose from: openrouter, gemini, openai.")


def _instrument_usage(client: BaseLLMClient, usage_totals: dict[str, Any]) -> None:
    """Attach lightweight token/cost accounting without logging credentials."""
    if isinstance(client, OpenRouterClient):
        orig_create = client._client.chat.completions.create

        def tracked_openrouter(*args: Any, **kwargs: Any) -> Any:
            resp = orig_create(*args, **kwargs)
            usage_totals["api_calls"] += 1
            usage = getattr(resp, "usage", None)
            if usage is not None:
                usage_totals["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
                usage_totals["completion_tokens"] += int(
                    getattr(usage, "completion_tokens", 0) or 0
                )
                cost = getattr(usage, "cost", None)
                if isinstance(cost, (int, float)):
                    usage_totals["cost_usd"] += float(cost)
            return resp

        client._client.chat.completions.create = tracked_openrouter
    elif isinstance(client, OpenAIClient):
        orig_create = client._client.responses.create

        def tracked_openai(*args: Any, **kwargs: Any) -> Any:
            resp = orig_create(*args, **kwargs)
            usage_totals["api_calls"] += 1
            usage = getattr(resp, "usage", None)
            if usage is not None:
                usage_totals["prompt_tokens"] += int(getattr(usage, "input_tokens", 0) or 0)
                usage_totals["completion_tokens"] += int(getattr(usage, "output_tokens", 0) or 0)
            return resp

        client._client.responses.create = tracked_openai
    elif isinstance(client, GeminiClient):
        orig_gen = client._client.models.generate_content

        def tracked_gemini(*args: Any, **kwargs: Any) -> Any:
            resp = orig_gen(*args, **kwargs)
            usage_totals["api_calls"] += 1
            meta = getattr(resp, "usage_metadata", None)
            if meta is not None:
                usage_totals["prompt_tokens"] += int(getattr(meta, "prompt_token_count", 0) or 0)
                usage_totals["completion_tokens"] += int(
                    getattr(meta, "candidates_token_count", 0) or 0
                )
            return resp

        client._client.models.generate_content = tracked_gemini


def discover_deeds(
    sample_dir: Path,
    *,
    name_filter: str | list[str] | None = None,
    limit: int | None = None,
) -> list[Path]:
    """Return sorted ground-truth paths matching optional substring filter(s) and limit."""
    gts = sorted(sample_dir.glob("*.ground_truth.json"))
    if name_filter:
        filters = [name_filter] if isinstance(name_filter, str) else list(name_filter)
        needles = [f.lower() for f in filters if f and f.strip()]
        if needles:
            gts = [p for p in gts if any(n in p.name.lower() for n in needles)]
    if limit is not None and limit > 0:
        gts = gts[:limit]
    return gts


def run_self_check(sample_dir: Path) -> int:
    """Verify the scoring harness achieves 100% exact match on ground-truth texts."""
    gts = discover_deeds(sample_dir)
    fails: list[tuple[str, dict[str, Any], dict[str, Any], int]] = []
    total_courses = 0
    matched_courses = 0

    for gt_path in gts:
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        stem = gt_path.name.removesuffix(".ground_truth.json")
        exp = gt.get("expected_calls") or []
        total_courses += len(exp)
        legal = gt.get("expected_legal_description") or ""
        norm = gt.get("expected_normalized_text") or ""
        text = norm if norm else legal
        calls, _tracts, skips = extract_all_calls(text)
        cmp = compare_calls(calls, exp)
        matched_courses += cmp["matched"]
        if not cmp["exact"]:
            calls_leg, _, _ = extract_all_calls(legal)
            cmp_leg = compare_calls(calls_leg, exp)
            fails.append((stem, cmp, cmp_leg, len(skips)))

    print(
        f"Self-check on {len(gts)} GTs: {len(gts) - len(fails)}/{len(gts)} exact deeds, "
        f"{matched_courses}/{total_courses} courses"
    )
    for stem, cmp, cmp_leg, nskips in fails:
        print(f"  DIFF {stem}: norm={cmp} | legal_exact={cmp_leg['exact']} skips={nskips}")
    return 0 if not fails else 1


def _default_output_slug(
    *,
    provider: str,
    model: str,
    escalation_policy: EscalationPolicy = "never",
    escalation_model: str | None = None,
    escalation_dpi: int = 300,
) -> str:
    """Build a collision-free output slug reflecting primary and escalation config."""
    base = f"{provider}_{sanitize_slug(model)}"
    if escalation_policy == "never":
        return base
    esc_slug = sanitize_slug(escalation_model or model)
    return f"{base}__esc_{escalation_policy}_{esc_slug}_dpi{escalation_dpi}"


def _close_client(client: Any) -> None:
    """Close an SDK client's underlying HTTP pool if it exposes ``close()``."""
    inner = getattr(client, "_client", None)
    close_fn = getattr(inner, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            pass


def _checkpoint_matches_escalation(
    cached: dict[str, Any],
    *,
    escalation_policy: EscalationPolicy,
    escalation_model: str | None,
    escalation_dpi: int,
    primary_model: str | None = None,
) -> bool:
    """Return True only when a cached deed checkpoint matches the current model & escalation config."""
    if primary_model is not None and cached.get("model") != primary_model:
        return False
    cached_esc = cached.get("escalation")
    if not isinstance(cached_esc, dict):
        return escalation_policy == "never"
    if cached_esc.get("policy", "never") != escalation_policy:
        return False
    if escalation_policy == "never":
        return True
    if cached_esc.get("dpi") != escalation_dpi:
        return False
    cached_model = cached_esc.get("requested_model") or cached_esc.get("escalation_model")
    expected_model = escalation_model or primary_model or cached.get("model")
    if expected_model is not None and cached_model != expected_model:
        return False
    return True


def evaluate_deed(
    gt_path: Path,
    *,
    client_factory: Any,
    results_dir: Path,
    cache_dir: Path | None,
    use_cache: bool = True,
    force: bool = False,
    escalation_policy: EscalationPolicy = "never",
    escalation_client_factory: Any | None = None,
    escalation_model: str | None = None,
    escalation_dpi: int = 300,
    expected_primary_model: str | None = None,
) -> dict[str, Any]:
    """Run one deed PDF through the 3-stage OCR pipeline + parser and compare to ground truth."""
    validated_policy = validate_escalation_policy(escalation_policy)
    validated_dpi = validate_render_dpi(escalation_dpi, name="escalation_dpi")

    stem = gt_path.name.removesuffix(".ground_truth.json")
    pdf_path = gt_path.with_name(f"{stem}.pdf")
    result_file = results_dir / f"{stem}.json"

    if not force and result_file.exists():
        cached = json.loads(result_file.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and cached.get("status") == "ok"
            and _checkpoint_matches_escalation(
                cached,
                escalation_policy=validated_policy,
                escalation_model=escalation_model,
                escalation_dpi=validated_dpi,
                primary_model=expected_primary_model,
            )
        ):
            return cached

    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    exp_calls = gt.get("expected_calls") or []

    client, resolved_model = client_factory()
    esc_client: Any | None = None
    usage_totals: dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
        "api_calls": 0,
    }
    _instrument_usage(client, usage_totals)

    processor = PDFProcessor(client=client, cache=use_cache, cache_dir=cache_dir)
    requested_esc_model = (
        (escalation_model or resolved_model) if validated_policy != "never" else None
    )

    t0 = time.monotonic()
    try:
        # Stage 1 + Stage 2 (extract_legal_description calls extract_text_from_pdf internally)
        legal_text = processor.extract_legal_description(str(pdf_path), audit=True)
        # Retrieve Stage 1 raw text via public audit helper without repeating Stage 1
        stage_records = processor.pop_audit_stage_records()
        raw_text = stage_records[0].response if stage_records else ""
        # Stage 3
        norm_text = processor.normalize_legal_description(legal_text, audit=True)
        processor.pop_audit_stage_records()

        calls_norm, tracts_norm, skips_norm = extract_all_calls(norm_text)
        calls_legal, _tracts_legal, _skips_legal = extract_all_calls(legal_text)

        escalation_meta: dict[str, Any] = {
            "policy": validated_policy,
            "triggered": False,
        }
        if validated_policy != "never":
            escalation_meta["requested_model"] = requested_esc_model
            escalation_meta["dpi"] = validated_dpi

        if validated_policy != "never" and (calls_norm or skips_norm):
            pri_results = (
                verify_closure(calls_norm, tracts=tracts_norm, skipped_courses=skips_norm)
                if tracts_norm
                else [verify_closure(calls_norm, skipped_courses=skips_norm)]
            )
            should_esc, trigger_reasons = should_escalate_closure(
                pri_results, policy=validated_policy, has_calls=bool(calls_norm or skips_norm)
            )
            if should_esc:
                if escalation_client_factory is not None:
                    esc_client, esc_model = escalation_client_factory()
                    _instrument_usage(esc_client, usage_totals)
                    esc_proc = PDFProcessor(client=esc_client, cache=use_cache, cache_dir=cache_dir)
                else:
                    esc_model = resolved_model
                    esc_proc = processor
                esc_legal, esc_norm, legal_pages = esc_proc.extract_legal_description_from_images(
                    str(pdf_path),
                    dpi=validated_dpi,
                    strip_watermark=True,
                    crop_margins=True,
                    audit=True,
                    locator_processor=processor,
                )
                esc_stages = esc_proc.pop_audit_stage_records()
                esc_calls, esc_tracts, esc_skips = extract_all_calls(esc_norm)
                esc_calls_legal, _, _ = extract_all_calls(esc_legal)

                per_tract_truncated = bool(tracts_norm) and any(
                    pri_t.calls and len(esc_t.calls) < len(pri_t.calls)
                    for pri_t, esc_t in zip(tracts_norm, esc_tracts, strict=False)
                )
                truncated = (
                    (bool(tracts_norm) and len(esc_tracts) < len(tracts_norm))
                    or per_tract_truncated
                    or (bool(calls_norm) and len(esc_calls) < len(calls_norm))
                )
                if truncated:
                    total_pages = count_pdf_pages(str(pdf_path))
                    if len(legal_pages) < total_pages:
                        all_pages = list(range(1, total_pages + 1))
                        esc_legal, esc_norm, legal_pages = (
                            esc_proc.extract_legal_description_from_images(
                                str(pdf_path),
                                pages=all_pages,
                                dpi=validated_dpi,
                                strip_watermark=True,
                                crop_margins=True,
                                audit=True,
                                stage_prefix="escalation_fallback_",
                            )
                        )
                        esc_stages.extend(esc_proc.pop_audit_stage_records())
                        esc_calls, esc_tracts, esc_skips = extract_all_calls(esc_norm)
                        esc_calls_legal, _, _ = extract_all_calls(esc_legal)

                esc_results = (
                    verify_closure(esc_calls, tracts=esc_tracts, skipped_courses=esc_skips)
                    if esc_tracts
                    else (
                        [verify_closure(esc_calls, skipped_courses=esc_skips)] if esc_calls else []
                    )
                )
                disagreements = compare_call_readings(
                    calls_norm,
                    esc_calls,
                    primary_tracts=tracts_norm or None,
                    escalated_tracts=esc_tracts or None,
                    primary_skipped_courses=skips_norm,
                    escalated_skipped_courses=esc_skips,
                )
                selected, selection_reason = select_escalation_outcome(
                    primary_calls=calls_norm,
                    escalated_calls=esc_calls,
                    primary_results=pri_results,
                    escalated_results=esc_results,
                    disagreements=disagreements,
                    primary_tracts=tracts_norm or None,
                    escalated_tracts=esc_tracts or None,
                )
                escalation_meta = {
                    "policy": validated_policy,
                    "requested_model": requested_esc_model or esc_model,
                    "dpi": validated_dpi,
                    "triggered": True,
                    "trigger_reasons": trigger_reasons,
                    "legal_pages": legal_pages,
                    "escalation_model": esc_model,
                    "agrees": not disagreements,
                    "disagreement_count": len(disagreements),
                    "disagreements": [d.format_warning() for d in disagreements],
                    "selected": selected,
                    "selection_reason": selection_reason,
                }
                if selected == "escalated":
                    esc_raw_stages = [
                        s for s in esc_stages if s.stage.endswith("extract_text_from_images")
                    ]
                    if esc_raw_stages:
                        final_stage_name = esc_raw_stages[-1].stage
                        raw_text = "\n\n".join(
                            s.response
                            for s in esc_raw_stages
                            if s.stage == final_stage_name and s.response
                        )
                    legal_text = esc_legal
                    norm_text = esc_norm
                    calls_norm, tracts_norm, skips_norm = esc_calls, esc_tracts, esc_skips
                    calls_legal = esc_calls_legal

        elapsed_s = round(time.monotonic() - t0, 2)

        cmp_norm = compare_calls(calls_norm, exp_calls)
        cmp_legal = compare_calls(calls_legal, exp_calls)

        strict_ok = True
        strict_err = None
        if len(exp_calls) > 0:
            try:
                extract_calls(norm_text, strict=True)
            except Exception as exc:
                strict_ok = False
                strict_err = f"{type(exc).__name__}: {exc}"

        rec: dict[str, Any] = {
            "deed": stem,
            "model": resolved_model,
            "status": "ok",
            "elapsed_s": elapsed_s,
            "usage": usage_totals,
            "n_exp": len(exp_calls),
            "norm": cmp_norm,
            "legal": cmp_legal,
            "n_tracts_norm": len(tracts_norm),
            "n_skips_norm": len(skips_norm),
            "skips_norm": [str(s) for s in skips_norm[:5]],
            "strict_ok": strict_ok,
            "strict_err": strict_err,
            "escalation": escalation_meta,
            "markdown": {
                "raw": bool(_MARKDOWN_RE.search(raw_text)),
                "legal": bool(_MARKDOWN_RE.search(legal_text)),
                "norm": bool(_MARKDOWN_RE.search(norm_text)),
            },
            "raw_len": len(raw_text),
            "legal_text": legal_text,
            "norm_text": norm_text,
        }
        rec["classification"] = classify_result(rec)
    except Exception as exc:
        rec = {
            "deed": stem,
            "model": resolved_model,
            "status": "error",
            "classification": "api_error",
            "elapsed_s": round(time.monotonic() - t0, 2),
            "usage": usage_totals,
            "n_exp": len(exp_calls),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        _close_client(client)
        if esc_client is not None:
            _close_client(esc_client)

    results_dir.mkdir(parents=True, exist_ok=True)
    tmp = result_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(result_file)
    return rec


def summarize_results(
    results: list[dict[str, Any]],
    *,
    provider: str,
    model: str,
    wall_s: float,
) -> dict[str, Any]:
    """Compute aggregate accuracy, failure bucket counts, token/cost totals."""
    ok = [r for r in results if r.get("status") == "ok"]
    errs = [r for r in results if r.get("status") != "ok"]
    exact_norm = [r for r in ok if r["norm"]["exact"]]
    exact_legal = [r for r in ok if r["legal"]["exact"]]
    metes_results = [r for r in results if r.get("n_exp", 0) > 0]
    metes_exact = [r for r in exact_norm if r.get("n_exp", 0) > 0]
    zero_results = [r for r in results if r.get("n_exp", 0) == 0]
    zero_exact = [r for r in exact_norm if r.get("n_exp", 0) == 0]

    buckets: dict[str, int] = {}
    for r in results:
        cls = r.get("classification") or classify_result(r)
        buckets[cls] = buckets.get(cls, 0) + 1

    total_exp = sum(r.get("n_exp", 0) for r in results)
    matched_norm = sum(r["norm"]["matched"] for r in ok)
    matched_legal = sum(r["legal"]["matched"] for r in ok)
    markdown_leaks = sum(1 for r in ok if r.get("markdown", {}).get("norm"))
    escalated_runs = [r for r in ok if r.get("escalation", {}).get("triggered")]
    escalation_agreed = sum(1 for r in escalated_runs if r.get("escalation", {}).get("agrees"))
    escalation_selected = sum(
        1 for r in escalated_runs if r.get("escalation", {}).get("selected") == "escalated"
    )

    return {
        "provider": provider,
        "model": model,
        "wall_s": round(wall_s, 2),
        "total_deeds": len(results),
        "exact_deeds_norm": len(exact_norm),
        "exact_deeds_legal": len(exact_legal),
        "metes_deeds_total": len(metes_results),
        "metes_deeds_exact": len(metes_exact),
        "zero_call_deeds_total": len(zero_results),
        "zero_call_deeds_exact": len(zero_exact),
        "total_courses": total_exp,
        "matched_courses_norm": matched_norm,
        "matched_courses_legal": matched_legal,
        "api_errors": len(errs),
        "markdown_leaks_norm": markdown_leaks,
        "escalation_triggered": len(escalated_runs),
        "escalation_agreed": escalation_agreed,
        "escalation_disagreed": len(escalated_runs) - escalation_agreed,
        "escalation_selected_escalated": escalation_selected,
        "classifications": buckets,
        "prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in results),
        "completion_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in results),
        "cost_usd": round(sum(r.get("usage", {}).get("cost_usd", 0.0) for r in results), 6),
    }


def render_markdown_report(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    """Render a compact Markdown report of accuracy and every mistake."""
    n_deeds = summary["total_deeds"] or 1
    n_courses = summary["total_courses"] or 1
    lines = [
        f"# Model Evaluation vs Ground Truth: `{summary['provider']} / {summary['model']}`",
        "",
        "| Metric | Result |",
        "| --- | --- |",
        f"| Deeds exact (normalized) | {summary['exact_deeds_norm']}/{summary['total_deeds']} ({100 * summary['exact_deeds_norm'] / n_deeds:.1f}%) |",
        f"| Deeds exact (legal stage) | {summary['exact_deeds_legal']}/{summary['total_deeds']} ({100 * summary['exact_deeds_legal'] / n_deeds:.1f}%) |",
        f"| Metes-and-bounds deeds exact | {summary['metes_deeds_exact']}/{summary['metes_deeds_total']} |",
        f"| Zero-call deeds exact | {summary['zero_call_deeds_exact']}/{summary['zero_call_deeds_total']} |",
        f"| Courses exact (normalized) | {summary['matched_courses_norm']}/{summary['total_courses']} ({100 * summary['matched_courses_norm'] / n_courses:.1f}%) |",
        f"| Courses exact (legal stage) | {summary['matched_courses_legal']}/{summary['total_courses']} ({100 * summary['matched_courses_legal'] / n_courses:.1f}%) |",
        f"| API errors | {summary['api_errors']} |",
        f"| Markdown leaks (normalized) | {summary['markdown_leaks_norm']} |",
    ]
    if summary.get("escalation_triggered", 0) > 0:
        lines.append(
            "| Escalations (triggered / agreed / selected) | "
            f"{summary['escalation_triggered']} / {summary['escalation_agreed']} / "
            f"{summary['escalation_selected_escalated']} |"
        )
    lines.extend(
        [
            f"| Tokens (in / out) | {summary['prompt_tokens']:,} / {summary['completion_tokens']:,} |",
            f"| Reported cost | ${summary['cost_usd']:.4f} |",
            f"| Wall time | {summary['wall_s']}s |",
            "",
            "## Breakdown by Classification",
            "",
        ]
    )
    for cls, count in sorted(summary["classifications"].items()):
        lines.append(f"- `{cls}`: {count}")

    misses = [r for r in results if (r.get("classification") or classify_result(r)) != "exact"]
    lines.extend(["", f"## Mistakes ({len(misses)} deeds)", ""])
    if not misses:
        lines.append("None (100% exact across all evaluated deeds).")
    else:
        for r in misses:
            cls = r.get("classification") or classify_result(r)
            if r.get("status") != "ok":
                lines.append(f"- **{r['deed']}** (`{cls}`): `{r.get('error', '')}`")
                continue
            lines.append(
                f"- **{r['deed']}** (`{cls}`): norm `{r['norm']['matched']}/{r['n_exp']}` "
                f"(got {r['norm']['n_ext']}), legal `{r['legal']['matched']}/{r['n_exp']}` "
                f"(got {r['legal']['n_ext']})"
            )
            for m in r["norm"]["mismatches"][:8]:
                lines.append(f"  - `{m}`")
    lines.append("")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate a single LLM model across all sample deeds against ground truths."
    )
    parser.add_argument(
        "--provider",
        choices=["openrouter", "gemini", "openai"],
        default="openrouter",
        help="LLM provider to benchmark (default: openrouter)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID to test (defaults to provider default)",
    )
    parser.add_argument(
        "--fallback-model",
        default=None,
        help="Optional fallback model (default: None so only 1 model is tested)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="low",
        help="OpenRouter reasoning effort (default: low; pass 'off' to omit)",
    )
    parser.add_argument(
        "--pdf-engine",
        default=None,
        help="Optional OpenRouter PDF engine (e.g., mistral-ocr, pdf-text, native)",
    )
    parser.add_argument(
        "--thinking-level",
        default="LOW",
        help="Gemini thinking level (default: LOW; pass 'off' to disable)",
    )
    parser.add_argument(
        "--sample-dir",
        type=Path,
        default=DEFAULT_SAMPLE_DIR,
        help="Directory containing sample PDFs and *.ground_truth.json files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for checkpoints and reports (default: output/model_eval/<slug>)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Disk cache directory (default: <output-dir>/cache)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable LLM disk caching",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Max concurrent deeds to evaluate (default: 8)",
    )
    parser.add_argument(
        "--filter",
        dest="name_filter",
        action="append",
        default=None,
        help="Substring filter on deed filenames (case-insensitive; repeatable)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate only the first N matching deeds",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-evaluate deeds even if a checkpoint already exists in output-dir/results",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=180.0,
        help="Per-request timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Retries per request on transient errors (default: 3)",
    )
    parser.add_argument(
        "--escalate-policy",
        choices=list(VALID_ESCALATION_POLICIES),
        default="never",
        help="Optional blind high-DPI escalation policy (default: never)",
    )
    parser.add_argument(
        "--escalate-model",
        default=None,
        help="Model ID for blind escalation passes (defaults to --model)",
    )
    parser.add_argument(
        "--escalate-dpi",
        type=int,
        default=300,
        help="Render DPI for cropped legal-page escalation images (default: 300)",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Offline self-check: score ground truths against themselves (0 API calls)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.self_check:
        return run_self_check(args.sample_dir)

    load_dotenv(Path.cwd() / ".env")

    resolved_model = (args.model or "").strip() or _DEFAULT_MODELS[args.provider]
    esc_model = (args.escalate_model or "").strip() or resolved_model
    try:
        validate_render_dpi(args.escalate_dpi, name="--escalate-dpi")
    except ValueError:
        print(
            f"ERROR: --escalate-dpi must be between 1 and {MAX_RENDER_DPI}, got {args.escalate_dpi}",
            file=sys.stderr,
        )
        return 2

    slug = _default_output_slug(
        provider=args.provider,
        model=resolved_model,
        escalation_policy=args.escalate_policy,
        escalation_model=esc_model,
        escalation_dpi=args.escalate_dpi,
    )
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / slug)
    results_dir = output_dir / "results"
    cache_dir = None if args.no_cache else (args.cache_dir or (output_dir / "cache"))

    def _make_client(model_id: str = resolved_model) -> tuple[BaseLLMClient, str]:
        return build_client(
            provider=args.provider,
            model=model_id,
            fallback_model=args.fallback_model,
            reasoning_effort=args.reasoning_effort,
            pdf_engine=args.pdf_engine,
            thinking_level=args.thinking_level,
            timeout_s=args.timeout_s,
            max_retries=args.max_retries,
        )

    esc_client_factory = (
        (lambda: _make_client(esc_model))
        if args.escalate_policy != "never" and esc_model != resolved_model
        else None
    )

    # Validate client configuration eagerly before spawning workers
    try:
        probe_client, _ = _make_client()
        _close_client(probe_client)
        if esc_client_factory is not None:
            probe_esc, _ = esc_client_factory()
            _close_client(probe_esc)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    gts = discover_deeds(args.sample_dir, name_filter=args.name_filter, limit=args.limit)
    if not gts:
        print(f"ERROR: No ground truth files matched in {args.sample_dir}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    t_start = time.monotonic()
    lock = threading.Lock()
    done = 0
    results: list[dict[str, Any]] = []
    workers = max(1, args.workers)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(
                evaluate_deed,
                gt_path,
                client_factory=_make_client,
                results_dir=results_dir,
                cache_dir=cache_dir,
                use_cache=not args.no_cache,
                force=args.force,
                escalation_policy=args.escalate_policy,
                escalation_client_factory=esc_client_factory,
                escalation_model=(esc_model if args.escalate_policy != "never" else None),
                escalation_dpi=args.escalate_dpi,
                expected_primary_model=resolved_model,
            ): gt_path
            for gt_path in gts
        }
        for fut in as_completed(futs):
            rec = fut.result()
            results.append(rec)
            with lock:
                done += 1
                cls = rec.get("classification") or classify_result(rec)
                if rec["status"] == "ok":
                    tag = "PASS" if cls == "exact" else "MISS"
                    detail = f"{rec['norm']['matched']}/{rec['n_exp']}"
                    if cls != "exact":
                        detail += f" [{cls}] got={rec['norm']['n_ext']} legal={rec['legal']['matched']}/{rec['n_exp']}"
                else:
                    tag = "ERR "
                    detail = str(rec.get("error", ""))[:90]
                print(
                    f"[{done:02d}/{len(gts)}] {tag} | {rec['deed']} | {detail} ({rec['elapsed_s']}s)",
                    flush=True,
                )

    results.sort(key=lambda r: r["deed"])
    summary = summarize_results(
        results,
        provider=args.provider,
        model=resolved_model,
        wall_s=time.monotonic() - t_start,
    )
    (output_dir / "summary.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    report_md = render_markdown_report(summary, results)
    (output_dir / "report.md").write_text(report_md, encoding="utf-8")

    print("\n" + report_md)
    print(f"Artifacts saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
