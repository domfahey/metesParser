"""Closure result and related models."""

from pydantic import (
    Field,
    FiniteFloat,
    ValidationInfo,
    field_validator,
)

from .base import _Model


class Point(_Model):
    """Represents a 2D coordinate point."""

    x: FiniteFloat = Field(..., description="X coordinate (feet)")
    y: FiniteFloat = Field(..., description="Y coordinate (feet)")

    def __str__(self) -> str:
        return f"({self.x:.2f}, {self.y:.2f})"


class CheckResult(_Model):
    """Result of a single verification check."""

    name: str = Field(..., description="Check name")
    passed: bool = Field(..., description="Whether the check passed")
    detail: str = Field(..., description="Human-readable detail")
    inputs: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Values used in the check"
    )


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
    perimeter_ft: FiniteFloat = Field(..., description="Total perimeter in feet")

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

    @field_validator(
        "closure_passed",
        "angle_check_passed",
        "curve_consistency_passed",
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
        """Check if all verification checks passed."""
        return (
            self.closure_passed
            and self.angle_check_passed
            and self.curve_consistency_passed
            and len(self.warnings) == 0
        )

    def get_closure_status(self) -> str:
        """Get human-readable closure status."""
        if self.warnings:
            return "NEEDS REVIEW"
        if self.misclosure_ft < 0.01:
            return "EXCELLENT"
        if self.misclosure_ft < 0.1:
            return "GOOD"
        if self.misclosure_ft < 1.0:
            return "ACCEPTABLE"
        return "POOR"
