"""LLM provider port and adapters (ARCHITECTURE.md §8.1).

The business code depends only on `LLMProvider`. The provider is chosen by
configuration (`FMS_AI_PROVIDER`); with `null` (default) the assistant is
unavailable and every feature keeps working manually (FR-106).
"""

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings


class ProviderUnavailableError(Exception):
    """No provider configured, SDK missing or credentials rejected."""


class ProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        retryable: bool = False,
        usage: "LLMUsage | None" = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.retryable = retryable
        self.usage = usage


@dataclass(frozen=True)
class DocumentPart:
    media_type: str  # application/pdf, image/jpeg, image/png, image/webp
    data: bytes


@dataclass(frozen=True)
class LLMRequest:
    system: str
    text: str
    schema: dict[str, Any]
    documents: list[DocumentPart] = field(default_factory=list)
    max_tokens: int = 16000


@dataclass
class LLMUsage:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    request_id: str = ""


@dataclass
class LLMResponse:
    data: dict[str, Any]
    usage: LLMUsage


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, request: LLMRequest) -> LLMResponse: ...


class NullProvider:
    name = "null"
    model = ""

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        raise ProviderUnavailableError("Aucun fournisseur IA n'est configuré.")


class AnthropicProvider:
    """Adapter for the Anthropic Messages API (official SDK, structured JSON outputs)."""

    name = "anthropic"

    def __init__(self, model: str) -> None:
        try:
            import anthropic
        except ImportError as exc:  # optional dependency group "ai"
            raise ProviderUnavailableError("SDK anthropic non installé.") from exc
        self._sdk = anthropic
        self.model = model
        # Credentials are resolved by the SDK from the environment (ANTHROPIC_API_KEY...).
        self._client = anthropic.Anthropic(max_retries=2)

    def _content(self, request: LLMRequest) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for document in request.documents:
            encoded = base64.standard_b64encode(document.data).decode("ascii")
            block_type = "document" if document.media_type == "application/pdf" else "image"
            blocks.append(
                {
                    "type": block_type,
                    "source": {
                        "type": "base64",
                        "media_type": document.media_type,
                        "data": encoded,
                    },
                }
            )
        blocks.append({"type": "text", "text": request.text})
        return blocks

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        sdk = self._sdk
        started = time.monotonic()
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": self._content(request)}],
            "output_config": {
                "effort": "high",
                "format": {"type": "json_schema", "schema": request.schema},
            },
            # On a safety refusal, the API retries on a fallback model in the same call.
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
        try:
            response = self._client.beta.messages.create(**params)
        except sdk.AuthenticationError as exc:
            raise ProviderUnavailableError("Identifiants du fournisseur IA refusés.") from exc
        except sdk.RateLimitError as exc:
            raise ProviderError(
                "rate_limited", "Limite de débit du fournisseur atteinte.", retryable=True
            ) from exc
        except (sdk.APIConnectionError, sdk.APITimeoutError) as exc:
            raise ProviderError(
                "connection_error", "Fournisseur IA injoignable.", retryable=True
            ) from exc
        except sdk.APIStatusError as exc:
            raise ProviderError(
                f"http_{exc.status_code}", exc.message, retryable=exc.status_code >= 500
            ) from exc
        usage = LLMUsage(
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
            request_id=getattr(response, "_request_id", "") or "",
        )
        if response.stop_reason == "refusal":
            raise ProviderError("refusal", "Le fournisseur a refusé la demande.", usage=usage)
        if response.stop_reason == "max_tokens":
            raise ProviderError("truncated", "Réponse tronquée.", usage=usage)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("invalid_json", "Réponse non JSON.", usage=usage) from exc
        return LLMResponse(data=data, usage=usage)


def get_provider() -> LLMProvider:
    name = settings.FMS_AI_PROVIDER
    if name == "anthropic":
        return AnthropicProvider(settings.FMS_AI_MODEL)
    return NullProvider()
