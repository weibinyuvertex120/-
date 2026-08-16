"""Tests for the local llama.cpp Qwen3-VL observation adapter."""

# ruff: noqa: E402 -- the bundled Skill directory is intentionally added before imports.

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import Request

import pytest
from PIL import Image

SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "visual-art-direction"
sys.path.insert(0, str(SKILL_ROOT))

from scripts.adapters.llama_cpp import LlamaCppQwenAdapter
from scripts.compare_candidates import LocalCompareAdapter
from scripts.contracts import canonical_observation_sha256
from scripts.deterministic_editor import DeterministicEditorAdapter
from scripts.evidence import sha256_file
from scripts.runner import run_case


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _image(path: Path) -> Path:
    Image.new("RGB", (2, 2), color=(100, 120, 140)).save(path)
    return path


def _payload() -> dict:
    return {
        "items": [
            {
                "dimension": "scene",
                "statement": "A centered subject is visible against a plain background.",
                "evidence": ["The subject occupies the center of the frame."],
                "confidence": "high",
            }
        ],
        "uncertainties": ["The synthetic fixture has limited semantic detail."],
    }


def _fake_urlopen(request: Request, timeout: float | None = None) -> _Response:
    assert timeout == 3.0
    if request.full_url.endswith("/health"):
        return _Response({"status": "ok"})
    if request.full_url.endswith("/v1/models"):
        return _Response(
            {
                "data": [
                    {
                        "id": "Qwen/Qwen3-VL-4B-Instruct-GGUF",
                        "architecture": {"input_modalities": ["text", "image"]},
                    }
                ]
            }
        )
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "Qwen/Qwen3-VL-4B-Instruct-GGUF"
    assert body["temperature"] == 0.0
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["schema"]["additionalProperties"] is False
    content = body["messages"][1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    return _Response({"choices": [{"message": {"content": json.dumps(_payload())}}]})


def test_llama_cpp_healthcheck_and_observe_bind_hashes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("scripts.adapters.llama_cpp.urllib_request.urlopen", _fake_urlopen)
    image = _image(tmp_path / "input.png")
    prompt = "Record visible facts only."
    adapter = LlamaCppQwenAdapter(
        base_url="http://127.0.0.1:8080",
        timeout_seconds=3.0,
    )

    health = adapter.healthcheck()
    observation = adapter.observe(image, prompt)

    assert health.healthy
    assert "Qwen3-VL-4B-Instruct-GGUF" in health.evidence
    assert observation.provider == adapter.name
    assert observation.provider_version == adapter.version
    assert observation.input_sha256 == sha256_file(image)
    assert observation.prompt_sha256 == hashlib.sha256(prompt.encode()).hexdigest()
    assert observation.items[0].dimension == "scene"


def test_llama_cpp_healthcheck_rejects_missing_or_text_only_model(monkeypatch) -> None:
    def wrong_model_urlopen(request: Request, timeout: float | None = None) -> _Response:
        if request.full_url.endswith("/health"):
            return _Response({"status": "ok"})
        return _Response(
            {
                "data": [
                    {
                        "id": "text-only",
                        "architecture": {"input_modalities": ["text"]},
                    }
                ]
            }
        )

    monkeypatch.setattr("scripts.adapters.llama_cpp.urllib_request.urlopen", wrong_model_urlopen)

    health = LlamaCppQwenAdapter().healthcheck()

    assert not health.healthy
    assert not health.capabilities
    assert "model" in health.evidence.lower()


def test_llama_cpp_first_phase_rejects_non_loopback_server() -> None:
    with pytest.raises(ValueError, match="loopback"):
        LlamaCppQwenAdapter(base_url="https://example.com")


def test_llama_cpp_malformed_response_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("scripts.adapters.llama_cpp.urllib_request.urlopen", _fake_urlopen)
    image = _image(tmp_path / "input.png")

    def malformed_urlopen(request: Request, timeout: float | None = None) -> _Response:
        if request.full_url.endswith("/health"):
            return _Response({"status": "ok"})
        if request.full_url.endswith("/v1/models"):
            return _fake_urlopen(request, timeout)
        return _Response({"choices": [{"message": {"content": "not-json"}}]})

    monkeypatch.setattr("scripts.adapters.llama_cpp.urllib_request.urlopen", malformed_urlopen)
    adapter = LlamaCppQwenAdapter(timeout_seconds=3.0)

    try:
        adapter.observe(image, "Record visible facts only.")
    except RuntimeError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("Malformed llama.cpp output must fail closed")


def test_llama_cpp_adapter_runs_full_case_with_existing_v2_v3(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("scripts.adapters.llama_cpp.urllib_request.urlopen", _fake_urlopen)
    image = _image(tmp_path / "input.png")
    candidate = tmp_path / "candidate.png"
    adapter = LlamaCppQwenAdapter(timeout_seconds=3.0)
    prompt = "Record visible facts only."
    observation = adapter.observe(image, prompt)
    case = {
        "case_id": "llama-full",
        "input_image": str(image.resolve()),
        "requested_phase": "full",
        "observation_prompt": prompt,
        "source_observation": observation.model_dump(mode="json"),
        "plan": {
            "plan_id": "plan-llama-full",
            "visual_goal": "Make the centered subject easier to read.",
            "recommended_level": "L1",
            "operations": ["exposure_contrast_color"],
            "success_criteria": ["The bounded exposure change is present."],
            "must_preserve": ["scene facts"],
            "allowed_changes": ["exposure"],
            "forbidden_changes": ["generation"],
            "stop_condition": "Stop after the bounded edit.",
            "decision_source": "agent",
            "basis": [
                {
                    "observation_index": 0,
                    "dimension": "scene",
                    "evidence": "The subject occupies the center of the frame.",
                }
            ],
            "observation_sha256": canonical_observation_sha256(observation),
        },
        "operations": [
            {
                "case_id": "llama-full",
                "input_image": str(image.resolve()),
                "level": "L1",
                "operation": "exposure_contrast_color",
                "parameters": {"exposure": 0.1},
                "output_image": str(candidate.resolve()),
            }
        ],
    }
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(case), encoding="utf-8")

    result = run_case(
        case_file,
        adapters=[adapter, DeterministicEditorAdapter(), LocalCompareAdapter()],
    )

    assert result.status.value == "completed_with_user_feedback_pending"
    assert result.observation_result is not None
    assert result.observation_result.provider == adapter.name
    assert result.comparison_results[0].candidate_readable


def test_cli_exposes_llama_cpp_config_entrypoint() -> None:
    skill_root = Path(__file__).resolve().parents[1] / "skills" / "visual-art-direction"
    completed = subprocess.run(
        [sys.executable, "-m", "scripts", "--help"],
        cwd=skill_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--llama-cpp-config" in completed.stdout


def test_cli_rejects_ambiguous_v1_adapter_configs(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts",
            "--case",
            str(tmp_path / "case.json"),
            "--output",
            str(tmp_path / "output"),
            "--host-config",
            str(tmp_path / "host.json"),
            "--llama-cpp-config",
            str(tmp_path / "llama.json"),
        ],
        cwd=SKILL_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "not allowed with argument" in completed.stderr


def test_bundled_llama_cpp_config_example_is_loadable() -> None:
    skill_root = Path(__file__).resolve().parents[1] / "skills" / "visual-art-direction"
    config_path = skill_root / "references" / "llama-cpp-qwen3-vl.config.example.json"

    adapter = LlamaCppQwenAdapter.from_json(config_path)

    assert adapter.name == "qwen3-vl-4b-llama.cpp"
    assert adapter.version == "Qwen3-VL-4B-Instruct-GGUF-Q4_K_M"


def test_llama_cpp_config_rejects_invalid_field_types(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.json"
    config_path.write_text(json.dumps({"base_url": 123}), encoding="utf-8")

    with pytest.raises(ValueError):
        LlamaCppQwenAdapter.from_json(config_path)
