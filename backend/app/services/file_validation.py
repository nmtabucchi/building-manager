"""Validación de archivos subidos: extensión, firma real (magic bytes), tamaño y nombre."""
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from app.domain.enums import FileType
from app.domain.exceptions import FileTooLargeError, UnsupportedFileTypeError, ValidationError

MIME = {
    FileType.PDF: "application/pdf",
    FileType.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_EXT = {".pdf": FileType.PDF, ".docx": FileType.DOCX}


@dataclass(frozen=True)
class ValidatedFile:
    file_name: str
    file_type: FileType
    mime_type: str
    size_bytes: int
    sha256: str


def sanitize_file_name(name: str) -> str:
    base = PureWindowsPath(PurePosixPath(name or "").name).name  # descarta cualquier ruta
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    if not base or len(base) > 255:
        raise ValidationError("Nombre de archivo inválido")
    return base


def validate_upload(file_name: str, data: bytes, max_bytes: int) -> ValidatedFile:
    name = sanitize_file_name(file_name)
    ext = PurePosixPath(name.lower()).suffix
    file_type = _EXT.get(ext)
    if file_type is None:
        raise UnsupportedFileTypeError("Solo se admiten archivos PDF y DOCX")
    if not data:
        raise ValidationError("El archivo está vacío")
    if len(data) > max_bytes:
        raise FileTooLargeError(f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB")

    if file_type == FileType.PDF:
        ok = data[:1024].lstrip().startswith(b"%PDF-")
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                ok = "word/document.xml" in zf.namelist() and "[Content_Types].xml" in zf.namelist()
        except zipfile.BadZipFile:
            ok = False
    if not ok:
        raise UnsupportedFileTypeError("El contenido del archivo no corresponde a su extensión")

    return ValidatedFile(name, file_type, MIME[file_type], len(data), hashlib.sha256(data).hexdigest())
