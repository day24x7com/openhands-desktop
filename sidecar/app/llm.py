"""LLM layer.

A small provider adapter over the Chat Completions wire format that virtually every
provider speaks (OpenAI, Azure, OpenRouter, Ollama, LM Studio, vLLM, Groq, …) plus
Anthropic's Messages API. It deliberately keeps the surface minimal — the OpenHands
desktop app needs tool calling, streaming text and token accounting, nothing more.

Using an ``LLMClient`` protocol keeps the agent loop testable: tests inject
``MockLLM`` and never hit the network.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": {"base_url": "https://api.anthropic.com", "style": "anthropic"},
    "openai": {"base_url": "https://api.openai.com/v1", "style": "openai"},
    "azure": {"base_url": "", "style": "azure"},
    "google": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "style": "openai"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "style": "openai"},
    "bedrock": {"base_url": "", "style": "openai"},
    "openai-compatible": {"base_url": "", "style": "openai"},
    "ollama": {"base_url": "http://localhost:11434/v1", "style": "openai"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "style": "openai"},
    "vllm": {"base_url": "http://localhost:8000/v1", "style": "openai"},
    "mock": {"base_url": "", "style": "mock"},
}

#: Rough $/1k-token prices, used only for the live cost meter (spec FR-2.6).
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus": (0.015, 0.075),
    "claude-sonnet": (0.003, 0.015),
    "claude-haiku": (0.0008, 0.004),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4.1": (0.002, 0.008),
    "o4-mini": (0.0011, 0.0044),
    "gemini-2.5-pro": (0.00125, 0.01),
    "gemini-2.5-flash": (0.0003, 0.0025),
    "qwen": (0.0002, 0.0006),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    lowered = model.lower()
    for key, (in_price, out_price) in MODEL_PRICES.items():
        if key in lowered:
            return (prompt_tokens / 1000) * in_price + (completion_tokens / 1000) * out_price
    return 0.0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class LlmReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""


class LlmError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMClient(Protocol):
    model: str

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], stream: bool = False
    ) -> LlmReply: ...


class ChatCompletionsClient:
    """OpenAI-compatible Chat Completions client (one class, many providers)."""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str | None,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout_seconds: int = 300,
        retries: int = 2,
        extra_headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai-compatible"])
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or defaults["base_url"]).rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout_seconds
        self.retries = retries
        self.extra_headers = extra_headers or {}
        self._transport = transport

    # ------------------------------------------------------------- headers
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.provider == "azure":
            if self.api_key:
                headers["api-key"] = self.api_key
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.provider == "openrouter":
            headers.setdefault("HTTP-Referer", "https://github.com/day24x7com/openhands-desktop")
            headers.setdefault("X-Title", "OpenHands Desktop")
        return headers

    def endpoint(self) -> str:
        if self.provider == "azure":
            if not self.base_url:
                raise LlmError("Azure requires a base URL, e.g. https://<res>.openai.azure.com")
            sep = "&" if "?" in self.base_url else "?"
            return f"{self.base_url}/openai/deployments/{self.model}/chat/completions{sep}api-version=2024-10-21"
        return f"{self.base_url}/chat/completions"

    # ---------------------------------------------------------------- call
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], stream: bool = False
    ) -> LlmReply:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(self.timeout, connect=20.0),
                    transport=self._transport,
                ) as client:
                    response = client.post(self.endpoint(), json=body, headers=self._headers())
                if response.status_code >= 400:
                    raise LlmError(_describe_http_error(response), response.status_code)
                return _parse_chat_completion(response.json(), self.model)
            except LlmError as exc:
                if exc.status_code and 400 <= exc.status_code < 500 and exc.status_code not in (408, 429):
                    raise
                last_error = exc
            except httpx.HTTPError as exc:
                last_error = LlmError(f"network error talking to {self.provider}: {exc}")
            if attempt < self.retries:
                time.sleep(min(2**attempt, 5))
        raise last_error or LlmError("unknown LLM failure")

    # ------------------------------------------------------------- helpers
    def test_connection(self) -> tuple[bool, int, str]:
        started = time.monotonic()
        try:
            reply = self.complete([{"role": "user", "content": "Reply with the single word: pong"}], [])
        except LlmError as exc:
            return False, int((time.monotonic() - started) * 1000), str(exc)
        latency = int((time.monotonic() - started) * 1000)
        return True, latency, (reply.text or "connected")[:200]


class AnthropicClient(ChatCompletionsClient):
    """Anthropic Messages API adapter, normalised to the same ``LlmReply`` shape."""

    def endpoint(self) -> str:
        return f"{self.base_url or 'https://api.anthropic.com'}/v1/messages"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            **self.extra_headers,
            **({"x-api-key": self.api_key} if self.api_key else {}),
        }

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], stream: bool = False
    ) -> LlmReply:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role == "system":
                continue
            if role == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.get("tool_call_id") or message.get("name"),
                                "content": message.get("content") or "",
                            }
                        ],
                    }
                )
            elif role == "assistant" and message.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": message["content"]})
                for call in message["tool_calls"]:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call["id"],
                            "name": call["function"]["name"],
                            "input": json.loads(call["function"].get("arguments") or "{}"),
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
            else:
                converted.append({"role": role, "content": message.get("content") or ""})

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": converted,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(self.timeout, connect=20.0), transport=self._transport
                ) as client:
                    response = client.post(self.endpoint(), json=body, headers=self._headers())
                if response.status_code >= 400:
                    raise LlmError(_describe_http_error(response), response.status_code)
                return _parse_anthropic(response.json(), self.model)
            except LlmError as exc:
                if exc.status_code and 400 <= exc.status_code < 500 and exc.status_code not in (408, 429):
                    raise
                last_error = exc
            except httpx.HTTPError as exc:
                last_error = LlmError(f"network error: {exc}")
            if attempt < self.retries:
                time.sleep(min(2**attempt, 5))
        raise last_error or LlmError("unknown LLM failure")


class MockLLM:
    """Deterministic offline model used by tests and the 'demo' provider.

    The scripted reply sequence is passed in by the caller; when exhausted it finishes
    the task so the agent loop always terminates.
    """

    model = "mock-model"

    def __init__(self, script: list[LlmReply] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[list[dict[str, Any]]] = []

    def test_connection(self) -> tuple[bool, int, str]:
        return True, 0, "mock model ready (no network call)"

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], stream: bool = False
    ) -> LlmReply:
        self.calls.append(messages)
        if self.script:
            return self.script.pop(0)
        return LlmReply(
            text="Done.",
            tool_calls=[ToolCall(id=f"call-{len(self.calls)}", name="finish", arguments={"summary": "Done."})],
            usage=Usage(prompt_tokens=10, completion_tokens=5),
            model=self.model,
        )


# -------------------------------------------------------------- factories


def build_client(
    provider: str,
    model: str,
    api_key: str | None,
    base_url: str | None = None,
    **kwargs: Any,
) -> LLMClient:
    if provider == "mock":
        return MockLLM()
    if provider == "anthropic":
        return AnthropicClient(provider, model, api_key, base_url, **kwargs)
    return ChatCompletionsClient(provider, model, api_key, base_url, **kwargs)


def iter_tool_definitions(tools: list[dict[str, Any]]) -> Iterator[str]:
    for tool in tools:
        yield tool["function"]["name"]


# ------------------------------------------------------------- parsers


def _parse_chat_completion(payload: dict[str, Any], fallback_model: str) -> LlmReply:
    choices = payload.get("choices") or []
    if not choices:
        raise LlmError(f"provider returned no choices: {json.dumps(payload)[:300]}")
    message = choices[0].get("message") or {}
    tool_calls: list[ToolCall] = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {"raw": raw_args}
        tool_calls.append(
            ToolCall(
                id=call.get("id") or f"call_{len(tool_calls)}",
                name=fn.get("name", ""),
                arguments=args,
            )
        )
    usage = payload.get("usage") or {}
    return LlmReply(
        text=(message.get("content") or "").strip(),
        tool_calls=tool_calls,
        usage=Usage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        ),
        model=payload.get("model") or fallback_model,
    )


def _parse_anthropic(payload: dict[str, Any], fallback_model: str) -> LlmReply:
    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in payload.get("content") or []:
        if block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input") or {},
                )
            )
    usage = payload.get("usage") or {}
    return LlmReply(
        text="\n".join(texts).strip(),
        tool_calls=tool_calls,
        usage=Usage(
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
        ),
        model=payload.get("model") or fallback_model,
    )


def _describe_http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("error", payload)
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail)
    except Exception:
        detail = response.text[:300]
    if response.status_code in (401, 403):
        return f"Authentication failed ({response.status_code}): {detail}"
    if response.status_code == 404:
        return f"Model or endpoint not found ({response.status_code}): {detail}"
    if response.status_code == 429:
        return f"Rate limited by provider ({response.status_code}): {detail}"
    return f"Provider error {response.status_code}: {detail}"
