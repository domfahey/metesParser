"""Project-wide Pydantic base configuration."""

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    """Project-wide Pydantic base configuration."""

    # frozen=True: models are immutable. The object.__setattr__() bypass in
    # normalize_curve_radius_sign() still works on frozen models.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    @staticmethod
    def _coerce_bool_field(value: object) -> bool:
        """Normalize boolean-like values used by multiple models."""
        if isinstance(value, bool):
            return value

        if value is None:
            return False

        if isinstance(value, (int, float)):
            if value in (0, 1):
                return bool(value)
            raise ValueError("flag must be a boolean value")

        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"", "false", "0", "no", "n", "off"}:
                return False
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True

        raise ValueError("flag must be a boolean value")
