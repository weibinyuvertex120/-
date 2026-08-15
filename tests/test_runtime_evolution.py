"""Regression tests for the executable Seeform runtime contract."""

# ruff: noqa: E402 -- the bundled Skill directory is intentionally added before imports.

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "visual-art-direction"
sys.path.insert(0, str(SKILL_ROOT))

from scripts.capability_probe import probe_capabilities
from scripts.compare_candidates import LocalCompareAdapter, compare_images
from scripts.contracts import (
    AdapterHealth,
    Capability,
    CaseRequest,
    ComparisonResult,
    EditOperation,
    EditRequest,
    EditResult,
    RunResult,
    Status,
)
from scripts.deterministic_editor import DeterministicEditorAdapter
from scripts.evidence import read_evidence, sha256_file
from scripts.runner import run_case


class RecordingEditAdapter:
    name = "recording-edit"
    version = "1.0.0"

    def __init__(self) -> None:
        self.calls: list[EditRequest] = []

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities={Capability.V2_IMAGE_EDITING},
            evidence="test edit adapter",
        )

    def capabilities(self) -> set[Capability]:
        return {Capability.V2_IMAGE_EDITING}

    def edit(self, request: EditRequest) -> EditResult:
        self.calls.append(request)
        return DeterministicEditorAdapter().edit(request)


class RecordingCompareAdapter:
    name = "recording-compare"
    version = "1.0.0"

    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path]] = []

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities={Capability.V3_RESULT_COMPARISON},
            evidence="test compare adapter",
        )

    def capabilities(self) -> set[Capability]:
        return {Capability.V3_RESULT_COMPARISON}

    def compare(
        self,
        original: Path,
        candidate: Path,
        report_dir: Path,
        *,
        candidate_id: str = "",
        parent_candidate_id: str = "",
        plan_id: str = "",
    ) -> ComparisonResult:
        self.calls.append((original, candidate))
        return compare_images(
            original,
            candidate,
            report_dir,
            candidate_id=candidate_id,
            parent_candidate_id=parent_candidate_id,
            plan_id=plan_id,
        )


def _image(path: Path, *, color: tuple[int, int, int] = (128, 128, 128)) -> Path:
    Image.new("RGB", (2, 2), color=color).save(path)
    return path


def _plan(*operations: str) -> dict:
    return {
        "plan_id": "plan-1",
        "visual_goal": "Make the subject easier to read without changing scene facts.",
        "recommended_level": "L3" if "local_adjustment" in operations else "L1",
        "operations": list(operations),
        "success_criteria": ["The requested bounded change is present."],
        "must_preserve": ["scene facts"],
        "allowed_changes": list(operations),
        "forbidden_changes": ["generation"],
        "stop_condition": "Stop after the bounded operation succeeds.",
    }


def test_scripts_module_is_the_single_bundle_entrypoint() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scripts", "--help"],
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Visual Art Direction Runner" in completed.stdout


def test_installed_command_points_to_the_same_runtime_main() -> None:
    pyproject = tomllib.loads(
        (SKILL_ROOT.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["scripts"]["seeform"] == "scripts.runner:main"


def test_case_contract_exposes_visual_transformation_plan() -> None:
    properties = CaseRequest.model_json_schema()["properties"]

    assert "plan" in properties


def test_editor_contract_exposes_local_reversible_adjustment() -> None:
    operations = {operation.value for operation in EditOperation}

    assert "local_adjustment" in operations


def test_v3_counts_changed_pixels_instead_of_rgb_channels(tmp_path: Path) -> None:
    original = _image(tmp_path / "original.png", color=(0, 0, 0))
    candidate = _image(tmp_path / "candidate.png", color=(0, 0, 0))
    with Image.open(candidate) as image:
        image.putpixel((1, 0), (255, 255, 255))
        image.save(candidate)

    result = compare_images(original, candidate, tmp_path / "report")

    assert result.pixel_change_summary == "1/4 pixels changed (25.0%)"
    assert result.change_bounding_box == (1, 0, 2, 1)


def test_v3_exposes_stable_numeric_metrics_and_candidate_inputs() -> None:
    comparison_properties = ComparisonResult.model_json_schema()["properties"]
    case_properties = CaseRequest.model_json_schema()["properties"]

    assert {"changed_pixels", "total_pixels", "change_ratio", "size_matches"} <= set(
        comparison_properties
    )
    assert "comparison_candidates" in case_properties


def test_run_result_exposes_candidate_lineage() -> None:
    properties = RunResult.model_json_schema()["properties"]

    assert "candidate_lineage" in properties


def test_capability_report_serializes_complete_fields(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")

    report = probe_capabilities(
        input_image,
        adapters=[DeterministicEditorAdapter(), LocalCompareAdapter()],
    )
    payload = report.model_dump(mode="json")

    assert payload["input_exists"] is True
    assert payload["adapters_checked"] == ["deterministic-pillow", "local-compare"]
    assert payload["has_v0"] is True
    assert payload["has_v1"] is False
    assert payload["has_v2"] is True
    assert payload["has_v3"] is True


def test_plan_rejects_an_operation_outside_its_contract(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")
    output_image = tmp_path / "output.png"
    case = {
        "case_id": "plan-mismatch",
        "input_image": str(input_image.resolve()),
        "requested_phase": "edit",
        "truth_mode": "表达",
        "plan": _plan("crop"),
        "operations": [
            {
                "case_id": "plan-mismatch",
                "input_image": str(input_image.resolve()),
                "level": "L1",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.2},
                "output_image": str(output_image.resolve()),
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file)

    assert result.status == Status.FAILED_INVALID_CONTRACT
    assert "plan" in result.error.lower()
    assert not output_image.exists()


def test_plan_rejects_an_operation_above_recommended_level(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")
    output_image = tmp_path / "output.png"
    plan = _plan("crop")
    plan["recommended_level"] = "L1"
    case = {
        "case_id": "plan-level-mismatch",
        "input_image": str(input_image.resolve()),
        "requested_phase": "edit",
        "plan": plan,
        "operations": [
            {
                "case_id": "plan-level-mismatch",
                "input_image": str(input_image.resolve()),
                "level": "L2",
                "operation": "crop",
                "parameters": {"box": [0, 0, 1, 1]},
                "output_image": str(output_image.resolve()),
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file)

    assert result.status == Status.FAILED_INVALID_CONTRACT
    assert "recommended level" in result.error.lower()


def test_local_adjustment_changes_only_the_bounded_region(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png", color=(100, 100, 100))
    output_image = tmp_path / "output.png"
    request = EditRequest(
        case_id="local-adjustment",
        input_image=input_image.resolve(),
        level="L3",
        operation="local_adjustment",
        parameters={
            "box": [1, 0, 2, 1],
            "exposure": 0.5,
            "contrast": 1.0,
            "saturation": 1.0,
            "feather": 0,
        },
        output_image=output_image.resolve(),
        candidate_id="candidate-local",
    )

    result = DeterministicEditorAdapter().edit(request)

    assert result.success, result.error
    assert sha256_file(input_image) != result.output_sha256
    with Image.open(input_image) as original, Image.open(output_image) as candidate:
        assert candidate.getpixel((0, 0)) == original.getpixel((0, 0))
        assert candidate.getpixel((1, 0)) != original.getpixel((1, 0))


def test_edit_operation_rejects_an_incorrect_level(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")

    with pytest.raises(ValidationError, match="requires level L3"):
        EditRequest(
            case_id="wrong-level",
            input_image=input_image.resolve(),
            level="L1",
            operation="local_adjustment",
            parameters={"box": [0, 0, 1, 1]},
            output_image=(tmp_path / "output.png").resolve(),
        )


def test_l3_local_adjustment_requires_a_plan(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")
    output_image = tmp_path / "output.png"
    case = {
        "case_id": "unplanned-local",
        "input_image": str(input_image.resolve()),
        "requested_phase": "edit",
        "operations": [
            {
                "case_id": "unplanned-local",
                "input_image": str(input_image.resolve()),
                "level": "L3",
                "operation": "local_adjustment",
                "parameters": {"box": [0, 0, 1, 1], "exposure": 0.2},
                "output_image": str(output_image.resolve()),
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file)

    assert result.status == Status.FAILED_INVALID_CONTRACT
    assert "requires a visual transformation plan" in result.error.lower()


def test_compare_phase_accepts_existing_candidate_with_lineage(tmp_path: Path) -> None:
    original = _image(tmp_path / "original.png", color=(0, 0, 0))
    candidate = _image(tmp_path / "candidate.png", color=(0, 0, 0))
    with Image.open(candidate) as image:
        image.putpixel((0, 0), (255, 255, 255))
        image.save(candidate)
    case = {
        "case_id": "compare-existing",
        "input_image": str(original.resolve()),
        "requested_phase": "compare",
        "comparison_candidates": [
            {
                "candidate_id": "candidate-existing",
                "image_path": str(candidate.resolve()),
                "image_sha256": sha256_file(candidate),
                "parent_candidate_id": "original",
                "parent_sha256": sha256_file(original),
                "plan_id": "plan-external",
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file)

    assert result.status == Status.COMPLETED_WITH_USER_CONFIRMATION_PENDING
    assert result.comparison_results[0].candidate_id == "candidate-existing"
    assert result.comparison_results[0].changed_pixels == 1
    assert result.candidate_lineage[0].parent_candidate_id == "original"
    report_payload = json.loads(
        result.comparison_results[0].report_json_path.read_text(encoding="utf-8")
    )
    assert report_payload["candidate_id"] == "candidate-existing"
    assert report_payload["parent_candidate_id"] == "original"
    assert report_payload["plan_id"] == "plan-external"
    html_report = result.comparison_results[0].report_html_path.read_text(encoding="utf-8")
    assert "candidate-existing" in html_report
    assert "plan-external" in html_report


def test_edit_records_plan_lineage_and_complete_capabilities(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")
    output_image = tmp_path / "output.png"
    case = {
        "case_id": "lineage-edit",
        "input_image": str(input_image.resolve()),
        "requested_phase": "edit",
        "truth_mode": "表达",
        "plan": _plan("exposure_contrast_color"),
        "operations": [
            {
                "case_id": "lineage-edit",
                "input_image": str(input_image.resolve()),
                "level": "L1",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.2},
                "output_image": str(output_image.resolve()),
                "candidate_id": "candidate-a",
                "parent_candidate_id": "original",
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file)

    assert result.status == Status.COMPLETED_WITH_USER_CONFIRMATION_PENDING
    assert result.plan is not None and result.plan.plan_id == "plan-1"
    assert len(result.candidate_lineage) == 1
    lineage = result.candidate_lineage[0]
    assert lineage.candidate_id == "candidate-a"
    assert lineage.parent_candidate_id == "original"
    assert lineage.input_sha256 == sha256_file(input_image)
    assert lineage.output_sha256 == sha256_file(output_image)
    evidence = read_evidence(result.evidence_path)
    assert evidence.plan is not None and evidence.plan.plan_id == "plan-1"
    assert evidence.candidate_lineage[0].candidate_id == "candidate-a"
    assert evidence.capability_report["input_exists"] is True
    assert evidence.capability_report["has_v2"] is True
    assert evidence.capability_report["adapters_checked"] == [
        "deterministic-pillow",
        "local-compare",
    ]


def test_cli_returns_blocked_exit_code_and_writes_result(tmp_path: Path) -> None:
    case_file = tmp_path / "case.json"
    output_dir = tmp_path / "output"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "missing-input",
                "input_image": str((tmp_path / "missing.png").resolve()),
                "requested_phase": "diagnosis",
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts",
            "--case",
            str(case_file),
            "--output",
            str(output_dir),
        ],
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads((output_dir / "run-result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "blocked_no_input"


def test_editor_rejects_hardlink_output_without_changing_original(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png", color=(80, 80, 80))
    output_alias = tmp_path / "output.png"
    original_hash = sha256_file(input_image)
    os.link(input_image, output_alias)
    request = EditRequest(
        case_id="hardlink-output",
        input_image=input_image.resolve(),
        level="L1",
        operation="exposure_contrast_color",
        parameters={"exposure": 0.5},
        output_image=output_alias.resolve(),
    )

    result = DeterministicEditorAdapter().edit(request)

    assert not result.success
    assert "same file" in result.error.lower()
    assert sha256_file(input_image) == original_hash


def test_runner_dispatches_edit_to_reported_v2_provider(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")
    output_image = tmp_path / "output.png"
    adapter = RecordingEditAdapter()
    case = {
        "case_id": "adapter-edit",
        "input_image": str(input_image.resolve()),
        "requested_phase": "edit",
        "operations": [
            {
                "case_id": "adapter-edit",
                "input_image": str(input_image.resolve()),
                "level": "L1",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.2},
                "output_image": str(output_image.resolve()),
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file, adapters=[adapter])

    assert result.status == Status.COMPLETED_WITH_USER_CONFIRMATION_PENDING
    assert len(adapter.calls) == 1


def test_runner_dispatches_comparison_to_reported_v3_provider(tmp_path: Path) -> None:
    original = _image(tmp_path / "original.png", color=(0, 0, 0))
    candidate = _image(tmp_path / "candidate.png", color=(255, 255, 255))
    adapter = RecordingCompareAdapter()
    case = {
        "case_id": "adapter-compare",
        "input_image": str(original.resolve()),
        "requested_phase": "compare",
        "comparison_candidates": [
            {
                "candidate_id": "candidate-a",
                "image_path": str(candidate.resolve()),
                "image_sha256": sha256_file(candidate),
                "parent_candidate_id": "original",
                "parent_sha256": sha256_file(original),
                "plan_id": "plan-a",
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file, adapters=[adapter])

    assert result.status == Status.COMPLETED_WITH_USER_CONFIRMATION_PENDING
    assert adapter.calls == [(original.resolve(), candidate.resolve())]


def test_runner_rejects_duplicate_candidate_output_paths_before_editing(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")
    output_image = tmp_path / "same-output.png"
    operations = []
    for candidate_id, exposure in (("candidate-a", 0.1), ("candidate-b", 0.2)):
        operations.append(
            {
                "case_id": "duplicate-output",
                "input_image": str(input_image.resolve()),
                "level": "L1",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": exposure},
                "output_image": str(output_image.resolve()),
                "candidate_id": candidate_id,
            }
        )
    case_file = tmp_path / "case.json"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "duplicate-output",
                "input_image": str(input_image.resolve()),
                "requested_phase": "edit",
                "operations": operations,
            }
        ),
        encoding="utf-8",
    )

    result = run_case(case_file)

    assert result.status == Status.FAILED_INVALID_CONTRACT
    assert "output" in result.error.lower()
    assert not output_image.exists()


def test_runner_returns_invalid_contract_for_malformed_parameters(tmp_path: Path) -> None:
    input_image = _image(tmp_path / "input.png")
    case_file = tmp_path / "case.json"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "bad-parameters",
                "input_image": str(input_image.resolve()),
                "requested_phase": "edit",
                "operations": [
                    {
                        "case_id": "bad-parameters",
                        "input_image": str(input_image.resolve()),
                        "level": "L1",
                        "operation": "exposure_contrast_color",
                        "parameters": {"exposure": "bad"},
                        "output_image": str((tmp_path / "output.png").resolve()),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_case(case_file)

    assert result.status == Status.FAILED_INVALID_CONTRACT
    assert "exposure" in result.error.lower()


def test_case_rejects_duplicate_comparison_ids_and_mixed_candidate_sources(
    tmp_path: Path,
) -> None:
    input_image = _image(tmp_path / "input.png")
    candidate = _image(tmp_path / "candidate.png")
    reference = {
        "candidate_id": "candidate-a",
        "image_path": str(candidate.resolve()),
        "image_sha256": sha256_file(candidate),
        "parent_candidate_id": "original",
        "parent_sha256": sha256_file(input_image),
        "plan_id": "plan-a",
    }
    base = {
        "case_id": "invalid-candidates",
        "input_image": str(input_image.resolve()),
        "requested_phase": "compare",
    }

    duplicate_file = tmp_path / "duplicate.json"
    duplicate_file.write_text(
        json.dumps({**base, "comparison_candidates": [reference, reference]}),
        encoding="utf-8",
    )
    duplicate_result = run_case(duplicate_file)

    mixed_file = tmp_path / "mixed.json"
    mixed_file.write_text(
        json.dumps(
            {
                **base,
                "requested_phase": "full",
                "comparison_candidates": [reference],
                "operations": [
                    {
                        "case_id": "invalid-candidates",
                        "input_image": str(input_image.resolve()),
                        "level": "L1",
                        "operation": "exposure_contrast_color",
                        "output_image": str((tmp_path / "output.png").resolve()),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    mixed_result = run_case(mixed_file)

    assert duplicate_result.status == Status.FAILED_INVALID_CONTRACT
    assert "duplicate" in duplicate_result.error.lower()
    assert mixed_result.status == Status.FAILED_INVALID_CONTRACT
    assert "both" in mixed_result.error.lower()


def test_html_comparison_report_escapes_lineage_fields(tmp_path: Path) -> None:
    original = _image(tmp_path / "original.png")
    candidate = _image(tmp_path / "candidate.png", color=(255, 255, 255))

    result = compare_images(
        original,
        candidate,
        tmp_path / "report",
        candidate_id="<script>alert(1)</script>",
        parent_candidate_id="parent<&>",
        plan_id='plan"quoted',
    )
    html = result.report_html_path.read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
