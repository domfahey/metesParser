"""Versioned source ledger and isolated calculations for offline dashboards."""

import base64
import binascii
import hashlib
import re
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, field_validator, model_validator

from .base import _Model
from .closure import CheckResult, Point
from .deed_call import DeedCall
from .relative import RelativeDescription

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")]
Number = Annotated[FiniteFloat, Field(strict=True)]
Positive = Annotated[Number, Field(gt=0)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class _DashboardModel(_Model):
    model_config = ConfigDict(str_strip_whitespace=False, revalidate_instances="always")


def _image(value: str | None) -> str | None:
    if value is None:
        return value
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", value)
    if not match:
        raise ValueError("images must be embedded PNG, JPEG or WebP data URIs")
    try:
        data = base64.b64decode(match[2], validate=True)
    except binascii.Error as exc:
        raise ValueError("invalid image base64") from exc
    signatures = {
        "png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpeg": data.startswith(b"\xff\xd8\xff"),
        "webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if not signatures[match[1]]:
        raise ValueError("image content does not match MIME type")
    return value


class DashboardDocument(_DashboardModel):
    id: Identifier
    label: str
    source_name: str
    sha256: Digest | None = None
    expected_page_count: int = Field(gt=0, strict=True)


class DashboardPage(_DashboardModel):
    id: Identifier
    document_id: Identifier
    number: int = Field(gt=0, strict=True)
    label: str = ""
    image: str | None = None
    image_sha256: Digest | None = None
    reading_status: Literal["unread", "read", "missing"] = "unread"
    notes: str = ""
    _safe_image = field_validator("image")(_image)

    @model_validator(mode="after")
    def _image_hash(self) -> Self:
        if self.image is not None:
            digest = hashlib.sha256(base64.b64decode(self.image.split(",", 1)[1])).hexdigest()
            if self.image_sha256 != digest:
                raise ValueError("embedded image SHA256 missing or incorrect")
        elif self.image_sha256 is not None:
            raise ValueError("image hash requires an image")
        return self


class DashboardParcel(_DashboardModel):
    id: Identifier
    label: str


class DashboardOccurrence(_DashboardModel):
    id: Identifier
    parcel_id: Identifier
    version_label: str
    page_ids: tuple[Identifier, ...] = Field(min_length=1)
    transcript: str
    reading_status: Literal["uncertain", "read", "unread"] = "unread"
    source_review_status: Literal["unreviewed", "partial", "reviewed"] = "unreviewed"
    notes: str = ""

    @model_validator(mode="after")
    def _consistent_review(self) -> Self:
        if self.source_review_status == "reviewed" and self.reading_status != "read":
            raise ValueError("reviewed occurrence must have read reading_status")
        return self


class DashboardCall(_DashboardModel):
    id: Identifier
    occurrence_id: Identifier
    page_id: Identifier
    quote: str
    reading_status: Literal["certain", "uncertain", "unknown"] = "unknown"
    reading_note: str = ""
    distance_text: str | None = None
    stated_angle_text: str | None = None
    stated_angle_type: Literal["interior", "exterior", "perpendicular", "parallel"] | None = None
    call: DeedCall | None = None

    @model_validator(mode="after")
    def _uncertain(self) -> Self:
        if self.reading_status != "certain" and not self.reading_note.strip():
            raise ValueError("uncertain or unknown readings require a reading_note")
        if not self.quote.strip():
            raise ValueError("source quote must not be blank")
        if self.reading_status == "certain" and self.call is None:
            raise ValueError("certain reading requires a parsed call")
        if self.reading_status == "unknown" and self.call is not None:
            raise ValueError("unknown readings must retain an unknown call")
        return self


class DashboardEvidence(_DashboardModel):
    id: Identifier
    occurrence_id: Identifier
    page_id: Identifier
    call_id: Identifier | None = None
    image: str | None = None
    image_sha256: Digest | None = None
    label: str
    notes: str = ""
    bounds_px: tuple[int, int, int, int] | None = None
    _safe_image = field_validator("image")(_image)

    @model_validator(mode="after")
    def _image_hash(self) -> Self:
        if self.image is not None:
            digest = hashlib.sha256(base64.b64decode(self.image.split(",", 1)[1])).hexdigest()
            if self.image_sha256 != digest:
                raise ValueError("embedded image SHA256 missing or incorrect")
        elif self.image_sha256 is not None:
            raise ValueError("image hash requires an image")
        return self

    @model_validator(mode="after")
    def _bounds(self) -> Self:
        if self.bounds_px is not None:
            x, y, width, height = self.bounds_px
            if x < 0 or y < 0 or width <= 0 or height <= 0:
                raise ValueError("crop bounds must have nonnegative origin and positive size")
        return self


class DashboardFrame(_DashboardModel):
    units: Literal["ft"] = "ft"
    basis: Literal["recorded_bearings", "arbitrary_local"]
    name: str = Field(min_length=1)


class DashboardCalculation(_DashboardModel):
    id: Identifier
    occurrence_id: Identifier
    method: Literal["canonical", "relative"]
    frame: DashboardFrame
    assumptions: tuple[str, ...] = ()
    relative: RelativeDescription | None = None
    stated_area_sq_ft: Positive | None = None

    @model_validator(mode="after")
    def _method(self) -> Self:
        if self.method == "relative":
            if self.relative is None or self.frame.basis != "arbitrary_local":
                raise ValueError(
                    "relative calculation needs relative input and arbitrary_local frame"
                )
            if self.frame.name != self.relative.frame.name:
                raise ValueError("relative calculation frame name must match its local frame")
        elif self.relative is not None or self.frame.basis != "recorded_bearings":
            raise ValueError("canonical calculation uses recorded bearings and no relative input")
        return self


class DashboardEdit(_DashboardModel):
    call_id: Identifier
    distance_ft: Positive | None = None
    interior_angle_deg: Annotated[Number, Field(gt=0, lt=360)] | None = None
    bearing_azimuth_deg_from_north: Annotated[Number, Field(ge=0, lt=360)] | None = None
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _has_change(self) -> Self:
        if all(
            value is None
            for value in (
                self.distance_ft,
                self.interior_angle_deg,
                self.bearing_azimuth_deg_from_north,
            )
        ):
            raise ValueError("scenario edit must change a value")
        return self


class DashboardScenario(_DashboardModel):
    id: Identifier
    label: str
    calculation_id: Identifier
    edits: tuple[DashboardEdit, ...] = Field(min_length=1)


class DashboardPresentation(_DashboardModel):
    subtitle: str = ""
    method_notes: tuple[str, ...] = ()


class DashboardBundle(_DashboardModel):
    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1)
    documents: tuple[DashboardDocument, ...] = Field(min_length=1)
    pages: tuple[DashboardPage, ...] = Field(min_length=1)
    parcels: tuple[DashboardParcel, ...] = Field(min_length=1)
    occurrences: tuple[DashboardOccurrence, ...] = Field(min_length=1)
    calls: tuple[DashboardCall, ...] = ()
    evidence: tuple[DashboardEvidence, ...] = ()
    calculations: tuple[DashboardCalculation, ...] = Field(min_length=1)
    scenarios: tuple[DashboardScenario, ...] = ()
    presentation: DashboardPresentation = Field(default_factory=DashboardPresentation)

    @model_validator(mode="after")
    def _references(self) -> Self:
        groups = (
            self.documents,
            self.pages,
            self.parcels,
            self.occurrences,
            self.calls,
            self.evidence,
            self.calculations,
            self.scenarios,
        )
        ids = [item.id for group in groups for item in group]
        if len(ids) != len(set(ids)):
            raise ValueError("dashboard IDs must be globally unique")
        docs = {item.id: item for item in self.documents}
        pages = {item.id: item for item in self.pages}
        parcels = {item.id for item in self.parcels}
        occurrences = {item.id: item for item in self.occurrences}
        calls = {item.id: item for item in self.calls}
        evidence = {item.id: item for item in self.evidence}
        calculations = {item.id: item for item in self.calculations}
        numbered = set()
        for page in self.pages:
            if page.document_id not in docs:
                raise ValueError("page references unknown document")
            if page.number > docs[page.document_id].expected_page_count:
                raise ValueError("page exceeds document expected page count")
            key = (page.document_id, page.number)
            if key in numbered:
                raise ValueError("duplicate document page number")
            numbered.add(key)
        for occurrence in self.occurrences:
            if occurrence.parcel_id not in parcels or any(
                p not in pages for p in occurrence.page_ids
            ):
                raise ValueError("occurrence references unknown parcel or page")
            if len(set(occurrence.page_ids)) != len(occurrence.page_ids):
                raise ValueError("occurrence page IDs must be unique")
            if len({pages[p].document_id for p in occurrence.page_ids}) != 1:
                raise ValueError("one occurrence must belong to one document")
        for call in self.calls:
            if (
                call.occurrence_id not in occurrences
                or call.page_id not in occurrences[call.occurrence_id].page_ids
            ):
                raise ValueError("call references an unknown or cross-occurrence page")
        for item in self.evidence:
            if (
                item.occurrence_id not in occurrences
                or item.page_id not in occurrences[item.occurrence_id].page_ids
            ):
                raise ValueError("evidence references an unknown or cross-occurrence page")
            if item.call_id is not None and (
                item.call_id not in calls
                or calls[item.call_id].occurrence_id != item.occurrence_id
                or calls[item.call_id].page_id != item.page_id
            ):
                raise ValueError("evidence references an unknown or cross-occurrence call")
        for calculation in self.calculations:
            if calculation.occurrence_id not in occurrences:
                raise ValueError("calculation references unknown occurrence")
            own = [c for c in self.calls if c.occurrence_id == calculation.occurrence_id]
            courses = [c.call.course for c in own if c.call is not None]
            if len(courses) != len(set(courses)):
                raise ValueError("course numbers must be unique within occurrence")
            if calculation.relative is not None:
                relative = calculation.relative
                if tuple(c.course_id for c in relative.courses) != tuple(c.id for c in own):
                    raise ValueError("relative courses must match occurrence call IDs in order")
                for source in [c.source for c in relative.courses] + [
                    c.source for c in relative.constraints
                ]:
                    if source.reference not in {c.id for c in own} | set(
                        occurrences[calculation.occurrence_id].page_ids
                    ):
                        raise ValueError(
                            "relative source references unknown or cross-occurrence source"
                        )

                def supported_quote(reference: str, quote: str, transcript: str) -> bool:
                    if reference in calls:
                        return quote in calls[reference].quote
                    return quote in transcript

                for constraint in relative.constraints:
                    if not supported_quote(
                        constraint.source.reference,
                        constraint.source.quote,
                        occurrences[calculation.occurrence_id].transcript,
                    ):
                        raise ValueError("relative constraint quote is not supported by its source")
                for course, record in zip(relative.courses, own, strict=True):
                    if course.source.reference not in {record.id, record.page_id}:
                        raise ValueError(
                            "relative course source must reference its own call or page"
                        )
                    if not supported_quote(
                        course.source.reference,
                        course.source.quote,
                        occurrences[calculation.occurrence_id].transcript,
                    ):
                        raise ValueError("relative course quote is not supported by its source")
                    if (
                        record.call is None
                        or record.call.is_curve()
                        or record.call.is_tie_in
                        or record.call.is_exception
                    ):
                        raise ValueError(
                            "relative courses require known straight boundary call distances"
                        )
                    if (
                        course.distance_ft != record.call.distance_ft
                        or course.recorded_bearing_azimuth_deg_from_north
                        != record.call.bearing_azimuth_deg_from_north
                    ):
                        raise ValueError(
                            "relative input must preserve recorded distances and bearings"
                        )
        for scenario in self.scenarios:
            if scenario.calculation_id not in calculations:
                raise ValueError("scenario references unknown calculation")
            occurrence_id = calculations[scenario.calculation_id].occurrence_id
            edited = set()
            for edit in scenario.edits:
                if edit.call_id not in calls or calls[edit.call_id].occurrence_id != occurrence_id:
                    raise ValueError("scenario edit references unknown or cross-occurrence call")
                if edit.call_id in edited:
                    raise ValueError("scenario call edits must be unique")
                edited.add(edit.call_id)
                if any(e not in evidence for e in edit.evidence_ids):
                    raise ValueError("scenario references unknown evidence")
                if any(evidence[e].occurrence_id != occurrence_id for e in edit.evidence_ids):
                    raise ValueError("scenario references cross-occurrence evidence")
        return self


class DashboardCourseGeometry(_DashboardModel):
    call_id: Identifier
    local_azimuth_deg: Number
    delta_x_ft: Number
    delta_y_ft: Number


class DashboardResult(_DashboardModel):
    id: Identifier
    occurrence_id: Identifier
    method: Literal["canonical", "relative"]
    engine_status: Literal["checks_passed", "needs_review"]
    engine_verified: bool
    verified_export_eligible: bool
    geometry_status: Literal["analyzed", "unresolved", "inconsistent", "blocked"]
    points: tuple[Point, ...] = ()
    courses: tuple[DashboardCourseGeometry, ...] = ()
    misclosure_ft: Number | None = None
    misclosure_x_ft: Number | None = None
    misclosure_y_ft: Number | None = None
    area_sq_ft: Number | None = None
    perimeter_ft: Number | None = None
    precision_denominator: Number | None = None
    stated_angle_sum_deg: Number | None = None
    expected_angle_sum_deg: Number | None = None
    computed_closing_angle_deg: Number | None = None
    warnings: tuple[str, ...] = ()
    checks: tuple[CheckResult, ...] = ()
    source_review_complete: bool = False

    @model_validator(mode="after")
    def _no_relative_promotion(self) -> Self:
        if self.method == "relative" and (
            self.engine_verified
            or self.verified_export_eligible
            or self.engine_status != "needs_review"
        ):
            raise ValueError("relative analysis cannot promote canonical engine status")
        return self


class DashboardManifest(_DashboardModel):
    schema_version: Literal["1.0"] = "1.0"
    calculator_version: str
    source_review_hash: Digest
    calculation_input_hash: Digest
    calculation_output_hash: Digest
    presentation_hash: Digest
    source_review_complete: bool
    cache_reused: bool = False


class PreparedDashboard(_DashboardModel):
    bundle: DashboardBundle
    calculations: tuple[DashboardResult, ...]
    manifest: DashboardManifest
