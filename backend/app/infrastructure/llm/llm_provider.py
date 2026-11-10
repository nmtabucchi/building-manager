"""Proveedor de LLM (Claude) detrás de una interfaz, para poder mockearlo y reemplazarlo."""
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.core.config import Settings
from app.domain.exceptions import InfrastructureError, LLMRefusalError, LLMUnavailableError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    data: dict[str, Any] | None = None  # JSON parseado cuando se pidió salida estructurada


class LLMProvider(ABC):
    @abstractmethod
    async def generate_text(self, system: str, user: str, *, max_tokens: int, effort: str) -> LLMResult: ...

    @abstractmethod
    async def generate_structured(self, system: str, user: str, schema: dict[str, Any], *,
                                  max_tokens: int, effort: str) -> LLMResult: ...


class ClaudeProvider(LLMProvider):
    """Anthropic Claude vía SDK oficial.

    - El razonamiento adaptativo está siempre activo en Opus 5.5: solo se controla con `effort`.
    - Salida estructurada nativa (`output_config.format`): evita `tool_choice` forzado (400 en Opus 5.5).
    - Fallback del lado del servidor ante rechazos de seguridad (`fallbacks="default"`).
    """

    BETA_FALLBACK = "server-side-fallback-2026-07-01"

    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self._model = settings.claude_model
        self._fallbacks = settings.claude_fallbacks
        self._client = client
        self._settings = settings

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            key = self._settings.anthropic_api_key
            if key is None:
                raise InfrastructureError("ANTHROPIC_API_KEY no está configurada")
            self._client = anthropic.AsyncAnthropic(
                api_key=key.get_secret_value(), timeout=self._settings.claude_timeout_seconds)
        return self._client

    async def generate_text(self, system: str, user: str, *, max_tokens: int, effort: str) -> LLMResult:
        return await self._call(system, user, max_tokens, effort, None)

    async def generate_structured(self, system: str, user: str, schema: dict[str, Any], *,
                                  max_tokens: int, effort: str) -> LLMResult:
        result = await self._call(system, user, max_tokens, effort, schema)
        try:
            data = json.loads(result.text)
        except ValueError as exc:
            raise LLMUnavailableError("Claude devolvió una respuesta que no es JSON válido") from exc
        return LLMResult(text=result.text, model=result.model, usage=result.usage, data=data)

    async def _call(self, system: str, user: str, max_tokens: int, effort: str,
                    schema: dict[str, Any] | None) -> LLMResult:
        client = self._get_client()
        output_config: dict[str, Any] = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        kwargs: dict[str, Any] = {
            "model": self._model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}], "output_config": output_config}
        try:
            if self._fallbacks:
                response = await client.beta.messages.create(
                    betas=[self.BETA_FALLBACK], fallbacks="default", **kwargs)
            else:
                response = await client.messages.create(**kwargs)
        except anthropic.APIConnectionError as exc:  # incluye timeouts
            raise LLMUnavailableError("No se pudo contactar a Claude") from exc
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError("Claude está limitando las solicitudes; intente en unos segundos") from exc
        except anthropic.APIStatusError as exc:
            logger.error("Claude API error status=%s", exc.status_code)
            raise LLMUnavailableError("Claude devolvió un error", f"HTTP {exc.status_code}") from exc

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            logger.warning("Claude rechazó la solicitud (categoría=%s)", category)
            raise LLMRefusalError("Claude no pudo responder a esta consulta")
        if response.stop_reason == "max_tokens":
            raise LLMUnavailableError("La respuesta de Claude fue truncada (max_tokens)")

        text = next((b.text for b in response.content if b.type == "text"), "")
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        return LLMResult(text=text, model=response.model, usage=usage)
