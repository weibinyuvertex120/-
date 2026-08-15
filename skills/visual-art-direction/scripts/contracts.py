"""Runtime contracts for visual-art-direction skill."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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


# --- Models ---


class CapabilityState(BaseModel, extra="forbid"):
    available: bool
    evidence: str = ""
    provider: str = ""
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

    @property
    def has_v0(self) -> bool:
        return self.capabilities.get(
            Capability.V0_FILE_ACCESS, CapabilityState(available=False)
        ).available

    @property
    def has_v1(self) -> bool:
        return self.capabilities.get(
            Capability.V1_VISUAL_OBSERVATION, CapabilityState(available=False)
        ).available

    @property
    def has_v2(self) -> bool:
        return self.capabilities.get(
            Capability.V2_IMAGE_EDITING, CapabilityState(available=False)
        ).available

    @property
    def has_v3(self) -> bool:
        return self.capabilities.get(
            Capability.V3_RESULT_COMPARISON, CapabilityState(available=False)
        ).available


class EditRequest(BaseModel, extra="forbid"):
    case_id: str
    input_image: Path
    level: Literal["L1", "L2"]
    operation: EditOperation
    parameters: dict[str, Any] = Field(default_factory=dict)
    must_preserve: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    strength: EditStrength = EditStrength.SUBTLE
    output_image: Path

    @field_validator("input_image", "output_image")
    @classmethod
    def validate_absolute_path(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"Path must be absolute: {v}")
        return v


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
    change_bounding_box: tuple[int, int, int, int] | None = None
    report_json_path: Path | None = None
    report_html_path: Path | None = None
    error: str = ""


class EvidenceRecord(BaseModel, extra="forbid"):
    case_id: str
    timestamp: datetime
    input_path: str = ""
    input_sha256: str = ""
    capability_report: dict[str, Any] = Field(default_factory=dict)
    operations: list[dict[str, Any]] = Field(default_factory=list)
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    user_confirmation: UserConfirmationStatus = UserConfirmationStatus.PENDING
    status: Status = Status.READY
    residual_risks: list[str] = Field(default_factory=list)


class CaseRequest(BaseModel, extra="forbid"):
    case_id: str
    input_image: Path
    requested_phase: Phase
    truth_mode: TruthMode = TruthMode.DOCUMENTARY
    must_preserve: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    operations: list[EditRequest] = Field(default_factory=list)
    user_confirmation_status: UserConfirmationStatus = UserConfirmationStatus.PENDING

    @field_validator("input_image")
    @classmethod
    def validate_absolute_path(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"Path must be absolute: {v}")
        return v


class RunResult(BaseModel, extra="forbid"):
    case_id: str
    status: Status
    capability_report: CapabilityReport | None = None
    edit_results: list[EditResult] = Field(default_factory=list)
    comparison_results: list[ComparisonResult] = Field(default_factory=list)
    evidence_path: Path | None = None
    error: str = ""
    execution_time_ms: float = 0.0
