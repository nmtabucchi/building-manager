# Frontend (Etapa 5)

Next.js (App Router) + React, JavaScript. Estilos con CSS plano (claro/oscuro automático).

```bash
npm install
cp .env.example .env.local     # NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_BASE_URL
npm run dev                    # http://localhost:3000
npm test                       # utilidades puras (node:test)
npm run build
```

El navegador solo habla con Supabase Auth (clave pública) y con el backend FastAPI (`Authorization: Bearer <JWT>`).
No accede a tablas ni a Storage. Node 20+ (se fija `@supabase/supabase-js@~2.100` porque las versiones recientes exigen Node 22).

Pantallas: `/login`, `/dashboard`, `/edificios` (+ `nuevo`, `[id]` con miembros), `/documentos`, `/asistente`.
