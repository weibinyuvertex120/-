"""Evidence recording for visual-art-direction skill."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import EvidenceRecord


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file.

    Args:
        path: Path to file.

    Returns:
        SHA-256 hex string.

    Raises:
        FileNotFoundError: If file doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def write_evidence(record: EvidenceRecord, output_path: Path) -> None:
    """Write evidence record to JSON file.

    Args:
        record: Evidence record to write.
        output_path: Path to output JSON file.

    Notes:
        - JSON serialization is stable (sorted keys).
        - Paths recorded as absolute strings.
        - Time injected by runner; tests use fixed time.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict with sorted keys
    data = record.model_dump(mode="json")

    # Write with sorted keys for stable serialization
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


def read_evidence(input_path: Path) -> EvidenceRecord:
    """Read evidence record from JSON file.

    Args:
        input_path: Path to input JSON file.

    Returns:
        EvidenceRecord instance.

    Raises:
        FileNotFoundError: If file doesn't exist.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Evidence file not found: {input_path}")

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    return EvidenceRecord.model_validate(data)
