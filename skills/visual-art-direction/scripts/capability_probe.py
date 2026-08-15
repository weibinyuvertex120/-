"""Capability probe for visual-art-direction skill."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from .contracts import (
    AdapterHealth,
    Capability,
    CapabilityReport,
    CapabilityState,
    ObservationResult,
    Status,
)


@runtime_checkable
class CapabilityAdapter(Protocol):
    """Protocol for capability adapters."""

    name: str
    version: str

    def healthcheck(self) -> AdapterHealth: ...
    def capabilities(self) -> set[Capability]: ...
    def observe(self, image: Path, prompt: str) -> ObservationResult: ...


def _check_v0(input_path: Path) -> tuple[bool, str]:
    """Check V0 file access capability."""
    if not input_path.exists():
        return False, f"File does not exist: {input_path}"

    if not input_path.is_file():
        return False, f"Path is not a file: {input_path}"

    # Check if Pillow can identify the image
    try:
        from PIL import Image

        with Image.open(input_path) as img:
            img.verify()
    except Exception as e:
        return False, f"Pillow cannot identify image: {e}"

    # Check if file is readable and compute hash
    try:
        from .evidence import sha256_file

        sha256_file(input_path)
    except Exception as e:
        return False, f"Cannot compute SHA-256: {e}"

    return True, "File exists, Pillow-identifiable, readable, SHA-256 computed"


def _get_image_size(input_path: Path) -> tuple[int, int]:
    """Get image size using Pillow."""
    try:
        from PIL import Image

        with Image.open(input_path) as img:
            return img.size
    except Exception:
        return (0, 0)


def probe_capabilities(
    input_path: Path | None,
    *,
    adapters: list[CapabilityAdapter] | None = None,
    now: datetime | None = None,
) -> CapabilityReport:
    """Probe capabilities for a given input image.

    Args:
        input_path: Path to the input image.
        adapters: List of capability adapters to check.
        now: Current time (for testing).

    Returns:
        CapabilityReport with capability states.
    """
    if now is None:
        now = datetime.now()

    report = CapabilityReport(checked_at=now)

    # No input
    if input_path is None:
        report.status = Status.BLOCKED_NO_INPUT
        return report

    report.input_path = input_path
    report.input_exists = input_path.exists() and input_path.is_file()

    # Check V0
    v0_available, v0_evidence = _check_v0(input_path)
    report.capabilities[Capability.V0_FILE_ACCESS] = CapabilityState(
        available=v0_available,
        evidence=v0_evidence,
        provider="local",
        checked_at=now,
    )

    if not v0_available:
        report.status = Status.BLOCKED_NO_INPUT
        return report

    # Get image info
    from .evidence import sha256_file

    report.input_sha256 = sha256_file(input_path)
    report.input_size = _get_image_size(input_path)

    # Initialize V1-V3 as unavailable
    report.capabilities[Capability.V1_VISUAL_OBSERVATION] = CapabilityState(
        available=False,
        evidence="No adapter provided",
        provider="none",
        checked_at=now,
    )
    report.capabilities[Capability.V2_IMAGE_EDITING] = CapabilityState(
        available=False,
        evidence="No adapter provided",
        provider="none",
        checked_at=now,
    )
    report.capabilities[Capability.V3_RESULT_COMPARISON] = CapabilityState(
        available=False,
        evidence="No adapter provided",
        provider="none",
        checked_at=now,
    )

    # Check adapters
    if adapters:
        for adapter in adapters:
            report.adapters_checked.append(adapter.name)
            try:
                health = adapter.healthcheck()
                if health.healthy:
                    for cap in health.capabilities:
                        if cap in report.capabilities:
                            # Only update if not already available from a previous adapter
                            if not report.capabilities[cap].available:
                                report.capabilities[cap] = CapabilityState(
                                    available=True,
                                    evidence=health.evidence,
                                    provider=adapter.name,
                                    provider_version=adapter.version,
                                    checked_at=now,
                                )
            except Exception:
                # Adapter failed, skip
                pass

    report.status = Status.READY
    return report
