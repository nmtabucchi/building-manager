"""Verificación local del JWT emitido por Supabase Auth."""
import asyncio
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.domain.auth import UserAuthContext
from app.domain.exceptions import AuthenticationError


class SupabaseJwtVerifier:
    """Valida firma, expiración, audiencia e issuer.

    - Proyectos con claves asimétricas (ES256/RS256): JWKS cacheado.
    - Proyectos legados con secreto compartido: HS256 si SUPABASE_JWT_SECRET está definido.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._secret = settings.supabase_jwt_secret.get_secret_value() if settings.supabase_jwt_secret else None
        self._jwks = None if self._secret else PyJWKClient(settings.supabase_jwks_url, cache_keys=True)

    def _verify(self, token: str) -> dict:
        try:
            if self._secret:
                key, algorithms = self._secret, ["HS256"]
            else:
                key = self._jwks.get_signing_key_from_jwt(token).key  # type: ignore[union-attr]
                algorithms = ["ES256", "RS256"]
            return jwt.decode(
                token,
                key,
                algorithms=algorithms,
                audience=self._settings.supabase_jwt_audience,
                issuer=self._settings.supabase_issuer,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Token inválido o expirado") from exc

    async def authenticate(self, token: str) -> UserAuthContext:
        claims = await asyncio.to_thread(self._verify, token)
        try:
            user_id = UUID(claims["sub"])
        except ValueError as exc:
            raise AuthenticationError("Token inválido") from exc
        return UserAuthContext(user_id=user_id, email=claims.get("email"), jwt=token)
