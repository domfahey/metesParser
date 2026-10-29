"""Supplied section references and explicitly computational aliquot derivation."""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from .base import _Model
from .plot import XY, Digest, Identifier, MapSource, PlotScene, Ring, VectorLayer

Text = Annotated[str, Field(min_length=1)]
Aliquot = Literal["N2", "S2", "E2", "W2", "NE4", "NW4", "SE4", "SW4"]


class PLSSSectionKey(_Model):
    principal_meridian: Text
    township: Annotated[int, Field(gt=0, strict=True)]
    township_direction: Literal["N", "S"]
    range: Annotated[int, Field(gt=0, strict=True)]
    range_direction: Literal["E", "W"]
    section: Annotated[int, Field(ge=1, le=36, strict=True)]


class PLSSCorner(_Model):
    name: Literal["SW", "SE", "NE", "NW"]
    xy: XY
    source_id: Identifier


class PLSSSectionReference(_Model):
    id: Identifier
    section: PLSSSectionKey
    subdivision_class: Literal["rectangular", "irregular", "excess_deficiency", "government_lot"]
    corners: tuple[PLSSCorner, ...]


class PLSSReferenceDataset(_Model):
    id: Identifier
    version: Text
    authority_citation: Text
    scene: PlotScene
    source: MapSource
    references: tuple[PLSSSectionReference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if self.source.source_date is not None:
            date.fromisoformat(self.source.source_date)
        if self.source.retrieved_at is not None:
            timestamp = datetime.fromisoformat(self.source.retrieved_at.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("source retrieval timestamp must include timezone")
        identities = [r.section.model_dump_json().casefold() for r in self.references]
        if len({r.id for r in self.references}) != len(self.references) or len(
            set(identities)
        ) != len(identities):
            raise ValueError("duplicate or ambiguous section/reference identity")
        return self


class PLSSDerivationRequest(_Model):
    schema_version: Literal["1.0"] = "1.0"
    purpose: Literal["computed_reference_geometry"] = "computed_reference_geometry"
    dataset: PLSSReferenceDataset
    selected_dataset_id: Identifier
    selected_reference_id: Identifier
    section: PLSSSectionKey
    rule: Literal["rectangular_aliquot_v1"]
    # Outermost selection first: SE4, NW4 means NW quarter OF SE quarter.
    aliquot_steps: tuple[Aliquot, ...] = Field(min_length=1, max_length=8)


class PLSSDerivationResult(_Model):
    schema_version: Literal["1.0"] = "1.0"
    builder_version: Literal["plss-reference-1.0.0"] = "plss-reference-1.0.0"
    status: Literal["needs_review"] = "needs_review"
    availability: Literal["computed", "unsupported"]
    purpose: Literal["computed_reference_geometry"] = "computed_reference_geometry"
    input_hash: Digest
    dataset_hash: Digest
    source_hash: Digest
    dataset_id: Identifier
    reference_id: Identifier
    section: PLSSSectionKey
    rule: Literal["rectangular_aliquot_v1"]
    aliquot_steps: tuple[Aliquot, ...]
    ring: Ring | None = None
    area_scene_units_squared: FiniteFloat | None = None
    scenes: tuple[PlotScene, ...] = ()
    map_sources: tuple[MapSource, ...] = ()
    vector_layers: tuple[VectorLayer, ...] = ()
    reason: str = ""
    limitations: tuple[str, ...]
    boundary_established: Literal[False] = False
    verified_export_eligible: Literal[False] = False
