"""Runtime contracts for visual-art-direction skill."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

# --- Enums ---


class Capability(StrEnum):
    V0_FILE_ACCESS = "V0_file_access"
    V1_VISUAL_OBSERVATION = "V1_visual_observation"
    V2_IMAGE_EDITING = "V2_image_editing"
    V3_RESULT_COMPARISON = "V3_result_comparison"


class Status(StrEnum):
    READY = "ready"
    BLOCKED_NO_INPUT = "blocked_no_input"
    BLOCKED_NO_VIEW_CAPABILITY = "blocked_no_view_capability"
    BLOCKED_NO_EDIT_CAPABILITY = "blocked_no_edit_capability"
    BLOCKED_NO_COMPARISON_CAPABILITY = "blocked_no_comparison_capability"
    BLOCKED_NO_CANDIDATE = "blocked_no_candidate"
    COMPLETED_PHASE = "completed_phase"
    COMPLETED_WITH_USER_FEEDBACK_PENDING = "completed_with_user_feedback_pending"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    FAILED_INVALID_CONTRACT = "failed_invalid_contract"
    FAILED_EXECUTION = "failed_execution"


class EditOperation(StrEnum):
    EXPOSURE_CONTRAST_COLOR = "exposure_contrast_color"
    LOCAL_ADJUSTMENT = "local_adjustment"
    CROP = "crop"
    RESIZE = "resize"


class TruthMode(StrEnum):
    DOCUMENTARY = "纪实"
    EXPRESSION = "表达"
    CONCEPT = "概念"


class Phase(StrEnum):
    DIAGNOSIS = "diagnosis"
    EDIT = "edit"
    COMPARE = "compare"
    FULL = "full"


class DecisionSource(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    MODEL = "model"
    HYBRID = "hybrid"


class UserFeedbackDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class EditStrength(StrEnum):
    SUBTLE = "subtle"
    MODERATE = "moderate"
    STRONG = "strong"
    GENERATIVE = "generative"


class ObservationConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ObservationDimension(StrEnum):
    P01 = "P01"
    P02 = "P02"
    P03 = "P03"
    P04 = "P04"
    P05 = "P05"
    P06 = "P06"
    P07 = "P07"
    P08 = "P08"
    P09 = "P09"
    P10 = "P10"
    SCENE = "scene"
    PORTRAIT = "portrait"
    OTHER = "other"


# --- Models ---


class ExposureContrastColorParameters(BaseModel, extra="forbid"):
    exposure: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast: float = Field(default=1.0, ge=0.5, le=1.5)
    saturation: float = Field(default=1.0, ge=0.5, le=1.5)


class CropParameters(BaseModel, extra="forbid"):
    box: tuple[int, int, int, int]

    @field_validator("box")
    @classmethod
    def validate_box_order(cls, value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        left, upper, right, lower = value
        if min(value) < 0 or right <= left or lower <= upper:
            raise ValueError("Crop box must have non-negative coordinates and positive area")
        return value


class ResizeParameters(BaseModel, extra="forbid"):
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    fit: Literal["contain", "cover"] = "contain"


class LocalAdjustmentParameters(ExposureContrastColorParameters):
    box: tuple[int, int, int, int]
    feather: int = Field(default=0, ge=0, le=256)


def validate_operation_parameters(
    operation: EditOperation,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    parameter_models = {
        EditOperation.EXPOSURE_CONTRAST_COLOR: ExposureContrastColorParameters,
        EditOperation.CROP: CropParameters,
        EditOperation.RESIZE: ResizeParameters,
        EditOperation.LOCAL_ADJUSTMENT: LocalAdjustmentParameters,
    }
    validated = parameter_models[operation].model_validate(parameters)
    return validated.model_dump(mode="python")


class CapabilityState(BaseModel, extra="forbid"):
    available: bool
    evidence: str = ""
    provider: str = ""
    provider_version: str = ""
    checked_at: datetime | None = None


class AdapterHealth(BaseModel, extra="forbid"):
    name: str
    version: str
    healthy: bool
    capabilities: set[Capability] = Field(default_factory=set)
    evidence: str = ""
    checked_at: datetime | None = None


class CapabilityReport(BaseModel, extra="forbid"):
    input_path: Path | None = None
    input_exists: bool = False
    input_sha256: str = ""
    input_size: tuple[int, int] = Field(default=(0, 0))
    capabilities: dict[Capability, CapabilityState] = Field(default_factory=dict)
    status: Status = Status.READY
    checked_at: datetime | None = None
    adapters_checked: list[str] = Field(default_factory=list)

    @computed_field(return_type=bool)
    @property
    def has_v0(self) -> bool:
        return self.capabilities.get(
            Capability.V0_FILE_ACCESS, CapabilityState(available=False)
        ).available

    @computed_field(return_type=bool)
    @property
    def has_v1(self) -> bool:
        return self.capabilities.get(
            Capability.V1_VISUAL_OBSERVATION, CapabilityState(available=False)
        ).available

    @computed_field(return_type=bool)
    @property
    def has_v2(self) -> bool:
        return self.capabilities.get(
            Capability.V2_IMAGE_EDITING, CapabilityState(available=False)
        ).available

    @computed_field(return_type=bool)
    @property
    def has_v3(self) -> bool:
        return self.capabilities.get(
            Capability.V3_RESULT_COMPARISON, CapabilityState(available=False)
        ).available


class ObservationItem(BaseModel, extra="forbid"):
    dimension: ObservationDimension
    statement: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    confidence: ObservationConfidence


class ObservationResult(BaseModel, extra="forbid"):
    success: bool
    provider: str = Field(min_length=1)
    provider_version: str = ""
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[ObservationItem] = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list)
    error: str = ""


def canonical_observation_sha256(observation: ObservationResult) -> str:
    """Hash an ObservationResult using canonical JSON serialization."""
    encoded = json.dumps(
        observation.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EditRequest(BaseModel, extra="forbid"):
    case_id: str
    input_image: Path
    level: Literal["L1", "L2", "L3"]
    operation: EditOperation
    parameters: dict[str, Any] = Field(default_factory=dict)
    must_preserve: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    strength: EditStrength = EditStrength.SUBTLE
    output_image: Path
    candidate_id: str = ""
    parent_candidate_id: str = "original"

    @field_validator("input_image", "output_image")
    @classmethod
    def validate_absolute_path(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"Path must be absolute: {v}")
        return v

    @model_validator(mode="after")
    def validate_operation_level(self) -> EditRequest:
        required_levels = {
            EditOperation.EXPOSURE_CONTRAST_COLOR: "L1",
            EditOperation.CROP: "L2",
            EditOperation.RESIZE: "L2",
            EditOperation.LOCAL_ADJUSTMENT: "L3",
        }
        required = required_levels[self.operation]
        if self.level != required:
            raise ValueError(f"Operation {self.operation.value} requires level {required}")

        self.parameters = validate_operation_parameters(self.operation, self.parameters)
        return self


class EditResult(BaseModel, extra="forbid"):
    success: bool
    operation: EditOperation
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_sha256: str = ""
    output_sha256: str = ""
    output_size: tuple[int, int] = (0, 0)
    error: str = ""
    execution_time_ms: float = 0.0


class ComparisonResult(BaseModel, extra="forbid"):
    original_readable: bool = False
    candidate_readable: bool = False
    original_sha256: str = ""
    candidate_sha256: str = ""
    original_size: tuple[int, int] = (0, 0)
    candidate_size: tuple[int, int] = (0, 0)
    pixel_change_summary: str = ""
    changed_pixels: int | None = None
    total_pixels: int | None = None
    change_ratio: float | None = None
    size_matches: bool = False
    change_bounding_box: tuple[int, int, int, int] | None = None
    operation: EditOperation | None = None
    crop_box: tuple[int, int, int, int] | None = None
    source_area_pixels: int | None = None
    retained_area_pixels: int | None = None
    removed_area_pixels: int | None = None
    retained_ratio: float | None = None
    removed_ratio: float | None = None
    candidate_id: str = ""
    parent_candidate_id: str = ""
    plan_id: str = ""
    report_json_path: Path | None = None
    report_html_path: Path | None = None
    error: str = ""


class EvidenceRecord(BaseModel, extra="forbid"):
    case_id: str
    timestamp: datetime
    input_path: str = ""
    input_sha256: str = ""
    capability_report: dict[str, Any] = Field(default_factory=dict)
    observation: ObservationResult | None = None
    plan: VisualTransformationPlan | None = None
    parent_plan: VisualTransformationPlan | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)
    candidate_lineage: list[CandidateLineage] = Field(default_factory=list)
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    user_feedback: UserFeedback | None = None
    status: Status = Status.READY
    residual_risks: list[str] = Field(default_factory=list)


class ObservationBasis(BaseModel, extra="forbid"):
    observation_index: int = Field(ge=0)
    dimension: ObservationDimension
    evidence: str = Field(min_length=1)


class VisualTransformationPlan(BaseModel, extra="forbid"):
    plan_id: str = Field(min_length=1)
    visual_goal: str = Field(min_length=1)
    recommended_level: Literal["L1", "L2", "L3"]
    operations: list[EditOperation] = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    must_preserve: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    stop_condition: str = Field(min_length=1)
    decision_source: DecisionSource
    basis: list[ObservationBasis] = Field(min_length=1)
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_plan_id: str | None = None
    parent_plan_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    trigger_feedback_id: str | None = None
    trigger_feedback_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parent_candidate_id: str | None = None
    parent_candidate_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_revision_provenance(self) -> VisualTransformationPlan:
        provenance = (
            self.parent_plan_id,
            self.parent_plan_sha256,
            self.trigger_feedback_id,
            self.trigger_feedback_sha256,
            self.parent_candidate_id,
            self.parent_candidate_sha256,
        )
        if self.decision_source == DecisionSource.HYBRID and any(
            value is None for value in provenance
        ):
            raise ValueError(
                "hybrid Plan requires parent_plan_id, trigger_feedback_id, "
                "parent_plan_sha256, trigger_feedback_sha256, parent_candidate_id "
                "and parent_candidate_sha256"
            )
        if self.decision_source != DecisionSource.HYBRID and any(
            value is not None for value in provenance
        ):
            raise ValueError("Plan revision provenance requires decision_source=hybrid")
        return self


def canonical_plan_sha256(plan: VisualTransformationPlan) -> str:
    """Hash a VisualTransformationPlan using canonical JSON serialization."""
    encoded = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class UserFeedback(BaseModel, extra="forbid"):
    feedback_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: UserFeedbackDecision
    comment: str = ""
    source_event_id: str = Field(min_length=1)
    submitted_at: datetime


def canonical_user_feedback_sha256(feedback: UserFeedback) -> str:
    """Hash a UserFeedback event using canonical JSON serialization."""
    encoded = json.dumps(
        feedback.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CandidateReference(BaseModel, extra="forbid"):
    candidate_id: str = Field(min_length=1)
    image_path: Path
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_candidate_id: str = "original"
    parent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: str = Field(min_length=1)
    operation: EditOperation
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("image_path")
    @classmethod
    def validate_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"Path must be absolute: {value}")
        return value

    @model_validator(mode="after")
    def validate_parameters(self) -> CandidateReference:
        self.parameters = validate_operation_parameters(self.operation, self.parameters)
        return self


class CandidateLineage(BaseModel, extra="forbid"):
    candidate_id: str
    parent_candidate_id: str
    plan_id: str
    input_path: Path
    input_sha256: str
    output_path: Path
    output_sha256: str
    operation: EditOperation
    parameters: dict[str, Any] = Field(default_factory=dict)
    reversible: bool = False


class CaseRequest(BaseModel, extra="forbid"):
    case_id: str
    input_image: Path
    requested_phase: Phase
    truth_mode: TruthMode = TruthMode.EXPRESSION
    visual_intent: str = ""
    use_context: str = ""
    target_medium: str = ""
    observation_prompt: str = ""
    must_preserve: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    source_observation: ObservationResult | None = None
    trigger_feedback: UserFeedback | None = None
    plan: VisualTransformationPlan | None = None
    parent_plan: VisualTransformationPlan | None = None
    operations: list[EditRequest] = Field(default_factory=list)
    comparison_candidates: list[CandidateReference] = Field(default_factory=list)
    user_feedback: UserFeedback | None = None

    @field_validator("input_image")
    @classmethod
    def validate_absolute_path(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"Path must be absolute: {v}")
        return v

    @model_validator(mode="after")
    def validate_phase_contract(self) -> CaseRequest:
        if self.requested_phase == Phase.DIAGNOSIS:
            if any(
                (
                    self.operations,
                    self.comparison_candidates,
                    self.source_observation,
                self.plan,
                    self.parent_plan,
                    self.user_feedback,
                    self.trigger_feedback,
                )
            ):
                raise ValueError("diagnosis phase accepts observation input only")
        elif self.requested_phase == Phase.EDIT:
            if not self.operations or self.comparison_candidates or self.user_feedback:
                raise ValueError(
                    "edit phase requires operations and forbids comparison or feedback"
                )
        elif self.requested_phase == Phase.COMPARE:
            if not self.comparison_candidates or self.operations:
                raise ValueError(
                    "compare phase requires comparison_candidates and forbids operations"
                )
            if self.plan is not None or self.source_observation is not None:
                raise ValueError(
                    "compare phase uses candidate lineage, not Plan or Observation input"
                )
        elif self.requested_phase == Phase.FULL:
            if not self.operations or self.comparison_candidates:
                raise ValueError("full phase requires operations and forbids existing candidates")
            if (
                self.plan is None
                or self.source_observation is None
                or self.user_feedback
                or (
                    self.plan is not None
                    and self.plan.decision_source == DecisionSource.HYBRID
                    and self.trigger_feedback is None
                )
            ):
                raise ValueError(
                    "full phase requires a bound Plan, source Observation and trigger feedback"
                )

        reference_ids = [item.candidate_id for item in self.comparison_candidates]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("Duplicate comparison candidate_id")

        if self.plan is not None and self.requested_phase in (Phase.EDIT, Phase.FULL):
            if self.source_observation is None:
                raise ValueError("A Plan requires source_observation in edit or full phase")
            self._validate_plan_observation(self.plan, self.source_observation)
            if self.plan.decision_source == DecisionSource.HYBRID:
                if self.trigger_feedback is None:
                    raise ValueError("hybrid Plan requires trigger_feedback")
                if self.plan.trigger_feedback_id != self.trigger_feedback.feedback_id:
                    raise ValueError("Plan trigger_feedback_id does not match trigger_feedback")
                if self.plan.trigger_feedback_sha256 != canonical_user_feedback_sha256(
                    self.trigger_feedback
                ):
                    raise ValueError("Plan trigger_feedback_sha256 does not match trigger_feedback")
                if (
                    self.plan.parent_candidate_id != self.trigger_feedback.candidate_id
                    or self.plan.parent_candidate_sha256 != self.trigger_feedback.candidate_sha256
                ):
                    raise ValueError("Plan parent candidate does not match trigger_feedback")
                if self.parent_plan is None:
                    raise ValueError("hybrid Plan requires parent_plan artifact")
                if self.plan.parent_plan_id != self.parent_plan.plan_id:
                    raise ValueError("Plan parent_plan_id does not match parent_plan")
                if self.plan.parent_plan_sha256 != canonical_plan_sha256(self.parent_plan):
                    raise ValueError("Plan parent_plan_sha256 does not match parent_plan")
            elif self.trigger_feedback is not None:
                raise ValueError("trigger_feedback requires decision_source=hybrid")
            elif self.parent_plan is not None:
                raise ValueError("parent_plan requires decision_source=hybrid")
        elif self.source_observation is not None:
            raise ValueError("source_observation requires a Plan")
        elif self.trigger_feedback is not None:
            raise ValueError("trigger_feedback requires a Plan")
        elif self.parent_plan is not None:
            raise ValueError("parent_plan requires a Plan")

        if self.user_feedback is not None:
            if self.user_feedback.case_id != self.case_id:
                raise ValueError("UserFeedback case_id does not match the case")
            matches = [
                item
                for item in self.comparison_candidates
                if item.candidate_id == self.user_feedback.candidate_id
                and item.image_sha256 == self.user_feedback.candidate_sha256
            ]
            if len(matches) != 1:
                raise ValueError("UserFeedback must bind to exactly one comparison candidate hash")
            parent_ids = {item.parent_candidate_id for item in self.comparison_candidates}
            if self.user_feedback.candidate_id in parent_ids:
                raise ValueError("UserFeedback must bind to a final leaf candidate")
        return self

    @staticmethod
    def _validate_plan_observation(
        plan: VisualTransformationPlan,
        observation: ObservationResult,
    ) -> None:
        if plan.observation_sha256 != canonical_observation_sha256(observation):
            raise ValueError("Plan observation_sha256 does not match source_observation")
        for basis in plan.basis:
            if basis.observation_index >= len(observation.items):
                raise ValueError("Plan basis observation_index is out of range")
            item = observation.items[basis.observation_index]
            if basis.dimension != item.dimension or basis.evidence not in item.evidence:
                raise ValueError("Plan basis does not match the referenced Observation item")


class RunResult(BaseModel, extra="forbid"):
    case_id: str
    status: Status
    capability_report: CapabilityReport | None = None
    observation_result: ObservationResult | None = None
    plan: VisualTransformationPlan | None = None
    parent_plan: VisualTransformationPlan | None = None
    edit_results: list[EditResult] = Field(default_factory=list)
    candidate_lineage: list[CandidateLineage] = Field(default_factory=list)
    comparison_results: list[ComparisonResult] = Field(default_factory=list)
    user_feedback: UserFeedback | None = None
    evidence_path: Path | None = None
    error: str = ""
    execution_time_ms: float = 0.0
