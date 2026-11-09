from enum import StrEnum


class BuildingRole(StrEnum):
    ADMINISTRADOR = "administrador"
    COLABORADOR = "colaborador"
    LECTOR = "lector"


class DocumentStatus(StrEnum):
    PENDIENTE = "pendiente"
    PROCESANDO = "procesando"
    PROCESADO = "procesado"
    ERROR = "error"


class FileType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class DocumentCategory(StrEnum):
    REGLAMENTO = "reglamento"
    ACTA_ASAMBLEA = "acta_asamblea"
    ACTA_REUNION = "acta_reunion"
    COMUNICACION = "comunicacion"
    CONTRATO = "contrato"
    PRESUPUESTO = "presupuesto"
    MANUAL_TECNICO = "manual_tecnico"
    OTRO = "otro"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
