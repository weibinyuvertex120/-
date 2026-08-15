"""Tests for visual-art-direction runtime capabilities."""

import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "visual-art-direction"))

from scripts.capability_probe import probe_capabilities
from scripts.compare_candidates import LocalCompareAdapter, compare_images
from scripts.contracts import (
    AdapterHealth,
    Capability,
    CapabilityReport,
    EditOperation,
    EditRequest,
    EvidenceRecord,
    Status,
    UserConfirmationStatus,
)
from scripts.deterministic_editor import (
    DeterministicEditorAdapter,
    crop_l2,
    edit_l1,
    resize_for_media,
)
from scripts.evidence import read_evidence, sha256_file, write_evidence
from scripts.runner import run_case


class ObservationAdapter:
    """Minimal test-only declaration of a real V1 host capability."""

    name = "test-observer"
    version = "1.0.0"

    def healthcheck(self) -> AdapterHealth:
        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities={Capability.V1_VISUAL_OBSERVATION},
            evidence="Test adapter supplied structured observation capability",
        )

    def capabilities(self) -> set[Capability]:
        return {Capability.V1_VISUAL_OBSERVATION}


# --- Fixtures ---


@pytest.fixture
def tmp_image(tmp_path: Path) -> Path:
    """Create a temporary test image."""
    img = Image.new("RGB", (200, 100), color=(128, 128, 128))
    path = tmp_path / "test_input.png"
    img.save(path)
    return path


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Create a temporary output path."""
    return tmp_path / "test_output.png"


@pytest.fixture
def tmp_case_file(tmp_path: Path, tmp_image: Path, tmp_output: Path) -> Path:
    """Create a temporary case file."""
    case_data = {
        "case_id": "test-case",
        "input_image": str(tmp_image),
        "requested_phase": "edit",
        "truth_mode": "纪实",
        "operations": [
            {
                "case_id": "test-case",
                "input_image": str(tmp_image),
                "level": "L1",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.1, "contrast": 1.1, "saturation": 1.0},
                "must_preserve": [],
                "allowed_changes": ["exposure", "contrast"],
                "forbidden_changes": [],
                "strength": "subtle",
                "output_image": str(tmp_output),
            }
        ],
        "user_confirmation_status": "pending",
    }
    case_file = tmp_path / "case.json"
    with open(case_file, "w", encoding="utf-8") as f:
        json.dump(case_data, f)
    return case_file


# --- Contract Tests ---


class TestContracts:
    """Test contract validation."""

    def test_edit_request_unknown_field_rejected(self, tmp_image: Path, tmp_output: Path):
        """Contract rejects unknown fields."""
        with pytest.raises(ValidationError):
            EditRequest(
                case_id="test",
                input_image=tmp_image,
                level="L1",
                operation=EditOperation.EXPOSURE_CONTRAST_COLOR,
                parameters={},
                must_preserve=[],
                allowed_changes=[],
                forbidden_changes=[],
                strength="subtle",
                output_image=tmp_output,
                unknown_field="should_fail",
            )

    def test_edit_request_relative_path_rejected(self, tmp_path: Path):
        """Contract rejects relative paths."""
        with pytest.raises(ValidationError):
            EditRequest(
                case_id="test",
                input_image=Path("relative/path.jpg"),
                level="L1",
                operation=EditOperation.EXPOSURE_CONTRAST_COLOR,
                parameters={},
                must_preserve=[],
                allowed_changes=[],
                forbidden_changes=[],
                strength="subtle",
                output_image=Path("relative/output.jpg"),
            )

    def test_capability_report_extra_forbid(self):
        """CapabilityReport rejects unknown fields."""
        with pytest.raises(ValidationError):
            CapabilityReport(unknown_field="should_fail")


# --- Capability Probe Tests ---


class TestCapabilityProbe:
    """Test capability probing."""

    def test_no_input_returns_blocked(self):
        """No input returns blocked_no_input."""
        report = probe_capabilities(None)
        assert report.status == Status.BLOCKED_NO_INPUT

    def test_nonexistent_file_returns_blocked(self, tmp_path: Path):
        """Nonexistent file returns blocked_no_input."""
        report = probe_capabilities(tmp_path / "nonexistent.jpg")
        assert report.status == Status.BLOCKED_NO_INPUT
        assert not report.has_v0

    def test_non_image_file_returns_blocked(self, tmp_path: Path):
        """Non-image file returns blocked_no_input."""
        text_file = tmp_path / "test.txt"
        text_file.write_text("not an image")
        report = probe_capabilities(text_file)
        assert report.status == Status.BLOCKED_NO_INPUT
        assert not report.has_v0

    def test_valid_image_has_v0(self, tmp_image: Path):
        """Valid image has V0 capability."""
        report = probe_capabilities(tmp_image)
        assert report.has_v0
        assert report.status == Status.READY
        assert report.input_sha256 != ""
        assert report.input_size == (200, 100)

    def test_v1_v2_v3_false_without_adapters(self, tmp_image: Path):
        """V1/V2/V3 are false without adapters."""
        report = probe_capabilities(tmp_image)
        assert not report.has_v1
        assert not report.has_v2
        assert not report.has_v3

    def test_builtin_adapters_report_limited_v2_and_v3(self, tmp_image: Path):
        """Built-in capabilities come from explicit healthcheck evidence."""
        report = probe_capabilities(
            tmp_image,
            adapters=[DeterministicEditorAdapter(), LocalCompareAdapter()],
        )
        assert not report.has_v1
        assert report.has_v2
        assert report.has_v3
        assert report.capabilities[Capability.V2_IMAGE_EDITING].provider == "deterministic-pillow"
        assert report.capabilities[Capability.V3_RESULT_COMPARISON].provider == "local-compare"


# --- Deterministic Editor Tests ---


class TestDeterministicEditor:
    """Test deterministic L1/L2 editing."""

    def test_l1_exposure(self, tmp_image: Path, tmp_output: Path):
        """L1 exposure adjustment works."""
        result = edit_l1(tmp_image, tmp_output, exposure=0.2, contrast=1.0, saturation=1.0)
        assert result.success
        assert result.input_sha256 != ""
        assert result.output_sha256 != ""
        assert result.output_size == (200, 100)
        assert tmp_output.exists()

    def test_l1_contrast(self, tmp_image: Path, tmp_output: Path):
        """L1 contrast adjustment works."""
        result = edit_l1(tmp_image, tmp_output, exposure=0.0, contrast=1.3, saturation=1.0)
        assert result.success

    def test_l1_saturation(self, tmp_image: Path, tmp_output: Path):
        """L1 saturation adjustment works."""
        result = edit_l1(tmp_image, tmp_output, exposure=0.0, contrast=1.0, saturation=0.8)
        assert result.success

    def test_l1_extreme_exposure_rejected(self, tmp_image: Path, tmp_output: Path):
        """Extreme exposure is rejected."""
        result = edit_l1(tmp_image, tmp_output, exposure=2.0)
        assert not result.success
        assert "exposure" in result.error.lower()

    def test_l1_extreme_contrast_rejected(self, tmp_image: Path, tmp_output: Path):
        """Extreme contrast is rejected."""
        result = edit_l1(tmp_image, tmp_output, contrast=0.1)
        assert not result.success
        assert "contrast" in result.error.lower()

    def test_l2_crop(self, tmp_image: Path, tmp_output: Path):
        """L2 crop works."""
        result = crop_l2(tmp_image, tmp_output, box=(10, 10, 50, 50))
        assert result.success
        assert result.output_size == (40, 40)

    def test_l2_crop_out_of_bounds_rejected(self, tmp_image: Path, tmp_output: Path):
        """Out-of-bounds crop is rejected."""
        result = crop_l2(tmp_image, tmp_output, box=(-10, -10, 999, 999))
        assert not result.success

    def test_l2_crop_zero_area_rejected(self, tmp_image: Path, tmp_output: Path):
        """Zero-area crop is rejected."""
        result = crop_l2(tmp_image, tmp_output, box=(10, 10, 10, 10))
        assert not result.success

    def test_l2_crop_inverted_rejected(self, tmp_image: Path, tmp_output: Path):
        """Inverted crop is rejected."""
        result = crop_l2(tmp_image, tmp_output, box=(50, 50, 10, 10))
        assert not result.success

    def test_resize_contain(self, tmp_image: Path, tmp_output: Path):
        """Resize with contain mode works."""
        result = resize_for_media(tmp_image, tmp_output, width=100, height=100, fit="contain")
        assert result.success
        # Aspect ratio preserved: 200x100 -> 100x50
        assert result.output_size == (100, 50)

    def test_resize_cover(self, tmp_image: Path, tmp_output: Path):
        """Resize with cover mode works."""
        result = resize_for_media(tmp_image, tmp_output, width=100, height=100, fit="cover")
        assert result.success
        assert result.output_size == (100, 100)

    def test_resize_negative_dims_rejected(self, tmp_image: Path, tmp_output: Path):
        """Negative dimensions are rejected."""
        result = resize_for_media(tmp_image, tmp_output, width=-100, height=100)
        assert not result.success

    def test_resize_huge_dims_rejected(self, tmp_image: Path, tmp_output: Path):
        """Huge dimensions are rejected."""
        result = resize_for_media(tmp_image, tmp_output, width=99999, height=99999)
        assert not result.success

    def test_cannot_overwrite_original(self, tmp_image: Path):
        """Cannot overwrite original image."""
        result = edit_l1(tmp_image, tmp_image)
        assert not result.success
        assert "differ" in result.error.lower() or "overwrite" in result.error.lower()

    def test_output_hash_differs_from_input(self, tmp_image: Path, tmp_output: Path):
        """Output hash differs from input after edit."""
        result = edit_l1(tmp_image, tmp_output, exposure=0.5)
        assert result.success
        assert result.input_sha256 != result.output_sha256


# --- Comparison Tests ---


class TestComparison:
    """Test image comparison."""

    def test_comparison_generates_reports(self, tmp_image: Path, tmp_path: Path):
        """Comparison generates JSON and HTML reports."""
        # Create a modified image
        modified = tmp_path / "modified.png"
        with Image.open(tmp_image) as img:
            img = img.point(lambda x: min(255, x + 20))
            img.save(modified)

        report_dir = tmp_path / "reports"
        result = compare_images(tmp_image, modified, report_dir)

        assert result.original_readable
        assert result.candidate_readable
        assert result.original_sha256 != ""
        assert result.candidate_sha256 != ""
        assert result.pixel_change_summary != ""
        assert result.report_json_path is not None
        assert result.report_html_path is not None
        assert result.report_json_path.exists()
        assert result.report_html_path.exists()

    def test_comparison_unreadable_original(self, tmp_path: Path):
        """Comparison handles unreadable original."""
        nonexistent = tmp_path / "nonexistent.jpg"
        candidate = tmp_path / "candidate.jpg"
        report_dir = tmp_path / "reports"

        result = compare_images(nonexistent, candidate, report_dir)
        assert not result.original_readable
        assert result.error != ""

    def test_comparison_unreadable_candidate(self, tmp_image: Path, tmp_path: Path):
        """Comparison handles unreadable candidate."""
        nonexistent = tmp_path / "nonexistent.jpg"
        report_dir = tmp_path / "reports"

        result = compare_images(tmp_image, nonexistent, report_dir)
        assert result.original_readable
        assert not result.candidate_readable
        assert result.error != ""


# --- Evidence Tests ---


class TestEvidence:
    """Test evidence recording."""

    def test_sha256_file(self, tmp_image: Path):
        """SHA-256 computation works."""
        hash_val = sha256_file(tmp_image)
        assert len(hash_val) == 64
        assert hash_val == sha256_file(tmp_image)  # Deterministic

    def test_sha256_nonexistent_raises(self, tmp_path: Path):
        """SHA-256 of nonexistent file raises."""
        with pytest.raises(FileNotFoundError):
            sha256_file(tmp_path / "nonexistent.jpg")

    def test_evidence_roundtrip(self, tmp_path: Path):
        """Evidence record can be written and read."""
        from datetime import datetime

        record = EvidenceRecord(
            case_id="test",
            timestamp=datetime(2025, 1, 1),
            input_path="/test/image.jpg",
            input_sha256="abc123",
            capability_report={"v0": True, "v1": False},
            operations=[{"op": "test", "success": True}],
            comparisons=[],
            user_confirmation=UserConfirmationStatus.PENDING,
            status=Status.COMPLETED,
            residual_risks=["test risk"],
        )

        output_path = tmp_path / "evidence.json"
        write_evidence(record, output_path)

        loaded = read_evidence(output_path)
        assert loaded.case_id == "test"
        assert loaded.input_sha256 == "abc123"
        assert loaded.status == Status.COMPLETED

    def test_evidence_stable_serialization(self, tmp_path: Path):
        """Evidence serialization is stable (sorted keys)."""
        from datetime import datetime

        record = EvidenceRecord(
            case_id="test",
            timestamp=datetime(2025, 1, 1),
        )

        path1 = tmp_path / "evidence1.json"
        path2 = tmp_path / "evidence2.json"

        write_evidence(record, path1)
        write_evidence(record, path2)

        assert path1.read_text() == path2.read_text()


# --- Runner Tests ---


class TestRunner:
    """Test case runner."""

    def test_no_input_returns_blocked(self, tmp_path: Path):
        """No input returns blocked_no_input."""
        case_data = {
            "case_id": "test",
            "input_image": str(tmp_path / "nonexistent.jpg"),
            "requested_phase": "diagnosis",
            "truth_mode": "纪实",
            "operations": [],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case.json"
        with open(case_file, "w") as f:
            json.dump(case_data, f)

        result = run_case(case_file)
        assert result.status == Status.BLOCKED_NO_INPUT

    def test_v0_only_blocks_diagnosis(self, tmp_image: Path, tmp_path: Path):
        """V0 only blocks diagnosis."""
        case_data = {
            "case_id": "test",
            "input_image": str(tmp_image),
            "requested_phase": "diagnosis",
            "truth_mode": "纪实",
            "operations": [],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case.json"
        with open(case_file, "w") as f:
            json.dump(case_data, f)

        result = run_case(case_file)
        assert result.status == Status.BLOCKED_NO_VIEW_CAPABILITY

    def test_l1_edit_succeeds(self, tmp_image: Path, tmp_path: Path, tmp_output: Path):
        """L1 edit succeeds with V0 + deterministic V2."""
        case_data = {
            "case_id": "test",
            "input_image": str(tmp_image),
            "requested_phase": "edit",
            "truth_mode": "纪实",
            "operations": [
                {
                    "case_id": "test",
                    "input_image": str(tmp_image),
                    "level": "L1",
                    "operation": "exposure_contrast_color",
                    "parameters": {"exposure": 0.1, "contrast": 1.1, "saturation": 1.0},
                    "must_preserve": [],
                    "allowed_changes": ["exposure", "contrast"],
                    "forbidden_changes": [],
                    "strength": "subtle",
                    "output_image": str(tmp_output),
                }
            ],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case.json"
        with open(case_file, "w") as f:
            json.dump(case_data, f)

        result = run_case(case_file)
        assert result.status == Status.COMPLETED_WITH_USER_CONFIRMATION_PENDING
        assert len(result.edit_results) == 1
        assert result.edit_results[0].success

    def test_overwrite_original_rejected(self, tmp_image: Path, tmp_path: Path):
        """Overwriting original is rejected."""
        case_data = {
            "case_id": "test",
            "input_image": str(tmp_image),
            "requested_phase": "edit",
            "truth_mode": "纪实",
            "operations": [
                {
                    "case_id": "test",
                    "input_image": str(tmp_image),
                    "level": "L1",
                    "operation": "exposure_contrast_color",
                    "parameters": {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0},
                    "must_preserve": [],
                    "allowed_changes": [],
                    "forbidden_changes": [],
                    "strength": "subtle",
                    "output_image": str(tmp_image),
                }
            ],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case.json"
        with open(case_file, "w") as f:
            json.dump(case_data, f)

        result = run_case(case_file)
        assert result.status == Status.FAILED_INVALID_CONTRACT

    def test_unsupported_operation_rejected(
        self, tmp_image: Path, tmp_path: Path, tmp_output: Path
    ):
        """Unsupported operation is rejected."""
        case_data = {
            "case_id": "test",
            "input_image": str(tmp_image),
            "requested_phase": "edit",
            "truth_mode": "纪实",
            "operations": [
                {
                    "case_id": "test",
                    "input_image": str(tmp_image),
                    "level": "L2",
                    "operation": "generate_background",
                    "parameters": {"prompt": "sunset"},
                    "must_preserve": [],
                    "allowed_changes": [],
                    "forbidden_changes": [],
                    "strength": "generative",
                    "output_image": str(tmp_output),
                }
            ],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case.json"
        with open(case_file, "w") as f:
            json.dump(case_data, f)

        result = run_case(case_file)
        assert result.status == Status.FAILED_INVALID_CONTRACT

    def test_runner_does_not_fake_diagnosis(self, tmp_image: Path, tmp_path: Path):
        """Runner does not write framework preparation as visual diagnosis."""
        case_data = {
            "case_id": "test",
            "input_image": str(tmp_image),
            "requested_phase": "diagnosis",
            "truth_mode": "纪实",
            "operations": [],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case.json"
        with open(case_file, "w") as f:
            json.dump(case_data, f)

        result = run_case(case_file)
        # Without V1, diagnosis is blocked
        assert result.status == Status.BLOCKED_NO_VIEW_CAPABILITY
        # Should NOT say completed
        assert result.status != Status.COMPLETED

    def test_edit_without_v2_is_blocked(self, tmp_image: Path, tmp_path: Path, tmp_output: Path):
        """An explicitly adapter-less edit cannot use an undeclared capability."""
        case_data = {
            "case_id": "test-no-v2",
            "input_image": str(tmp_image),
            "requested_phase": "edit",
            "truth_mode": "纪实",
            "operations": [
                {
                    "case_id": "test-no-v2",
                    "input_image": str(tmp_image),
                    "level": "L1",
                    "operation": "exposure_contrast_color",
                    "parameters": {"exposure": 0.1},
                    "output_image": str(tmp_output),
                }
            ],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case-no-v2.json"
        case_file.write_text(json.dumps(case_data), encoding="utf-8")

        result = run_case(case_file, adapters=[])

        assert result.status == Status.BLOCKED_NO_EDIT_CAPABILITY
        assert not tmp_output.exists()

    def test_full_phase_compares_each_candidate_and_records_evidence(
        self, tmp_image: Path, tmp_path: Path
    ):
        """Full phase produces engineering comparisons and traceable evidence."""
        candidate = tmp_path / "candidate.png"
        case_data = {
            "case_id": "test-full",
            "input_image": str(tmp_image),
            "requested_phase": "full",
            "truth_mode": "纪实",
            "operations": [
                {
                    "case_id": "test-full",
                    "input_image": str(tmp_image),
                    "level": "L1",
                    "operation": "exposure_contrast_color",
                    "parameters": {"exposure": 0.1, "contrast": 1.1},
                    "must_preserve": ["identity"],
                    "allowed_changes": ["exposure", "contrast"],
                    "forbidden_changes": ["face_structure"],
                    "strength": "subtle",
                    "output_image": str(candidate),
                }
            ],
            "user_confirmation_status": "pending",
        }
        case_file = tmp_path / "case-full.json"
        case_file.write_text(json.dumps(case_data), encoding="utf-8")

        result = run_case(
            case_file,
            adapters=[ObservationAdapter(), DeterministicEditorAdapter(), LocalCompareAdapter()],
            now=__import__("datetime").datetime(2025, 1, 1),
        )

        assert result.status == Status.COMPLETED_WITH_USER_CONFIRMATION_PENDING
        assert len(result.comparison_results) == 1
        comparison = result.comparison_results[0]
        assert comparison.candidate_readable
        assert comparison.report_json_path is not None
        assert comparison.report_json_path.exists()
        evidence = read_evidence(result.evidence_path)
        assert evidence.operations[0]["parameters"]["exposure"] == 0.1
        assert evidence.operations[0]["output_image"] == str(candidate)
        assert evidence.operations[0]["output_sha256"] == result.edit_results[0].output_sha256
        assert len(evidence.comparisons) == 1
        assert evidence.comparisons[0]["candidate_sha256"] == comparison.candidate_sha256
