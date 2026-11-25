"""Project-wide Pydantic base configuration."""

import math
import types
from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator

STATED_AREA_REL_TOL: float = 1e-6
STATED_AREA_ABS_TOL: float = 1e-4


def stated_areas_match(first: float, second: float) -> bool:
    """Return True when two finite stated-area values match within shared tolerance."""
    if (
        isinstance(first, bool)
        or isinstance(second, bool)
        or not math.isfinite(first)
        or not math.isfinite(second)
    ):
        return False
    return math.isclose(first, second, rel_tol=STATED_AREA_REL_TOL, abs_tol=STATED_AREA_ABS_TOL)


def coerce_bool_field(value: object) -> bool:
    """Normalize boolean-like values used across models and packet inputs."""
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


def _annotation_contains_type(annotation: Any, target: type) -> bool:
    if annotation is target:
        return True
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        return bool(args) and _annotation_contains_type(args[0], target)
    if origin in (Union, types.UnionType):
        return any(_annotation_contains_type(arg, target) for arg in get_args(annotation))
    return False


def _non_bool_float_field_names(model_cls: type[BaseModel]) -> frozenset[str]:
    return frozenset(
        name
        for name, field in model_cls.model_fields.items()
        if _annotation_contains_type(field.annotation, float)
        and not _annotation_contains_type(field.annotation, bool)
    )


class _NoBoolFloatModel(BaseModel):
    """Base model rejecting booleans on numeric float fields."""

    _non_bool_float_fields: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        cls._non_bool_float_fields = _non_bool_float_field_names(cls)

    @model_validator(mode="before")
    @classmethod
    def _reject_bool_on_float_fields(cls, data: Any) -> Any:
        """Reject booleans on numeric float fields (``bool`` subclasses ``int`` in Python)."""
        if isinstance(data, Mapping):
            for field_name in cls._non_bool_float_fields:
                if field_name in data and isinstance(data[field_name], bool):
                    raise ValueError(f"{field_name} must be a number, not a boolean")
        return data


class _Model(_NoBoolFloatModel):
    """Project-wide Pydantic base configuration."""

    # frozen=True: models are immutable. The object.__setattr__() bypass in
    # normalize_curve_radius_sign() still works on frozen models.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    _coerce_bool_field = staticmethod(coerce_bool_field)
