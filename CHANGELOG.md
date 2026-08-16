# Changelog

## Unreleased

- Formalized Seeform as a visual decision and transformation layer for AI agents.
- Added a direct, low-burden user surface: one visual intent produces a concise viewpoint and a default direction before execution.
- Documented the difference from generic AI photo editing: Seeform owns visual judgment, strategy explanation, constraints, comparison, and feedback continuity while adapters provide editing capabilities.
- Focused V1 product validation on ordinary photos and portrait expression for Chinese social-media use cases, including Xiaohongshu publishing.
- Set unspecified cases to expression mode by default while preserving explicit documentary mode, and documented capability-dependent portrait routing.
- Added one canonical `seeform` execution entry with a bundle module fallback.
- Added the minimal Visual Transformation Plan contract and execution gates.
- Added bounded, non-destructive local L3 adjustment with candidate rollback lineage.
- Added compare-only candidate inputs and stable V3 numeric metrics.
- Added plan-bound candidate lineage to evidence and comparison reports.
- Fixed complete capability report serialization, including `input_exists`, adapters, and `has_v*` fields.
- Routed V2/V3 execution through the provider recorded by capability probing.
- Rejected hardlink aliases, duplicate candidate outputs, ambiguous candidate sources, and malformed operation parameters.
- Escaped lineage metadata in HTML comparison reports and verified hashes after edits.
- Added a loopback-only llama.cpp adapter for schema-constrained Qwen3-VL GGUF observation.
- Added `--llama-cpp-config` so local V1 observation can participate in the existing full runtime.

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
