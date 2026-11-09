-- =============================================================================
-- Building Manager AI — Migración 0003
-- Índices convencionales y vectoriales
-- =============================================================================

-- buildings
create index buildings_created_by_idx on app.buildings (created_by);
create index buildings_activos_idx    on app.buildings (nombre) where deleted_at is null;

-- building_users: la PK (building_id, user_id) cubre búsquedas por edificio;
-- este índice cubre "edificios de un usuario" (consulta más frecuente: RLS).
create index building_users_user_idx on app.building_users (user_id, building_id);

-- documents
create index documents_building_created_idx on app.documents (building_id, created_at desc);
create index documents_building_status_idx  on app.documents (building_id, status);
create index documents_pendientes_idx       on app.documents (created_at)
    where status in ('pendiente', 'procesando');
create index documents_uploaded_by_idx      on app.documents (uploaded_by);

-- document_chunks
-- (document_id, chunk_index) ya está indexado por la restricción UNIQUE.
create index document_chunks_building_idx on app.document_chunks (building_id);

-- Índice vectorial HNSW con distancia coseno.
--   * HNSW: mejor recall/latencia que IVFFlat y no requiere "entrenamiento"
--     previo con datos (IVFFlat necesita filas para calcular listas).
--   * m / ef_construction: valores por defecto razonables para el MVP.
--   * El filtrado por edificio se combina con iterative index scan
--     (pgvector >= 0.8) dentro de sp_chunk_buscar_similares.
create index document_chunks_embedding_hnsw_idx
    on app.document_chunks
    using hnsw (embedding extensions.vector_cosine_ops)
    with (m = 16, ef_construction = 64);

-- conversations
create index conversations_user_building_idx on app.conversations (user_id, building_id, updated_at desc);
create index conversations_building_idx      on app.conversations (building_id);

-- messages
create index messages_conversation_created_idx on app.messages (conversation_id, created_at);
