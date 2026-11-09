-- =============================================================================
-- Building Manager AI — Datos iniciales para desarrollo LOCAL
-- (supabase db reset ejecuta este archivo después de las migraciones)
-- =============================================================================
-- NO ejecutar en producción. Crea usuarios de prueba directamente en
-- auth.users (solo válido en el stack local de Supabase) con contraseñas de
-- prueba; el trigger on_auth_user_created crea sus perfiles en app.users.
--
--   admin.demo@example.test   -> administrador de "Edificio Demo Palermo"
--   lector.demo@example.test  -> lector de "Edificio Demo Palermo"
--   otro.demo@example.test    -> administrador de "Edificio Demo Rosario"
--                                (sirve para probar aislamiento)
-- =============================================================================

do $$
declare
    v_users constant jsonb := '[
        {"id": "11111111-1111-1111-1111-111111111111", "email": "admin.demo@example.test",  "name": "Admin Demo"},
        {"id": "22222222-2222-2222-2222-222222222222", "email": "lector.demo@example.test", "name": "Lector Demo"},
        {"id": "33333333-3333-3333-3333-333333333333", "email": "otro.demo@example.test",   "name": "Otro Admin"}
    ]';
    u jsonb;
begin
    for u in select * from jsonb_array_elements(v_users) loop
        insert into auth.users (
            instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
            raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
            confirmation_token, email_change, email_change_token_new, recovery_token)
        values (
            '00000000-0000-0000-0000-000000000000', (u ->> 'id')::uuid, 'authenticated', 'authenticated',
            u ->> 'email', extensions.crypt('Demo-local-123', extensions.gen_salt('bf')), now(),
            '{"provider":"email","providers":["email"]}'::jsonb,
            jsonb_build_object('full_name', u ->> 'name'), now(), now(), '', '', '', '')
        on conflict (id) do nothing;

        insert into auth.identities (id, user_id, provider_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
        values (
            gen_random_uuid(), (u ->> 'id')::uuid, u ->> 'id',
            jsonb_build_object('sub', u ->> 'id', 'email', u ->> 'email', 'email_verified', true),
            'email', now(), now(), now())
        on conflict do nothing;
    end loop;
end;
$$;

insert into app.buildings (id, nombre, direccion, localidad, provincia, informacion_general, created_by)
values
    ('aaaaaaaa-0000-0000-0000-000000000001', 'Edificio Demo Palermo', 'Av. Santa Fe 1234', 'CABA', 'Buenos Aires',
     'Consorcio de 40 unidades funcionales, 2 ascensores, encargado con vivienda.',
     '11111111-1111-1111-1111-111111111111'),
    ('aaaaaaaa-0000-0000-0000-000000000002', 'Edificio Demo Rosario', 'Bv. Oroño 567', 'Rosario', 'Santa Fe',
     'Consorcio de 12 unidades funcionales.',
     '33333333-3333-3333-3333-333333333333')
on conflict (id) do nothing;

insert into app.building_users (building_id, user_id, rol)
values
    ('aaaaaaaa-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'administrador'),
    ('aaaaaaaa-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'lector'),
    ('aaaaaaaa-0000-0000-0000-000000000002', '33333333-3333-3333-3333-333333333333', 'administrador')
on conflict do nothing;

-- Los documentos reales se cargan desde la aplicación (requieren archivo en
-- Storage y embeddings reales). Ver supabase/tests para fixtures sintéticos.
