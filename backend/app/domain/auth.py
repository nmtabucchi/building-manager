"""Contextos de autenticación con los que se invoca un stored procedure."""
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuthContext:
    """Base: define con qué credenciales se ejecuta una llamada RPC."""


@dataclass(frozen=True)
class UserAuthContext(AuthContext):
    """Usuario final: se reenvía su JWT; la base ejecuta como rol `authenticated` y aplica RLS."""

    user_id: UUID
    email: str | None
    jwt: str

    def __repr__(self) -> str:  # nunca exponer el token en logs
        return f"UserAuthContext(user_id={self.user_id})"


@dataclass(frozen=True)
class ServiceAuthContext(AuthContext):
    """Backend (worker de ingesta, Etapa 3): usa la clave service_role."""
