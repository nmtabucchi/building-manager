import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.domain.exceptions import InfrastructureError, LLMRefusalError, LLMUnavailableError
from app.infrastructure.llm import gemini_provider as gp
from app.infrastructure.llm.factory import build_llm_provider
from app.infrastructure.llm.gemini_provider import GeminiProvider
from app.infrastructure.llm.llm_provider import ClaudeProvider

URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"


@pytest.fixture
def provider(settings, monkeypatch):
    async def no_sleep(_):
        pass

    monkeypatch.setattr(gp.asyncio, "sleep", no_sleep)
    return GeminiProvider(settings.model_copy(update={"gemini_api_key": SecretStr("g-key")}))


def ok(text='{"a": 1}', finish="STOP", **extra):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 5, "thoughtsTokenCount": 2},
            "modelVersion": "gemini-3.5-flash-lite", **extra}


@respx.mock
async def test_estructurado_envia_esquema_y_clave_en_cabecera(provider):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=ok()))
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    result = await provider.generate_structured("sys", "user", schema, max_tokens=500, effort="medium")
    req = route.calls[0].request
    body = json.loads(req.content)
    assert result.data == {"a": 1} and result.usage == {"input_tokens": 11, "output_tokens": 7}
    assert req.headers["x-goog-api-key"] == "g-key" and "g-key" not in str(req.url)
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["contents"] == [{"role": "user", "parts": [{"text": "user"}]}]
    cfg = body["generationConfig"]
    assert cfg["maxOutputTokens"] == 500 and cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"] == schema
    for forbidden in ("temperature", "topP", "topK"):
        assert forbidden not in cfg


@respx.mock
async def test_texto_libre_no_pide_json(provider):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=ok("hola")))
    assert (await provider.generate_text("s", "u", max_tokens=10, effort="low")).text == "hola"
    assert "responseMimeType" not in json.loads(route.calls[0].request.content)["generationConfig"]


@respx.mock
async def test_json_con_fences_y_partes_de_pensamiento(provider):
    payload = {"candidates": [{"content": {"parts": [
        {"text": "razonando...", "thought": True}, {"text": '```json\n{"a": 2}\n```'}]}, "finishReason": "STOP"}]}
    respx.post(URL).mock(return_value=httpx.Response(200, json=payload))
    assert (await provider.generate_structured("s", "u", {}, max_tokens=10, effort="low")).data == {"a": 2}


@pytest.mark.parametrize("payload,exc", [
    ({"promptFeedback": {"blockReason": "SAFETY"}}, LLMRefusalError),
    (ok(finish="SAFETY"), LLMRefusalError),
    (ok(finish="PROHIBITED_CONTENT"), LLMRefusalError),
    (ok(finish="MAX_TOKENS"), LLMUnavailableError),
    ({"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}, LLMUnavailableError),
    (ok("no es json"), LLMUnavailableError),
    (ok("[1, 2]"), LLMUnavailableError),
])
@respx.mock
async def test_respuestas_problematicas(provider, payload, exc):
    respx.post(URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(exc):
        await provider.generate_structured("s", "u", {}, max_tokens=10, effort="low")


@respx.mock
async def test_reintenta_429_y_luego_informa_cuota(provider):
    route = respx.post(URL).mock(side_effect=[httpx.Response(429), httpx.Response(200, json=ok())])
    assert (await provider.generate_structured("s", "u", {}, max_tokens=10, effort="low")).data == {"a": 1}
    assert route.call_count == 2


@respx.mock
async def test_cuota_agotada_es_error_de_servicio(provider):
    route = respx.post(URL).mock(return_value=httpx.Response(429))
    with pytest.raises(LLMUnavailableError, match="cuota"):
        await provider.generate_text("s", "u", max_tokens=10, effort="low")
    assert route.call_count == 3  # 1 + 2 reintentos


@respx.mock
async def test_clave_invalida_error_de_red_y_error_del_servidor(provider):
    respx.post(URL).mock(return_value=httpx.Response(403))
    with pytest.raises(LLMUnavailableError, match="GEMINI_API_KEY"):
        await provider.generate_text("s", "u", max_tokens=10, effort="low")
    respx.post(URL).mock(side_effect=httpx.ConnectError("x"))
    # la primera ruta (403) sigue registrada; se prueba la red con un proveedor nuevo
    respx.clear()
    respx.post(URL).mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(LLMUnavailableError):
        await provider.generate_text("s", "u", max_tokens=10, effort="low")
    respx.clear()
    respx.post(URL).mock(return_value=httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(LLMUnavailableError):
        await provider.generate_text("s", "u", max_tokens=10, effort="low")


async def test_sin_api_key(settings):
    with pytest.raises(InfrastructureError, match="GEMINI_API_KEY"):
        await GeminiProvider(settings).generate_text("s", "u", max_tokens=10, effort="low")


def test_fabrica_elige_proveedor(settings):
    assert isinstance(build_llm_provider(settings), ClaudeProvider)
    assert isinstance(build_llm_provider(settings.model_copy(update={"llm_provider": "gemini"})), GeminiProvider)
    with pytest.raises(InfrastructureError, match="LLM_PROVIDER"):
        build_llm_provider(settings.model_copy(update={"llm_provider": "otro"}))
