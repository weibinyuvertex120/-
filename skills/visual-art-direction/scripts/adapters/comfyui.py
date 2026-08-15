"""ComfyUI adapter for visual-art-direction skill.

First version: only healthcheck and workflow hash.
Does NOT execute models, download models, or store API keys.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from ..contracts import (
    AdapterHealth,
    Capability,
    ComparisonResult,
    EditRequest,
    EditResult,
)


class ComfyUIAdapter:
    """Adapter for ComfyUI integration (first version: healthcheck only)."""

    name: str = "comfyui"
    version: str = "1.0.0"

    def __init__(self, base_url: str, timeout_seconds: float = 5.0):
        """Initialize ComfyUI adapter.

        Args:
            base_url: ComfyUI server URL.
            timeout_seconds: Connection timeout.
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._workflow_hash: str = ""

    def healthcheck(self) -> AdapterHealth:
        """Check ComfyUI server health.

        Note: Server reachable != model available != edit result completed.

        Returns:
            AdapterHealth with connection status.
        """
        now = datetime.now()

        # First version: just check if we can reach the server
        # In real implementation, this would make an HTTP request
        # For now, return unhealthy as we don't have network access
        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=False,
            capabilities=set(),
            evidence="ComfyUI adapter is protocol-only in v1; no network healthcheck implemented",
            checked_at=now,
        )

    def capabilities(self) -> set[Capability]:
        """Return capabilities (none in v1).

        Returns:
            Empty set.
        """
        return set()

    def set_workflow_hash(self, workflow_path: Path) -> str:
        """Compute and store workflow hash.

        Args:
            workflow_path: Path to workflow JSON.

        Returns:
            SHA-256 hash of workflow.
        """
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow not found: {workflow_path}")

        with open(workflow_path, "rb") as f:
            self._workflow_hash = hashlib.sha256(f.read()).hexdigest()

        return self._workflow_hash

    def observe(self, image: Path, prompt: str) -> dict:
        """Not supported in v1.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("ComfyUI observe not implemented in v1")

    def edit(self, request: EditRequest) -> EditResult:
        """Not supported in v1.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("ComfyUI edit not implemented in v1")

    def compare(self, original: Path, candidate: Path) -> ComparisonResult:
        """Not supported in v1.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("ComfyUI compare not implemented in v1")
