"""Validación estática del SQL con el parser real de PostgreSQL (libpg_query via pglast).

No reemplaza ejecutar las migraciones (eso lo hacen `supabase db reset` y `supabase test db`), pero detecta
errores de sintaxis SQL y PL/pgSQL sin necesitar una base de datos.
"""
import re
from pathlib import Path

import pytest

pglast = pytest.importorskip("pglast")
from pglast import parse_plpgsql, parse_sql
from pglast.ast import CreateFunctionStmt

SUPABASE = Path(__file__).resolve().parents[3] / "supabase"
FILES = sorted(SUPABASE.glob("migrations/*.sql")) + [SUPABASE / "seed.sql"] + sorted(SUPABASE.glob("tests/database/*.sql"))
MIGRATIONS = sorted(SUPABASE.glob("migrations/*.sql"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_sql_es_sintacticamente_valido(path):
    stmts = parse_sql(path.read_text(encoding="utf-8"))
    assert stmts, "el archivo no contiene sentencias"


@pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.name)
def test_cuerpos_plpgsql_son_validos(path):
    n = 0
    for raw in parse_sql(path.read_text(encoding="utf-8")):
        stmt = raw.stmt
        if isinstance(stmt, CreateFunctionStmt):
            lang = next((o.arg.sval for o in stmt.options if o.defname == "language"), "")
            if lang == "plpgsql":
                text = path.read_text(encoding="utf-8")[raw.stmt_location: raw.stmt_location + raw.stmt_len]
                # el parser de PL/pgSQL de pglast solo resuelve los esquemas pg_catalog y public:
                # se normalizan los demás (no afecta a la sintaxis que se verifica)
                # y los tipos propios (enums, vector), que no existen en el entorno del parser, se sustituyen por text
                text = re.sub(r"\bapp\.(building_role|document_status|file_type|document_category|message_role)\b", "text", text)
                text = re.sub(r"\bextensions\.vector(\(\d+\))?", "text", text)
                parse_plpgsql(re.sub(r"\b(app|extensions|auth|storage)\.", "public.", text))
                n += 1
    assert n > 0 or path.name.endswith(("tipos.sql", "tablas.sql", "indices.sql", "tablas.sql")) or "rls" in path.name or "permisos" in path.name


def _functions(path):
    text = path.read_text(encoding="utf-8")
    for raw in parse_sql(text):
        if isinstance(raw.stmt, CreateFunctionStmt):
            yield raw.stmt, text[raw.stmt_location: raw.stmt_location + raw.stmt_len]


def test_todos_los_sp_publicos_fijan_search_path_vacio():
    sin = []
    for path in MIGRATIONS:
        for stmt, text in _functions(path):
            name = ".".join(s.sval for s in stmt.funcname)
            if re.search(r"(?i)search_path\s*=\s*''", text) is None and name.startswith(("public.", "app.")):
                sin.append(f"{path.name}:{name}")
    assert not sin, sin


def test_sp_de_usuario_son_security_invoker_salvo_excepciones_documentadas():
    """Los SP públicos corren con el rol del usuario (RLS aplica). Excepciones documentadas en el diseño."""
    permitidos_definer = {"public.sp_building_usuario_asignar"}
    definer = set()
    for path in MIGRATIONS:
        for stmt, text in _functions(path):
            name = ".".join(s.sval for s in stmt.funcname)
            if name.startswith("public.sp_") and re.search(r"(?i)\bsecurity\s+definer\b", text):
                definer.add(name)
    assert definer == permitidos_definer


def test_sp_de_ingesta_solo_para_service_role():
    perms = (SUPABASE / "migrations" / "20261109000011_permisos_stored_procedures.sql").read_text(encoding="utf-8")
    ingesta = set(re.findall(r"public\.(sp_ingesta_\w+)\(", perms))
    bloque_service = perms.split("-- 3) SP del worker de ingesta")[1].split("-- 4)")[0]
    bloque_auth = perms.split("-- 2) SP de usuario final")[1].split("-- 3)")[0]
    assert ingesta and all(sp in bloque_service for sp in ingesta)
    assert "sp_ingesta" not in bloque_auth and "to service_role" in bloque_service and "authenticated" not in bloque_service


def test_todos_los_sp_creados_tienen_permiso_explicito():
    """Cada sp_* definido debe aparecer en la migración de permisos (si no, queda sin EXECUTE para nadie)."""
    creados = set()
    for path in MIGRATIONS:
        for stmt, _ in _functions(path):
            parts = [s.sval for s in stmt.funcname]
            if parts[0] == "public" and parts[1].startswith("sp_"):
                creados.add(parts[1])
    perms = (SUPABASE / "migrations" / "20261109000011_permisos_stored_procedures.sql").read_text(encoding="utf-8")
    concedidos = set(re.findall(r"public\.(sp_\w+)\(", perms))
    assert creados == concedidos, (creados ^ concedidos)


def test_todas_las_tablas_de_app_tienen_rls():
    tablas = set()
    rls = set()
    for path in MIGRATIONS:
        text = path.read_text(encoding="utf-8")
        tablas |= set(re.findall(r"(?i)create table app\.(\w+)", text))
        rls |= set(re.findall(r"(?i)alter table app\.(\w+)\s+enable row level security", text))
    assert tablas and tablas == rls, tablas ^ rls
