---
name: review-deed
description: Reviews the metes-and-bounds description in a deed by applying the review-metes-and-bounds workflow. Use when the user invokes /review-deed or specifically asks to review a deed or check a deed description. Not for other source types or general closure questions (review-metes-and-bounds) or checks of already-selected calls (verify-traverse).
disable-model-invocation: true
metadata:
  version: "0.1.0"
---

# Review a deed

Manual slash-command alias; Claude does not select it automatically, so general closure requests reach [Review Metes and Bounds](../review-metes-and-bounds/SKILL.md). Follow that workflow in full: it locates the description before closure calculation. Keep this entrypoint for deed-specific requests; do not maintain a separate extraction or verification implementation.

Apply the shared workflow's source-preservation and no-fabrication rules. A deed with several descriptions needs one tract per review (see [multiple descriptions](../../references/review-limits.md#multiple-descriptions)). See [artifact handoffs](../../references/artifact-handoffs.md) for reuse and status boundaries.
