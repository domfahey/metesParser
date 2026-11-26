"""Unit tests for scripts/eval_model_vs_gt.py (offline, mocked LLM clients)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mp_models import DeedCall

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_model_vs_gt.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("eval_model_vs_gt", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_self_check_matches_all_sample_ground_truths() -> None:
    mod = _load_module()
    assert mod.main(["--self-check"]) == 0


def test_sanitize_slug() -> None:
    mod = _load_module()
    assert mod.sanitize_slug("anthropic/claude-haiku-5.5") == "anthropic_claude-haiku-5.5"
    assert mod.sanitize_slug("  ///  ") == "model"


def test_discover_deeds_supports_single_and_multiple_filters(tmp_path: Path) -> None:
    mod = _load_module()
    for name in ("Alpha (1 - 1)", "Beta (2 - 2)", "Gamma (3 - 3)"):
        (tmp_path / f"{name}.ground_truth.json").write_text("{}", encoding="utf-8")
    assert len(mod.discover_deeds(tmp_path, name_filter="beta")) == 1
    matched = mod.discover_deeds(tmp_path, name_filter=["1 - 1", "gamma"])
    assert [p.name for p in matched] == [
        "Alpha (1 - 1).ground_truth.json",
        "Gamma (3 - 3).ground_truth.json",
    ]


def test_compare_calls_exact_and_edge_cases() -> None:
    mod = _load_module()
    ext = [
        DeedCall(
            course=1,
            direction_text="N 45°00'00\" E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="southeasterly",
            bearing_azimuth_deg_from_north=None,
            distance_ft=50.0,
        ),
    ]
    exp = [
        {"course": 1, "bearing_azimuth_deg_from_north": 45.01, "distance_ft": 100.02},
        {"course": 2, "bearing_azimuth_deg_from_north": None, "distance_ft": 50.0},
    ]
    ok = mod.compare_calls(ext, exp)
    assert ok["exact"] is True
    assert ok["matched"] == 2

    # Fabricated bearing on a cardinal-only course must fail
    fabricated = [
        ext[0],
        DeedCall(
            course=2,
            direction_text="S 45° E",
            bearing_azimuth_deg_from_north=135.0,
            distance_ft=50.0,
        ),
    ]
    bad = mod.compare_calls(fabricated, exp)
    assert bad["exact"] is False
    assert bad["matched"] == 1
    assert "cardinal-only" in bad["mismatches"][0]["issues"][0]

    # Zero-call deed handling
    assert mod.compare_calls([], [])["exact"] is True
    spurious = mod.compare_calls([ext[0]], [])
    assert spurious["exact"] is False
    assert spurious["mismatches"][0]["type"] == "spurious_calls_on_zero_call_deed"


def test_classify_result_buckets() -> None:
    mod = _load_module()
    assert mod.classify_result({"status": "error"}) == "api_error"
    assert (
        mod.classify_result(
            {
                "status": "ok",
                "norm": {"exact": True, "n_exp": 4, "n_ext": 4},
                "legal": {"exact": True},
            }
        )
        == "exact"
    )
    assert (
        mod.classify_result(
            {
                "status": "ok",
                "norm": {"exact": False, "n_exp": 4, "n_ext": 3},
                "legal": {"exact": True},
            }
        )
        == "normalization_regression"
    )
    assert (
        mod.classify_result(
            {
                "status": "ok",
                "norm": {"exact": False, "n_exp": 0, "n_ext": 2},
                "legal": {"exact": False},
            }
        )
        == "zero_call_false_positive"
    )
    assert (
        mod.classify_result(
            {
                "status": "ok",
                "norm": {"exact": False, "n_exp": 4, "n_ext": 3},
                "legal": {"exact": False},
            }
        )
        == "call_count_mismatch"
    )
    assert (
        mod.classify_result(
            {
                "status": "ok",
                "norm": {"exact": False, "n_exp": 4, "n_ext": 4},
                "legal": {"exact": False},
            }
        )
        == "value_mismatch"
    )


def test_build_client_disables_fallback_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    client, resolved = mod.build_client(provider="openrouter", model="anthropic/claude-haiku-5.5")
    assert resolved == "anthropic/claude-haiku-5.5"
    assert client.fallback_model is None
    assert client.reasoning_effort == "low"

    client_off, _ = mod.build_client(
        provider="openrouter",
        model="anthropic/claude-haiku-5.5",
        reasoning_effort="off",
        pdf_engine="mistral-ocr",
    )
    assert client_off.reasoning_effort is None
    assert client_off.pdf_engine == "mistral-ocr"

    with pytest.raises(ValueError, match="Unsupported provider"):
        mod.build_client(provider="unknown")


def test_evaluate_deed_end_to_end_and_resume(tmp_path: Path) -> None:
    mod = _load_module()
    legal_text = (
        "BEGINNING at a pin; "
        "THENCE North 00 degrees 00 minutes 00 seconds East, 100.00 feet to a pin; "
        "THENCE South 90 degrees 00 minutes 00 seconds East, 100.00 feet to a pin; "
        "THENCE South 00 degrees 00 minutes 00 seconds West, 100.00 feet to a pin; "
        "THENCE North 90 degrees 00 minutes 00 seconds West, 100.00 feet to the point of beginning."
    )
    gt = {
        "expected_legal_description": legal_text,
        "expected_calls": [
            {"course": 1, "bearing_azimuth_deg_from_north": 0.0, "distance_ft": 100.0},
            {"course": 2, "bearing_azimuth_deg_from_north": 90.0, "distance_ft": 100.0},
            {"course": 3, "bearing_azimuth_deg_from_north": 180.0, "distance_ft": 100.0},
            {"course": 4, "bearing_azimuth_deg_from_north": 270.0, "distance_ft": 100.0},
        ],
    }
    stem = "Test Square - Deed Image (1 - 1)"
    (tmp_path / f"{stem}.pdf").write_bytes(b"%PDF-1.4\nfake\n")
    gt_path = tmp_path / f"{stem}.ground_truth.json"
    gt_path.write_text(json.dumps(gt), encoding="utf-8")

    calls_seen = {"pdf": 0, "text": 0}

    class FakeClient:
        model = "fake/model"

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            calls_seen["pdf"] += 1
            return f"HEADER\n\n{legal_text}\n\nFOOTER"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            calls_seen["text"] += 1
            return legal_text

    results_dir = tmp_path / "results"
    rec = mod.evaluate_deed(
        gt_path,
        client_factory=lambda: (FakeClient(), "fake/model"),
        results_dir=results_dir,
        cache_dir=None,
        use_cache=False,
    )
    assert rec["status"] == "ok"
    assert rec["classification"] == "exact"
    assert rec["norm"]["exact"] is True
    assert rec["norm"]["matched"] == 4
    assert calls_seen == {"pdf": 1, "text": 2}

    # Second run resumes from checkpoint without calling client again
    rec2 = mod.evaluate_deed(
        gt_path,
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("should resume")),
        results_dir=results_dir,
        cache_dir=None,
        use_cache=False,
    )
    assert rec2["deed"] == stem

    summary = mod.summarize_results([rec], provider="openrouter", model="fake/model", wall_s=1.2)
    assert summary["exact_deeds_norm"] == 1
    assert summary["matched_courses_norm"] == 4
    md = mod.render_markdown_report(summary, [rec])
    assert "fake/model" in md
    assert "None (100% exact" in md


def test_instrument_usage_tracks_openrouter_tokens_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_module()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret-never-logged")
    client, _ = mod.build_client(provider="openrouter", model="anthropic/claude-haiku-5.5")

    fake_resp = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=300, cost=0.00027)
    )
    client._client.chat.completions.create = lambda *a, **kw: fake_resp
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "api_calls": 0}
    mod._instrument_usage(client, totals)
    client._client.chat.completions.create(model="anthropic/claude-haiku-5.5", messages=[])
    assert totals == {
        "prompt_tokens": 1200,
        "completion_tokens": 300,
        "cost_usd": pytest.approx(0.00027),
        "api_calls": 1,
    }
    assert "or-secret-never-logged" not in json.dumps(totals)
