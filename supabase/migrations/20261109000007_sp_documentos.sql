-- =============================================================================
-- Building Manager AI — Migración 0007
-- Stored procedures: documentos (operaciones de usuario, SECURITY INVOKER)
-- =============================================================================
-- Política de borrado: FÍSICA. sp_document_eliminar borra la fila (y en
-- cascada sus chunks) y devuelve storage_path para que el backend elimine el
-- archivo de Storage. Motivo: un documento eliminado no debe poder seguir
-- alimentando respuestas del RAG, y no hay requisito de auditoría en el MVP.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Helper interno: proyección estándar de documentos visibles (RLS aplica).
-- -----------------------------------------------------------------------------
create or replace function app.fn_documents_visibles(
    p_building_id uuid default null,
    p_document_id uuid default null,
    p_status      app.document_status default null,
    p_categoria   app.document_category default null
)
returns table (
    id                uuid,
    building_id       uuid,
    building_nombre   text,
    file_name         text,
    file_type         app.file_type,
    mime_type         text,
    size_bytes        bigint,
    storage_path      text,
    categoria         app.document_category,
    titulo            text,
    fecha_documento   date,
    status            app.document_status,
    error_message     text,
    page_count        integer,
    chunk_count       integer,
    uploaded_by       uuid,
    uploaded_by_email text,
    processed_at      timestamptz,
    created_at        timestamptz,
    updated_at        timestamptz
)
language sql
stable
set search_path = ''
as $$
    select d.id, d.building_id, b.nombre, d.file_name, d.file_type, d.mime_type, d.size_bytes,
           d.storage_path, d.categoria, d.titulo, d.fecha_documento, d.status, d.error_message,
           d.page_count, d.chunk_count, d.uploaded_by, u.email, d.processed_at, d.created_at, d.updated_at
    from app.documents d
    join app.buildings b on b.id = d.building_id
    left join app.users u on u.id = d.uploaded_by
    where b.deleted_at is null
      and (p_building_id is null or d.building_id = p_building_id)
      and (p_document_id is null or d.id = p_document_id)
      and (p_status      is null or d.status = p_status)
      and (p_categoria   is null or d.categoria = p_categoria)
    order by d.created_at desc;
$$;
revoke all on function app.fn_documents_visibles(uuid, uuid, app.document_status, app.document_category) from public, anon;
grant execute on function app.fn_documents_visibles(uuid, uuid, app.document_status, app.document_category) to authenticated;

-- -----------------------------------------------------------------------------
-- Helper interno: building_id de un documento visible, o BM404.
-- -----------------------------------------------------------------------------
create or replace function app.fn_building_de_documento(p_document_id uuid)
returns uuid
language plpgsql
stable
set search_path = ''
as $$
declare
    v_building uuid;
begin
    perform app.fn_usuario_actual();
    select d.building_id into v_building
    from app.documents d
    join app.buildings b on b.id = d.building_id and b.deleted_at is null
    where d.id = p_document_id;           -- RLS: solo documentos de mis edificios
    if v_building is null then
        perform app.raise_error('BM404', 'Documento no encontrado');
    end if;
    return v_building;
end;
$$;
revoke all on function app.fn_building_de_documento(uuid) from public, anon;
grant execute on function app.fn_building_de_documento(uuid) to authenticated;

-- -----------------------------------------------------------------------------
-- sp_document_crear: registra un documento (status 'pendiente') ANTES de subir
-- el archivo a Storage. Calcula storage_path. Roles: administrador, colaborador.
-- -----------------------------------------------------------------------------
create or replace function public.sp_document_crear(
    p_building_id     uuid,
    p_file_name       text,
    p_file_type       app.file_type,
    p_mime_type       text,
    p_size_bytes      bigint,
    p_sha256          text,
    p_categoria       app.document_category default 'otro',
    p_titulo          text default null,
    p_fecha_documento date default null
)
returns table (
    id uuid, building_id uuid, building_nombre text, file_name text, file_type app.file_type,
    mime_type text, size_bytes bigint, storage_path text, categoria app.document_category,
    titulo text, fecha_documento date, status app.document_status, error_message text,
    page_count integer, chunk_count integer, uploaded_by uuid, uploaded_by_email text,
    processed_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_uid       uuid := app.fn_usuario_actual();
    v_id        uuid := gen_random_uuid();
    v_file_name text;
    v_sha       text := lower(btrim(p_sha256));
    v_existente uuid;
begin
    perform app.fn_exigir_rol(p_building_id, array['administrador', 'colaborador']::app.building_role[]);

    v_file_name := app.fn_validar_texto(p_file_name, 'file_name', 1, 255);
    if v_file_name ~ '[/\\]' or v_file_name ~ '[[:cntrl:]]' then
        perform app.raise_error('BM422', 'El nombre de archivo contiene caracteres no permitidos');
    end if;

    if p_file_type is null then
        perform app.raise_error('BM422', 'p_file_type es obligatorio');
    end if;
    if (p_file_type = 'pdf'  and p_mime_type <> 'application/pdf')
    or (p_file_type = 'docx' and p_mime_type <> 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') then
        perform app.raise_error('BM422', 'El tipo MIME no coincide con el tipo de archivo');
    end if;

    if p_size_bytes is null or p_size_bytes <= 0 or p_size_bytes > 20 * 1024 * 1024 then
        perform app.raise_error('BM422', 'El tamaño del archivo debe estar entre 1 byte y 20 MB');
    end if;

    if v_sha is null or v_sha !~ '^[0-9a-f]{64}$' then
        perform app.raise_error('BM422', 'p_sha256 debe ser un hash SHA-256 hexadecimal');
    end if;

    if p_fecha_documento is not null and p_fecha_documento > current_date then
        perform app.raise_error('BM422', 'La fecha del documento no puede ser futura');
    end if;

    if p_titulo is not null and length(p_titulo) > 255 then
        perform app.raise_error('BM422', 'El título no puede superar 255 caracteres');
    end if;

    select d.id into v_existente
    from app.documents d
    where d.building_id = p_building_id and d.sha256 = v_sha;
    if v_existente is not null then
        perform app.raise_error('BM409', 'El documento ya fue cargado en este edificio', v_existente::text);
    end if;

    insert into app.documents (
        id, building_id, uploaded_by, file_name, file_type, mime_type, size_bytes, sha256,
        storage_path, categoria, titulo, fecha_documento, status)
    values (
        v_id, p_building_id, v_uid, v_file_name, p_file_type, p_mime_type, p_size_bytes, v_sha,
        p_building_id::text || '/' || v_id::text || '.' || p_file_type::text,
        coalesce(p_categoria, 'otro'), nullif(btrim(p_titulo), ''), p_fecha_documento, 'pendiente');

    return query select * from app.fn_documents_visibles(null, v_id, null, null);
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_document_listar_por_edificio: listado con filtros opcionales. Cualquier rol.
-- -----------------------------------------------------------------------------
create or replace function public.sp_document_listar_por_edificio(
    p_building_id uuid,
    p_status      app.document_status   default null,
    p_categoria   app.document_category default null
)
returns table (
    id uuid, building_id uuid, building_nombre text, file_name text, file_type app.file_type,
    mime_type text, size_bytes bigint, storage_path text, categoria app.document_category,
    titulo text, fecha_documento date, status app.document_status, error_message text,
    page_count integer, chunk_count integer, uploaded_by uuid, uploaded_by_email text,
    processed_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    if p_building_id is null or not app.fn_es_miembro(p_building_id) then
        perform app.raise_error('BM404', 'Edificio no encontrado');
    end if;
    return query select * from app.fn_documents_visibles(p_building_id, null, p_status, p_categoria);
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_document_obtener_por_id
-- -----------------------------------------------------------------------------
create or replace function public.sp_document_obtener_por_id(p_document_id uuid)
returns table (
    id uuid, building_id uuid, building_nombre text, file_name text, file_type app.file_type,
    mime_type text, size_bytes bigint, storage_path text, categoria app.document_category,
    titulo text, fecha_documento date, status app.document_status, error_message text,
    page_count integer, chunk_count integer, uploaded_by uuid, uploaded_by_email text,
    processed_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    return query select * from app.fn_documents_visibles(null, p_document_id, null, null);
    if not found then
        perform app.raise_error('BM404', 'Documento no encontrado');
    end if;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_document_actualizar_metadatos: categoría, título y fecha (semántica PUT).
-- Roles: administrador, colaborador. No requiere reprocesar: la búsqueda toma
-- estos metadatos de app.documents en tiempo de consulta.
-- -----------------------------------------------------------------------------
create or replace function public.sp_document_actualizar_metadatos(
    p_document_id     uuid,
    p_categoria       app.document_category,
    p_titulo          text default null,
    p_fecha_documento date default null
)
returns table (
    id uuid, building_id uuid, building_nombre text, file_name text, file_type app.file_type,
    mime_type text, size_bytes bigint, storage_path text, categoria app.document_category,
    titulo text, fecha_documento date, status app.document_status, error_message text,
    page_count integer, chunk_count integer, uploaded_by uuid, uploaded_by_email text,
    processed_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_building uuid := app.fn_building_de_documento(p_document_id);
begin
    perform app.fn_exigir_rol(v_building, array['administrador', 'colaborador']::app.building_role[]);

    if p_categoria is null then
        perform app.raise_error('BM422', 'p_categoria es obligatoria');
    end if;
    if p_titulo is not null and length(p_titulo) > 255 then
        perform app.raise_error('BM422', 'El título no puede superar 255 caracteres');
    end if;
    if p_fecha_documento is not null and p_fecha_documento > current_date then
        perform app.raise_error('BM422', 'La fecha del documento no puede ser futura');
    end if;

    update app.documents d
       set categoria       = p_categoria,
           titulo          = nullif(btrim(p_titulo), ''),
           fecha_documento = p_fecha_documento
     where d.id = p_document_id;

    return query select * from app.fn_documents_visibles(null, p_document_id, null, null);
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_document_eliminar: borrado físico (chunks en cascada). Devuelve
-- storage_path para que el backend borre el objeto en Storage.
-- Roles: administrador, colaborador.
-- -----------------------------------------------------------------------------
create or replace function public.sp_document_eliminar(p_document_id uuid)
returns table (id uuid, building_id uuid, storage_path text, eliminado boolean)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_building uuid := app.fn_building_de_documento(p_document_id);
    v_path     text;
begin
    perform app.fn_exigir_rol(v_building, array['administrador', 'colaborador']::app.building_role[]);

    delete from app.documents d
    where d.id = p_document_id
    returning d.storage_path into v_path;

    if v_path is null then
        perform app.raise_error('BM404', 'Documento no encontrado');
    end if;

    return query select p_document_id, v_building, v_path, true;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_document_reprocesar: vuelve a 'pendiente' un documento procesado o con
-- error para que el worker lo reprocese. Roles: administrador, colaborador.
-- -----------------------------------------------------------------------------
create or replace function public.sp_document_reprocesar(p_document_id uuid)
returns table (
    id uuid, building_id uuid, building_nombre text, file_name text, file_type app.file_type,
    mime_type text, size_bytes bigint, storage_path text, categoria app.document_category,
    titulo text, fecha_documento date, status app.document_status, error_message text,
    page_count integer, chunk_count integer, uploaded_by uuid, uploaded_by_email text,
    processed_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_building uuid := app.fn_building_de_documento(p_document_id);
    v_status   app.document_status;
begin
    perform app.fn_exigir_rol(v_building, array['administrador', 'colaborador']::app.building_role[]);

    select d.status into v_status from app.documents d where d.id = p_document_id for update;
    if v_status not in ('procesado', 'error') then
        perform app.raise_error('BM409',
            format('No se puede reprocesar un documento en estado %s', v_status));
    end if;

    update app.documents d
       set status = 'pendiente', error_message = null
     where d.id = p_document_id;

    return query select * from app.fn_documents_visibles(null, p_document_id, null, null);
end;
$$;
