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

        # Parse capabilities
        caps = set()
        for cap_str in self._config.get("capabilities", []):
            try:
                caps.add(Capability(cap_str))
            except ValueError:
                pass

        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities=caps,
            evidence=self._config.get("evidence", ""),
            checked_at=now,
        )

    def capabilities(self) -> set[Capability]:
        """Return capabilities from config.

        Returns:
            Set of capabilities declared in config.
        """
        caps = set()
        for cap_str in self._config.get("capabilities", []):
            try:
                caps.add(Capability(cap_str))
            except ValueError:
                pass
        return caps

    def observe(self, image: Path, prompt: str) -> dict:
        """Not supported by host bridge in first version.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("Host bridge does not support observe in v1")

    def edit(self, request: EditRequest) -> EditResult:
        """Not supported by host bridge in first version.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("Host bridge does not support edit in v1")

    def compare(self, original: Path, candidate: Path) -> ComparisonResult:
        """Not supported by host bridge in first version.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError("Host bridge does not support compare in v1")
