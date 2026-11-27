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


def test_escalation_slug_checkpoint_isolation_raw_text_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import patch

    from pypdf import PdfWriter

    mod = _load_module()
    monkeypatch.setattr(mod, "load_dotenv", lambda *a, **kw: False)
    assert (
        mod._default_output_slug(
            provider="openrouter",
            model="anthropic/claude-haiku-5.5",
            escalation_policy="never",
        )
        == "openrouter_anthropic_claude-haiku-5.5"
    )
    esc_slug = mod._default_output_slug(
        provider="openrouter",
        model="anthropic/claude-haiku-5.5",
        escalation_policy="unverified",
        escalation_model="anthropic/claude-sonnet-5.5",
        escalation_dpi=300,
    )
    assert esc_slug == (
        "openrouter_anthropic_claude-haiku-5.5__esc_unverified_anthropic_claude-sonnet-5.5_dpi300"
    )

    # Invalid --escalate-dpi exits cleanly with code 2
    assert mod.main(["--escalate-policy", "unverified", "--escalate-dpi", "0"]) == 2
    assert mod.main(["--escalate-policy", "unverified", "--escalate-dpi", "601"]) == 2

    broken_text = (
        "BEGINNING at a pin; "
        "THENCE N 0°00'00\" E, 100.00 feet; "
        "THENCE S 90°00'00\" E, 100.00 feet; "
        "THENCE S 0°00'00\" W, 100.00 feet; "
        "THENCE N 90°00'00\" W, 99.00 feet to the point of beginning."
    )
    fixed_text = broken_text.replace("99.00", "100.00")
    gt = {
        "expected_legal_description": fixed_text,
        "expected_calls": [
            {"course": 1, "bearing_azimuth_deg_from_north": 0.0, "distance_ft": 100.0},
            {"course": 2, "bearing_azimuth_deg_from_north": 90.0, "distance_ft": 100.0},
            {"course": 3, "bearing_azimuth_deg_from_north": 180.0, "distance_ft": 100.0},
            {"course": 4, "bearing_azimuth_deg_from_north": 270.0, "distance_ft": 100.0},
        ],
    }
    stem = "Test Esc - Deed Image (2 - 2)"
    pdf_path = tmp_path / f"{stem}.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as handle:
        writer.write(handle)
    gt_path = tmp_path / f"{stem}.ground_truth.json"
    gt_path.write_text(json.dumps(gt), encoding="utf-8")
    fake_png = tmp_path / "p1.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\n")

    class _PriClient:
        model = "fake/haiku"

        def generate_text_with_pdf(self, prompt: str, pdf_path: str, **kwargs):
            return "**MARKDOWN RAW**\n" + broken_text

        def generate_text(self, prompt: str, **kwargs):
            return broken_text

        def generate_text_with_images(self, prompt: str, image_paths, **kwargs):
            return '{"pages": [1]}'

    class _EscClient:
        model = "fake/sonnet"

        def generate_text_with_pdf(self, prompt: str, pdf_path: str, **kwargs):
            return fixed_text

        def generate_text(self, prompt: str, **kwargs):
            return fixed_text

        def generate_text_with_images(self, prompt: str, image_paths, **kwargs):
            return "CLEAN ESCALATED RAW\n" + fixed_text

    results_dir = tmp_path / "results"
    # First run without escalation saves a policy="never" checkpoint
    rec_never = mod.evaluate_deed(
        gt_path,
        client_factory=lambda: (_PriClient(), "fake/haiku"),
        results_dir=results_dir,
        cache_dir=None,
        use_cache=False,
        escalation_policy="never",
    )
    assert rec_never["norm"]["exact"] is False
    assert rec_never["markdown"]["raw"] is True

    # Running with escalation_policy="closure_failed" must NOT reuse the stale policy="never" checkpoint
    with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", return_value=[fake_png]):
        rec_esc = mod.evaluate_deed(
            gt_path,
            client_factory=lambda: (_PriClient(), "fake/haiku"),
            results_dir=results_dir,
            cache_dir=None,
            use_cache=False,
            escalation_policy="closure_failed",
            escalation_client_factory=lambda: (_EscClient(), "fake/sonnet"),
            escalation_model="fake/sonnet",
            escalation_dpi=300,
        )
    assert rec_esc["norm"]["exact"] is True
    assert rec_esc["escalation"]["triggered"] is True
    assert rec_esc["escalation"]["selected"] == "escalated"
    # Selected escalated raw_text replaced primary raw_text (no stale markdown leak!)
    assert rec_esc["markdown"]["raw"] is False
    assert rec_esc["raw_len"] == len("CLEAN ESCALATED RAW\n" + fixed_text)

    # Matching escalation config DOES resume from checkpoint without invoking clients
    rec_resumed = mod.evaluate_deed(
        gt_path,
        client_factory=lambda: (_ for _ in ()).throw(AssertionError("should resume")),
        results_dir=results_dir,
        cache_dir=None,
        use_cache=False,
        escalation_policy="closure_failed",
        escalation_model="fake/sonnet",
        escalation_dpi=300,
    )
    assert rec_resumed["escalation"]["selected"] == "escalated"

    # Changed escalation_dpi, primary model, or escalation_model=None vs stale model invalidate checkpoint
    assert (
        mod._checkpoint_matches_escalation(
            rec_esc,
            escalation_policy="closure_failed",
            escalation_model="fake/sonnet",
            escalation_dpi=400,
        )
        is False
    )
    assert (
        mod._checkpoint_matches_escalation(
            rec_esc,
            escalation_policy="closure_failed",
            escalation_model=None,
            escalation_dpi=300,
            primary_model="fake/haiku",
        )
        is False
    )
    assert (
        mod._checkpoint_matches_escalation(
            rec_esc,
            escalation_policy="closure_failed",
            escalation_model="fake/sonnet",
            escalation_dpi=300,
            primary_model="other/model",
        )
        is False
    )

    summary = mod.summarize_results(
        [rec_esc], provider="openrouter", model="fake/haiku", wall_s=1.0
    )
    assert summary["escalation_triggered"] == 1
    assert summary["escalation_agreed"] == 0
    assert summary["escalation_disagreed"] == 1
    assert summary["escalation_selected_escalated"] == 1
    md = mod.render_markdown_report(summary, [rec_esc])
    assert "Escalations (triggered / agreed / selected) | 1 / 0 / 1 |" in md
