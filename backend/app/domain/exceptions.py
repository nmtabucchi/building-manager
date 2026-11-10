"""Excepciones de dominio. La capa API las traduce a respuestas HTTP."""


class DomainError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class AuthenticationError(DomainError):
    code, http_status = "UNAUTHENTICATED", 401


class PermissionDeniedError(DomainError):
    code, http_status = "FORBIDDEN", 403


class NotFoundError(DomainError):
    code, http_status = "NOT_FOUND", 404


class ConflictError(DomainError):
    code, http_status = "CONFLICT", 409


class ValidationError(DomainError):
    code, http_status = "VALIDATION_ERROR", 422


class FileTooLargeError(DomainError):
    code, http_status = "FILE_TOO_LARGE", 413


class UnsupportedFileTypeError(DomainError):
    code, http_status = "UNSUPPORTED_FILE_TYPE", 415


class RateLimitError(DomainError):
    code, http_status = "RATE_LIMITED", 429


class LLMUnavailableError(DomainError):
    """Claude no disponible, sin créditos, truncado, etc. Se informa como error de servicio externo."""

    code, http_status = "UPSTREAM_ERROR", 502


class LLMRefusalError(DomainError):
    """Claude rechazó la solicitud por sus clasificadores de seguridad."""

    code, http_status = "UPSTREAM_ERROR", 502


class InfrastructureError(DomainError):
    """Error de configuración o de contrato con la base (p. ej. SP inexistente)."""

    code, http_status = "INTERNAL_ERROR", 500


class PersistenceUnavailableError(DomainError):
    code, http_status = "UPSTREAM_ERROR", 502
