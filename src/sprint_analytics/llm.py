"""OpenRouter client (OpenAI-compatible chat completions) with usage and cost."""
import os
import time
from dataclasses import dataclass

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-5"


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    latency_ms: int


def llm_configured() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def default_model() -> str:
    return os.environ.get("SA_MODEL", DEFAULT_MODEL)


def complete(messages: list[dict], model: str | None = None, temperature: float = 0.2,
             client: httpx.Client | None = None, timeout: float = 60.0) -> LLMResult:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    model = model or default_model()
    payload = {"model": model, "messages": messages, "temperature": temperature,
               "usage": {"include": True}}
    started = time.perf_counter()
    try:
        http = client or httpx.Client(timeout=timeout)
        response = http.post(OPENROUTER_URL, json=payload,
                             headers={"Authorization": f"Bearer {key}", "X-Title": "sprint-analytics"})
    except httpx.HTTPError as exc:
        raise LLMError(f"request failed: {exc}") from exc
    latency = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        raise LLMError(f"OpenRouter returned {response.status_code}: {response.text[:200]}")
    body = response.json()
    choices = body.get("choices") or []
    text = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
    if not text:
        raise LLMError("empty completion")
    usage = body.get("usage") or {}
    return LLMResult(text=text, model=body.get("model", model),
                     prompt_tokens=usage.get("prompt_tokens"),
                     completion_tokens=usage.get("completion_tokens"),
                     cost_usd=usage.get("cost"), latency_ms=latency)
