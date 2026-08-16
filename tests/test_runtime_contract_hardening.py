"""Contract hardening tests for Seeform phase, decisions, and feedback."""

# ruff: noqa: E402 -- the Skill source directory must win import resolution.

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "visual-art-direction"
sys.path.insert(0, str(SKILL_ROOT))

from scripts.compare_candidates import compare_images
from scripts.contracts import (
    CaseRequest,
    ComparisonResult,
    Status,
    TruthMode,
    UserFeedback,
    VisualTransformationPlan,
    canonical_plan_sha256,
    canonical_user_feedback_sha256,
)
from scripts.evidence import read_evidence, sha256_file
from scripts.runner import run_case


def _image(
    path: Path,
    *,
    size: tuple[int, int] = (4, 4),
    color: tuple[int, int, int] = (100, 120, 140),
) -> Path:
    Image.new("RGB", size, color=color).save(path)
    return path


def _observation(image: Path, prompt: str = "Record visible facts only.") -> dict:
    return {
        "success": True,
        "provider": "test-observer",
        "provider_version": "1.0.0",
        "input_sha256": sha256_file(image),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "items": [
            {
                "dimension": "scene",
                "statement": "A centered subject is visible.",
                "evidence": ["The subject occupies the center of the frame."],
                "confidence": "high",
            }
        ],
        "uncertainties": [],
        "error": "",
    }


def _canonical_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan(observation: dict, *operations: str) -> dict:
    return {
        "plan_id": "plan-observed",
        "visual_goal": "Make the subject easier to read without changing scene facts.",
        "recommended_level": "L2",
        "operations": list(operations),
        "success_criteria": ["The requested bounded change is present."],
        "must_preserve": ["scene facts"],
        "allowed_changes": list(operations),
        "forbidden_changes": ["generation"],
        "stop_condition": "Stop after the bounded operation succeeds.",
        "decision_source": "agent",
        "basis": [
            {
                "observation_index": 0,
                "dimension": "scene",
                "evidence": "The subject occupies the center of the frame.",
            }
        ],
        "observation_sha256": _canonical_sha256(observation),
    }


@pytest.mark.parametrize(
    ("phase", "source", "message"),
    [
        ("diagnosis", "operation", "diagnosis"),
        ("edit", "none", "edit"),
        ("compare", "none", "compare"),
        ("full", "candidate", "full"),
    ],
)
def test_phase_contract_rejects_semantically_invalid_sources(
    tmp_path: Path,
    phase: str,
    source: str,
    message: str,
) -> None:
    image = _image(tmp_path / "input.png")
    candidate = _image(tmp_path / "candidate.png", color=(120, 140, 160))
    operations = []
    comparison_candidates = []
    if source == "operation":
        operations = [
            {
                "case_id": "phase-contract",
                "input_image": str(image.resolve()),
                "level": "L1",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.1},
                "output_image": str((tmp_path / "output.png").resolve()),
            }
        ]
    if source == "candidate":
        comparison_candidates = [
            {
                "candidate_id": "candidate-existing",
                "image_path": str(candidate.resolve()),
                "image_sha256": sha256_file(candidate),
                "parent_candidate_id": "original",
                "parent_sha256": sha256_file(image),
                "plan_id": "plan-existing",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.1},
            }
        ]
    payload = {
        "case_id": "phase-contract",
        "input_image": str(image.resolve()),
        "requested_phase": phase,
        "operations": operations,
        "comparison_candidates": comparison_candidates,
    }

    with pytest.raises(ValidationError, match=message):
        CaseRequest.model_validate(payload)


def test_old_confirmation_field_cannot_claim_user_approval(tmp_path: Path) -> None:
    image = _image(tmp_path / "input.png")

    with pytest.raises(ValidationError, match="user_confirmation_status"):
        CaseRequest.model_validate(
            {
                "case_id": "forged-confirmation",
                "input_image": str(image.resolve()),
                "requested_phase": "diagnosis",
                "user_confirmation_status": "confirmed",
            }
        )


def test_case_defaults_to_expression_mode_for_product_surface(tmp_path: Path) -> None:
    image = _image(tmp_path / "input.png")

    case = CaseRequest.model_validate(
        {
            "case_id": "default-expression-mode",
            "input_image": str(image.resolve()),
            "requested_phase": "diagnosis",
        }
    )

    assert case.truth_mode == TruthMode.EXPRESSION


def test_plan_binds_to_a_structured_source_observation(tmp_path: Path) -> None:
    image = _image(tmp_path / "input.png")
    observation = _observation(image)
    output = tmp_path / "candidate.png"
    case = CaseRequest.model_validate(
        {
            "case_id": "observed-plan",
            "input_image": str(image.resolve()),
            "requested_phase": "edit",
            "source_observation": observation,
            "plan": _plan(observation, "crop"),
            "operations": [
                {
                    "case_id": "observed-plan",
                    "input_image": str(image.resolve()),
                    "level": "L2",
                    "operation": "crop",
                    "parameters": {"box": [0, 0, 2, 2]},
                    "output_image": str(output.resolve()),
                    "candidate_id": "candidate-crop",
                }
            ],
        }
    )

    assert case.plan is not None
    assert case.plan.decision_source.value == "agent"
    assert case.plan.observation_sha256 == _canonical_sha256(observation)
    assert case.source_observation is not None


def test_plan_rejects_an_observation_hash_mismatch(tmp_path: Path) -> None:
    image = _image(tmp_path / "input.png")
    observation = _observation(image)
    plan = _plan(observation, "crop")
    plan["observation_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="observation_sha256"):
        CaseRequest.model_validate(
            {
                "case_id": "bad-observation-link",
                "input_image": str(image.resolve()),
                "requested_phase": "edit",
                "source_observation": observation,
                "plan": plan,
                "operations": [
                    {
                        "case_id": "bad-observation-link",
                        "input_image": str(image.resolve()),
                        "level": "L2",
                        "operation": "crop",
                        "parameters": {"box": [0, 0, 2, 2]},
                        "output_image": str((tmp_path / "candidate.png").resolve()),
                    }
                ],
            }
        )


def test_full_consumes_the_bound_source_observation_without_reobserving(
    tmp_path: Path,
) -> None:
    image = _image(tmp_path / "input.png")
    observation = _observation(image)
    output = tmp_path / "candidate.png"
    case_file = tmp_path / "case.json"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "staged-full",
                "input_image": str(image.resolve()),
                "requested_phase": "full",
                "source_observation": observation,
                "plan": _plan(observation, "exposure_contrast_color"),
                "operations": [
                    {
                        "case_id": "staged-full",
                        "input_image": str(image.resolve()),
                        "level": "L1",
                        "operation": "exposure_contrast_color",
                        "parameters": {"exposure": 0.1},
                        "output_image": str(output.resolve()),
                        "candidate_id": "candidate-full",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_case(case_file)

    assert result.status == Status.COMPLETED_WITH_USER_FEEDBACK_PENDING
    assert result.observation_result is not None
    assert result.observation_result.provider == "test-observer"
    assert len(result.edit_results) == 1
    assert len(result.comparison_results) == 1


def test_hybrid_plan_requires_feedback_and_parent_lineage(tmp_path: Path) -> None:
    image = _image(tmp_path / "input.png")
    observation = _observation(image)
    output = tmp_path / "candidate.png"
    plan = _plan(observation, "exposure_contrast_color")
    plan["decision_source"] = "hybrid"

    with pytest.raises(ValidationError, match="trigger_feedback_id"):
        CaseRequest.model_validate(
            {
                "case_id": "hybrid-plan",
                "input_image": str(image.resolve()),
                "requested_phase": "edit",
                "source_observation": observation,
                "plan": plan,
                "operations": [
                    {
                        "case_id": "hybrid-plan",
                        "input_image": str(image.resolve()),
                        "level": "L1",
                        "operation": "exposure_contrast_color",
                        "parameters": {"exposure": 0.1},
                        "output_image": str(output.resolve()),
                    }
                ],
            }
        )


def test_hybrid_plan_validates_feedback_and_external_parent_candidate(
    tmp_path: Path,
) -> None:
    image = _image(tmp_path / "input.png")
    parent = _image(tmp_path / "parent.png", color=(150, 130, 110))
    observation = _observation(image)
    feedback = UserFeedback.model_validate(
        {
            "feedback_id": "feedback-001",
            "case_id": "compare-case",
            "candidate_id": "candidate-real-crop",
            "candidate_sha256": sha256_file(parent),
            "decision": "changes_requested",
            "comment": "Reduce the empty sky further while keeping the road and mountain.",
            "source_event_id": "user-event-001",
            "submitted_at": "2026-08-16T12:00:00+00:00",
        }
    )
    parent_plan = _plan(observation, "exposure_contrast_color")
    parent_plan["plan_id"] = "plan-real-crop-001"
    plan = _plan(observation, "exposure_contrast_color")
    plan.update(
        {
            "decision_source": "hybrid",
            "parent_plan_id": "plan-real-crop-001",
            "parent_plan_sha256": canonical_plan_sha256(
                VisualTransformationPlan.model_validate(parent_plan)
            ),
            "trigger_feedback_id": feedback.feedback_id,
            "trigger_feedback_sha256": canonical_user_feedback_sha256(feedback),
            "parent_candidate_id": feedback.candidate_id,
            "parent_candidate_sha256": feedback.candidate_sha256,
        }
    )
    output = tmp_path / "next.png"
    case_file = tmp_path / "case.json"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "hybrid-next",
                "input_image": str(image.resolve()),
                "requested_phase": "edit",
                "source_observation": observation,
                "trigger_feedback": feedback.model_dump(mode="json"),
                "parent_plan": parent_plan,
                "plan": plan,
                "operations": [
                    {
                        "case_id": "hybrid-next",
                        "input_image": str(parent.resolve()),
                        "level": "L1",
                        "operation": "exposure_contrast_color",
                        "parameters": {"exposure": 0.1},
                        "output_image": str(output.resolve()),
                        "candidate_id": "candidate-next",
                        "parent_candidate_id": feedback.candidate_id,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_case(case_file)

    assert result.status == Status.COMPLETED_PHASE
    assert result.candidate_lineage[0].parent_candidate_id == "candidate-real-crop"
    assert result.plan is not None
    assert result.plan.decision_source.value == "hybrid"
    assert result.parent_plan is not None
    assert result.parent_plan.plan_id == "plan-real-crop-001"
    assert result.evidence_path is not None
    evidence = read_evidence(result.evidence_path)
    assert evidence.parent_plan is not None
    assert evidence.parent_plan.plan_id == "plan-real-crop-001"


def test_hybrid_plan_rejects_parent_plan_id_without_bound_parent_artifact(
    tmp_path: Path,
) -> None:
    image = _image(tmp_path / "input.png")
    parent = _image(tmp_path / "parent.png", color=(150, 130, 110))
    observation = _observation(image)
    feedback = UserFeedback.model_validate(
        {
            "feedback_id": "feedback-parent-plan",
            "case_id": "hybrid-parent-plan",
            "candidate_id": "candidate-parent",
            "candidate_sha256": sha256_file(parent),
            "decision": "changes_requested",
            "comment": "Keep the subject readable while reducing empty space.",
            "source_event_id": "user-event-parent-plan",
            "submitted_at": "2026-08-16T12:00:00+00:00",
        }
    )
    plan = _plan(observation, "exposure_contrast_color")
    plan.update(
        {
            "decision_source": "hybrid",
            "parent_plan_id": "parent-plan-without-artifact",
            "parent_plan_sha256": "0" * 64,
            "trigger_feedback_id": feedback.feedback_id,
            "trigger_feedback_sha256": canonical_user_feedback_sha256(feedback),
            "parent_candidate_id": feedback.candidate_id,
            "parent_candidate_sha256": feedback.candidate_sha256,
        }
    )

    with pytest.raises(ValidationError, match="parent_plan"):
        CaseRequest.model_validate(
            {
                "case_id": "hybrid-parent-plan",
                "input_image": str(image.resolve()),
                "requested_phase": "edit",
                "source_observation": observation,
                "trigger_feedback": feedback.model_dump(mode="json"),
                "plan": plan,
                "operations": [
                    {
                        "case_id": "hybrid-parent-plan",
                        "input_image": str(parent.resolve()),
                        "level": "L1",
                        "operation": "exposure_contrast_color",
                        "parameters": {"exposure": 0.1},
                        "output_image": str((tmp_path / "next.png").resolve()),
                        "candidate_id": "candidate-next",
                        "parent_candidate_id": feedback.candidate_id,
                    }
                ],
            }
        )


def test_hybrid_plan_rejects_parent_plan_hash_mismatch(tmp_path: Path) -> None:
    image = _image(tmp_path / "input.png")
    parent = _image(tmp_path / "parent.png", color=(150, 130, 110))
    observation = _observation(image)
    feedback = UserFeedback.model_validate(
        {
            "feedback_id": "feedback-parent-hash",
            "case_id": "hybrid-parent-hash",
            "candidate_id": "candidate-parent",
            "candidate_sha256": sha256_file(parent),
            "decision": "changes_requested",
            "comment": "Keep the subject readable while reducing empty space.",
            "source_event_id": "user-event-parent-hash",
            "submitted_at": "2026-08-16T12:00:00+00:00",
        }
    )
    parent_plan = _plan(observation, "exposure_contrast_color")
    parent_plan["plan_id"] = "parent-plan-hash"
    plan = _plan(observation, "exposure_contrast_color")
    plan.update(
        {
            "decision_source": "hybrid",
            "parent_plan_id": parent_plan["plan_id"],
            "parent_plan_sha256": "0" * 64,
            "trigger_feedback_id": feedback.feedback_id,
            "trigger_feedback_sha256": canonical_user_feedback_sha256(feedback),
            "parent_candidate_id": feedback.candidate_id,
            "parent_candidate_sha256": feedback.candidate_sha256,
        }
    )

    with pytest.raises(ValidationError, match="parent_plan_sha256"):
        CaseRequest.model_validate(
            {
                "case_id": "hybrid-parent-hash",
                "input_image": str(image.resolve()),
                "requested_phase": "edit",
                "source_observation": observation,
                "trigger_feedback": feedback.model_dump(mode="json"),
                "parent_plan": parent_plan,
                "plan": plan,
                "operations": [
                    {
                        "case_id": "hybrid-parent-hash",
                        "input_image": str(parent.resolve()),
                        "level": "L1",
                        "operation": "exposure_contrast_color",
                        "parameters": {"exposure": 0.1},
                        "output_image": str((tmp_path / "next.png").resolve()),
                        "candidate_id": "candidate-next",
                        "parent_candidate_id": feedback.candidate_id,
                    }
                ],
            }
        )


def test_crop_comparison_reports_operation_aware_area_metrics(tmp_path: Path) -> None:
    original = _image(tmp_path / "original.png", size=(4, 4))
    with Image.open(original) as source:
        source.crop((1, 1, 4, 3)).save(tmp_path / "candidate.png")

    result = compare_images(
        original,
        tmp_path / "candidate.png",
        tmp_path / "report",
        candidate_id="candidate-crop",
        parent_candidate_id="original",
        plan_id="plan-crop",
        operation="crop",
        parameters={"box": [1, 1, 4, 3]},
    )

    assert result.operation.value == "crop"
    assert result.crop_box == (1, 1, 4, 3)
    assert result.source_area_pixels == 16
    assert result.retained_area_pixels == 6
    assert result.removed_area_pixels == 10
    assert result.retained_ratio == pytest.approx(0.375)
    assert result.removed_ratio == pytest.approx(0.625)


def test_compare_feedback_is_bound_to_the_reviewed_candidate(tmp_path: Path) -> None:
    original = _image(tmp_path / "original.png")
    candidate = _image(tmp_path / "candidate.png", color=(120, 140, 160))
    case = {
        "case_id": "feedback-case",
        "input_image": str(original.resolve()),
        "requested_phase": "compare",
        "comparison_candidates": [
            {
                "candidate_id": "candidate-final",
                "image_path": str(candidate.resolve()),
                "image_sha256": sha256_file(candidate),
                "parent_candidate_id": "original",
                "parent_sha256": sha256_file(original),
                "plan_id": "plan-final",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.1},
            }
        ],
        "user_feedback": {
            "feedback_id": "feedback-001",
            "case_id": "feedback-case",
            "candidate_id": "candidate-final",
            "candidate_sha256": sha256_file(candidate),
            "decision": "accepted",
            "comment": "This is the version I approve.",
            "source_event_id": "host-event-001",
            "submitted_at": datetime.now(UTC).isoformat(),
        },
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(case_file)

    assert result.status == Status.COMPLETED
    assert result.user_feedback is not None
    assert result.user_feedback.candidate_sha256 == sha256_file(candidate)


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [("rejected", "rejected"), ("changes_requested", "changes_requested")],
)
def test_negative_user_feedback_never_becomes_completed(
    tmp_path: Path,
    decision: str,
    expected_status: str,
) -> None:
    original = _image(tmp_path / "original.png")
    candidate = _image(tmp_path / "candidate.png", color=(130, 150, 170))
    candidate_hash = sha256_file(candidate)
    case_file = tmp_path / "case.json"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "negative-feedback",
                "input_image": str(original.resolve()),
                "requested_phase": "compare",
                "comparison_candidates": [
                    {
                        "candidate_id": "candidate-final",
                        "image_path": str(candidate.resolve()),
                        "image_sha256": candidate_hash,
                        "parent_candidate_id": "original",
                        "parent_sha256": sha256_file(original),
                        "plan_id": "plan-final",
                        "operation": "exposure_contrast_color",
                        "parameters": {"exposure": 0.1},
                    }
                ],
                "user_feedback": {
                    "feedback_id": "feedback-negative",
                    "case_id": "negative-feedback",
                    "candidate_id": "candidate-final",
                    "candidate_sha256": candidate_hash,
                    "decision": decision,
                    "source_event_id": "host-event-negative",
                    "submitted_at": datetime.now(UTC).isoformat(),
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_case(case_file)

    assert result.status.value == expected_status
    assert result.status != Status.COMPLETED


def test_comparison_schema_exposes_crop_contract() -> None:
    properties = ComparisonResult.model_json_schema()["properties"]

    assert {
        "operation",
        "crop_box",
        "source_area_pixels",
        "retained_area_pixels",
        "removed_area_pixels",
        "retained_ratio",
        "removed_ratio",
    } <= set(properties)
