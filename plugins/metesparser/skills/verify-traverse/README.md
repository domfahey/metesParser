# verify-traverse

Verify an identified boundary's selected CSV/JSON call set, or run an explicitly requested local relative-angle analysis.

## Example request

> Verify the closure of these selected boundary calls.

## Inputs and outputs

**Inputs:** For canonical verification, a strict CSV, JSON calls list, or LegalDescription JSON object. For relative analysis, a RelativeDescription JSON supplied for that requested purpose. Each mode uses a new output directory or configured output base.

**Outputs:** Canonical statuses `checks_passed`, `needs_review`, or `error`; a verified CSV only when engine gates pass. Relative analysis has separate `analysis.status` (`analyzed`, `unresolved`, or `inconsistent`) and top-level `needs_review`; it never creates verified CSV. Unknown bearings remain unknown.

## Documentation

- [Claude instructions](SKILL.md)
- [Usage and routing](../../references/usage.md)
- [Detailed reference](../../references/review-limits.md)
- [Plugin changelog](../../CHANGELOG.md)

See the usage guide for installation, prerequisites, settings, and validation limits.
