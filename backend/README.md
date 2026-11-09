# Backend (Etapa 2)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Linux/macOS: .venv/bin/python
cp .env.example .env                                 # completar SUPABASE_URL y SUPABASE_ANON_KEY
.venv/Scripts/python -m pytest                       # 61 pruebas unitarias
.venv/Scripts/python -m uvicorn app.main:create_app --factory --reload
```

Documentación interactiva: http://localhost:8000/docs

Base de datos local (requiere Docker + Supabase CLI), desde la raíz del repo:

```bash
supabase start && supabase db reset && supabase test db
```

Flujo: Route → Service → Repository → `StoredProcedureClient` → Supabase RPC → `sp_*`.
Solo `StoredProcedureClient` habla con la base; `tests/unit/test_architecture.py` falla si aparece SQL o un ORM en `app/`.
