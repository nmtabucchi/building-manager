"""Regla arquitectónica: Python no ejecuta SQL ni usa ORM; todo pasa por stored procedures."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

FORBIDDEN = [
    (r"\b(select|insert\s+into|update|delete\s+from)\b[^\n]{0,80}\b(from|set|values|where)\b", "SQL embebido"),
    (r"\.table\(|\.from_\(", "acceso directo a tablas (cliente Supabase)"),
    (r"sqlalchemy|psycopg|asyncpg", "driver/ORM SQL"),
    (r"\.execute\(", "ejecución de sentencias"),
]


def _code_lines(path: Path):
    in_doc = False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if s.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or s.startswith("#") or (s.startswith('"""') and s.endswith('"""')):
            continue
        yield n, line


def test_no_hay_sql_ni_orm_en_app():
    problemas = []
    for py in APP.rglob("*.py"):
        for n, line in _code_lines(py):
            for pattern, why in FORBIDDEN:
                if re.search(pattern, line, re.IGNORECASE):
                    problemas.append(f"{py.relative_to(APP)}:{n} {why}: {line.strip()}")
    assert not problemas, "\n".join(problemas)


def test_solo_el_cliente_de_sp_usa_http_hacia_la_base():
    for py in APP.rglob("*.py"):
        if py.name in ("stored_procedure_client.py", "config.py"):  # config solo arma la URL base
            continue
        assert "/rest/v1" not in py.read_text(encoding="utf-8"), py
