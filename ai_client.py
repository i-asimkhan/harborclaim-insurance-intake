"""
The model client for HarborClaim's Phase 5 agents (docs/design/AGENTS.md, section 3).

Off by default. With no configuration nothing is ever sent anywhere: enabled() is False and
chat() returns an "off" result without making a request. Real calls are switched on with:

    AI_PROVIDER         "openrouter" to enable; blank = off
    AI_ENABLED          optional kill switch: "false" (or 0/no/off) turns AI off without
                        clearing the other settings
    OPENROUTER_API_KEY  the owner's OpenRouter key (a secret -- .env or an Azure app setting,
                        never the repo)
    AI_MODELS           comma-separated model IDs in order of preference, e.g.
                        "nvidia/nemotron-3.5-super-vl:free" first. Only models that passed the
                        probe or bake-off belong here; never the "openrouter/free" router, which
                        picks a different model per request. At most MAX_MODELS are used.
    AI_TIMEOUT_SECONDS  whole-run time limit used by the harness (default 30)

The provider is OpenRouter, called with one httpx POST to its OpenAI-compatible
/chat/completions endpoint. No OpenAI service, model, key or package is involved.

Failover: when a model is busy or broken (rate-limited, HTTP error, timeout, empty or bad
reply), chat() tries the next model in AI_MODELS, at most once each. A missing key never fails
over. The harness passes models=[the model that answered] for the rest of a run, so one run is
always one model, and the result says which model answered and what was tried.

chat() never raises. Every outcome is a ChatResult: ok, or a failure with an error_type the
harness stores on the run ("off", "bad_config", "timeout", "rate_limited", "http_error",
"bad_response", "empty_reply"). Errors are logged by type only -- never the key, the prompt,
or document text -- the same rule as email_delivery.py.
"""

import logging
import os
import time
from dataclasses import dataclass, field

import httpx

OPENROUTER = "openrouter"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_MODELS = 3
FAILOVER_ERRORS = {"rate_limited", "http_error", "timeout", "bad_response", "empty_reply"}

# Per-model request settings, learned from the model probe (AGENTS.md section 11.4). Reasoning
# models can spend the whole output budget thinking and return nothing; Nemotron 3.5 needs
# reasoning switched off, while some models (e.g. Flint) refuse to switch it off. Anything not
# listed gets short, hidden reasoning, which models without a reasoning mode ignore.
MODEL_SETTINGS: dict[str, dict] = {
    "nvidia/nemotron-3.5-super-vl:free": {"reasoning": {"enabled": False}},
}
DEFAULT_REASONING = {"effort": "low", "exclude": True}

log = logging.getLogger("uvicorn.error")


def provider() -> str:
    """The active provider, or "" when AI is off."""
    if os.environ.get("AI_ENABLED", "").strip().lower() in ("false", "0", "no", "off"):
        return ""
    return os.environ.get("AI_PROVIDER", "").strip().lower()


def enabled() -> bool:
    return provider() != ""


def configured_models() -> list[str]:
    """The configured models, in order, without blanks or duplicates, capped at MAX_MODELS."""
    seen: list[str] = []
    for name in os.environ.get("AI_MODELS", "").split(","):
        name = name.strip()
        if name and name not in seen:
            seen.append(name)
    return seen[:MAX_MODELS]


def timeout_seconds() -> int:
    try:
        return max(1, int(os.environ.get("AI_TIMEOUT_SECONDS", "") or DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


@dataclass
class ChatResult:
    ok: bool
    error_type: str | None = None
    message: dict = field(default_factory=dict)  # the assistant message, ready to append to the conversation
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None
    model_served: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    attempts: list[dict] = field(default_factory=list)  # every model tried: {"model", "error_type"}


def _post(payload: dict, headers: dict, timeout: float) -> httpx.Response:
    """The one network call. Tests replace this function; nothing else talks to the network."""
    return httpx.post(ENDPOINT, json=payload, headers=headers, timeout=timeout)


def _failed(error_type: str, started: float, detail: str = "") -> ChatResult:
    log.warning("AI call failed: %s%s.", error_type, f" ({detail})" if detail else "")
    return ChatResult(ok=False, error_type=error_type, latency_ms=int((time.monotonic() - started) * 1000))


def _call_one(name: str, key: str, messages: list[dict], tools: list[dict] | None, tool_choice: str | None,
              response_format: dict | None, max_tokens: int, timeout: float) -> ChatResult:
    """One request to one model."""
    started = time.monotonic()
    payload: dict = {
        "model": name,
        "messages": messages,
        "max_tokens": max_tokens,
        "reasoning": MODEL_SETTINGS.get(name, {}).get("reasoning", DEFAULT_REASONING),
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    if response_format:
        payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {key}", "X-Title": "HarborClaim"}

    try:
        response = _post(payload, headers, timeout)
    except httpx.TimeoutException:
        return _failed("timeout", started)
    except Exception as exc:  # noqa: BLE001 -- must never break the request; logged by type only
        return _failed("http_error", started, type(exc).__name__)

    if response.status_code == 429:
        return _failed("rate_limited", started, "HTTP 429")
    if response.status_code != 200:
        return _failed("http_error", started, f"HTTP {response.status_code}")
    try:
        body = response.json()
        if "error" in body:
            code = body["error"].get("code") if isinstance(body["error"], dict) else None
            return _failed("rate_limited" if code == 429 else "http_error", started, f"provider error {code}")
        choice = body["choices"][0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
    except Exception as exc:  # noqa: BLE001
        return _failed("bad_response", started, type(exc).__name__)

    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    if not content.strip() and not tool_calls:
        return _failed("empty_reply", started, f"finish_reason {choice.get('finish_reason')}")

    assistant = {"role": "assistant", "content": content}
    if tool_calls:
        assistant["tool_calls"] = tool_calls
    return ChatResult(
        ok=True,
        message=assistant,
        content=content,
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason"),
        model_served=body.get("model") or name,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def chat(messages: list[dict], *, tools: list[dict] | None = None, tool_choice: str | None = None,
         response_format: dict | None = None, max_tokens: int = 800, timeout: float | None = None,
         models: list[str] | None = None) -> ChatResult:
    """One model call, failing over down the model list. Returns a ChatResult; never raises.

    `models` overrides AI_MODELS: the harness passes the model that answered a run's first call,
    so the rest of the run stays on it. `timeout` is the time left for this call, shared by all
    the models tried.
    """
    started = time.monotonic()
    if not enabled():
        return ChatResult(ok=False, error_type="off")
    if provider() != OPENROUTER:
        return _failed("bad_config", started, "unknown AI_PROVIDER")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    candidates = (models or configured_models())[:MAX_MODELS]
    if not key or not candidates:
        return _failed("bad_config", started, "OPENROUTER_API_KEY or AI_MODELS missing")

    budget = timeout or timeout_seconds()
    attempts: list[dict] = []
    result = ChatResult(ok=False, error_type="timeout")
    for name in candidates:
        left = budget - (time.monotonic() - started)
        if left <= 1:
            break
        result = _call_one(name, key, messages, tools, tool_choice, response_format, max_tokens, left)
        attempts.append({"model": name, "error_type": result.error_type})
        if result.ok or result.error_type not in FAILOVER_ERRORS:
            break
    result.attempts = attempts
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result
