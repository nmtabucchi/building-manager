-- =============================================================================
-- Building Manager AI — Migración 0002
-- Tablas, claves primarias/foráneas y restricciones
-- =============================================================================

-- -----------------------------------------------------------------------------
-- users: perfil de aplicación, 1:1 con auth.users (Supabase Auth).
-- Se crea automáticamente por trigger al registrarse un usuario (ver 0004).
-- -----------------------------------------------------------------------------
create table app.users (
    id          uuid        primary key references auth.users (id) on delete cascade,
    email       text        not null,
    full_name   text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint users_email_formato_chk check (position('@' in email) > 1)
);
create unique index users_email_uq on app.users (lower(email));
comment on table app.users is 'Perfil de aplicación de cada usuario de Supabase Auth.';

-- -----------------------------------------------------------------------------
-- buildings: edificios / consorcios administrados.
-- Borrado lógico (deleted_at) para no perder historial de conversaciones.
-- -----------------------------------------------------------------------------
create table app.buildings (
    id                   uuid        primary key default gen_random_uuid(),
    nombre               text        not null,
    direccion            text        not null,
    localidad            text        not null,
    provincia            text        not null,
    informacion_general  text,
    created_by           uuid        not null references app.users (id) on delete restrict,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),
    deleted_at           timestamptz,
    constraint buildings_nombre_chk     check (length(btrim(nombre))    between 2 and 150),
    constraint buildings_direccion_chk  check (length(btrim(direccion)) between 3 and 250),
    constraint buildings_localidad_chk  check (length(btrim(localidad)) between 2 and 120),
    constraint buildings_provincia_chk  check (length(btrim(provincia)) between 2 and 120),
    constraint buildings_info_chk       check (informacion_general is null or length(informacion_general) <= 5000)
);
comment on table app.buildings is 'Edificios administrados. Unidad de aislamiento de la información documental.';

-- -----------------------------------------------------------------------------
-- building_users: membresía y rol de cada usuario en cada edificio.
-- -----------------------------------------------------------------------------
create table app.building_users (
    building_id  uuid              not null references app.buildings (id) on delete cascade,
    user_id      uuid              not null references app.users (id)     on delete cascade,
    rol          app.building_role not null default 'lector',
    created_at   timestamptz       not null default now(),
    primary key (building_id, user_id)
);
comment on table app.building_users is 'Relación N:M usuarios-edificios con rol de acceso.';

-- -----------------------------------------------------------------------------
-- documents: archivos cargados y estado de procesamiento.
-- El archivo binario vive en Supabase Storage (bucket privado) en storage_path.
-- -----------------------------------------------------------------------------
create table app.documents (
    id              uuid                  primary key default gen_random_uuid(),
    building_id     uuid                  not null references app.buildings (id) on delete cascade,
    uploaded_by     uuid                  references app.users (id) on delete set null,
    file_name       text                  not null,
    file_type       app.file_type         not null,
    mime_type       text                  not null,
    size_bytes      bigint                not null,
    sha256          text                  not null,
    storage_path    text                  not null,
    categoria       app.document_category not null default 'otro',
    titulo          text,
    fecha_documento date,                 -- p. ej. fecha de la asamblea del acta
    status          app.document_status   not null default 'pendiente',
    error_message   text,
    page_count      integer,
    chunk_count     integer               not null default 0,
    processed_at    timestamptz,
    created_at      timestamptz           not null default now(),
    updated_at      timestamptz           not null default now(),
    -- Necesaria para la FK compuesta desde document_chunks (garantiza que un
    -- chunk nunca quede asociado a un edificio distinto al de su documento).
    constraint documents_id_building_uq unique (id, building_id),
    -- Evita cargar dos veces el mismo archivo en el mismo edificio.
    constraint documents_hash_building_uq unique (building_id, sha256),
    constraint documents_storage_path_uq unique (storage_path),
    constraint documents_file_name_chk  check (length(btrim(file_name)) between 1 and 255),
    constraint documents_size_chk       check (size_bytes > 0 and size_bytes <= 20 * 1024 * 1024),
    constraint documents_sha256_chk     check (sha256 ~ '^[0-9a-f]{64}$'),
    constraint documents_mime_chk       check (mime_type in (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
    constraint documents_page_count_chk check (page_count is null or page_count >= 0),
    constraint documents_chunk_count_chk check (chunk_count >= 0),
    constraint documents_error_chk      check (status <> 'error' or error_message is not null),
    constraint documents_titulo_chk     check (titulo is null or length(titulo) <= 255)
);
comment on table app.documents is 'Documentos cargados por edificio, con metadatos y estado del pipeline.';

-- -----------------------------------------------------------------------------
-- document_chunks: fragmentos de texto + embedding.
-- building_id está desnormalizado a propósito: permite filtrar la búsqueda
-- vectorial por edificio sin JOIN y aplicar RLS directamente.
-- La dimensión 1024 corresponde al modelo de embeddings elegido (ver diseño);
-- cambiar de modelo con otra dimensión requiere una migración y reindexación.
-- -----------------------------------------------------------------------------
create table app.document_chunks (
    id               uuid        primary key default gen_random_uuid(),
    document_id      uuid        not null,
    building_id      uuid        not null,
    chunk_index      integer     not null,
    page_number      integer,          -- página inicial (null en DOCX)
    page_end         integer,          -- página final si el chunk cruza páginas
    content          text        not null,
    token_count      integer,
    metadata         jsonb       not null default '{}'::jsonb,
    embedding        extensions.vector(1024) not null,
    embedding_model  text        not null,
    created_at       timestamptz not null default now(),
    constraint document_chunks_document_fk
        foreign key (document_id, building_id)
        references app.documents (id, building_id) on delete cascade,
    constraint document_chunks_doc_index_uq unique (document_id, chunk_index),
    constraint document_chunks_index_chk   check (chunk_index >= 0),
    constraint document_chunks_page_chk    check (page_number is null or page_number >= 1),
    constraint document_chunks_page_end_chk check (page_end is null or (page_number is not null and page_end >= page_number)),
    constraint document_chunks_content_chk check (length(btrim(content)) > 0),
    constraint document_chunks_metadata_chk check (jsonb_typeof(metadata) = 'object')
);
comment on table app.document_chunks is 'Fragmentos de documentos con su embedding vectorial (pgvector).';

-- -----------------------------------------------------------------------------
-- conversations: hilos de chat de un usuario sobre un edificio.
-- -----------------------------------------------------------------------------
create table app.conversations (
    id           uuid        primary key default gen_random_uuid(),
    building_id  uuid        not null references app.buildings (id) on delete cascade,
    user_id      uuid        not null references app.users (id)     on delete cascade,
    titulo       text,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    constraint conversations_titulo_chk check (titulo is null or length(titulo) <= 200)
);
comment on table app.conversations is 'Conversaciones con el asistente, privadas de cada usuario y ligadas a un edificio.';

-- -----------------------------------------------------------------------------
-- messages: mensajes de usuario y respuestas del asistente.
--   sources  : citas documentales devueltas por el RAG (array JSON).
--   metadata : modelo, tokens, latencia, cobertura, etc.
-- -----------------------------------------------------------------------------
create table app.messages (
    id               uuid             primary key default gen_random_uuid(),
    conversation_id  uuid             not null references app.conversations (id) on delete cascade,
    role             app.message_role not null,
    content          text             not null,
    sources          jsonb            not null default '[]'::jsonb,
    metadata         jsonb            not null default '{}'::jsonb,
    created_at       timestamptz      not null default now(),
    constraint messages_content_chk  check (length(btrim(content)) between 1 and 20000),
    constraint messages_sources_chk  check (jsonb_typeof(sources) = 'array'),
    constraint messages_metadata_chk check (jsonb_typeof(metadata) = 'object'),
    constraint messages_user_sources_chk check (role = 'assistant' or sources = '[]'::jsonb)
);
comment on table app.messages is 'Historial de mensajes de cada conversación.';
