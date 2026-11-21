"""Proveedor alternativo de LLM: Google Gemini (API REST `generateContent`, sin SDK).

Mismo contrato que ClaudeProvider (`LLMProvider`): el grafo RAG no cambia. Diferencias a tener en cuenta:
- La clave viaja en la cabecera `x-goog-api-key` (nunca en la URL, para que no aparezca en logs).
- La salida estructurada usa `responseMimeType` + `responseJsonSchema`.
- `effort` se ignora (es un concepto de Claude) y no se envían parámetros de muestreo.
"""
import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app.core.config import Settings
from app.domain.exceptions import InfrastructureError, LLMRefusalError, LLMUnavailableError
from app.infrastructure.llm.llm_provider import LLMProvider, LLMResult

logger = logging.getLogger(__name__)

_BLOCKED_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class GeminiProvider(LLMProvider):
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None, retries: int = 2):
        self._model = settings.gemini_model
        self._key = settings.gemini_api_key
        self._max_tokens_cap = settings.claude_max_tokens
        self._http = http or httpx.AsyncClient(timeout=settings.claude_timeout_seconds)
        self._retries = retries

    async def generate_text(self, system: str, user: str, *, max_tokens: int, effort: str) -> LLMResult:
        return await self._call(system, user, max_tokens, None)

    async def generate_structured(self, system: str, user: str, schema: dict[str, Any], *,
                                  max_tokens: int, effort: str) -> LLMResult:
        result = await self._call(system, user, max_tokens, schema)
        try:
            data = json.loads(_FENCE.sub("", result.text.strip()))
        except ValueError as exc:
            raise LLMUnavailableError("Gemini devolvió una respuesta que no es JSON válido") from exc
        if not isinstance(data, dict):
            raise LLMUnavailableError("Gemini devolvió un JSON con formato inesperado")
        return LLMResult(text=result.text, model=result.model, usage=result.usage, data=data)

    async def _call(self, system: str, user: str, max_tokens: int, schema: dict[str, Any] | None) -> LLMResult:
        if self._key is None:
            raise InfrastructureError("GEMINI_API_KEY no está configurada")
        generation: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if schema is not None:
            generation["responseMimeType"] = "application/json"
            generation["responseJsonSchema"] = schema
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation,
        }
        url = f"{self.BASE}/{self._model}:generateContent"
        headers = {"x-goog-api-key": self._key.get_secret_value(), "Content-Type": "application/json"}

        response = None
        for attempt in range(self._retries + 1):
            try:
                response = await self._http.post(url, json=body, headers=headers)
            except httpx.TransportError as exc:
                if attempt == self._retries:
                    raise LLMUnavailableError("No se pudo contactar a Gemini") from exc
            else:
                if response.status_code != 429 and response.status_code < 500:
                    break
                if attempt == self._retries:
                    break
            logger.warning("Gemini: reintento %d/%d", attempt + 1, self._retries)
            await asyncio.sleep(1.0 * 2**attempt)

        assert response is not None
        if response.status_code == 429:
            raise LLMUnavailableError("Gemini está limitando las solicitudes (cuota); intente en unos segundos")
        if response.status_code in (401, 403):
            raise LLMUnavailableError("Gemini rechazó la clave (revise GEMINI_API_KEY)", f"HTTP {response.status_code}")
        if not response.is_success:
            logger.error("Gemini API error status=%s", response.status_code)
            raise LLMUnavailableError("Gemini devolvió un error", f"HTTP {response.status_code}")
        return self._parse(response.json())

    def _parse(self, data: dict[str, Any]) -> LLMResult:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        candidates = data.get("candidates") or []
        if block or not candidates:
            logger.warning("Gemini bloqueó la solicitud (motivo=%s)", block)
            raise LLMRefusalError("Gemini no pudo responder a esta consulta")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish in _BLOCKED_FINISH:
            logger.warning("Gemini cortó la respuesta (finishReason=%s)", finish)
            raise LLMRefusalError("Gemini no pudo responder a esta consulta")
        if finish == "MAX_TOKENS":
            raise LLMUnavailableError("La respuesta de Gemini fue truncada (max_tokens)")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMUnavailableError("Gemini devolvió una respuesta vacía")
        usage = data.get("usageMetadata") or {}
        return LLMResult(
            text=text,
            model=data.get("modelVersion") or self._model,
            usage={"input_tokens": usage.get("promptTokenCount", 0),
                   "output_tokens": usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)},
        )
