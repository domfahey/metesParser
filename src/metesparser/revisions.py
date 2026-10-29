"""Compatibility facade for recoverable, non-verifying review revisions."""

from mp_models.revisions import (
    DashboardRevision,
    PreparedRevision,
    PreparedRevisionCorridor,
    RevisionBaseline,
    RevisionCallDraft,
    RevisionComparison,
    RevisionCorridor,
    RevisionError,
    RevisionGeometry,
    RevisionManifest,
    RevisionPreparedCall,
    RevisionSourceChange,
    RevisionSourceRef,
    RevisionTract,
    bind_baseline,
    revision_template,
)
from mp_review.revision_view import render_revision_file  # type: ignore[import-untyped]
from mp_review.revisions import (  # type: ignore[import-untyped]
    import_revision,
    load_revision,
    publish_revision,
)

__all__ = [
    "render_revision_file",
    "RevisionPreparedCall",
    "RevisionComparison",
    "DashboardRevision",
    "PreparedRevision",
    "PreparedRevisionCorridor",
    "RevisionBaseline",
    "RevisionCallDraft",
    "RevisionCorridor",
    "RevisionError",
    "RevisionGeometry",
    "RevisionManifest",
    "RevisionSourceChange",
    "RevisionSourceRef",
    "RevisionTract",
    "bind_baseline",
    "revision_template",
    "import_revision",
    "load_revision",
    "publish_revision",
]
