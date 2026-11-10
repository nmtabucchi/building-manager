"""Configuración de la aplicación mediante variables de entorno (.env)."""
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Supabase (obligatorias)
    supabase_url: str
    supabase_anon_key: SecretStr
    # Solo backend: worker de ingesta y Storage (Etapa 3). Opcional en Etapa 2.
    supabase_service_role_key: SecretStr | None = None
    # Validación del JWT. Se usa JWKS (claves asimétricas) salvo que se defina el secreto HS256 legado.
    supabase_jwt_secret: SecretStr | None = None
    supabase_jwt_audience: str = "authenticated"

    supabase_storage_bucket: str = "building-documents"

    # Subida e ingesta
    max_upload_mb: int = Field(default=20, ge=1, le=20)  # el SP y el bucket también limitan a 20 MB
    ingestion_batch_size: int = Field(default=50, ge=1, le=200)
    ingestion_enabled: bool = True
    chunk_size: int = 1200
    chunk_overlap: int = 200

    # Embeddings (Etapa 3). 'fake' solo para desarrollo/tests.
    embedding_provider: str = "voyage"
    embedding_model: str = "voyage-3.5"
    embedding_api_key: SecretStr | None = None
    embedding_dimension: int = 1024

    # Claude (Etapa 4)
    anthropic_api_key: SecretStr | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"  # low | medium | high | xhigh | max
    claude_max_tokens: int = 4096
    claude_fallbacks: bool = True  # fallback del lado del servidor ante rechazos de seguridad
    claude_timeout_seconds: float = 120.0

    # RAG
    rag_top_k: int = Field(default=8, ge=1, le=50)
    rag_min_similarity: float = Field(default=0.35, ge=-1, le=1)
    rag_history_messages: int = Field(default=6, ge=0, le=50)
    rag_context_token_budget: int = Field(default=6000, ge=500)
    rag_max_question_chars: int = Field(default=2000, ge=50, le=5000)
    chat_rate_limit_per_minute: int = Field(default=20, ge=1)

    # Cliente HTTP hacia PostgREST
    sp_timeout_seconds: float = Field(default=30.0, gt=0)
    sp_read_retries: int = Field(default=2, ge=0, le=5)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_rest_url(self) -> str:
        return self.supabase_url.rstrip("/") + "/rest/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return self.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"

    @property
    def supabase_issuer(self) -> str:
        return self.supabase_url.rstrip("/") + "/auth/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
