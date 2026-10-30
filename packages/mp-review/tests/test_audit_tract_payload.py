"""verify the single-tract review audit payload has no per-tract key."""

from __future__ import annotations

import mp_review.api as api

SQUARE = "BEGINNING at a point; THENCE N 0° E 100 feet; THENCE S 90° E 100 feet; THENCE S 0° E 100 feet; THENCE N 90° W 100 feet."


def test_audit_payload_omits_tract_key_for_single_traverse():
    out = api._run(SQUARE.encode(), "d.txt", "text", None, None, include_audit=True)
    assert "tract_verification_audits" not in out["audit"]
