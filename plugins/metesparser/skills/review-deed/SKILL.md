---
name: review-deed
description: This skill should be used when the user specifically asks to "review a deed" or "check a deed description" for metes-and-bounds geometry. Routes to the document-agnostic review workflow, locating the intended description before closure calculation.
---

# Review a deed

Use [Review Metes and Bounds](../review-metes-and-bounds/SKILL.md) as the workflow. Keep this entrypoint for deed-specific requests; do not maintain a separate extraction or verification implementation.

Apply the shared workflow's source-preservation and no-fabrication rules. See [artifact handoffs](../../references/artifact-handoffs.md) for reuse and status boundaries.
