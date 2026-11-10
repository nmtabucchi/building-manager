# Building Manager AI

Asistente inteligente para la administración de edificios y consorcios: consulta de reglamentos, actas y
documentación en lenguaje natural mediante RAG (Claude + pgvector sobre Supabase), con citas a documento y página.

**Stack:** Next.js + React (JavaScript) · FastAPI (Python, POO) · Claude API · LangChain (chunking) · LangGraph ·
Supabase (PostgreSQL, pgvector, Auth, Storage) · PyMuPDF · python-docx · Voyage AI (embeddings).

**Regla central:** Python nunca ejecuta SQL. Todo acceso a datos pasa por stored procedures (`sp_*`) invocados por
Supabase RPC (`Route → Service → Repository → StoredProcedureClient → sp_*`).

## Estructura

```text
supabase/   migraciones SQL (tablas, índices, RLS, 27 stored procedures), seed, tests pgTAP
backend/    FastAPI: api · services · repositories · infrastructure · rag · tests
frontend/   Next.js: login, dashboard, edificios, documentación, asistente
docs/       diseño (Etapa 1), catálogo de SP, checklist de calidad RAG
```

## Puesta en marcha local

Requisitos: Docker Desktop, [Supabase CLI](https://supabase.com/docs/guides/cli), Python ≥ 3.12, Node ≥ 20,
cuentas de Anthropic y Voyage AI (o `EMBEDDING_PROVIDER=fake` para probar sin Voyage).

```bash
# 1. Base de datos (migraciones + seed) y pruebas SQL
supabase start
supabase db reset
supabase test db                 # 12 pruebas pgTAP de aislamiento y permisos
supabase status                  # muestra URL, anon key y service_role key
```

```bash
# 2. Backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Linux/macOS: .venv/bin/python
cp .env.example .env             # completar SUPABASE_*, ANTHROPIC_API_KEY, EMBEDDING_API_KEY
.venv/Scripts/python -m uvicorn app.main:create_app --factory --reload     # http://localhost:8000/docs
```

```bash
# 3. Frontend
cd frontend
npm install
cp .env.example .env.local       # NEXT_PUBLIC_SUPABASE_URL / ANON_KEY / API_BASE_URL
npm run dev                      # http://localhost:3000
```

Usuarios de prueba del seed (solo local): `admin.demo@example.test`, `lector.demo@example.test`,
`otro.demo@example.test`, contraseña `Demo-local-123`. También se puede registrar uno nuevo desde `/login`.

Las claves `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY` y `EMBEDDING_API_KEY` viven **solo** en `backend/.env`.

## Pruebas

| Nivel | Comando | Requiere |
|-------|---------|----------|
| Backend unitarias, SQL estático, seguridad, arquitectura | `cd backend && .venv/Scripts/python -m pytest` | nada |
| Backend integración (extremo a extremo) | `... pytest -m integration` | Supabase local + variables `SUPABASE_*` |
| SQL (pgTAP) | `supabase test db` | Docker + Supabase CLI |
| Frontend utilidades | `cd frontend && npm test` | nada |
| Frontend build | `cd frontend && npm run build` | nada |
| Calidad del RAG | [docs/calidad-rag-checklist.md](docs/calidad-rag-checklist.md) | todo el stack + claves reales |

## Documentación

- [Análisis y diseño](docs/etapa-1-analisis-y-diseno.md) — arquitectura, ER, RAG, LangGraph, API, seguridad, ADR, riesgos.
- [Catálogo de stored procedures](docs/catalogo-stored-procedures.md) — y matriz método Python ↔ SP.

## Desviaciones respecto del diseño inicial

| Diseño | Implementado | Motivo |
|--------|--------------|--------|
| Cliente `supabase-py` para RPC y Storage | `httpx` directo contra PostgREST/Storage | Más simple y testeable; mismo mecanismo (RPC). |
| Retriever como `BaseRetriever` de LangChain | Clase propia `SupabaseRetriever` | Pasar el JWT del usuario por ese contrato es incómodo. |
| Tailwind | CSS plano | Menos dependencias para el MVP. |
| Sesión con `@supabase/ssr` (cookies) | `supabase-js` con localStorage | MVP; la autorización real está en el backend y la base. |
| `supabase-js` última versión | `~2.100` | Las versiones recientes exigen Node 22. |

## Estado de verificación (honesto)

- **Verificado automáticamente:** lógica del backend con simulación de la base, Claude y Voyage; sintaxis de todo el SQL
  con el parser real de PostgreSQL; invariantes de seguridad del SQL (RLS en todas las tablas, `search_path`, permisos
  de `EXECUTE`, excepciones `SECURITY DEFINER`); build del frontend.
- **Escrito pero no ejecutado todavía:** las migraciones contra un PostgreSQL real, las pruebas pgTAP y las pruebas de
  integración (no había Docker en la máquina de desarrollo). Es lo primero que hay que correr.
- **No verificado:** llamadas reales a Claude, Voyage y Storage; el flujo completo en el navegador; la calibración
  del umbral de similitud.
