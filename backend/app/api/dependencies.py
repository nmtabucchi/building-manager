"""Dependencias FastAPI: contenedor y contexto de autenticación."""
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.container import Container
from app.domain.auth import UserAuthContext
from app.domain.exceptions import AuthenticationError

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    container: Container = Depends(get_container),
) -> UserAuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Falta el token de autenticación")
    return await container.jwt_verifier.authenticate(credentials.credentials)
