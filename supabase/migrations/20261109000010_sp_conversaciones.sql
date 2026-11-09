-- =============================================================================
-- Building Manager AI — Migración 0010
-- Stored procedures: conversaciones y mensajes (SECURITY INVOKER)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Helper interno: proyección estándar de conversaciones visibles (RLS:
-- propias y de edificios de los que el usuario sigue siendo miembro).
-- -----------------------------------------------------------------------------
create or replace function app.fn_conversations_visibles(
    p_building_id     uuid default null,
    p_conversation_id uuid default null,
    p_limit           integer default 50,
    p_offset          integer default 0
)
returns table (
    id                 uuid,
    building_id        uuid,
    building_nombre    text,
    titulo             text,
    total_mensajes     bigint,
    ultimo_mensaje_at  timestamptz,
    created_at         timestamptz,
    updated_at         timestamptz
)
language sql
stable
set search_path = ''
as $$
    select c.id, c.building_id, b.nombre, c.titulo,
           (select count(*)        from app.messages m where m.conversation_id = c.id),
           (select max(m.created_at) from app.messages m where m.conversation_id = c.id),
           c.created_at, c.updated_at
    from app.conversations c
    join app.buildings b on b.id = c.building_id
    where (p_building_id     is null or c.building_id = p_building_id)
      and (p_conversation_id is null or c.id = p_conversation_id)
    order by c.updated_at desc
    limit p_limit offset p_offset;
$$;
revoke all on function app.fn_conversations_visibles(uuid, uuid, integer, integer) from public, anon;
grant execute on function app.fn_conversations_visibles(uuid, uuid, integer, integer) to authenticated;

-- -----------------------------------------------------------------------------
-- sp_conversation_crear: nueva conversación del usuario sobre un edificio.
-- Cualquier rol del edificio puede conversar con el asistente.
-- -----------------------------------------------------------------------------
create or replace function public.sp_conversation_crear(
    p_building_id uuid,
    p_titulo      text default null
)
returns table (
    id uuid, building_id uuid, building_nombre text, titulo text, total_mensajes bigint,
    ultimo_mensaje_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_uid uuid := app.fn_usuario_actual();
    v_id  uuid := gen_random_uuid();
begin
    if p_building_id is null or not app.fn_es_miembro(p_building_id) then
        perform app.raise_error('BM404', 'Edificio no encontrado');
    end if;
    if p_titulo is not null and length(p_titulo) > 200 then
        perform app.raise_error('BM422', 'El título no puede superar 200 caracteres');
    end if;

    insert into app.conversations (id, building_id, user_id, titulo)
    values (v_id, p_building_id, v_uid, nullif(btrim(p_titulo), ''));

    return query select * from app.fn_conversations_visibles(null, v_id, 1, 0);
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_conversation_listar: conversaciones del usuario, opcionalmente por edificio.
-- -----------------------------------------------------------------------------
create or replace function public.sp_conversation_listar(
    p_building_id uuid    default null,
    p_limit       integer default 20,
    p_offset      integer default 0
)
returns table (
    id uuid, building_id uuid, building_nombre text, titulo text, total_mensajes bigint,
    ultimo_mensaje_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    if p_building_id is not null and not app.fn_es_miembro(p_building_id) then
        perform app.raise_error('BM404', 'Edificio no encontrado');
    end if;
    if p_limit is null or p_limit not between 1 and 100 then
        perform app.raise_error('BM422', 'p_limit debe estar entre 1 y 100');
    end if;
    if p_offset is null or p_offset < 0 then
        perform app.raise_error('BM422', 'p_offset debe ser >= 0');
    end if;

    return query select * from app.fn_conversations_visibles(p_building_id, null, p_limit, p_offset);
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_conversation_obtener_por_id
-- -----------------------------------------------------------------------------
create or replace function public.sp_conversation_obtener_por_id(p_conversation_id uuid)
returns table (
    id uuid, building_id uuid, building_nombre text, titulo text, total_mensajes bigint,
    ultimo_mensaje_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    return query select * from app.fn_conversations_visibles(null, p_conversation_id, 1, 0);
    if not found then
        perform app.raise_error('BM404', 'Conversación no encontrada');
    end if;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_message_crear: agrega un mensaje a una conversación propia.
--   * role 'user'      : pregunta del usuario (sources debe ser []).
--   * role 'assistant' : respuesta del RAG con sources (citas) y metadata.
-- Si la conversación no tiene título, se toma de la primera pregunta.
-- -----------------------------------------------------------------------------
create or replace function public.sp_message_crear(
    p_conversation_id uuid,
    p_role            app.message_role,
    p_content         text,
    p_sources         jsonb default '[]'::jsonb,
    p_metadata        jsonb default '{}'::jsonb
)
returns table (
    id uuid, conversation_id uuid, role app.message_role, content text,
    sources jsonb, metadata jsonb, created_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_id      uuid := gen_random_uuid();
    v_content text := btrim(p_content);
    v_sources jsonb := coalesce(p_sources, '[]'::jsonb);
begin
    perform app.fn_usuario_actual();

    if not exists (select 1 from app.conversations c where c.id = p_conversation_id) then
        perform app.raise_error('BM404', 'Conversación no encontrada');
    end if;
    if p_role is null then
        perform app.raise_error('BM422', 'p_role es obligatorio');
    end if;
    if v_content is null or length(v_content) not between 1 and 20000 then
        perform app.raise_error('BM422', 'El contenido debe tener entre 1 y 20000 caracteres');
    end if;
    if jsonb_typeof(v_sources) <> 'array' then
        perform app.raise_error('BM422', 'p_sources debe ser un array JSON');
    end if;
    if p_role = 'user' and v_sources <> '[]'::jsonb then
        perform app.raise_error('BM422', 'Un mensaje de usuario no puede tener fuentes');
    end if;
    if exists (select 1 from jsonb_array_elements(v_sources) s where jsonb_typeof(s) <> 'object') then
        perform app.raise_error('BM422', 'Cada fuente debe ser un objeto JSON');
    end if;
    if p_metadata is not null and jsonb_typeof(p_metadata) <> 'object' then
        perform app.raise_error('BM422', 'p_metadata debe ser un objeto JSON');
    end if;

    insert into app.messages (id, conversation_id, role, content, sources, metadata)
    values (v_id, p_conversation_id, p_role, v_content, v_sources, coalesce(p_metadata, '{}'::jsonb));

    -- Actualiza updated_at (trigger) y asigna título si no tenía.
    update app.conversations c
       set titulo = case
                       when c.titulo is null and p_role = 'user'
                       then left(regexp_replace(v_content, '\s+', ' ', 'g'), 80)
                       else c.titulo
                    end
     where c.id = p_conversation_id;

    return query
        select m.id, m.conversation_id, m.role, m.content, m.sources, m.metadata, m.created_at
        from app.messages m where m.id = v_id;
end;
$$;

-- -----------------------------------------------------------------------------
-- sp_message_listar_por_conversacion: últimos p_limit mensajes (opcionalmente
-- anteriores a p_antes_de, para paginar hacia atrás), en orden cronológico.
-- El grafo RAG lo usa con p_limit pequeño para recuperar el contexto reciente.
-- -----------------------------------------------------------------------------
create or replace function public.sp_message_listar_por_conversacion(
    p_conversation_id uuid,
    p_limit           integer     default 50,
    p_antes_de        timestamptz default null
)
returns table (
    id uuid, conversation_id uuid, role app.message_role, content text,
    sources jsonb, metadata jsonb, created_at timestamptz
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    if not exists (select 1 from app.conversations c where c.id = p_conversation_id) then
        perform app.raise_error('BM404', 'Conversación no encontrada');
    end if;
    if p_limit is null or p_limit not between 1 and 200 then
        perform app.raise_error('BM422', 'p_limit debe estar entre 1 y 200');
    end if;

    return query
        select t.id, t.conversation_id, t.role, t.content, t.sources, t.metadata, t.created_at
        from (
            select m.*
            from app.messages m
            where m.conversation_id = p_conversation_id
              and (p_antes_de is null or m.created_at < p_antes_de)
            order by m.created_at desc
            limit p_limit
        ) t
        order by t.created_at asc;
end;
$$;
