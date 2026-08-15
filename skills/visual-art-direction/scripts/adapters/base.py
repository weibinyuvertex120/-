"""Base adapter protocol for visual-art-direction skill."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..contracts import (
    AdapterHealth,
    Capability,
    ComparisonResult,
    EditRequest,
    EditResult,
    ObservationResult,
)


@runtime_checkable
class CapabilityAdapter(Protocol):
    """Protocol for capability adapters."""

    name: str
    version: str

    def healthcheck(self) -> AdapterHealth:
        """Check adapter health and return capabilities.

        Returns:
            AdapterHealth with capabilities and evidence.
        """
        ...

    def capabilities(self) -> set[Capability]:
        """Return set of capabilities this adapter provides.

        Returns:
            Set of Capability enums.
        """
        ...

    def observe(self, image: Path, prompt: str) -> ObservationResult:
        """Observe image and return structured result.

        Args:
            image: Path to the image.
            prompt: Observation prompt.

        Returns:
            Structured observation result.

        Raises:
            NotImplementedError: If not supported.
        """
        ...

    def edit(self, request: EditRequest) -> EditResult:
        """Execute an edit request.

        Args:
            request: Edit request with parameters.

        Returns:
            EditResult with output information.

        Raises:
            NotImplementedError: If not supported.
        """
        ...

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
        """Compare original and candidate images.

        Args:
            original: Path to original image.
            candidate: Path to candidate image.
            report_dir: Directory for comparison artifacts.

        Returns:
            ComparisonResult with comparison information.

        Raises:
            NotImplementedError: If not supported.
        """
        ...
