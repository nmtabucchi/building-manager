from typing import Any, TypeVar

from pydantic import BaseModel

from app.infrastructure.database.stored_procedure_client import StoredProcedureClient

T = TypeVar("T", bound=BaseModel)


class BaseRepository:
    """Un repositorio solo invoca stored procedures y mapea filas a entidades.

    No contiene SQL ni reglas de negocio.
    """

    def __init__(self, sp: StoredProcedureClient):
        self._sp = sp

    @staticmethod
    def _one(model: type[T], row: dict[str, Any]) -> T:
        return model.model_validate(row)

    @staticmethod
    def _many(model: type[T], rows: list[dict[str, Any]]) -> list[T]:
        return [model.model_validate(r) for r in rows]
