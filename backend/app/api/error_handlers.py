"""Manejo centralizado de excepciones -> JSON uniforme."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import request_id_var
from app.domain.exceptions import DomainError

logger = logging.getLogger(__name__)


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id_var.get()}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.error("%s: %s (%s)", exc.code, exc.message, exc.detail)
            message = "Error interno" if exc.http_status == 500 else exc.message
        else:
            message = exc.message
        return JSONResponse(status_code=exc.http_status, content=_body(exc.code, message))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse(status_code=422, content=_body("VALIDATION_ERROR", f"{loc}: {first.get('msg', 'inválido')}"))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Error no controlado")
        return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", "Error interno"))
