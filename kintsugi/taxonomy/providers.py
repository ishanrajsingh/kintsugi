"""Pluggable language-model providers, defaulting to something free.

Every provider here can be run at zero cost, and the system is designed to
remain correct when there is no provider at all. That is not a limitation
worked around; it is the intended failure mode. A payments component that stops
working when an inference endpoint is down or a bill goes unpaid has no business
sitting in the authorisation path, so the taxonomy degrades to rules and marks
the residue ``UNKNOWN``, and the policy treats ``UNKNOWN`` conservatively.

Resolution order is by cost, cheapest first: an already-cached answer, then a
local model, then a free hosted tier, then a paid API only if a key is present.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

#: Generous by design. A local 7B model on a contended machine can take well
#: over a minute per call, and a timeout is indistinguishable from a refusal at
#: the call site: the string degrades to UNKNOWN. That is safe but wasteful,
#: since the answer was merely slow, not unavailable. Measured directly: at a
#: 120s timeout under load, 5 of 20 held-out strings timed out and were scored
#: as misses; all five resolved correctly once the machine was free.
DEFAULT_TIMEOUT = 300


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(self, prompt: str, max_tokens: int = 24) -> str | None: ...


def _post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict | None:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


class OllamaProvider:
    """A model running locally. Free, private, and needs no account.

    The natural default for this project: classifying a few hundred short
    decline strings is well within a 7B model's competence, and the results are
    cached, so the whole workload is a one-off cost measured in minutes.
    """

    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5vl:7b",
        host: str = "http://localhost:11434",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as r:
                tags = json.loads(r.read().decode())
        except Exception:
            return False
        return any(m.get("name") == self.model for m in tags.get("models", []))

    def complete(self, prompt: str, max_tokens: int = 24) -> str | None:
        data = _post_json(
            f"{self.host}/api/generate",
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": max_tokens},
            },
            {"Content-Type": "application/json"},
            self.timeout,
        )
        return (data or {}).get("response")


class GeminiProvider:
    """Google AI Studio. Has a genuinely free tier; needs ``GEMINI_API_KEY``."""

    name = "gemini"

    def __init__(self, model: str = "gemini-2.0-flash", timeout: int = 60) -> None:
        self.model = model
        self.timeout = timeout
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY")

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, max_tokens: int = 24) -> str | None:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.api_key}")
        data = _post_json(
            url,
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0, "maxOutputTokens": max_tokens},
            },
            {"Content-Type": "application/json"},
            self.timeout,
        )
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return None


class AnthropicProvider:
    """Claude. Used only when ``ANTHROPIC_API_KEY`` is explicitly set."""

    name = "anthropic"

    def __init__(
        self, model: str = "claude-haiku-4-5-20251001", timeout: int = 60
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, max_tokens: int = 24) -> str | None:
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
            {
                "Content-Type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            },
            self.timeout,
        )
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return None


class NullProvider:
    """No model. Everything the rules cannot match stays ``UNKNOWN``."""

    name = "none"

    def available(self) -> bool:
        return False

    def complete(self, prompt: str, max_tokens: int = 24) -> str | None:
        return None


def default_provider(prefer: str | None = None) -> LLMProvider:
    """First available provider, cheapest first."""
    candidates: list[LLMProvider] = [
        OllamaProvider(), GeminiProvider(), AnthropicProvider()]
    if prefer:
        candidates.sort(key=lambda p: 0 if p.name == prefer else 1)
    for provider in candidates:
        try:
            if provider.available():
                return provider
        except Exception:
            continue
    return NullProvider()
