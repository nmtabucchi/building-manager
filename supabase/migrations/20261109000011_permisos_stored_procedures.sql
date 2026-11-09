-- =============================================================================
-- Building Manager AI — Migración 0011
-- Privilegios mínimos de ejecución de stored procedures
-- =============================================================================
-- PostgreSQL concede EXECUTE a PUBLIC por defecto, y Supabase además configura
-- default privileges que conceden EXECUTE a anon/authenticated/service_role en
-- el esquema public. Por eso primero se revoca TODO y luego se concede
-- explícitamente lo mínimo a cada rol.
-- =============================================================================

-- 1) Revocar EXECUTE de todos los sp_* de public a todos los roles de API.
do $$
declare
    r record;
begin
    for r in
        select p.oid::regprocedure as firma
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname like 'sp\_%'
    loop
        execute format('revoke all on function %s from public, anon, authenticated, service_role', r.firma);
    end loop;
end;
$$;

-- 2) SP de usuario final: rol `authenticated` (invocados con el JWT del usuario).
grant execute on function
    public.sp_user_obtener_actual(),
    public.sp_building_crear(text, text, text, text, text),
    public.sp_building_actualizar(uuid, text, text, text, text, text),
    public.sp_building_eliminar(uuid),
    public.sp_building_obtener_por_id(uuid),
    public.sp_building_listar_por_usuario(),
    public.sp_building_usuario_listar(uuid),
    public.sp_building_usuario_asignar(uuid, text, app.building_role),
    public.sp_building_usuario_quitar(uuid, uuid),
    public.sp_dashboard_resumen(),
    public.sp_document_crear(uuid, text, app.file_type, text, bigint, text, app.document_category, text, date),
    public.sp_document_listar_por_edificio(uuid, app.document_status, app.document_category),
    public.sp_document_obtener_por_id(uuid),
    public.sp_document_actualizar_metadatos(uuid, app.document_category, text, date),
    public.sp_document_eliminar(uuid),
    public.sp_document_reprocesar(uuid),
    public.sp_chunk_buscar_similares(uuid, extensions.vector, integer, double precision, app.document_category[]),
    public.sp_conversation_crear(uuid, text),
    public.sp_conversation_listar(uuid, integer, integer),
    public.sp_conversation_obtener_por_id(uuid),
    public.sp_message_crear(uuid, app.message_role, text, jsonb, jsonb),
    public.sp_message_listar_por_conversacion(uuid, integer, timestamptz)
to authenticated;

-- 3) SP del worker de ingesta: SOLO service_role.
grant execute on function
    public.sp_ingesta_document_obtener(uuid),
    public.sp_ingesta_document_actualizar_estado(uuid, app.document_status, text, integer, integer),
    public.sp_ingesta_document_listar_pendientes(integer, integer),
    public.sp_ingesta_chunks_eliminar_por_documento(uuid),
    public.sp_ingesta_chunks_insertar_lote(uuid, text, jsonb)
to service_role;

-- 4) Funciones auxiliares del esquema app (no expuesto): sin acceso anónimo.
revoke all on all functions in schema app from public, anon;
grant execute on all functions in schema app to authenticated, service_role;

-- 5) Que PostgREST recargue el esquema y publique las nuevas firmas RPC.
notify pgrst, 'reload schema';
