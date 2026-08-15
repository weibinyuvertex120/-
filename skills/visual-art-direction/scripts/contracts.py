"""Runtime contracts for visual-art-direction skill."""

from __future__ import annotations

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
    COMPLETED_WITH_USER_CONFIRMATION_PENDING = "completed_with_user_confirmation_pending"
    COMPLETED = "completed"
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


class UserConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


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


class ResizeParameters(BaseModel, extra="forbid"):
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    fit: Literal["contain", "cover"] = "contain"


class LocalAdjustmentParameters(ExposureContrastColorParameters):
    box: tuple[int, int, int, int]
    feather: int = Field(default=0, ge=0, le=256)


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
    evidence: list[str] = Field(default_factory=list)
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

        parameter_models = {
            EditOperation.EXPOSURE_CONTRAST_COLOR: ExposureContrastColorParameters,
            EditOperation.CROP: CropParameters,
            EditOperation.RESIZE: ResizeParameters,
            EditOperation.LOCAL_ADJUSTMENT: LocalAdjustmentParameters,
        }
        validated = parameter_models[self.operation].model_validate(self.parameters)
        self.parameters = validated.model_dump(mode="python")
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
    operations: list[dict[str, Any]] = Field(default_factory=list)
    candidate_lineage: list[CandidateLineage] = Field(default_factory=list)
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    user_confirmation: UserConfirmationStatus = UserConfirmationStatus.PENDING
    status: Status = Status.READY
    residual_risks: list[str] = Field(default_factory=list)


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


class CandidateReference(BaseModel, extra="forbid"):
    candidate_id: str = Field(min_length=1)
    image_path: Path
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_candidate_id: str = "original"
    parent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: str = Field(min_length=1)

    @field_validator("image_path")
    @classmethod
    def validate_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(f"Path must be absolute: {value}")
        return value


class CandidateLineage(BaseModel, extra="forbid"):
    candidate_id: str
    parent_candidate_id: str
    plan_id: str
    input_path: Path
    input_sha256: str
    output_path: Path
    output_sha256: str
    operation: EditOperation | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    reversible: bool = False


class CaseRequest(BaseModel, extra="forbid"):
    case_id: str
    input_image: Path
    requested_phase: Phase
    truth_mode: TruthMode = TruthMode.DOCUMENTARY
    visual_intent: str = ""
    use_context: str = ""
    target_medium: str = ""
    observation_prompt: str = ""
    must_preserve: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    plan: VisualTransformationPlan | None = None
    operations: list[EditRequest] = Field(default_factory=list)
    comparison_candidates: list[CandidateReference] = Field(default_factory=list)
    user_confirmation_status: UserConfirmationStatus = UserConfirmationStatus.PENDING

    @field_validator("input_image")
    @classmethod
    def validate_absolute_path(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"Path must be absolute: {v}")
        return v

    @model_validator(mode="after")
    def validate_candidate_sources(self) -> CaseRequest:
        if self.operations and self.comparison_candidates:
            raise ValueError("Case cannot provide both operations and comparison_candidates")
        reference_ids = [item.candidate_id for item in self.comparison_candidates]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("Duplicate comparison candidate_id")
        return self


class RunResult(BaseModel, extra="forbid"):
    case_id: str
    status: Status
    capability_report: CapabilityReport | None = None
    observation_result: ObservationResult | None = None
    plan: VisualTransformationPlan | None = None
    edit_results: list[EditResult] = Field(default_factory=list)
    candidate_lineage: list[CandidateLineage] = Field(default_factory=list)
    comparison_results: list[ComparisonResult] = Field(default_factory=list)
    evidence_path: Path | None = None
    error: str = ""
    execution_time_ms: float = 0.0
