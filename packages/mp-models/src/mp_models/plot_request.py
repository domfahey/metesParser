"""Standalone, source-honest plotting inputs; no review or verification attestations."""

from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from .base import _Model
from .deed_call import DeedCall
from .plot import Digest, Identifier, LinearUnit, PlotGeometry
from .relative import RelativeDescription


class PlotCall(_Model):
    """A supplied call and optional actual source references, never invented pages."""

    model_config = ConfigDict(str_strip_whitespace=False)
    id: Identifier
    call: DeedCall | None
    occurrence_id: Identifier | None = None
    page_id: Identifier | None = None
    source_reference: str | None = None
    quote: str = ""


class PlotRequest(_Model):
    """Calls to plot in an unadjusted local frame, independently of a dashboard."""

    model_config = ConfigDict(str_strip_whitespace=False)
    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1)
    calculation_id: Identifier = "plot"
    calls: tuple[PlotCall, ...] = Field(min_length=1)
    foot_definition: LinearUnit = "unknown_ft"
    relative: RelativeDescription | None = None

    @model_validator(mode="after")
    def _references(self) -> Self:
        if not self.title.strip():
            raise ValueError("plot title must not be blank")
        if self.foot_definition == "m":
            raise ValueError("call distances are in feet; foot_definition must identify feet")
        if len({c.id for c in self.calls}) != len(self.calls):
            raise ValueError("plot call IDs must be unique")
        if self.relative is not None:
            if len(self.calls) != len(self.relative.courses):
                raise ValueError("relative courses must correspond in order to all plot calls")
            for record, course in zip(self.calls, self.relative.courses, strict=True):
                call = record.call
                if (
                    call is None
                    or call.is_curve()
                    or call.is_tie_in
                    or call.is_exception
                    or call.is_meander
                    or call.distance_ft != course.distance_ft
                    or call.bearing_azimuth_deg_from_north
                    != course.recorded_bearing_azimuth_deg_from_north
                ):
                    raise ValueError("relative course differs from its supplied straight plot call")
        return self


class PreparedPlot(_Model):
    """Fresh deterministic geometry, advisory regardless of geometric closure."""

    request: PlotRequest
    geometry: PlotGeometry
    input_hash: Digest
