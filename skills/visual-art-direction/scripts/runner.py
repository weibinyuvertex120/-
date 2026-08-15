"""Single-case runner for the visual-art-direction runtime."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .capability_probe import CapabilityAdapter, probe_capabilities
from .compare_candidates import LocalCompareAdapter, compare_images
from .contracts import (
    CaseRequest,
    EditRequest,
    EditResult,
    EvidenceRecord,
    Phase,
    RunResult,
    Status,
    UserConfirmationStatus,
)
from .deterministic_editor import DeterministicEditorAdapter
from .evidence import write_evidence


def _execute_edit(request: EditRequest) -> EditResult:
    """Execute a bounded operation through the deterministic adapter."""
    return DeterministicEditorAdapter().edit(request)


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

    capability_report = {}
    if result.capability_report:
        capability_report = {
            capability.value: state.model_dump(mode="json")
            for capability, state in result.capability_report.capabilities.items()
        }

    evidence = EvidenceRecord(
        case_id=case.case_id,
        timestamp=now,
        input_path=str(case.input_image.resolve()),
        input_sha256=(result.capability_report.input_sha256 if result.capability_report else ""),
        capability_report=capability_report,
        operations=operations,
        comparisons=[
            comparison.model_dump(mode="json") for comparison in result.comparison_results
        ],
        user_confirmation=case.user_confirmation_status,
        status=result.status,
        residual_risks=[
            "Deterministic V2 is limited to Pillow L1/L2 operations",
            "Engineering comparison does not replace visual or aesthetic judgment",
            "User confirmation is recorded separately and remains required",
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

    if case.requested_phase in (Phase.DIAGNOSIS, Phase.FULL):
        if not result.capability_report.has_v1:
            result.status = Status.BLOCKED_NO_VIEW_CAPABILITY
            result.error = "V1 visual observation required for diagnosis"
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

        for request in case.operations:
            if request.output_image.resolve() == case.input_image.resolve():
                result.status = Status.FAILED_INVALID_CONTRACT
                result.error = "Cannot overwrite original image"
                result.edit_results.append(
                    EditResult(
                        success=False,
                        operation=request.operation,
                        parameters=request.parameters,
                        error=result.error,
                    )
                )
                _write_evidence(case, result, now, case_file)
                return result

            edit_result = _execute_edit(request)
            result.edit_results.append(edit_result)
            if not edit_result.success:
                result.status = Status.FAILED_EXECUTION
                result.error = f"Edit failed: {edit_result.error}"
                _write_evidence(case, result, now, case_file)
                return result

    if case.requested_phase in (Phase.COMPARE, Phase.FULL):
        if not result.capability_report.has_v3:
            result.status = Status.BLOCKED_NO_COMPARISON_CAPABILITY
            result.error = "V3 comparison capability required"
            _write_evidence(case, result, now, case_file)
            return result
        if not result.edit_results:
            result.status = Status.BLOCKED_NO_CANDIDATE
            result.error = "No candidate available for comparison"
            _write_evidence(case, result, now, case_file)
            return result

        for index, (request, edit_result) in enumerate(
            zip(case.operations, result.edit_results, strict=True)
        ):
            if not edit_result.success:
                continue
            report_dir = (
                request.output_image.parent
                / "comparison"
                / f"{index:02d}_{request.output_image.stem}"
            )
            comparison = compare_images(
                case.input_image,
                request.output_image,
                report_dir,
            )
            result.comparison_results.append(comparison)
            if not comparison.candidate_readable:
                result.status = Status.FAILED_EXECUTION
                result.error = f"Candidate comparison failed: {comparison.error}"
                _write_evidence(case, result, now, case_file)
                return result

    result.status = (
        Status.COMPLETED_WITH_USER_CONFIRMATION_PENDING
        if case.user_confirmation_status == UserConfirmationStatus.PENDING
        else Status.COMPLETED
    )
    result.execution_time_ms = (time.time() - started) * 1000
    _write_evidence(case, result, now, case_file)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Visual Art Direction Runner")
    parser.add_argument("--case", required=True, help="Path to case JSON file")
    parser.add_argument("--output", required=True, help="Output directory")
    args = parser.parse_args()

    case_file = Path(args.case)
    if not case_file.exists():
        print(f"Error: Case file not found: {case_file}", file=sys.stderr)
        raise SystemExit(1)

    result = run_case(case_file)
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


if __name__ == "__main__":
    main()
