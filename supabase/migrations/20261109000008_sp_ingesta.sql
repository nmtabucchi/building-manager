-- =============================================================================
-- Building Manager AI — Migración 0008
-- Stored procedures del pipeline de ingesta (solo service_role)
-- =============================================================================
-- EXCEPCIÓN DOCUMENTADA (contexto de ejecución): estos SP los invoca el worker
-- de ingesta del backend con la clave service_role, que tiene BYPASSRLS.
-- Motivo: el procesamiento es asíncrono e independiente de la sesión del
-- usuario (RF03); el JWT del usuario puede expirar durante el proceso y la
-- tabla document_chunks no admite escritura desde `authenticated`.
-- Compensaciones:
--   * EXECUTE concedido SOLO a service_role (ver migración 0011).
--   * Validan existencia, estado y coherencia documento/edificio.
--   * La clave service_role vive solo en el backend, nunca en el frontend.
-- =============================================================================

-- Dimensión del embedding esperada (debe coincidir con document_chunks.embedding).
create or replace function app.fn_embedding_dim()
returns integer
language sql
immutable
set search_path = ''
as $$ select 1024 $$;

-- -----------------------------------------------------------------------------
-- sp_ingesta_document_obtener: datos necesarios para procesar un documento.
-- -----------------------------------------------------------------------------
create or replace function public.sp_ingesta_document_obtener(p_document_id uuid)
returns table (
    id uuid, building_id uuid, file_name text, file_type app.file_type, mime_type text,
    storage_path text, categoria app.document_category, titulo text, fecha_documento date,
    status app.document_status
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    return query
        select d.id, d.building_id, d.file_name, d.file_type, d.mime_type, d.storage_path,
               d.categoria, d.titulo, d.fecha_documento, d.status
        from app.documents d
        where d.id = p_document_id;
    if not found then
        perform app.raise_error('BM404', 'Documento no encontrado');
    end if;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_ingesta_document_actualizar_estado: transición de estado validada.
--   pendiente  -> procesando | error
--   procesando -> procesado | error | pendiente (recuperación de un worker caído)
--   error      -> pendiente
--   procesado  -> pendiente
-- La transición pendiente -> procesando funciona como "claim": bloquea la fila
-- y falla con BM409 si otro worker ya la tomó.
-- Al pasar a 'procesado' verifica que p_chunk_count coincida con los chunks
-- realmente almacenados.
-- -----------------------------------------------------------------------------
create or replace function public.sp_ingesta_document_actualizar_estado(
    p_document_id   uuid,
    p_status        app.document_status,
    p_error_message text    default null,
    p_page_count    integer default null,
    p_chunk_count   integer default null
)
returns table (
    id uuid, status app.document_status, error_message text, page_count integer,
    chunk_count integer, processed_at timestamptz, updated_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_actual app.document_status;
    v_reales bigint;
begin
    if p_status is null then
        perform app.raise_error('BM422', 'p_status es obligatorio');
    end if;

    select d.status into v_actual from app.documents d where d.id = p_document_id for update;
    if v_actual is null then
        perform app.raise_error('BM404', 'Documento no encontrado');
    end if;

    if not (
           (v_actual = 'pendiente'  and p_status in ('procesando', 'error'))
        or (v_actual = 'procesando' and p_status in ('procesado', 'error', 'pendiente'))
        or (v_actual = 'error'      and p_status = 'pendiente')
        or (v_actual = 'procesado'  and p_status = 'pendiente')
    ) then
        perform app.raise_error('BM409', format('Transición de estado inválida: %s -> %s', v_actual, p_status));
    end if;

    if p_status = 'error' and nullif(btrim(p_error_message), '') is null then
        perform app.raise_error('BM422', 'p_error_message es obligatorio para el estado error');
    end if;

    if p_status = 'procesado' then
        if p_chunk_count is null or p_chunk_count < 1 then
            perform app.raise_error('BM422', 'Un documento procesado debe tener al menos un chunk');
        end if;
        if p_page_count is not null and p_page_count < 0 then
            perform app.raise_error('BM422', 'p_page_count no puede ser negativo');
        end if;
        select count(*) into v_reales from app.document_chunks c where c.document_id = p_document_id;
        if v_reales <> p_chunk_count then
            perform app.raise_error('BM409',
                format('chunk_count informado (%s) no coincide con los chunks almacenados (%s)', p_chunk_count, v_reales));
        end if;
    end if;

    update app.documents d
       set status        = p_status,
           error_message = case when p_status = 'error' then left(btrim(p_error_message), 2000) end,
           page_count    = case when p_status = 'procesado' then p_page_count else d.page_count end,
           chunk_count   = case when p_status = 'procesado' then p_chunk_count
                                when p_status = 'procesando' then 0
                                else d.chunk_count end,
           processed_at  = case when p_status = 'procesado' then now() else d.processed_at end
     where d.id = p_document_id;

    return query
        select d.id, d.status, d.error_message, d.page_count, d.chunk_count, d.processed_at, d.updated_at
        from app.documents d where d.id = p_document_id;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_ingesta_document_listar_pendientes: documentos a encolar al iniciar el
-- worker (pendientes, o "procesando" estancados por caída del proceso).
-- -----------------------------------------------------------------------------
create or replace function public.sp_ingesta_document_listar_pendientes(
    p_limit               integer  default 20,
    p_minutos_estancado   integer  default 15
)
returns table (id uuid, building_id uuid, status app.document_status, updated_at timestamptz)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    if p_limit is null or p_limit not between 1 and 500 then
        perform app.raise_error('BM422', 'p_limit debe estar entre 1 y 500');
    end if;
    if p_minutos_estancado is null or p_minutos_estancado < 1 then
        perform app.raise_error('BM422', 'p_minutos_estancado debe ser >= 1');
    end if;

    return query
        select d.id, d.building_id, d.status, d.updated_at
        from app.documents d
        join app.buildings b on b.id = d.building_id and b.deleted_at is null
        where d.status = 'pendiente'
           or (d.status = 'procesando' and d.updated_at < now() - make_interval(mins => p_minutos_estancado))
        order by d.created_at
        limit p_limit;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_ingesta_chunks_eliminar_por_documento: limpia chunks previos (reproceso
-- o reintento tras un fallo parcial). Idempotente.
-- -----------------------------------------------------------------------------
create or replace function public.sp_ingesta_chunks_eliminar_por_documento(p_document_id uuid)
returns table (document_id uuid, eliminados integer)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_count integer;
begin
    if not exists (select 1 from app.documents d where d.id = p_document_id) then
        perform app.raise_error('BM404', 'Documento no encontrado');
    end if;

    delete from app.document_chunks c where c.document_id = p_document_id;
    get diagnostics v_count = row_count;

    return query select p_document_id, v_count;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_ingesta_chunks_insertar_lote: inserta un lote de chunks con embeddings.
-- p_chunks: array JSON de objetos
--   { "chunk_index": int, "content": text, "embedding": [float x 1024],
--     "page_number": int|null, "page_end": int|null, "token_count": int|null,
--     "metadata": object|null }
-- Solo admite inserción mientras el documento está 'procesando'.
-- building_id se toma del documento (nunca del cliente) => aislamiento.
-- -----------------------------------------------------------------------------
create or replace function public.sp_ingesta_chunks_insertar_lote(
    p_document_id     uuid,
    p_embedding_model text,
    p_chunks          jsonb
)
returns table (document_id uuid, insertados integer, total_chunks bigint)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_building  uuid;
    v_status    app.document_status;
    v_invalidos integer;
    v_count     integer;
    v_dim       integer := app.fn_embedding_dim();
begin
    select d.building_id, d.status into v_building, v_status
    from app.documents d where d.id = p_document_id;
    if v_building is null then
        perform app.raise_error('BM404', 'Documento no encontrado');
    end if;
    if v_status <> 'procesando' then
        perform app.raise_error('BM409', format('El documento está en estado %s; se esperaba procesando', v_status));
    end if;

    perform app.fn_validar_texto(p_embedding_model, 'embedding_model', 1, 200);

    if p_chunks is null or jsonb_typeof(p_chunks) <> 'array'
       or jsonb_array_length(p_chunks) not between 1 and 200 then
        perform app.raise_error('BM422', 'p_chunks debe ser un array JSON de entre 1 y 200 elementos');
    end if;

    select count(*) into v_invalidos
    from jsonb_array_elements(p_chunks) e
    where jsonb_typeof(e) <> 'object'
       or coalesce(jsonb_typeof(e -> 'content'), '') <> 'string'
       or length(btrim(e ->> 'content')) = 0
       or coalesce(jsonb_typeof(e -> 'chunk_index'), '') <> 'number'
       or (case when jsonb_typeof(e -> 'chunk_index') = 'number' then (e ->> 'chunk_index')::numeric < 0 else true end)
       or (case when jsonb_typeof(e -> 'embedding') = 'array'
                then jsonb_array_length(e -> 'embedding') <> v_dim else true end)
       or (e ? 'page_number' and jsonb_typeof(e -> 'page_number') not in ('number', 'null'))
       or (e ? 'page_end'    and jsonb_typeof(e -> 'page_end')    not in ('number', 'null'))
       or (e ? 'metadata'    and jsonb_typeof(e -> 'metadata')    not in ('object', 'null'));
    if v_invalidos > 0 then
        perform app.raise_error('BM422',
            format('%s chunk(s) inválidos: se requiere content no vacío, chunk_index >= 0 y embedding de %s dimensiones',
                   v_invalidos, v_dim));
    end if;

    begin
        insert into app.document_chunks (
            document_id, building_id, chunk_index, page_number, page_end, content,
            token_count, metadata, embedding, embedding_model)
        select p_document_id,
               v_building,
               (e ->> 'chunk_index')::integer,
               (e ->> 'page_number')::integer,
               (e ->> 'page_end')::integer,
               e ->> 'content',
               (e ->> 'token_count')::integer,
               coalesce(nullif(e -> 'metadata', 'null'::jsonb), '{}'::jsonb),
               (e -> 'embedding')::text::extensions.vector(1024),
               btrim(p_embedding_model)
        from jsonb_array_elements(p_chunks) e;
        get diagnostics v_count = row_count;
    exception
        when unique_violation then
            perform app.raise_error('BM409', 'chunk_index duplicado para el documento');
        when check_violation then
            perform app.raise_error('BM422', 'Un chunk viola las restricciones (página o contenido)');
    end;

    return query
        select p_document_id, v_count,
               (select count(*) from app.document_chunks c where c.document_id = p_document_id);
end;
$$;
