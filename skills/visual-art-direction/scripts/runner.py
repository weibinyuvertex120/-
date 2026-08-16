"""Single-case runner for the visual-art-direction runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .adapters.host_bridge import HostBridgeAdapter
from .adapters.llama_cpp import LlamaCppQwenAdapter
from .capability_probe import CapabilityAdapter, probe_capabilities
from .compare_candidates import LocalCompareAdapter
from .contracts import (
    CandidateLineage,
    Capability,
    CapabilityReport,
    CaseRequest,
    ComparisonResult,
    EditOperation,
    EditRequest,
    EditResult,
    EvidenceRecord,
    ObservationResult,
    Phase,
    RunResult,
    Status,
    UserFeedbackDecision,
)
from .deterministic_editor import DeterministicEditorAdapter
from .evidence import sha256_file, write_evidence


def _provider_adapter(
    report: CapabilityReport,
    capability: Capability,
    adapters: list[CapabilityAdapter],
) -> CapabilityAdapter | None:
    provider = report.capabilities[capability].provider
    return next((adapter for adapter in adapters if adapter.name == provider), None)


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    if not left.exists() or not right.exists():
        return False
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _execute_edit(adapter: CapabilityAdapter, request: EditRequest) -> EditResult:
    """Execute a bounded operation through the reported V2 provider."""
    return EditResult.model_validate(adapter.edit(request))


def _evidence_path(case_file: Path, case_id: str, now: datetime) -> Path:
    return (
        case_file.resolve().parent / "evidence" / f"{case_id}-{now.strftime('%Y%m%d%H%M%S')}.json"
    )


def _write_evidence(
    case: CaseRequest,
    result: RunResult,
    now: datetime,
    case_file: Path,
) -> None:
    """Persist only execution facts; never infer visual or user approval."""
    operations = []
    for index, request in enumerate(case.operations):
        edit_result = result.edit_results[index] if index < len(result.edit_results) else None
        operations.append(
            {
                "operation": request.operation.value,
                "level": request.level,
                "parameters": request.parameters,
                "input_image": str(request.input_image.resolve()),
                "output_image": str(request.output_image.resolve()),
                "input_sha256": edit_result.input_sha256 if edit_result else "",
                "output_sha256": edit_result.output_sha256 if edit_result else "",
                "output_size": list(edit_result.output_size) if edit_result else [0, 0],
                "success": edit_result.success if edit_result else False,
                "error": edit_result.error if edit_result else "not executed",
            }
        )

    capability_report = (
        result.capability_report.model_dump(mode="json") if result.capability_report else {}
    )

    evidence = EvidenceRecord(
        case_id=case.case_id,
        timestamp=now,
        input_path=str(case.input_image.resolve()),
        input_sha256=(result.capability_report.input_sha256 if result.capability_report else ""),
        capability_report=capability_report,
        observation=result.observation_result,
        plan=result.plan,
        parent_plan=result.parent_plan,
        operations=operations,
        candidate_lineage=result.candidate_lineage,
        comparisons=[
            comparison.model_dump(mode="json") for comparison in result.comparison_results
        ],
        user_feedback=result.user_feedback,
        status=result.status,
        residual_risks=[
            "Deterministic V2 covers L1/L2 and bounded local L3 adjustment only",
            "Engineering comparison does not replace visual or aesthetic judgment",
            "UserFeedback is recorded separately and remains required for final acceptance",
        ],
    )
    output_path = _evidence_path(case_file, case.case_id, now)
    write_evidence(evidence, output_path)
    result.evidence_path = output_path.resolve()


def run_case(
    case_file: Path,
    *,
    adapters: list[CapabilityAdapter] | None = None,
    now: datetime | None = None,
) -> RunResult:
    """Run one case with explicit capability gates."""
    started = time.time()
    now = now or datetime.now()

    try:
        with case_file.open("r", encoding="utf-8") as handle:
            case = CaseRequest.model_validate(json.load(handle))
    except Exception as exc:
        return RunResult(
            case_id="unknown",
            status=Status.FAILED_INVALID_CONTRACT,
            error=f"Failed to load case: {exc}",
        )

    result = RunResult(case_id=case.case_id, status=Status.READY)

    if not case.input_image.exists() or not case.input_image.is_file():
        result.status = Status.BLOCKED_NO_INPUT
        result.error = f"Input image not found: {case.input_image}"
        _write_evidence(case, result, now, case_file)
        return result

    active_adapters = (
        [DeterministicEditorAdapter(), LocalCompareAdapter()] if adapters is None else adapters
    )
    result.capability_report = probe_capabilities(
        case.input_image,
        adapters=active_adapters,
        now=now,
    )

    if not result.capability_report.has_v0:
        result.status = Status.BLOCKED_NO_INPUT
        result.error = "V0 file access not available"
        _write_evidence(case, result, now, case_file)
        return result

    result.plan = case.plan
    result.parent_plan = case.parent_plan
    result.user_feedback = case.user_feedback
    if case.source_observation is not None:
        result.observation_result = case.source_observation
        if case.source_observation.input_sha256 != result.capability_report.input_sha256:
            result.status = Status.FAILED_INVALID_CONTRACT
            result.error = "source_observation input SHA-256 does not match V0 input"
            _write_evidence(case, result, now, case_file)
            return result

    if case.requested_phase == Phase.DIAGNOSIS:
        if not result.capability_report.has_v1:
            result.status = Status.BLOCKED_NO_VIEW_CAPABILITY
            result.error = "V1 visual observation required for diagnosis"
            _write_evidence(case, result, now, case_file)
            return result

        provider = result.capability_report.capabilities[Capability.V1_VISUAL_OBSERVATION].provider
        observer = next((adapter for adapter in active_adapters if adapter.name == provider), None)
        if observer is None:
            result.status = Status.FAILED_EXECUTION
            result.error = f"V1 provider adapter not found: {provider}"
            _write_evidence(case, result, now, case_file)
            return result

        try:
            observation = ObservationResult.model_validate(
                observer.observe(case.input_image, case.observation_prompt)
            )
            expected_prompt_sha256 = hashlib.sha256(
                case.observation_prompt.encode("utf-8")
            ).hexdigest()
            if observation.input_sha256 != result.capability_report.input_sha256:
                raise ValueError("Observation input SHA-256 does not match V0 input")
            if observation.prompt_sha256 != expected_prompt_sha256:
                raise ValueError("Observation prompt SHA-256 does not match request")
            if observation.provider != provider:
                raise ValueError("Observation provider does not match capability provider")
            if not observation.success:
                raise ValueError(observation.error or "Observation provider reported failure")
            result.observation_result = observation
        except Exception as exc:
            result.status = Status.FAILED_EXECUTION
            result.error = f"Visual observation failed: {exc}"
            _write_evidence(case, result, now, case_file)
            return result

    if case.requested_phase in (Phase.EDIT, Phase.FULL):
        if not case.operations:
            result.status = Status.FAILED_INVALID_CONTRACT
            result.error = "No operations specified for edit phase"
            _write_evidence(case, result, now, case_file)
            return result
        if not result.capability_report.has_v2:
            result.status = Status.BLOCKED_NO_EDIT_CAPABILITY
            result.error = "V2 image editing capability required"
            _write_evidence(case, result, now, case_file)
            return result

        if case.plan is None and any(request.level == "L3" for request in case.operations):
            result.status = Status.FAILED_INVALID_CONTRACT
            result.error = "L3 local adjustment requires a Visual Transformation Plan"
            _write_evidence(case, result, now, case_file)
            return result

        if case.plan:
            planned_operations = set(case.plan.operations)
            level_rank = {"L1": 1, "L2": 2, "L3": 3}
            for request in case.operations:
                if request.operation not in planned_operations:
                    result.status = Status.FAILED_INVALID_CONTRACT
                    result.error = (
                        f"Operation {request.operation.value} is not allowed by plan "
                        f"{case.plan.plan_id}"
                    )
                    _write_evidence(case, result, now, case_file)
                    return result
                if level_rank[request.level] > level_rank[case.plan.recommended_level]:
                    result.status = Status.FAILED_INVALID_CONTRACT
                    result.error = (
                        f"Operation level {request.level} exceeds plan recommended level "
                        f"{case.plan.recommended_level}"
                    )
                    _write_evidence(case, result, now, case_file)
                    return result

        editor = _provider_adapter(
            result.capability_report,
            Capability.V2_IMAGE_EDITING,
            active_adapters,
        )
        if editor is None or not callable(getattr(editor, "edit", None)):
            result.status = Status.FAILED_EXECUTION
            result.error = "Reported V2 provider has no executable edit operation"
            _write_evidence(case, result, now, case_file)
            return result

        candidate_ids: set[str] = set()
        reserved_outputs: list[Path] = []
        for index, request in enumerate(case.operations):
            candidate_id = request.candidate_id or f"{case.case_id}-candidate-{index + 1:02d}"
            if candidate_id in candidate_ids:
                result.status = Status.FAILED_INVALID_CONTRACT
                result.error = f"Duplicate candidate_id: {candidate_id}"
                _write_evidence(case, result, now, case_file)
                return result
            candidate_ids.add(candidate_id)

            if _paths_refer_to_same_file(request.output_image, case.input_image):
                result.status = Status.FAILED_INVALID_CONTRACT
                result.error = "Candidate output cannot overwrite or alias the original image"
                _write_evidence(case, result, now, case_file)
                return result
            if any(
                _paths_refer_to_same_file(request.output_image, existing)
                for existing in reserved_outputs
            ):
                result.status = Status.FAILED_INVALID_CONTRACT
                result.error = "Candidate output paths must be unique and must not alias"
                _write_evidence(case, result, now, case_file)
                return result
            reserved_outputs.append(request.output_image)

        for index, request in enumerate(case.operations):
            candidate_id = request.candidate_id or f"{case.case_id}-candidate-{index + 1:02d}"

            if request.parent_candidate_id == "original":
                expected_input = case.input_image.resolve()
                expected_hash = result.capability_report.input_sha256
            elif (
                index == 0
                and case.plan is not None
                and case.plan.decision_source.value == "hybrid"
                and request.parent_candidate_id == case.plan.parent_candidate_id
            ):
                expected_input = request.input_image.resolve()
                expected_hash = case.plan.parent_candidate_sha256 or ""
            else:
                parent = next(
                    (
                        item
                        for item in result.candidate_lineage
                        if item.candidate_id == request.parent_candidate_id
                    ),
                    None,
                )
                if parent is None:
                    result.status = Status.FAILED_INVALID_CONTRACT
                    result.error = f"Unknown parent candidate: {request.parent_candidate_id}"
                    _write_evidence(case, result, now, case_file)
                    return result
                expected_input = parent.output_path.resolve()
                expected_hash = parent.output_sha256
            if request.input_image.resolve() != expected_input:
                result.status = Status.FAILED_INVALID_CONTRACT
                result.error = f"Candidate {candidate_id} input does not match its parent"
                _write_evidence(case, result, now, case_file)
                return result
            if sha256_file(request.input_image) != expected_hash:
                result.status = Status.FAILED_INVALID_CONTRACT
                result.error = f"Candidate {candidate_id} parent SHA-256 mismatch"
                _write_evidence(case, result, now, case_file)
                return result

            try:
                edit_result = _execute_edit(editor, request)
            except Exception as exc:
                result.status = Status.FAILED_EXECUTION
                result.error = f"V2 provider {editor.name} edit failed: {exc}"
                _write_evidence(case, result, now, case_file)
                return result
            result.edit_results.append(edit_result)
            if not edit_result.success:
                result.status = Status.FAILED_EXECUTION
                result.error = f"Edit failed: {edit_result.error}"
                _write_evidence(case, result, now, case_file)
                return result
            try:
                current_input_hash = sha256_file(request.input_image)
                current_output_hash = sha256_file(request.output_image)
            except OSError as exc:
                result.status = Status.FAILED_EXECUTION
                result.error = f"Cannot verify candidate {candidate_id}: {exc}"
                _write_evidence(case, result, now, case_file)
                return result
            if (
                edit_result.operation != request.operation
                or edit_result.input_sha256 != expected_hash
                or current_input_hash != expected_hash
                or edit_result.output_sha256 != current_output_hash
            ):
                result.status = Status.FAILED_EXECUTION
                result.error = f"V2 provider returned inconsistent evidence for {candidate_id}"
                _write_evidence(case, result, now, case_file)
                return result
            if _paths_refer_to_same_file(request.output_image, case.input_image) or any(
                _paths_refer_to_same_file(request.output_image, item.output_path)
                for item in result.candidate_lineage
            ):
                result.status = Status.FAILED_EXECUTION
                result.error = f"V2 provider created an aliased output for {candidate_id}"
                _write_evidence(case, result, now, case_file)
                return result
            result.candidate_lineage.append(
                CandidateLineage(
                    candidate_id=candidate_id,
                    parent_candidate_id=request.parent_candidate_id,
                    plan_id=case.plan.plan_id if case.plan else "legacy-unplanned",
                    input_path=request.input_image.resolve(),
                    input_sha256=edit_result.input_sha256,
                    output_path=request.output_image.resolve(),
                    output_sha256=edit_result.output_sha256,
                    operation=request.operation,
                    parameters=request.parameters,
                    reversible=request.operation == EditOperation.LOCAL_ADJUSTMENT,
                )
            )

    if case.requested_phase in (Phase.COMPARE, Phase.FULL):
        if not result.capability_report.has_v3:
            result.status = Status.BLOCKED_NO_COMPARISON_CAPABILITY
            result.error = "V3 comparison capability required"
            _write_evidence(case, result, now, case_file)
            return result
        if not result.candidate_lineage and case.comparison_candidates:
            known_parents = {
                "original": (case.input_image.resolve(), result.capability_report.input_sha256)
            }
            for reference in case.comparison_candidates:
                parent = known_parents.get(reference.parent_candidate_id)
                if parent is None or parent[1] != reference.parent_sha256:
                    result.status = Status.FAILED_INVALID_CONTRACT
                    result.error = f"Invalid parent lineage for {reference.candidate_id}"
                    _write_evidence(case, result, now, case_file)
                    return result
                if (
                    not reference.image_path.exists()
                    or sha256_file(reference.image_path) != reference.image_sha256
                ):
                    result.status = Status.FAILED_INVALID_CONTRACT
                    result.error = f"Candidate SHA-256 mismatch for {reference.candidate_id}"
                    _write_evidence(case, result, now, case_file)
                    return result
                lineage = CandidateLineage(
                    candidate_id=reference.candidate_id,
                    parent_candidate_id=reference.parent_candidate_id,
                    plan_id=reference.plan_id,
                    input_path=parent[0],
                    input_sha256=reference.parent_sha256,
                    output_path=reference.image_path.resolve(),
                    output_sha256=reference.image_sha256,
                    operation=reference.operation,
                    parameters=reference.parameters,
                )
                result.candidate_lineage.append(lineage)
                known_parents[reference.candidate_id] = (
                    lineage.output_path,
                    lineage.output_sha256,
                )

        if not result.candidate_lineage:
            result.status = Status.BLOCKED_NO_CANDIDATE
            result.error = "No candidate available for comparison"
            _write_evidence(case, result, now, case_file)
            return result

        comparer = _provider_adapter(
            result.capability_report,
            Capability.V3_RESULT_COMPARISON,
            active_adapters,
        )
        if comparer is None or not callable(getattr(comparer, "compare", None)):
            result.status = Status.FAILED_EXECUTION
            result.error = "Reported V3 provider has no executable compare operation"
            _write_evidence(case, result, now, case_file)
            return result

        for index, lineage in enumerate(result.candidate_lineage):
            if (
                sha256_file(lineage.input_path) != lineage.input_sha256
                or sha256_file(lineage.output_path) != lineage.output_sha256
            ):
                result.status = Status.FAILED_EXECUTION
                result.error = (
                    f"Candidate lineage changed before comparison: {lineage.candidate_id}"
                )
                _write_evidence(case, result, now, case_file)
                return result
            report_dir = lineage.output_path.parent / "comparison" / f"candidate-{index:02d}"
            try:
                comparison = ComparisonResult.model_validate(
                    comparer.compare(
                        lineage.input_path,
                        lineage.output_path,
                        report_dir,
                        candidate_id=lineage.candidate_id,
                        parent_candidate_id=lineage.parent_candidate_id,
                        plan_id=lineage.plan_id,
                        operation=lineage.operation,
                        parameters=lineage.parameters,
                    )
                )
            except Exception as exc:
                result.status = Status.FAILED_EXECUTION
                result.error = f"V3 provider {comparer.name} comparison failed: {exc}"
                _write_evidence(case, result, now, case_file)
                return result
            result.comparison_results.append(comparison)
            if comparison.error or not comparison.candidate_readable:
                result.status = Status.FAILED_EXECUTION
                result.error = f"Candidate comparison failed: {comparison.error}"
                _write_evidence(case, result, now, case_file)
                return result
            if (
                comparison.candidate_id != lineage.candidate_id
                or comparison.parent_candidate_id != lineage.parent_candidate_id
                or comparison.plan_id != lineage.plan_id
                or comparison.original_sha256 != lineage.input_sha256
                or comparison.candidate_sha256 != lineage.output_sha256
                or comparison.operation != lineage.operation
            ):
                result.status = Status.FAILED_EXECUTION
                result.error = (
                    f"V3 provider returned inconsistent evidence for {lineage.candidate_id}"
                )
                _write_evidence(case, result, now, case_file)
                return result

    if case.requested_phase in (Phase.DIAGNOSIS, Phase.EDIT):
        result.status = Status.COMPLETED_PHASE
    elif case.user_feedback is None:
        result.status = Status.COMPLETED_WITH_USER_FEEDBACK_PENDING
    elif case.user_feedback.decision == UserFeedbackDecision.ACCEPTED:
        result.status = Status.COMPLETED
    elif case.user_feedback.decision == UserFeedbackDecision.REJECTED:
        result.status = Status.REJECTED
    else:
        result.status = Status.CHANGES_REQUESTED
    result.execution_time_ms = (time.time() - started) * 1000
    _write_evidence(case, result, now, case_file)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visual Art Direction Runner")
    parser.add_argument("--case", required=True, help="Path to case JSON file")
    parser.add_argument("--output", required=True, help="Output directory")
    v1_source = parser.add_mutually_exclusive_group()
    v1_source.add_argument("--host-config", help="Host bridge capability JSON")
    v1_source.add_argument(
        "--llama-cpp-config",
        help="Local llama.cpp Qwen3-VL adapter JSON",
    )
    args = parser.parse_args(argv)

    case_file = Path(args.case)
    if not case_file.exists():
        print(f"Error: Case file not found: {case_file}", file=sys.stderr)
        return 1

    external_adapters: list[CapabilityAdapter] = []
    try:
        if args.host_config:
            external_adapters.append(HostBridgeAdapter(Path(args.host_config)))
        if args.llama_cpp_config:
            external_adapters.append(LlamaCppQwenAdapter.from_json(Path(args.llama_cpp_config)))
    except (OSError, ValueError) as exc:
        print(f"Error: Failed to load adapter config: {exc}", file=sys.stderr)
        return 1
    adapters = (
        [*external_adapters, DeterministicEditorAdapter(), LocalCompareAdapter()]
        if external_adapters
        else None
    )
    result = run_case(case_file, adapters=adapters)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "run-result.json"
    result_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Status: {result.status.value}")
    print(f"Result written to: {result_path}")
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)
    if result.status in (
        Status.COMPLETED,
        Status.COMPLETED_PHASE,
        Status.COMPLETED_WITH_USER_FEEDBACK_PENDING,
        Status.REJECTED,
        Status.CHANGES_REQUESTED,
    ):
        return 0
    if result.status.value.startswith("blocked_"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
