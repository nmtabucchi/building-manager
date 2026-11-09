-- =============================================================================
-- Building Manager AI — Migración 0004
-- Funciones auxiliares y triggers
-- =============================================================================
-- Convención de errores (SQLSTATE propios, clase "BM"):
--   BM401  no autenticado (auth.uid() es null)
--   BM403  autenticado y miembro, pero sin el rol requerido
--   BM404  recurso inexistente o no visible para el usuario
--          (no se distingue a propósito, para no revelar la existencia de
--          edificios/documentos ajenos)
--   BM409  conflicto: duplicado o transición de estado inválida
--   BM422  datos de entrada inválidos
-- El backend Python mapea cada código a una excepción de dominio.
-- Todas las funciones fijan search_path = '' y califican cada objeto con su
-- esquema, para evitar secuestro de search_path.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Lanzar un error de negocio con código propio.
-- -----------------------------------------------------------------------------
create or replace function app.raise_error(p_code text, p_message text, p_detail text default null)
returns void
language plpgsql
volatile  -- nunca immutable: el planificador podría pre-evaluarla y lanzar el error
set search_path = ''
as $$
begin
    raise exception using errcode = p_code, message = p_message, detail = coalesce(p_detail, '');
end;
$$;

-- -----------------------------------------------------------------------------
-- Devuelve el usuario autenticado o lanza BM401.
-- -----------------------------------------------------------------------------
create or replace function app.fn_usuario_actual()
returns uuid
language plpgsql
stable
set search_path = ''
as $$
declare
    v_uid uuid := auth.uid();
begin
    if v_uid is null then
        perform app.raise_error('BM401', 'Usuario no autenticado');
    end if;
    return v_uid;
end;
$$;

-- -----------------------------------------------------------------------------
-- Helpers de autorización usados por las políticas RLS y por los SP.
-- SECURITY DEFINER: leen building_users sin quedar sujetos a su propia RLS
-- (evita recursión infinita de políticas). Solo devuelven datos del usuario
-- autenticado, nunca de terceros.
-- -----------------------------------------------------------------------------
create or replace function app.fn_edificios_usuario()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
    select bu.building_id
    from app.building_users bu
    join app.buildings b on b.id = bu.building_id
    where bu.user_id = auth.uid()
      and b.deleted_at is null;
$$;

create or replace function app.fn_es_miembro(p_building_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from app.building_users bu
        join app.buildings b on b.id = bu.building_id
        where bu.building_id = p_building_id
          and bu.user_id = auth.uid()
          and b.deleted_at is null
    );
$$;

create or replace function app.fn_tiene_rol(p_building_id uuid, p_roles app.building_role[])
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1
        from app.building_users bu
        join app.buildings b on b.id = bu.building_id
        where bu.building_id = p_building_id
          and bu.user_id = auth.uid()
          and bu.rol = any (p_roles)
          and b.deleted_at is null
    );
$$;

-- Verifica rol y lanza BM404 (no miembro) o BM403 (rol insuficiente).
create or replace function app.fn_exigir_rol(p_building_id uuid, p_roles app.building_role[])
returns void
language plpgsql
stable
set search_path = ''
as $$
begin
    perform app.fn_usuario_actual();
    if not app.fn_es_miembro(p_building_id) then
        perform app.raise_error('BM404', 'Edificio no encontrado');
    end if;
    if not app.fn_tiene_rol(p_building_id, p_roles) then
        perform app.raise_error('BM403', 'Permisos insuficientes para esta operación en el edificio');
    end if;
end;
$$;

-- -----------------------------------------------------------------------------
-- Trigger genérico: mantener updated_at.
-- -----------------------------------------------------------------------------
create or replace function app.tg_set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create trigger users_updated_at         before update on app.users         for each row execute function app.tg_set_updated_at();
create trigger buildings_updated_at     before update on app.buildings     for each row execute function app.tg_set_updated_at();
create trigger documents_updated_at     before update on app.documents     for each row execute function app.tg_set_updated_at();
create trigger conversations_updated_at before update on app.conversations for each row execute function app.tg_set_updated_at();

-- -----------------------------------------------------------------------------
-- Trigger: crear/actualizar el perfil app.users al registrarse en Supabase Auth.
-- SECURITY DEFINER porque lo dispara el rol interno de Auth.
-- -----------------------------------------------------------------------------
create or replace function app.tg_sync_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into app.users (id, email, full_name)
    values (
        new.id,
        coalesce(new.email, new.id::text || '@sin-email.local'),
        nullif(new.raw_user_meta_data ->> 'full_name', '')
    )
    on conflict (id) do update
        set email = excluded.email,
            full_name = coalesce(excluded.full_name, app.users.full_name);
    return new;
end;
$$;

create trigger on_auth_user_created
    after insert or update of email, raw_user_meta_data on auth.users
    for each row execute function app.tg_sync_auth_user();

-- Las funciones auxiliares no deben ser invocables por clientes anónimos.
revoke all on all functions in schema app from public, anon;
grant execute on function
    app.raise_error(text, text, text),
    app.fn_usuario_actual(),
    app.fn_edificios_usuario(),
    app.fn_es_miembro(uuid),
    app.fn_tiene_rol(uuid, app.building_role[]),
    app.fn_exigir_rol(uuid, app.building_role[])
to authenticated, service_role;
