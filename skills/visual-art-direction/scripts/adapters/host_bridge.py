"""Host bridge adapter for visual-art-direction skill.

This adapter reads host capability declarations from a JSON file.
It does not bind to any specific API (WorkBuddy, etc.).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..contracts import (
    AdapterHealth,
    Capability,
    ComparisonResult,
    EditRequest,
    EditResult,
    ObservationResult,
)


class HostBridgeAdapter:
    """Adapter that reads host capability declarations from JSON."""

    name: str = "host-bridge"
    version: str = "1.0.0"

    def __init__(self, config_path: Path):
        """Initialize from JSON config file.

        Args:
            config_path: Path to host capability JSON.
        """
        self._config_path = config_path
        self._config: dict = {}
        self._load_config()
        self.name = str(self._config.get("provider", self.name))
        self.version = str(self._config.get("provider_version", self.version))

    def _load_config(self) -> None:
        """Load config from JSON file."""
        if not self._config_path.exists():
            raise FileNotFoundError(f"Config not found: {self._config_path}")

        with open(self._config_path, encoding="utf-8") as f:
            self._config = json.load(f)

    @classmethod
    def from_json(cls, path: Path) -> HostBridgeAdapter:
        """Create adapter from JSON file.

        Args:
            path: Path to host capability JSON.

        Returns:
            HostBridgeAdapter instance.
        """
        return cls(path)

    def healthcheck(self) -> AdapterHealth:
        """Check host health based on config.

        Returns:
            AdapterHealth with capabilities from config.
        """
        now = datetime.now()

        # Config must have these fields
        required = ["capabilities", "provider", "healthcheck_time", "evidence"]
        for field in required:
            if field not in self._config:
                return AdapterHealth(
                    name=self.name,
                    version=self.version,
                    healthy=False,
                    capabilities=set(),
                    evidence=f"Missing required field: {field}",
                    checked_at=now,
                )

        caps = self.capabilities()

        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities=caps,
            evidence=self._config.get("evidence", ""),
            checked_at=now,
        )

    def capabilities(self) -> set[Capability]:
        """Return only declared capabilities with an executable bridge operation."""
        caps = set()
        for cap_str in self._config.get("capabilities", []):
            try:
                cap = Capability(cap_str)
            except ValueError:
                continue
            if cap == Capability.V1_VISUAL_OBSERVATION:
                operation = self._config.get("operations", {}).get("observe", {})
                result_path = Path(operation.get("result_path", ""))
                if operation.get("mode") != "file" or not result_path.is_absolute():
                    continue
                try:
                    ObservationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
            if cap == Capability.V1_VISUAL_OBSERVATION:
                caps.add(cap)
        return caps

    def observe(self, image: Path, prompt: str) -> ObservationResult:
        """Read and validate a host-produced, file-backed observation result."""
        operation = self._config.get("operations", {}).get("observe", {})
        if operation.get("mode") != "file":
            raise NotImplementedError("Host bridge observe operation is not configured")
        result_path = Path(operation.get("result_path", ""))
        if not result_path.is_absolute():
            raise ValueError("Host observation result_path must be absolute")
        return ObservationResult.model_validate_json(result_path.read_text(encoding="utf-8"))

    def edit(self, request: EditRequest) -> EditResult:
        """Not supported by host bridge in first version.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("Host bridge does not support edit in v1")

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
        """Not supported by host bridge in first version.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("Host bridge does not support compare in v1")
