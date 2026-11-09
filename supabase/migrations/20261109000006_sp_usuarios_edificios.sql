-- =============================================================================
-- Building Manager AI — Migración 0006
-- Stored procedures: usuarios, edificios, membresías y dashboard
-- =============================================================================
-- Convenciones de todos los SP:
--   * Nombre sp_<entidad>_<accion>, en esquema public (expuesto vía RPC).
--   * Parámetros p_*, explícitos y tipados.
--   * Devuelven SIEMPRE un conjunto de filas (RETURNS TABLE), aunque sea una:
--     el cliente Python recibe una lista JSON homogénea.
--   * SECURITY INVOKER salvo excepción documentada => RLS se aplica.
--   * #variable_conflict use_column: en caso de colisión entre una columna de
--     salida y una columna de tabla, se interpreta como columna de tabla.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Helper interno: proyección estándar de edificio para el usuario actual.
-- p_building_id null => todos los edificios del usuario.
-- -----------------------------------------------------------------------------
create or replace function app.fn_buildings_del_usuario(p_building_id uuid default null)
returns table (
    id                  uuid,
    nombre              text,
    direccion           text,
    localidad           text,
    provincia           text,
    informacion_general text,
    rol                 app.building_role,
    total_documentos    bigint,
    created_at          timestamptz,
    updated_at          timestamptz
)
language sql
stable
set search_path = ''
as $$
    select b.id, b.nombre, b.direccion, b.localidad, b.provincia, b.informacion_general,
           bu.rol,
           (select count(*) from app.documents d where d.building_id = b.id) as total_documentos,
           b.created_at, b.updated_at
    from app.buildings b
    join app.building_users bu on bu.building_id = b.id and bu.user_id = auth.uid()
    where b.deleted_at is null
      and (p_building_id is null or b.id = p_building_id)
    order by b.nombre;
$$;
revoke all on function app.fn_buildings_del_usuario(uuid) from public, anon;
grant execute on function app.fn_buildings_del_usuario(uuid) to authenticated;

-- -----------------------------------------------------------------------------
-- Helper interno: validar texto obligatorio con longitud.
-- -----------------------------------------------------------------------------
create or replace function app.fn_validar_texto(p_valor text, p_campo text, p_min int, p_max int)
returns text
language plpgsql
volatile
set search_path = ''
as $$
declare
    v text := btrim(p_valor);
begin
    if v is null or length(v) < p_min or length(v) > p_max then
        perform app.raise_error('BM422',
            format('El campo %s es obligatorio y debe tener entre %s y %s caracteres', p_campo, p_min, p_max));
    end if;
    return v;
end;
$$;
revoke all on function app.fn_validar_texto(text, text, int, int) from public, anon;
grant execute on function app.fn_validar_texto(text, text, int, int) to authenticated, service_role;

-- =============================================================================
-- USUARIOS
-- =============================================================================

-- sp_user_obtener_actual: perfil del usuario autenticado.
create or replace function public.sp_user_obtener_actual()
returns table (id uuid, email text, full_name text, created_at timestamptz)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_uid uuid := app.fn_usuario_actual();
begin
    return query
        select u.id, u.email, u.full_name, u.created_at
        from app.users u
        where u.id = v_uid;
    if not found then
        perform app.raise_error('BM404', 'Perfil de usuario no encontrado');
    end if;
end;
$$;

-- =============================================================================
-- EDIFICIOS
-- =============================================================================

-- sp_building_crear: alta de edificio; el creador queda como administrador.
create or replace function public.sp_building_crear(
    p_nombre              text,
    p_direccion           text,
    p_localidad           text,
    p_provincia           text,
    p_informacion_general text default null
)
returns table (
    id uuid, nombre text, direccion text, localidad text, provincia text,
    informacion_general text, rol app.building_role, total_documentos bigint,
    created_at timestamptz, updated_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_uid uuid := app.fn_usuario_actual();
    v_id  uuid;
begin
    if p_informacion_general is not null and length(p_informacion_general) > 5000 then
        perform app.raise_error('BM422', 'La información general no puede superar 5000 caracteres');
    end if;

    insert into app.buildings (nombre, direccion, localidad, provincia, informacion_general, created_by)
    values (
        app.fn_validar_texto(p_nombre,    'nombre',    2, 150),
        app.fn_validar_texto(p_direccion, 'direccion', 3, 250),
        app.fn_validar_texto(p_localidad, 'localidad', 2, 120),
        app.fn_validar_texto(p_provincia, 'provincia', 2, 120),
        nullif(btrim(p_informacion_general), ''),
        v_uid
    )
    returning id into v_id;

    insert into app.building_users (building_id, user_id, rol)
    values (v_id, v_uid, 'administrador');

    return query select * from app.fn_buildings_del_usuario(v_id);
end;
$$;

-- sp_building_actualizar: modificación completa (semántica PUT). Solo administrador.
create or replace function public.sp_building_actualizar(
    p_building_id         uuid,
    p_nombre              text,
    p_direccion           text,
    p_localidad           text,
    p_provincia           text,
    p_informacion_general text default null
)
returns table (
    id uuid, nombre text, direccion text, localidad text, provincia text,
    informacion_general text, rol app.building_role, total_documentos bigint,
    created_at timestamptz, updated_at timestamptz
)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_exigir_rol(p_building_id, array['administrador']::app.building_role[]);

    if p_informacion_general is not null and length(p_informacion_general) > 5000 then
        perform app.raise_error('BM422', 'La información general no puede superar 5000 caracteres');
    end if;

    update app.buildings b
       set nombre              = app.fn_validar_texto(p_nombre,    'nombre',    2, 150),
           direccion           = app.fn_validar_texto(p_direccion, 'direccion', 3, 250),
           localidad           = app.fn_validar_texto(p_localidad, 'localidad', 2, 120),
           provincia           = app.fn_validar_texto(p_provincia, 'provincia', 2, 120),
           informacion_general = nullif(btrim(p_informacion_general), '')
     where b.id = p_building_id
       and b.deleted_at is null;

    return query select * from app.fn_buildings_del_usuario(p_building_id);
end;
$$;

-- sp_building_eliminar: baja lógica. Solo administrador.
-- Los documentos y chunks se conservan (recuperables); dejan de ser visibles
-- porque fn_edificios_usuario() excluye edificios eliminados.
create or replace function public.sp_building_eliminar(p_building_id uuid)
returns table (id uuid, eliminado boolean, deleted_at timestamptz)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_deleted_at timestamptz := now();
begin
    perform app.fn_exigir_rol(p_building_id, array['administrador']::app.building_role[]);

    update app.buildings b
       set deleted_at = v_deleted_at
     where b.id = p_building_id
       and b.deleted_at is null;

    return query select p_building_id, true, v_deleted_at;
end;
$$;

-- sp_building_obtener_por_id: detalle de un edificio del que el usuario es miembro.
create or replace function public.sp_building_obtener_por_id(p_building_id uuid)
returns table (
    id uuid, nombre text, direccion text, localidad text, provincia text,
    informacion_general text, rol app.building_role, total_documentos bigint,
    created_at timestamptz, updated_at timestamptz
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    if p_building_id is null then
        perform app.raise_error('BM422', 'p_building_id es obligatorio');
    end if;

    return query select * from app.fn_buildings_del_usuario(p_building_id);
    if not found then
        perform app.raise_error('BM404', 'Edificio no encontrado');
    end if;
end;
$$;

-- sp_building_listar_por_usuario: edificios del usuario autenticado.
create or replace function public.sp_building_listar_por_usuario()
returns table (
    id uuid, nombre text, direccion text, localidad text, provincia text,
    informacion_general text, rol app.building_role, total_documentos bigint,
    created_at timestamptz, updated_at timestamptz
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    return query select * from app.fn_buildings_del_usuario(null);
end;
$$;

-- =============================================================================
-- MEMBRESÍAS (building_users)
-- =============================================================================

-- sp_building_usuario_listar: miembros de un edificio (cualquier rol puede verlos).
create or replace function public.sp_building_usuario_listar(p_building_id uuid)
returns table (user_id uuid, email text, full_name text, rol app.building_role, created_at timestamptz)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    if not app.fn_es_miembro(p_building_id) then
        perform app.raise_error('BM404', 'Edificio no encontrado');
    end if;

    return query
        select u.id, u.email, u.full_name, bu.rol, bu.created_at
        from app.building_users bu
        join app.users u on u.id = bu.user_id
        where bu.building_id = p_building_id
        order by bu.rol, u.email;
end;
$$;

-- sp_building_usuario_asignar: agrega un usuario registrado (por email) o
-- cambia su rol. Solo administrador.
-- EXCEPCIÓN DOCUMENTADA: SECURITY DEFINER. Motivo: el administrador necesita
-- localizar por email a un usuario que todavía NO comparte edificios con él,
-- y la RLS de app.users se lo ocultaría. Compensación: verificación explícita
-- de rol administrador, search_path vacío y solo devuelve datos del miembro
-- asignado.
create or replace function public.sp_building_usuario_asignar(
    p_building_id uuid,
    p_email       text,
    p_rol         app.building_role
)
returns table (user_id uuid, email text, full_name text, rol app.building_role, created_at timestamptz)
language plpgsql
volatile
security definer
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_target     uuid;
    v_rol_previo app.building_role;
    v_email      text;
begin
    perform app.fn_exigir_rol(p_building_id, array['administrador']::app.building_role[]);

    if p_rol is null then
        perform app.raise_error('BM422', 'p_rol es obligatorio');
    end if;
    v_email := lower(app.fn_validar_texto(p_email, 'email', 3, 320));

    select u.id into v_target
    from app.users u
    where lower(u.email) = v_email;
    if v_target is null then
        perform app.raise_error('BM404', 'No existe un usuario registrado con ese email');
    end if;

    select bu.rol into v_rol_previo
    from app.building_users bu
    where bu.building_id = p_building_id and bu.user_id = v_target;

    -- No permitir que el edificio quede sin administradores.
    if v_rol_previo = 'administrador' and p_rol <> 'administrador' and (
        select count(*) from app.building_users bu
        where bu.building_id = p_building_id and bu.rol = 'administrador') = 1 then
        perform app.raise_error('BM409', 'El edificio debe conservar al menos un administrador');
    end if;

    insert into app.building_users (building_id, user_id, rol)
    values (p_building_id, v_target, p_rol)
    on conflict (building_id, user_id) do update set rol = excluded.rol;

    return query
        select u.id, u.email, u.full_name, bu.rol, bu.created_at
        from app.building_users bu
        join app.users u on u.id = bu.user_id
        where bu.building_id = p_building_id and bu.user_id = v_target;
end;
$$;

-- sp_building_usuario_quitar: elimina la membresía. Solo administrador.
create or replace function public.sp_building_usuario_quitar(p_building_id uuid, p_user_id uuid)
returns table (building_id uuid, user_id uuid, eliminado boolean)
language plpgsql
volatile
set search_path = ''
as $$
#variable_conflict use_column
declare
    v_rol app.building_role;
begin
    perform app.fn_exigir_rol(p_building_id, array['administrador']::app.building_role[]);

    select bu.rol into v_rol
    from app.building_users bu
    where bu.building_id = p_building_id and bu.user_id = p_user_id;
    if v_rol is null then
        perform app.raise_error('BM404', 'El usuario no es miembro del edificio');
    end if;

    if v_rol = 'administrador' and (
        select count(*) from app.building_users bu
        where bu.building_id = p_building_id and bu.rol = 'administrador') = 1 then
        perform app.raise_error('BM409', 'No se puede quitar al único administrador del edificio');
    end if;

    delete from app.building_users bu
    where bu.building_id = p_building_id and bu.user_id = p_user_id;

    return query select p_building_id, p_user_id, true;
end;
$$;

-- =============================================================================
-- DASHBOARD
-- =============================================================================

-- sp_dashboard_resumen: métricas del usuario (RLS limita a sus edificios).
create or replace function public.sp_dashboard_resumen()
returns table (
    total_edificios        bigint,
    total_documentos       bigint,
    documentos_pendientes  bigint,
    documentos_procesando  bigint,
    documentos_procesados  bigint,
    documentos_con_error   bigint,
    total_conversaciones   bigint
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
begin
    perform app.fn_usuario_actual();
    return query
        select
            (select count(*) from app.fn_edificios_usuario()),
            count(d.id),
            count(d.id) filter (where d.status = 'pendiente'),
            count(d.id) filter (where d.status = 'procesando'),
            count(d.id) filter (where d.status = 'procesado'),
            count(d.id) filter (where d.status = 'error'),
            (select count(*) from app.conversations c)
        from app.documents d
        where d.building_id in (select app.fn_edificios_usuario());
end;
$$;
