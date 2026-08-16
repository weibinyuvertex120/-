"""Local llama.cpp Qwen3-VL observation adapter."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ..contracts import AdapterHealth, Capability, ObservationItem, ObservationResult
from ..evidence import sha256_file

_DEFAULT_MODEL = "Qwen/Qwen3-VL-4B-Instruct-GGUF"
_DEFAULT_PROVIDER = "qwen3-vl-4b-llama.cpp"
_DEFAULT_VERSION = "Qwen3-VL-4B-Instruct-GGUF"
_DEFAULT_SYSTEM_PROMPT = (
    "You are a visual observer for a photo transformation pipeline. "
    "Report only directly visible facts. Do not infer identity, age, profession, health, "
    "or an unstated story. Return only the requested JSON object, without Markdown. "
    "Every observation must include at least one visible evidence clue. "
    "Put uncertain details in uncertainties."
)
_STRUCTURED_OUTPUT_INSTRUCTION = """
The output contract is mandatory. Output exactly one JSON object with exactly these
top-level keys: "items" and "uncertainties". Never translate or rename these keys.
"items" must be a non-empty array. Each item must contain exactly these keys:
"dimension", "statement", "evidence", and "confidence".
"dimension" must be one of "P01", "P02", "P03", "P04", "P05", "P06", "P07",
"P08", "P09", "P10", "scene", "portrait", or "other".
"statement" must be a non-empty string describing a directly visible fact.
"evidence" must be a non-empty array of concrete visible clues.
"confidence" must be exactly "high", "medium", or "low".
"uncertainties" must be an array of strings and may be empty.
Use English JSON keys even when the user prompt is written in another language.
Do not output Markdown, commentary, translated keys, or any extra keys.
Example shape:
{"items":[{"dimension":"scene","statement":"A person stands beside a cabin.",
"evidence":["The person and cabin are both visible in the frame."],"confidence":"high"}],
"uncertainties":[]}
"""


class _ObservationPayload(BaseModel, extra="forbid"):
    """Model-owned semantic fields; identity and hashes are adapter-owned."""

    items: list[ObservationItem] = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list)


class _AdapterConfig(BaseModel, extra="forbid"):
    base_url: str = Field(default="http://127.0.0.1:8080", min_length=1)
    model: str = Field(default=_DEFAULT_MODEL, min_length=1)
    provider: str = Field(default=_DEFAULT_PROVIDER, min_length=1)
    provider_version: str = Field(default=_DEFAULT_VERSION, min_length=1)
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_tokens: int = Field(default=768, gt=0)
    system_prompt: str = Field(default=_DEFAULT_SYSTEM_PROMPT, min_length=1)
    api_key: str = "sk-no-key-required"
    seed: int = 0


_OBSERVATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "dimension": {
                        "type": "string",
                        "enum": [
                            "P01",
                            "P02",
                            "P03",
                            "P04",
                            "P05",
                            "P06",
                            "P07",
                            "P08",
                            "P09",
                            "P10",
                            "scene",
                            "portrait",
                            "other",
                        ],
                    },
                    "statement": {"type": "string", "minLength": 1},
                    "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["dimension", "statement", "evidence", "confidence"],
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["items", "uncertainties"],
}


class LlamaCppQwenAdapter:
    """Run Qwen3-VL GGUF through a local llama-server OpenAI-compatible API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        *,
        model: str = _DEFAULT_MODEL,
        provider: str = _DEFAULT_PROVIDER,
        provider_version: str = _DEFAULT_VERSION,
        timeout_seconds: float = 120.0,
        max_tokens: int = 768,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        api_key: str = "sk-no-key-required",
        seed: int = 0,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("llama.cpp base_url must use http:// or https://")
        hostname = urlparse(base_url).hostname
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("First-phase llama.cpp server must use a loopback address")
        if timeout_seconds <= 0:
            raise ValueError("llama.cpp timeout_seconds must be positive")
        if max_tokens <= 0:
            raise ValueError("llama.cpp max_tokens must be positive")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.name = provider
        self.version = provider_version
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._api_key = api_key
        self._seed = seed

    @classmethod
    def from_json(cls, path: Path) -> LlamaCppQwenAdapter:
        """Load adapter settings from a JSON config file."""
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise FileNotFoundError(f"llama.cpp config not found: {path}") from exc
        if not isinstance(config, dict):
            raise ValueError("llama.cpp config must be a JSON object")
        validated = _AdapterConfig.model_validate(config)
        return cls(**validated.model_dump(mode="python"))

    def healthcheck(self) -> AdapterHealth:
        """Require a live llama-server before exposing V1 capability."""
        now = datetime.now()
        try:
            self._request_json("GET", "/health")
            models = self._request_json("GET", "/v1/models")
            entries = models.get("data", [])
            model_entry = next(
                (
                    item
                    for item in entries
                    if isinstance(item, dict) and item.get("id") == self._model
                ),
                None,
            )
            if model_entry is None:
                raise RuntimeError(f"Configured model is not available: {self._model}")
            modalities = model_entry.get("architecture", {}).get("input_modalities")
            if isinstance(modalities, list) and "image" not in modalities:
                raise RuntimeError(f"Configured model does not expose image input: {self._model}")
        except Exception as exc:
            return AdapterHealth(
                name=self.name,
                version=self.version,
                healthy=False,
                capabilities=set(),
                evidence=f"llama.cpp healthcheck failed: {exc}",
                checked_at=now,
            )
        return AdapterHealth(
            name=self.name,
            version=self.version,
            healthy=True,
            capabilities={Capability.V1_VISUAL_OBSERVATION},
            evidence=f"llama.cpp server is healthy for {self._model}",
            checked_at=now,
        )

    def capabilities(self) -> set[Capability]:
        return {Capability.V1_VISUAL_OBSERVATION}

    def observe(self, image: Path, prompt: str) -> ObservationResult:
        """Observe one image and bind model semantics to runtime hashes."""
        if not image.exists() or not image.is_file():
            raise FileNotFoundError(f"Observation image not found: {image}")

        input_sha256 = sha256_file(image)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        media_type = mimetypes.guess_type(image.name)[0] or "image/png"
        encoded_image = base64.b64encode(image.read_bytes()).decode("ascii")
        request_body = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{self._system_prompt}\n{_STRUCTURED_OUTPUT_INSTRUCTION}",
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{encoded_image}"},
                        },
                        {"type": "text", "text": prompt or "Record visible facts only."},
                    ],
                },
            ],
            "temperature": 0.0,
            "seed": self._seed,
            "max_tokens": self._max_tokens,
            "response_format": {
                "type": "json_schema",
                "schema": _OBSERVATION_JSON_SCHEMA,
            },
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = self._request_json("POST", "/v1/chat/completions", request_body)
        content = self._extract_content(response)
        try:
            payload = _ObservationPayload.model_validate(json.loads(content))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"llama.cpp returned invalid ObservationResult JSON: {exc}") from exc

        return ObservationResult(
            success=True,
            provider=self.name,
            provider_version=self.version,
            input_sha256=input_sha256,
            prompt_sha256=prompt_sha256,
            items=payload.items,
            uncertainties=payload.uncertainties,
            error="",
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib_request.Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"llama.cpp HTTP {exc.code}: {detail[:500]}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"llama.cpp connection failed: {exc.reason}") from exc
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"llama.cpp returned non-JSON response: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("llama.cpp response must be a JSON object")
        return value

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("llama.cpp response has no chat completion content") from exc
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(text_parts)
        raise RuntimeError("llama.cpp message content must be text")
