# Catálogo de stored procedures y matriz Python ↔ SP

Complemento de [etapa-1-analisis-y-diseno.md](etapa-1-analisis-y-diseno.md).
El **SQL completo** de cada procedimiento está en el archivo de migración
indicado en cada sección (no se duplica aquí para evitar divergencias).

## Convenciones comunes

- Implementación: `FUNCTION` PL/pgSQL en el esquema `public`, `RETURNS TABLE (...)`,
  `SET search_path = ''`, objetos calificados (`app.`, `extensions.`).
- Invocación: Supabase RPC → `POST /rest/v1/rpc/<nombre>` con parámetros JSON con nombre.
  Siempre devuelve una **lista** de filas (vacía, una o varias).
- Contexto: **U** = rol `authenticated` con JWT del usuario (RLS activa) ·
  **S** = `service_role` (worker de ingesta).
- Errores de negocio (SQLSTATE → excepción Python → HTTP):

| SQLSTATE | Significado | Excepción de dominio | HTTP |
|----------|-------------|----------------------|------|
| `BM401` | Sin usuario autenticado | `AuthenticationError` | 401 |
| `BM403` | Miembro sin el rol requerido | `PermissionDeniedError` | 403 |
| `BM404` | No existe **o** no es visible para el usuario | `NotFoundError` | 404 |
| `BM409` | Duplicado / transición de estado inválida | `ConflictError` | 409 |
| `BM422` | Parámetros inválidos | `ValidationError` | 422 |
| `42501` | Sin privilegio `EXECUTE` sobre el SP | `PermissionDeniedError` | 403 |
| `PGRST202` | SP inexistente o firma distinta | `InfrastructureError` | 500 |
| `23xxx` no capturado | Violación de integridad inesperada | `PersistenceError` | 500 |

### Patrón de invocación desde Python (diseño)

```python
class BuildingRepository(BaseRepository):
    SP_OBTENER_POR_ID = "sp_building_obtener_por_id"

    async def obtener_por_id(self, auth: UserAuthContext, building_id: UUID) -> Building:
        row = await self._sp.call_one(
            self.SP_OBTENER_POR_ID,
            {"p_building_id": building_id},   # parámetros con nombre, nunca concatenados
            auth=auth,
        )
        return BuildingMapper.from_row(row)
```

Internamente `StoredProcedureClient.call_one` ejecuta
`client.postgrest.rpc(name, serialized_params)` con las cabeceras del `auth`
recibido, convierte la respuesta en `list[dict]` y traduce el error PostgREST
(`code`) a la excepción de dominio según la tabla anterior.

En los ejemplos de abajo, `sp` es la instancia de `StoredProcedureClient`.

---

## 1. Usuarios — `20261109000006_sp_usuarios_edificios.sql`

### `sp_user_obtener_actual` · U
- **Objetivo**: perfil del usuario autenticado.
- **Parámetros**: ninguno.
- **Validaciones**: usuario autenticado.
- **Resultado**: `id uuid, email text, full_name text, created_at timestamptz` (1 fila).
- **Errores**: `BM401`, `BM404` (perfil inexistente: trigger no ejecutado).
- **Python**: `await sp.call_one("sp_user_obtener_actual", {}, auth=ctx)`

## 2. Edificios — `20261109000006_sp_usuarios_edificios.sql`

Resultado común **`BuildingRow`**: `id uuid, nombre text, direccion text, localidad text,
provincia text, informacion_general text, rol building_role, total_documentos bigint,
created_at timestamptz, updated_at timestamptz` (`rol` = rol del usuario actual).

### `sp_building_crear` · U
- **Objetivo**: alta de edificio; en la misma transacción asigna al creador como `administrador`.
- **Parámetros**: `p_nombre text` (2–150), `p_direccion text` (3–250), `p_localidad text` (2–120), `p_provincia text` (2–120), `p_informacion_general text = null` (≤ 5000).
- **Validaciones**: autenticado; longitudes (tras `btrim`); RLS `buildings_insert` (`created_by = auth.uid()`) y `building_users_insert` (alta inicial).
- **Resultado**: 1 `BuildingRow` con `rol = administrador`.
- **Errores**: `BM401`, `BM422`.
- **Python**: `await sp.call_one("sp_building_crear", {"p_nombre": ..., "p_direccion": ..., "p_localidad": ..., "p_provincia": ..., "p_informacion_general": ...}, auth=ctx)`

### `sp_building_actualizar` · U
- **Objetivo**: modificación completa (PUT).
- **Parámetros**: `p_building_id uuid` + mismos campos que crear.
- **Validaciones**: rol `administrador` (`fn_exigir_rol`); longitudes; RLS `buildings_update_admin`.
- **Resultado**: 1 `BuildingRow`.
- **Errores**: `BM401`, `BM404`, `BM403`, `BM422`.
- **Python**: `await sp.call_one("sp_building_actualizar", {"p_building_id": id, ...}, auth=ctx)`

### `sp_building_eliminar` · U
- **Objetivo**: baja lógica (`deleted_at = now()`); deja de ser visible para todos sus miembros.
- **Parámetros**: `p_building_id uuid`.
- **Validaciones**: rol `administrador`.
- **Resultado**: `id uuid, eliminado boolean, deleted_at timestamptz`.
- **Errores**: `BM401`, `BM404`, `BM403`.
- **Python**: `await sp.call_one("sp_building_eliminar", {"p_building_id": id}, auth=ctx)`

### `sp_building_obtener_por_id` · U
- **Objetivo**: detalle de un edificio del que el usuario es miembro.
- **Parámetros**: `p_building_id uuid`.
- **Validaciones**: autenticado; no nulo; membresía (vía proyección + RLS).
- **Resultado**: 1 `BuildingRow`.
- **Errores**: `BM401`, `BM422`, `BM404`.
- **Python**: `await sp.call_one("sp_building_obtener_por_id", {"p_building_id": id}, auth=ctx)`

### `sp_building_listar_por_usuario` · U
- **Objetivo**: edificios activos del usuario, ordenados por nombre.
- **Parámetros**: ninguno.
- **Resultado**: 0..N `BuildingRow`.
- **Errores**: `BM401`.
- **Python**: `await sp.call("sp_building_listar_por_usuario", {}, auth=ctx)`

## 3. Membresías — `20261109000006_sp_usuarios_edificios.sql`

Resultado común **`MemberRow`**: `user_id uuid, email text, full_name text, rol building_role, created_at timestamptz`.

### `sp_building_usuario_listar` · U
- **Objetivo**: miembros del edificio.
- **Parámetros**: `p_building_id uuid`.
- **Validaciones**: membresía (cualquier rol).
- **Resultado**: 0..N `MemberRow`.
- **Errores**: `BM401`, `BM404`.
- **Python**: `await sp.call("sp_building_usuario_listar", {"p_building_id": id}, auth=ctx)`

### `sp_building_usuario_asignar` · U · **SECURITY DEFINER** (excepción documentada)
- **Objetivo**: agrega por email a un usuario registrado o cambia su rol (upsert).
- **Parámetros**: `p_building_id uuid`, `p_email text` (3–320), `p_rol building_role`.
- **Validaciones**: rol `administrador`; rol no nulo; email existente en `app.users`; el edificio conserva ≥ 1 administrador.
- **Resultado**: 1 `MemberRow`.
- **Errores**: `BM401`, `BM404` (edificio o email), `BM403`, `BM409` (último administrador), `BM422`.
- **Python**: `await sp.call_one("sp_building_usuario_asignar", {"p_building_id": id, "p_email": email, "p_rol": "colaborador"}, auth=ctx)`

### `sp_building_usuario_quitar` · U
- **Objetivo**: quitar un miembro.
- **Parámetros**: `p_building_id uuid`, `p_user_id uuid`.
- **Validaciones**: rol `administrador`; el usuario es miembro; no es el único administrador.
- **Resultado**: `building_id uuid, user_id uuid, eliminado boolean`.
- **Errores**: `BM401`, `BM404`, `BM403`, `BM409`.
- **Python**: `await sp.call_one("sp_building_usuario_quitar", {"p_building_id": id, "p_user_id": uid}, auth=ctx)`

## 4. Dashboard — `20261109000006_sp_usuarios_edificios.sql`

### `sp_dashboard_resumen` · U
- **Objetivo**: métricas agregadas de los edificios del usuario.
- **Parámetros**: ninguno.
- **Resultado**: `total_edificios, total_documentos, documentos_pendientes, documentos_procesando, documentos_procesados, documentos_con_error, total_conversaciones` (todos `bigint`, 1 fila).
- **Errores**: `BM401`.
- **Python**: `await sp.call_one("sp_dashboard_resumen", {}, auth=ctx)`

## 5. Documentos — `20261109000007_sp_documentos.sql`

Resultado común **`DocumentRow`**: `id, building_id, building_nombre, file_name, file_type,
mime_type, size_bytes, storage_path, categoria, titulo, fecha_documento, status,
error_message, page_count, chunk_count, uploaded_by, uploaded_by_email, processed_at,
created_at, updated_at`. (`storage_path` lo usa el backend; la API no lo expone.)

### `sp_document_crear` · U
- **Objetivo**: registrar el documento en estado `pendiente` y calcular `storage_path = {building_id}/{document_id}.{ext}` antes de subir el archivo.
- **Parámetros**: `p_building_id uuid`, `p_file_name text` (1–255, sin `/`, `\` ni caracteres de control), `p_file_type file_type`, `p_mime_type text`, `p_size_bytes bigint` (1 B–20 MB), `p_sha256 text` (64 hex), `p_categoria document_category = 'otro'`, `p_titulo text = null` (≤ 255), `p_fecha_documento date = null` (no futura).
- **Validaciones**: rol `administrador`/`colaborador`; coherencia tipo ↔ MIME; duplicado por hash en el edificio.
- **Resultado**: 1 `DocumentRow` (`status = pendiente`).
- **Errores**: `BM401`, `BM404`, `BM403`, `BM422`, `BM409` (`detail` = id del documento existente).
- **Python**: `await sp.call_one("sp_document_crear", {"p_building_id": id, "p_file_name": name, "p_file_type": "pdf", "p_mime_type": "application/pdf", "p_size_bytes": size, "p_sha256": digest, "p_categoria": "reglamento", "p_titulo": None, "p_fecha_documento": None}, auth=ctx)`

### `sp_document_listar_por_edificio` · U
- **Objetivo**: listado con filtros opcionales, más recientes primero.
- **Parámetros**: `p_building_id uuid`, `p_status document_status = null`, `p_categoria document_category = null`.
- **Validaciones**: membresía.
- **Resultado**: 0..N `DocumentRow`.
- **Errores**: `BM401`, `BM404`.
- **Python**: `await sp.call("sp_document_listar_por_edificio", {"p_building_id": id, "p_status": None, "p_categoria": None}, auth=ctx)`

### `sp_document_obtener_por_id` · U
- **Objetivo**: detalle (también autoriza la emisión de URL firmada de descarga).
- **Parámetros**: `p_document_id uuid`.
- **Resultado**: 1 `DocumentRow`.
- **Errores**: `BM401`, `BM404`.
- **Python**: `await sp.call_one("sp_document_obtener_por_id", {"p_document_id": doc_id}, auth=ctx)`

### `sp_document_actualizar_metadatos` · U
- **Objetivo**: editar categoría, título y fecha (no requiere reprocesar).
- **Parámetros**: `p_document_id uuid`, `p_categoria document_category`, `p_titulo text = null`, `p_fecha_documento date = null`.
- **Validaciones**: documento visible; rol `administrador`/`colaborador`; categoría no nula; título ≤ 255; fecha no futura.
- **Resultado**: 1 `DocumentRow`.
- **Errores**: `BM401`, `BM404`, `BM403`, `BM422`.
- **Python**: `await sp.call_one("sp_document_actualizar_metadatos", {"p_document_id": doc_id, "p_categoria": "acta_asamblea", "p_titulo": "Asamblea ordinaria 2025", "p_fecha_documento": "2025-04-12"}, auth=ctx)`

### `sp_document_eliminar` · U
- **Objetivo**: borrado físico del documento y sus chunks (cascada); devuelve la ruta para borrar el archivo.
- **Parámetros**: `p_document_id uuid`.
- **Validaciones**: documento visible; rol `administrador`/`colaborador`.
- **Resultado**: `id uuid, building_id uuid, storage_path text, eliminado boolean`.
- **Errores**: `BM401`, `BM404`, `BM403`.
- **Python**: `await sp.call_one("sp_document_eliminar", {"p_document_id": doc_id}, auth=ctx)` → luego `StorageGateway.delete(row["storage_path"])`.

### `sp_document_reprocesar` · U
- **Objetivo**: devolver a `pendiente` un documento `procesado` o `error`.
- **Parámetros**: `p_document_id uuid`.
- **Validaciones**: rol `administrador`/`colaborador`; estado actual ∈ {`procesado`, `error`} (con bloqueo de fila).
- **Resultado**: 1 `DocumentRow`.
- **Errores**: `BM401`, `BM404`, `BM403`, `BM409`.
- **Python**: `await sp.call_one("sp_document_reprocesar", {"p_document_id": doc_id}, auth=ctx)` → luego `IngestionQueue.enqueue(doc_id)`.

## 6. Ingesta — `20261109000008_sp_ingesta.sql` (solo `service_role`)

### `sp_ingesta_document_obtener` · S
- **Objetivo**: datos para procesar un documento.
- **Parámetros**: `p_document_id uuid`.
- **Resultado**: `id, building_id, file_name, file_type, mime_type, storage_path, categoria, titulo, fecha_documento, status`.
- **Errores**: `BM404`, `42501` si lo invoca otro rol.
- **Python**: `await sp.call_one("sp_ingesta_document_obtener", {"p_document_id": doc_id}, auth=service_ctx)`

### `sp_ingesta_document_actualizar_estado` · S
- **Objetivo**: transición de estado validada; `pendiente → procesando` actúa como *claim* exclusivo.
- **Parámetros**: `p_document_id uuid`, `p_status document_status`, `p_error_message text = null`, `p_page_count int = null`, `p_chunk_count int = null`.
- **Validaciones**: transiciones permitidas (`pendiente→procesando|error`, `procesando→procesado|error|pendiente`, `error→pendiente`, `procesado→pendiente`); `error` exige mensaje (se trunca a 2000); `procesado` exige `chunk_count ≥ 1` **igual** al número real de chunks guardados.
- **Resultado**: `id, status, error_message, page_count, chunk_count, processed_at, updated_at`.
- **Errores**: `BM404`, `BM409` (transición inválida / conteo distinto), `BM422`.
- **Python**: `await sp.call_one("sp_ingesta_document_actualizar_estado", {"p_document_id": doc_id, "p_status": "procesado", "p_page_count": 18, "p_chunk_count": 42}, auth=service_ctx)`

### `sp_ingesta_document_listar_pendientes` · S
- **Objetivo**: documentos a (re)encolar al iniciar el worker.
- **Parámetros**: `p_limit int = 20` (1–500), `p_minutos_estancado int = 15` (≥ 1).
- **Resultado**: `id, building_id, status, updated_at` de documentos `pendiente` o `procesando` estancados, de edificios activos.
- **Errores**: `BM422`.
- **Python**: `await sp.call("sp_ingesta_document_listar_pendientes", {"p_limit": 50, "p_minutos_estancado": 15}, auth=service_ctx)`

### `sp_ingesta_chunks_eliminar_por_documento` · S
- **Objetivo**: borrar chunks previos (reproceso / reintento). Idempotente.
- **Parámetros**: `p_document_id uuid`.
- **Resultado**: `document_id uuid, eliminados int`.
- **Errores**: `BM404`.
- **Python**: `await sp.call_one("sp_ingesta_chunks_eliminar_por_documento", {"p_document_id": doc_id}, auth=service_ctx)`

### `sp_ingesta_chunks_insertar_lote` · S
- **Objetivo**: insertar un lote de chunks con embeddings.
- **Parámetros**: `p_document_id uuid`, `p_embedding_model text` (1–200), `p_chunks jsonb` — array de 1 a 200 objetos `{chunk_index:int≥0, content:string no vacío, embedding:number[1024], page_number?:int|null, page_end?:int|null, token_count?:int|null, metadata?:object|null}`.
- **Validaciones**: documento existente y en estado `procesando`; estructura y dimensión de cada elemento; `building_id` tomado del documento (nunca del cliente); `chunk_index` único por documento; `CHECK` de páginas.
- **Resultado**: `document_id uuid, insertados int, total_chunks bigint`.
- **Errores**: `BM404`, `BM409` (estado o índice duplicado), `BM422`.
- **Python**:
  ```python
  await sp.call_one("sp_ingesta_chunks_insertar_lote", {
      "p_document_id": doc_id,
      "p_embedding_model": "voyage-3.5",
      "p_chunks": [{"chunk_index": 0, "content": "...", "page_number": 1, "page_end": 1,
                    "token_count": 280, "metadata": {"seccion": "Capítulo I"},
                    "embedding": [0.0123, ...]}],          # 1024 floats
  }, auth=service_ctx)
  ```

## 7. Búsqueda semántica — `20261109000009_sp_busqueda_semantica.sql`

### `sp_chunk_buscar_similares` · U
- **Objetivo**: los `p_match_count` fragmentos más similares a la pregunta, **solo** del edificio indicado y de documentos `procesado`.
- **Parámetros**: `p_building_id uuid`, `p_query_embedding vector(1024)` (Python envía `list[float]`), `p_match_count int = 8` (1–50), `p_min_similarity float8 = 0.0` (−1..1), `p_categorias document_category[] = null` (filtro opcional, pensado para agentes especializados).
- **Validaciones**: autenticado; membresía; parámetros en rango; dimensión garantizada por el tipo `vector(1024)`.
- **Operación**: ordena por distancia coseno (`<=>`) usando el índice HNSW con *iterative scan* (`relaxed_order`, `ef_search=100`, locales a la transacción), filtra por umbral y reordena.
- **Resultado**: `chunk_id, document_id, building_id, file_name, titulo, categoria, fecha_documento, chunk_index, page_number, page_end, content, metadata, similarity` (0..`p_match_count` filas, mayor similitud primero).
- **Errores**: `BM401`, `BM404`, `BM422`.
- **Python**:
  ```python
  vector = await embeddings.embed_query(question)        # list[float] de 1024
  rows = await sp.call("sp_chunk_buscar_similares", {
      "p_building_id": building_id, "p_query_embedding": vector,
      "p_match_count": 8, "p_min_similarity": 0.35, "p_categorias": None,
  }, auth=ctx)
  ```

## 8. Conversaciones — `20261109000010_sp_conversaciones.sql`

Resultado común **`ConversationRow`**: `id, building_id, building_nombre, titulo, total_mensajes bigint, ultimo_mensaje_at, created_at, updated_at`.

### `sp_conversation_crear` · U
- **Parámetros**: `p_building_id uuid`, `p_titulo text = null` (≤ 200).
- **Validaciones**: membresía (cualquier rol); RLS `conversations_owner`.
- **Resultado**: 1 `ConversationRow`.
- **Errores**: `BM401`, `BM404`, `BM422`.
- **Python**: `await sp.call_one("sp_conversation_crear", {"p_building_id": id, "p_titulo": None}, auth=ctx)`

### `sp_conversation_listar` · U
- **Parámetros**: `p_building_id uuid = null`, `p_limit int = 20` (1–100), `p_offset int = 0`.
- **Validaciones**: si se indica edificio, membresía. RLS: solo conversaciones propias de edificios activos.
- **Resultado**: 0..N `ConversationRow` (más recientes primero).
- **Errores**: `BM401`, `BM404`, `BM422`.
- **Python**: `await sp.call("sp_conversation_listar", {"p_building_id": id, "p_limit": 20, "p_offset": 0}, auth=ctx)`

### `sp_conversation_obtener_por_id` · U
- **Parámetros**: `p_conversation_id uuid`.
- **Resultado**: 1 `ConversationRow`.
- **Errores**: `BM401`, `BM404` (inexistente, ajena o de un edificio del que ya no es miembro).
- **Python**: `await sp.call_one("sp_conversation_obtener_por_id", {"p_conversation_id": cid}, auth=ctx)`

## 9. Mensajes — `20261109000010_sp_conversaciones.sql`

Resultado común **`MessageRow`**: `id, conversation_id, role, content, sources jsonb, metadata jsonb, created_at`.

### `sp_message_crear` · U
- **Objetivo**: agregar un mensaje; actualiza `updated_at` de la conversación y le asigna título con la primera pregunta (80 caracteres) si no tenía.
- **Parámetros**: `p_conversation_id uuid`, `p_role message_role`, `p_content text` (1–20000), `p_sources jsonb = '[]'` (array de objetos; vacío si `role = user`), `p_metadata jsonb = '{}'` (objeto).
- **Validaciones**: conversación visible (propia + membresía); tipos JSON; reglas por rol.
- **Resultado**: 1 `MessageRow`.
- **Errores**: `BM401`, `BM404`, `BM422`.
- **Python**: `await sp.call_one("sp_message_crear", {"p_conversation_id": cid, "p_role": "assistant", "p_content": answer, "p_sources": sources, "p_metadata": meta}, auth=ctx)`

### `sp_message_listar_por_conversacion` · U
- **Objetivo**: últimos `p_limit` mensajes (opcionalmente anteriores a `p_antes_de`) en orden cronológico. El grafo lo usa con `p_limit = 6` para el contexto.
- **Parámetros**: `p_conversation_id uuid`, `p_limit int = 50` (1–200), `p_antes_de timestamptz = null`.
- **Resultado**: 0..N `MessageRow`.
- **Errores**: `BM401`, `BM404`, `BM422`.
- **Python**: `await sp.call("sp_message_listar_por_conversacion", {"p_conversation_id": cid, "p_limit": 6, "p_antes_de": None}, auth=ctx)`

---

## Matriz de correspondencia: método Python → stored procedure

| Repositorio (backend/app/repositories) | Método | Stored procedure | Contexto | Lo usa |
|----------------------------------------|--------|------------------|:-------:|--------|
| `UserRepository` | `obtener_actual(auth)` | `sp_user_obtener_actual` | U | `GET /me` |
| `BuildingRepository` | `crear(auth, data)` | `sp_building_crear` | U | `BuildingService.crear` |
| `BuildingRepository` | `actualizar(auth, building_id, data)` | `sp_building_actualizar` | U | `BuildingService.actualizar` |
| `BuildingRepository` | `eliminar(auth, building_id)` | `sp_building_eliminar` | U | `BuildingService.eliminar` |
| `BuildingRepository` | `obtener_por_id(auth, building_id)` | `sp_building_obtener_por_id` | U | `BuildingService`, `ChatService` (nombre del edificio) |
| `BuildingRepository` | `listar_por_usuario(auth)` | `sp_building_listar_por_usuario` | U | `BuildingService.listar` |
| `MemberRepository` | `listar(auth, building_id)` | `sp_building_usuario_listar` | U | `MemberService.listar` |
| `MemberRepository` | `asignar(auth, building_id, email, rol)` | `sp_building_usuario_asignar` | U | `MemberService.asignar` |
| `MemberRepository` | `quitar(auth, building_id, user_id)` | `sp_building_usuario_quitar` | U | `MemberService.quitar` |
| `DashboardRepository` | `resumen(auth)` | `sp_dashboard_resumen` | U | `DashboardService` |
| `DocumentRepository` | `crear(auth, data)` | `sp_document_crear` | U | `DocumentService.cargar` |
| `DocumentRepository` | `listar_por_edificio(auth, building_id, status, categoria)` | `sp_document_listar_por_edificio` | U | `DocumentService.listar` |
| `DocumentRepository` | `obtener_por_id(auth, document_id)` | `sp_document_obtener_por_id` | U | `DocumentService.obtener`, `.url_descarga` |
| `DocumentRepository` | `actualizar_metadatos(auth, document_id, data)` | `sp_document_actualizar_metadatos` | U | `DocumentService.actualizar` |
| `DocumentRepository` | `eliminar(auth, document_id)` | `sp_document_eliminar` | U | `DocumentService.eliminar`, compensación de upload |
| `DocumentRepository` | `reprocesar(auth, document_id)` | `sp_document_reprocesar` | U | `DocumentService.reprocesar` |
| `IngestionRepository` | `obtener_documento(document_id)` | `sp_ingesta_document_obtener` | S | `IngestionService` |
| `IngestionRepository` | `actualizar_estado(document_id, status, ...)` | `sp_ingesta_document_actualizar_estado` | S | `IngestionService` |
| `IngestionRepository` | `listar_pendientes(limit, minutos)` | `sp_ingesta_document_listar_pendientes` | S | Worker (arranque) |
| `IngestionRepository` | `eliminar_chunks(document_id)` | `sp_ingesta_chunks_eliminar_por_documento` | S | `IngestionPipeline` |
| `IngestionRepository` | `insertar_chunks(document_id, model, chunks)` | `sp_ingesta_chunks_insertar_lote` | S | `IngestionPipeline` |
| `ChunkRepository` | `buscar_similares(auth, building_id, vector, k, min_sim, categorias)` | `sp_chunk_buscar_similares` | U | `SupabaseRetriever` (nodo `recuperar_fragmentos`) |
| `ConversationRepository` | `crear(auth, building_id, titulo)` | `sp_conversation_crear` | U | `ChatService` |
| `ConversationRepository` | `listar(auth, building_id, limit, offset)` | `sp_conversation_listar` | U | `ChatService` |
| `ConversationRepository` | `obtener_por_id(auth, conversation_id)` | `sp_conversation_obtener_por_id` | U | `ChatService` |
| `MessageRepository` | `crear(auth, conversation_id, role, content, sources, metadata)` | `sp_message_crear` | U | `ChatService` |
| `MessageRepository` | `listar_por_conversacion(auth, conversation_id, limit, antes_de)` | `sp_message_listar_por_conversacion` | U | `ChatService`, nodo `cargar_contexto` |

Funciones internas del esquema `app` (no invocables desde Python, no expuestas):
`raise_error`, `fn_usuario_actual`, `fn_edificios_usuario`, `fn_es_miembro`,
`fn_tiene_rol`, `fn_exigir_rol`, `fn_edificio_sin_miembros`, `fn_validar_texto`,
`fn_buildings_del_usuario`, `fn_documents_visibles`, `fn_building_de_documento`,
`fn_conversations_visibles`, `fn_embedding_dim`, triggers `tg_set_updated_at`, `tg_sync_auth_user`.
