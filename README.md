# Building Manager AI

Asistente inteligente para la administración de edificios y consorcios: consulta
de reglamentos, actas y documentación mediante RAG (Claude + pgvector sobre Supabase).

Estado: **Etapa 1 — Análisis y diseño** (pendiente de aprobación).

- Diseño: [docs/etapa-1-analisis-y-diseno.md](docs/etapa-1-analisis-y-diseno.md)
- Stored procedures y matriz Python ↔ SP: [docs/catalogo-stored-procedures.md](docs/catalogo-stored-procedures.md)
- Scripts SQL: [supabase/migrations/](supabase/migrations/), [supabase/seed.sql](supabase/seed.sql), [supabase/tests/](supabase/tests/)

Stack: Next.js + React (JavaScript) · FastAPI (Python, POO) · Claude API · LangChain ·
LangGraph · Supabase (PostgreSQL, pgvector, Auth, Storage) · PyMuPDF · python-docx.
