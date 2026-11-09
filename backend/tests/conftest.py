import pytest

from app.core.config import Settings

USER_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_url="http://supabase.test",
        supabase_anon_key="anon-key",
        supabase_service_role_key="service-key",
        supabase_jwt_secret="x" * 40,
        sp_read_retries=2,
        embedding_provider="fake",
        ingestion_enabled=False,  # los tests de API no arrancan el worker; los de ingesta lo usan directo
        _env_file=None,
    )
