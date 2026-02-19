"""Tract model for multi-tract deed support."""

from enum import Enum

from pydantic import Field, FiniteFloat

from .base import _Model
from .closure import ClosureResult
from .deed_call import DeedCall


class TractType(str, Enum):
    """Type of tract in a multi-tract deed."""

    MAIN = "main"
    EXCEPTION = "exception"
    ADDITION = "addition"
    EASEMENT = "easement"


class Tract(_Model):
    """A single tract within a multi-tract deed."""

    label: str = Field(..., min_length=1, description="Tract label (e.g., 'Tract 1', 'Exception 1')")
    tract_type: TractType = Field(..., description="Type of tract")
    calls: list[DeedCall] = Field(default_factory=list, description="Calls for this tract")
    pob_description: str | None = Field(default=None, description="POB for this tract")
    stated_area_sq_ft: FiniteFloat | None = Field(default=None, description="Stated area")
    closure_result: ClosureResult | None = Field(
        default=None, description="Closure result (populated by mp-verify)"
    )
