# Changelog

## Unreleased

- Added one canonical `seeform` execution entry with a bundle module fallback.
- Added the minimal Visual Transformation Plan contract and execution gates.
- Added bounded, non-destructive local L3 adjustment with candidate rollback lineage.
- Added compare-only candidate inputs and stable V3 numeric metrics.
- Added plan-bound candidate lineage to evidence and comparison reports.
- Fixed complete capability report serialization, including `input_exists`, adapters, and `has_v*` fields.
- Routed V2/V3 execution through the provider recorded by capability probing.
- Rejected hardlink aliases, duplicate candidate outputs, ambiguous candidate sources, and malformed operation parameters.
- Escaped lineage metadata in HTML comparison reports and verified hashes after edits.

## v0.1.0 - 2026-08-15

- Initial public release of the Seeform visual transformation Skill.
- Added deterministic L1/L2 image editing with Pillow.
- Added capability probing for file access, visual observation, editing, and comparison.
- Added engineering comparison reports and traceable evidence records.
- Added the first public deployment bundle.

Known limits:

- Real visual observation requires a host adapter.
- Editing is limited to deterministic L1/L2 operations.
- Engineering comparison does not replace aesthetic judgment or user confirmation.
