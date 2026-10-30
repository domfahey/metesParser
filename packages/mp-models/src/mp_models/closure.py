"""Closure result and related models."""

from typing import Literal, Self

from pydantic import (
    Field,
    FiniteFloat,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .base import _Model


class Point(_Model):
    """Represents a 2D coordinate point."""

    x: FiniteFloat = Field(..., description="X coordinate (feet)")
    y: FiniteFloat = Field(..., description="Y coordinate (feet)")

    def __str__(self) -> str:
        return f"({self.x:.2f}, {self.y:.2f})"


class CheckResult(_Model):
    """Executed outcome; legacy ``passed`` is true only for an actual pass.

    Old passed-only payloads infer status. Explicit status is authoritative when
    reading mixed old/new payloads, including historical true skip booleans.
    """

    name: str = Field(..., description="Check name")
    status: Literal["passed", "failed", "not_applicable", "blocked"] = "failed"
    passed: bool = Field(default=False, description="True only when status is passed")
    reason: str = Field(default="", description="Machine-readable outcome reason")
    detail: str = Field(..., description="Human-readable detail")
    inputs: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Values used in the check"
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy_status(cls, value: object) -> object:
        if isinstance(value, dict):
            value = dict(value)
            if "status" not in value and "passed" in value:
                value["status"] = "passed" if cls._coerce_bool_field(value["passed"]) else "failed"
        return value

    @model_validator(mode="after")
    def _synchronize_passed(self) -> Self:
        object.__setattr__(self, "passed", self.status == "passed")
        return self


class ClosureResult(_Model):
    """Results of traverse closure verification."""

    misclosure_x_ft: FiniteFloat = Field(..., description="Misclosure in X direction (feet)")
    misclosure_y_ft: FiniteFloat = Field(..., description="Misclosure in Y direction (feet)")
    misclosure_ft: FiniteFloat = Field(..., description="Total misclosure distance (feet)")

    area_sq_ft: FiniteFloat = Field(
        ...,
        description="Area in square feet (shoelace formula)",
    )
    area_acres: FiniteFloat = Field(..., description="Area in acres")
    perimeter_ft: FiniteFloat = Field(
        ...,
        description="Total perimeter in feet; 0.0 when perimeter_available is False",
    )
    misclosure_available: bool = Field(
        default=True,
        description="False when a course could not be positioned, so later vertices are not "
        "known in absolute terms; misclosure values are then 0.0 and not measurements",
    )
    area_available: bool = Field(
        default=True,
        description="False when area cannot be determined (e.g. a chord-only curve, an "
        "unpositioned course or an incomplete bearing); area_sq_ft/area_acres are then not "
        "measurements",
    )
    perimeter_available: bool = Field(
        default=True,
        description="False when a course length is not determined (e.g. a chord-only curve "
        "or an unpositioned course); perimeter_ft is then not a measurement",
    )

    closure_passed: bool = Field(
        ...,
        description="True if misclosure is within tolerance (< 0.01 ft)",
    )
    angle_check_passed: bool = Field(
        ...,
        description="True if interior angles sum correctly ((n-2)*180\u00b0)",
    )
    curve_consistency_passed: bool = Field(
        ...,
        description="True if curve math is consistent",
    )

    precision_ratio: FiniteFloat | None = Field(
        default=None,
        description="Misclosure / perimeter (e.g., 0.00004 means 1:25,000)",
        ge=0,
    )
    confidence_score: FiniteFloat | None = Field(
        default=None,
        description="Overall confidence score (0.0\u20131.0) based on closure, bearings, monuments",
        ge=0.0,
        le=1.0,
    )

    warnings: list[str] = Field(default_factory=list, description="List of warnings or issues")

    points: list[Point] = Field(
        default_factory=list,
        description="Computed vertex points (x, y in feet)",
    )

    checks: list[CheckResult] = Field(
        default_factory=list, description="Structured engine outcomes"
    )
    source_review_status: Literal["not_reviewed", "complete", "incomplete"] = Field(
        default="not_reviewed",
        description="Explicit source review state; never inferred from geometry",
    )

    @property
    def source_review_complete(self) -> bool:
        """Whether source completeness has been explicitly reviewed."""
        return self.source_review_status == "complete"

    @property
    def geometry_verified(self) -> bool:
        """Whether engine geometry checks allow verified export."""
        return self.is_fully_verified()

    @field_validator(
        "closure_passed",
        "angle_check_passed",
        "curve_consistency_passed",
        "perimeter_available",
        "area_available",
        "misclosure_available",
        mode="before",
    )
    @classmethod
    def _coerce_bool_fields(cls, value: object, info: ValidationInfo) -> bool:
        try:
            return cls._coerce_bool_field(value)
        except ValueError as exc:
            field = info.field_name or "flag"
            raise ValueError(f"{field} must be a boolean value") from exc

    def is_fully_verified(self) -> bool:
        """Check engine geometry eligibility, independently of source review."""
        if self.checks:
            outcomes = {check.name: check.status for check in self.checks}
            return (
                self.closure_passed
                and self.misclosure_available
                and outcomes.get("traverse_closure") == "passed"
                and (self.angle_check_passed or outcomes.get("interior_angles") == "not_applicable")
                and (
                    self.curve_consistency_passed
                    or outcomes.get("curve_consistency") == "not_applicable"
                )
                and all(name in outcomes for name in ("interior_angles", "curve_consistency"))
                and all(check.status in {"passed", "not_applicable"} for check in self.checks)
                and not self.warnings
            )
        # Old serialized results lack structured outcomes. Exporters still run
        # fresh verification against the calls before accepting these results.
        return (
            self.closure_passed
            and self.misclosure_available
            and self.angle_check_passed
            and self.curve_consistency_passed
            and not self.warnings
        )

    def get_closure_status(self) -> str:
        """Get human-readable closure status."""
        if self.warnings:
            return "NEEDS REVIEW"
        if not self.misclosure_available:
            return "NOT DETERMINED"
        if self.misclosure_ft < 0.01:
            return "EXCELLENT"
        if self.misclosure_ft < 0.1:
            return "GOOD"
        if self.misclosure_ft < 1.0:
            return "ACCEPTABLE"
        return "POOR"
