"""Model conversion between the compatibility monolith and the ``mp_*`` packages.

The monolith facades (``call_extractor``, ``closure_checker``, ``csv_builder``,
``text_parser``) delegate to the packages; these helpers mirror models across the
boundary. Monolith and package models declare the same fields, so values are copied
field for field and each model's explicitly-set fields are preserved.
"""

from __future__ import annotations

from collections.abc import Sequence

import mp_models

from .models import CallAudit, DeedCall, SkippedCourse


def package_call(call: DeedCall) -> mp_models.DeedCall:
    """Mirror a monolith call as a package call without revalidating it."""
    return mp_models.DeedCall.model_construct(_fields_set=call.model_fields_set, **dict(call))


def package_calls(calls: Sequence[DeedCall]) -> list[mp_models.DeedCall]:
    return [package_call(call) for call in calls]


def monolith_call(call: mp_models.DeedCall) -> DeedCall:
    """Validate a package call as a monolith call, keeping its explicitly-set fields."""
    return DeedCall.model_validate(call.model_dump(exclude_unset=True))


def monolith_calls_from(
    originals: Sequence[DeedCall],
    inputs: Sequence[mp_models.DeedCall],
    outputs: Sequence[mp_models.DeedCall],
) -> list[DeedCall]:
    """Map a per-call package transform back, returning untouched originals as-is."""
    return [
        original if output is mirrored else monolith_call(output)
        for original, mirrored, output in zip(originals, inputs, outputs, strict=True)
    ]


def package_skip(skip: SkippedCourse) -> mp_models.SkippedCourse:
    return mp_models.SkippedCourse.model_validate(skip.model_dump())


def package_skips(skips: Sequence[SkippedCourse]) -> list[mp_models.SkippedCourse]:
    return [package_skip(skip) for skip in skips]


def monolith_skip(skip: mp_models.SkippedCourse) -> SkippedCourse:
    return SkippedCourse.model_validate(skip.model_dump())


def monolith_skips(skips: Sequence[mp_models.SkippedCourse]) -> list[SkippedCourse]:
    return [monolith_skip(skip) for skip in skips]


def monolith_call_audit(audit: mp_models.CallAudit) -> CallAudit:
    return CallAudit.model_validate(audit.model_dump())
