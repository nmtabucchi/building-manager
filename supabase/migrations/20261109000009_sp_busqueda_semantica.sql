-- =============================================================================
-- Building Manager AI — Migración 0009
-- Stored procedure de búsqueda semántica (pgvector)
-- =============================================================================
-- Python genera el embedding de la pregunta y lo envía a este SP. La búsqueda,
-- el filtrado por edificio y la autorización ocurren en la base de datos.
--
-- Aislamiento por edificio (tres capas):
--   1. Validación explícita de membresía (BM404 si no es miembro).
--   2. Filtro WHERE c.building_id = p_building_id.
--   3. RLS de document_chunks (SECURITY INVOKER + JWT del usuario).
-- Solo se consideran documentos en estado 'procesado' (los chunks de un
-- procesamiento parcial o en curso nunca llegan al LLM).
--
-- Rendimiento: el índice HNSW ordena por distancia; el filtro por edificio se
-- aplica después. Con pgvector >= 0.8 se activa iterative index scan para que
-- el índice siga buscando hasta completar p_match_count resultados del
-- edificio, en lugar de devolver menos filas de las pedidas.
-- =============================================================================

create or replace function public.sp_chunk_buscar_similares(
    p_building_id     uuid,
    p_query_embedding extensions.vector(1024),
    p_match_count     integer                   default 8,
    p_min_similarity  double precision          default 0.0,
    p_categorias      app.document_category[]   default null
)
returns table (
    chunk_id         uuid,
    document_id      uuid,
    building_id      uuid,
    file_name        text,
    titulo           text,
    categoria        app.document_category,
    fecha_documento  date,
    chunk_index      integer,
    page_number      integer,
    page_end         integer,
    content          text,
    metadata         jsonb,
    similarity       double precision
)
language plpgsql
volatile          -- usa set_config
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();

    if p_building_id is null or not app.fn_es_miembro(p_building_id) then
        perform app.raise_error('BM404', 'Edificio no encontrado');
    end if;
    if p_query_embedding is null then
        perform app.raise_error('BM422', 'p_query_embedding es obligatorio');
    end if;
    if p_match_count is null or p_match_count not between 1 and 50 then
        perform app.raise_error('BM422', 'p_match_count debe estar entre 1 y 50');
    end if;
    if p_min_similarity is null or p_min_similarity not between -1 and 1 then
        perform app.raise_error('BM422', 'p_min_similarity debe estar entre -1 y 1');
    end if;

    -- Parámetros locales a la transacción (no afectan a otras sesiones).
    perform set_config('hnsw.iterative_scan', 'relaxed_order', true);
    perform set_config('hnsw.ef_search', '100', true);

    return query
        with candidatos as (
            select c.id, c.document_id, c.building_id, c.chunk_index, c.page_number, c.page_end,
                   c.content, c.metadata,
                   c.embedding operator(extensions.<=>) p_query_embedding as distancia
            from app.document_chunks c
            join app.documents d on d.id = c.document_id
            where c.building_id = p_building_id
              and d.status = 'procesado'
              and (p_categorias is null or d.categoria = any (p_categorias))
            order by c.embedding operator(extensions.<=>) p_query_embedding
            limit p_match_count
        )
        select k.id, k.document_id, k.building_id, d.file_name, d.titulo, d.categoria,
               d.fecha_documento, k.chunk_index, k.page_number, k.page_end, k.content, k.metadata,
               (1 - k.distancia)::double precision as similarity
        from candidatos k
        join app.documents d on d.id = k.document_id
        where (1 - k.distancia) >= p_min_similarity
        -- relaxed_order puede devolver candidatos levemente desordenados:
        -- se reordena el conjunto final.
        order by k.distancia;
end;
$$;
