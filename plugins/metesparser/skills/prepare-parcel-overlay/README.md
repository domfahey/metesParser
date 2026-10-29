# prepare-parcel-overlay

Prepare supplied vector or scanned-map evidence, with guided control-point registration and separate deed-placement evidence for requested overlays.

## Example request

> Import this GeoJSON parcel layer into the declared projected scene and retain its provenance.

## Inputs and outputs

**Inputs:** Supplied vector/raster/map source and a requested import or registration operation.

**Outputs:** Prepared layer data and provenance. Registration does not align a deed. A requested overlay also needs separately supplied position/orientation evidence and the existing supported placement contract; see the [guided procedure](references/overlay-preparation.md#guided-registration-and-separate-deed-placement). A dashboard requires an explicit request. If a dashboard is later requested, its bundle requires an explicit field mapping and fresh geometry calculation; see [artifact handoffs](../../references/artifact-handoffs.md).

## Documentation

- [Skill instructions](SKILL.md)
- [Overlay preparation reference](references/overlay-preparation.md)
- [Artifact handoffs](../../references/artifact-handoffs.md)
- [Plugin changelog](../../CHANGELOG.md)

A later requested [render-online-map](../render-online-map/README.md) view consumes this same prepared evidence; it does not replace registration. See the [online handoff](../../references/artifact-handoffs.md#optional-online-map-handoff).
