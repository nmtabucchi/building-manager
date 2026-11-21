from app.core.config import Settings
from app.domain.exceptions import InfrastructureError
from app.infrastructure.llm.gemini_provider import GeminiProvider
from app.infrastructure.llm.llm_provider import ClaudeProvider, LLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        return ClaudeProvider(settings)
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings)
    raise InfrastructureError(f"LLM_PROVIDER no soportado: {settings.llm_provider} (use 'anthropic' o 'gemini')")
