"""verify the review audit payload carries per-tract verification audits."""

from __future__ import annotations

import mp_review.api as api
from mp_models import VerificationAudit

SQUARE = "BEGINNING at a point; THENCE N 0 E 100 feet; THENCE S 90 E 100 feet; THENCE S 0 E 100 feet; THENCE N 90 W 100 feet."


def test_audit_payload_includes_tract_verification_audits(monkeypatch):
    real = api.verify_closure

    def fake(calls, *, audit_context=None, **kw):
        audit_context.tract_verification_audits.append(VerificationAudit(tract_label="A"))
        return real(calls, audit_context=audit_context, **kw)

    monkeypatch.setattr(api, "verify_closure", fake)
    out = (
        api.review_text(SQUARE, include_audit=True)
        if False
        else api._run(SQUARE.encode(), "d.txt", "text", None, None, include_audit=True)
    )
    assert out["audit"]["tract_verification_audits"][0]["tract_label"] == "A"


def test_audit_payload_omits_tract_key_for_single_traverse():
    out = api._run(SQUARE.encode(), "d.txt", "text", None, None, include_audit=True)
    assert "tract_verification_audits" not in out["audit"]
