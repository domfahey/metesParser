---
name: review-deed
description: This skill should be used when the user specifically asks to "review a deed" or "check a deed description" for metes-and-bounds geometry. Routes to the document-agnostic review workflow, locating the intended description before closure calculation.
---

# Review a deed

Use [Review Metes and Bounds](../review-metes-and-bounds/SKILL.md) as the workflow. Keep this entrypoint for deed-specific requests; do not maintain a separate extraction or verification implementation.

Locate the intended description before calculation. Use Claude's native document/image reading for PDF or image sources, then the extraction skill to isolate the complete description. Preserve the selected source and uncertainties in the handoff.

Report which description was checked and the deterministic result. Follow the shared workflow's source-preservation, no-fabrication, and verification rules.
