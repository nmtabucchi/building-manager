-- =============================================================================
-- Building Manager AI — Migración 0005
-- Row Level Security, privilegios sobre tablas y bucket de Storage
-- =============================================================================
-- Modelo de ejecución:
--   * Los SP de usuario son SECURITY INVOKER y se invocan vía Supabase RPC con
--     el JWT del usuario => se ejecutan con el rol `authenticated` y auth.uid()
--     = usuario. Las políticas RLS de abajo se aplican DENTRO de los SP.
--     Los SP además validan permisos explícitamente (defensa en profundidad).
--   * Los SP de ingesta (sp_ingesta_*) solo son ejecutables por `service_role`
--     (worker del backend), que tiene BYPASSRLS. Compensan con validaciones
--     propias y EXECUTE restringido.
--   * `anon` no tiene acceso a nada.
--   * El esquema `app` no está expuesto por la API REST: aunque `authenticated`
--     tenga privilegios sobre tablas (necesarios para SECURITY INVOKER), no
--     puede alcanzarlas por HTTP; solo a través de los SP de `public`.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Helper adicional para el alta inicial de un edificio (sin miembros aún).
-- -----------------------------------------------------------------------------
create or replace function app.fn_edificio_sin_miembros(p_building_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select not exists (select 1 from app.building_users bu where bu.building_id = p_building_id);
$$;
revoke all on function app.fn_edificio_sin_miembros(uuid) from public, anon;
grant execute on function app.fn_edificio_sin_miembros(uuid) to authenticated, service_role;

-- -----------------------------------------------------------------------------
-- Privilegios
-- -----------------------------------------------------------------------------
revoke all on schema app from public, anon;
grant usage on schema app to authenticated, service_role;

revoke all on all tables in schema app from public, anon, authenticated;

grant select, update                 on app.users           to authenticated;
grant select, insert, update         on app.buildings       to authenticated;
grant select, insert, update, delete on app.building_users  to authenticated;
grant select, insert, update, delete on app.documents       to authenticated;
grant select                         on app.document_chunks to authenticated;  -- escritura solo service_role
grant select, insert, update, delete on app.conversations   to authenticated;
grant select, insert                 on app.messages        to authenticated;

grant all on all tables in schema app to service_role;

-- -----------------------------------------------------------------------------
-- Activar RLS en todas las tablas
-- -----------------------------------------------------------------------------
alter table app.users           enable row level security;
alter table app.buildings       enable row level security;
alter table app.building_users  enable row level security;
alter table app.documents       enable row level security;
alter table app.document_chunks enable row level security;
alter table app.conversations   enable row level security;
alter table app.messages        enable row level security;

-- -----------------------------------------------------------------------------
-- users: cada uno ve su perfil y el de quienes comparten algún edificio.
-- -----------------------------------------------------------------------------
create policy users_select on app.users
    for select to authenticated
    using (
        id = (select auth.uid())
        or exists (
            select 1 from app.building_users bu
            where bu.user_id = users.id
              and bu.building_id in (select app.fn_edificios_usuario())
        )
    );

create policy users_update_propio on app.users
    for update to authenticated
    using (id = (select auth.uid()))
    with check (id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- buildings
-- -----------------------------------------------------------------------------
create policy buildings_select on app.buildings
    for select to authenticated
    using (
        id in (select app.fn_edificios_usuario())
        -- el creador puede ver la fila recién insertada antes de ser miembro
        or (created_by = (select auth.uid()) and deleted_at is null)
    );

create policy buildings_insert on app.buildings
    for insert to authenticated
    with check (created_by = (select auth.uid()) and deleted_at is null);

create policy buildings_update_admin on app.buildings
    for update to authenticated
    using (app.fn_tiene_rol(id, array['administrador']::app.building_role[]))
    -- USING ya restringe QUÉ filas puede modificar un administrador. El WITH CHECK
    -- es permisivo para que el borrado lógico (deleted_at = now()) no falle al
    -- dejar de cumplir la condición "edificio activo"; los SP nunca modifican
    -- id ni created_by.
    with check (true);
-- Sin política DELETE: los edificios se eliminan lógicamente (deleted_at).

-- -----------------------------------------------------------------------------
-- building_users
-- -----------------------------------------------------------------------------
create policy building_users_select on app.building_users
    for select to authenticated
    using (building_id in (select app.fn_edificios_usuario()));

create policy building_users_insert on app.building_users
    for insert to authenticated
    with check (
        app.fn_tiene_rol(building_id, array['administrador']::app.building_role[])
        or (
            -- alta inicial: el creador se autoasigna administrador
            user_id = (select auth.uid())
            and rol = 'administrador'
            and app.fn_edificio_sin_miembros(building_id)
            and exists (
                select 1 from app.buildings b
                where b.id = building_id and b.created_by = (select auth.uid())
            )
        )
    );

create policy building_users_update_admin on app.building_users
    for update to authenticated
    using (app.fn_tiene_rol(building_id, array['administrador']::app.building_role[]))
    with check (app.fn_tiene_rol(building_id, array['administrador']::app.building_role[]));

create policy building_users_delete_admin on app.building_users
    for delete to authenticated
    using (app.fn_tiene_rol(building_id, array['administrador']::app.building_role[]));

-- -----------------------------------------------------------------------------
-- documents
-- -----------------------------------------------------------------------------
create policy documents_select on app.documents
    for select to authenticated
    using (building_id in (select app.fn_edificios_usuario()));

create policy documents_insert on app.documents
    for insert to authenticated
    with check (
        uploaded_by = (select auth.uid())
        and app.fn_tiene_rol(building_id, array['administrador', 'colaborador']::app.building_role[])
    );

create policy documents_update on app.documents
    for update to authenticated
    using (app.fn_tiene_rol(building_id, array['administrador', 'colaborador']::app.building_role[]))
    with check (app.fn_tiene_rol(building_id, array['administrador', 'colaborador']::app.building_role[]));

create policy documents_delete on app.documents
    for delete to authenticated
    using (app.fn_tiene_rol(building_id, array['administrador', 'colaborador']::app.building_role[]));

-- -----------------------------------------------------------------------------
-- document_chunks: lectura por miembros; escritura solo service_role.
-- -----------------------------------------------------------------------------
create policy document_chunks_select on app.document_chunks
    for select to authenticated
    using (building_id in (select app.fn_edificios_usuario()));

-- -----------------------------------------------------------------------------
-- conversations: privadas del usuario y solo mientras sea miembro del edificio.
-- -----------------------------------------------------------------------------
create policy conversations_owner on app.conversations
    for all to authenticated
    using (
        user_id = (select auth.uid())
        and building_id in (select app.fn_edificios_usuario())
    )
    with check (
        user_id = (select auth.uid())
        and building_id in (select app.fn_edificios_usuario())
    );

-- -----------------------------------------------------------------------------
-- messages: heredan la visibilidad de su conversación.
-- -----------------------------------------------------------------------------
create policy messages_select on app.messages
    for select to authenticated
    using (exists (select 1 from app.conversations c where c.id = messages.conversation_id));

create policy messages_insert on app.messages
    for insert to authenticated
    with check (exists (select 1 from app.conversations c where c.id = messages.conversation_id));

-- -----------------------------------------------------------------------------
-- Supabase Storage: bucket privado. Sin políticas para `authenticated` en
-- storage.objects => ningún cliente puede leer/escribir archivos directamente.
-- El backend opera Storage con service_role DESPUÉS de autorizar vía SP, y
-- entrega al frontend URLs firmadas de corta duración.
-- -----------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'building-documents',
    'building-documents',
    false,
    20971520,
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]
)
on conflict (id) do nothing;
