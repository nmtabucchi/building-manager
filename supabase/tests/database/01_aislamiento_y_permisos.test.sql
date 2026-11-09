-- =============================================================================
-- Building Manager AI — Pruebas pgTAP de aislamiento y permisos
-- Ejecutar con:  supabase test db
-- Todo corre dentro de una transacción que se revierte al final.
-- =============================================================================
begin;
create extension if not exists pgtap with schema extensions;
set search_path = public, extensions;

select plan(12);

-- -----------------------------------------------------------------------------
-- Fixtures (como postgres): usuario A (admin edif. A), L (lector edif. A),
-- B (admin edif. B). Un documento procesado con 2 chunks en cada edificio.
-- -----------------------------------------------------------------------------
insert into auth.users (instance_id, id, aud, role, email, raw_user_meta_data, created_at, updated_at)
values
    ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-0000-0000-00000000000a', 'authenticated', 'authenticated', 'a@test.test', '{}', now(), now()),
    ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-0000-0000-00000000000b', 'authenticated', 'authenticated', 'b@test.test', '{}', now(), now()),
    ('00000000-0000-0000-0000-000000000000', 'a0000000-0000-0000-0000-00000000000c', 'authenticated', 'authenticated', 'l@test.test', '{}', now(), now());

insert into app.buildings (id, nombre, direccion, localidad, provincia, created_by) values
    ('b0000000-0000-0000-0000-00000000000a', 'Edificio A', 'Calle A 1', 'CABA', 'Buenos Aires', 'a0000000-0000-0000-0000-00000000000a'),
    ('b0000000-0000-0000-0000-00000000000b', 'Edificio B', 'Calle B 2', 'CABA', 'Buenos Aires', 'a0000000-0000-0000-0000-00000000000b');

insert into app.building_users (building_id, user_id, rol) values
    ('b0000000-0000-0000-0000-00000000000a', 'a0000000-0000-0000-0000-00000000000a', 'administrador'),
    ('b0000000-0000-0000-0000-00000000000a', 'a0000000-0000-0000-0000-00000000000c', 'lector'),
    ('b0000000-0000-0000-0000-00000000000b', 'a0000000-0000-0000-0000-00000000000b', 'administrador');

insert into app.documents (id, building_id, uploaded_by, file_name, file_type, mime_type, size_bytes, sha256, storage_path, categoria, status, chunk_count)
values
    ('d0000000-0000-0000-0000-00000000000a', 'b0000000-0000-0000-0000-00000000000a', 'a0000000-0000-0000-0000-00000000000a',
     'reglamento_a.pdf', 'pdf', 'application/pdf', 1000, encode(extensions.digest('a', 'sha256'), 'hex'),
     'b0000000-0000-0000-0000-00000000000a/d0000000-0000-0000-0000-00000000000a.pdf', 'reglamento', 'procesado', 2),
    ('d0000000-0000-0000-0000-00000000000b', 'b0000000-0000-0000-0000-00000000000b', 'a0000000-0000-0000-0000-00000000000b',
     'reglamento_b.pdf', 'pdf', 'application/pdf', 1000, encode(extensions.digest('b', 'sha256'), 'hex'),
     'b0000000-0000-0000-0000-00000000000b/d0000000-0000-0000-0000-00000000000b.pdf', 'reglamento', 'procesado', 2);

insert into app.document_chunks (document_id, building_id, chunk_index, page_number, content, embedding, embedding_model)
select d.id, d.building_id, i, 1, 'Texto de prueba ' || i || ' del documento ' || d.file_name,
       array_fill((0.1 + i * 0.01)::real, array[1024])::extensions.vector(1024), 'test-model'
from app.documents d cross join generate_series(0, 1) i
where d.id in ('d0000000-0000-0000-0000-00000000000a', 'd0000000-0000-0000-0000-00000000000b');

-- -----------------------------------------------------------------------------
-- Como usuario A (administrador del edificio A)
-- -----------------------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"a0000000-0000-0000-0000-00000000000a","role":"authenticated"}', true);

select is(
    (select count(*) from public.sp_building_listar_por_usuario()),
    1::bigint,
    'A solo ve su propio edificio');

select throws_ok(
    $$ select * from public.sp_building_obtener_por_id('b0000000-0000-0000-0000-00000000000b') $$,
    'BM404', null,
    'A no puede obtener el edificio B (no revela existencia)');

select throws_ok(
    $$ select * from public.sp_chunk_buscar_similares(
           'b0000000-0000-0000-0000-00000000000b',
           array_fill(0.1::real, array[1024])::extensions.vector(1024), 5, 0.0, null) $$,
    'BM404', null,
    'A no puede buscar en los documentos del edificio B');

select is(
    (select count(*) from public.sp_chunk_buscar_similares(
        'b0000000-0000-0000-0000-00000000000a',
        array_fill(0.1::real, array[1024])::extensions.vector(1024), 10, 0.0, null)
     where building_id <> 'b0000000-0000-0000-0000-00000000000a'),
    0::bigint,
    'La búsqueda en A nunca devuelve chunks de otro edificio');

select is(
    (select count(*) from public.sp_chunk_buscar_similares(
        'b0000000-0000-0000-0000-00000000000a',
        array_fill(0.1::real, array[1024])::extensions.vector(1024), 10, 0.0, null)),
    2::bigint,
    'La búsqueda en A devuelve los chunks de A');

select is(
    (select count(*) from app.document_chunks where building_id = 'b0000000-0000-0000-0000-00000000000b'),
    0::bigint,
    'RLS: lectura directa de chunks de B devuelve 0 filas');

select throws_ok(
    $$ select * from public.sp_ingesta_chunks_eliminar_por_documento('d0000000-0000-0000-0000-00000000000a') $$,
    '42501', null,
    'authenticated no puede ejecutar SP de ingesta');

select throws_ok(
    $$ select * from public.sp_document_reprocesar('d0000000-0000-0000-0000-00000000000b') $$,
    'BM404', null,
    'A no puede reprocesar un documento de B');

-- -----------------------------------------------------------------------------
-- Como lector L del edificio A
-- -----------------------------------------------------------------------------
select set_config('request.jwt.claims', '{"sub":"a0000000-0000-0000-0000-00000000000c","role":"authenticated"}', true);

select throws_ok(
    $$ select * from public.sp_document_crear(
           'b0000000-0000-0000-0000-00000000000a', 'acta.pdf', 'pdf', 'application/pdf', 100,
           repeat('a', 64), 'acta_asamblea', null, null) $$,
    'BM403', null,
    'Un lector no puede cargar documentos');

select throws_ok(
    $$ select * from public.sp_building_eliminar('b0000000-0000-0000-0000-00000000000a') $$,
    'BM403', null,
    'Un lector no puede eliminar el edificio');

select lives_ok(
    $$ select * from public.sp_conversation_crear('b0000000-0000-0000-0000-00000000000a', 'Consulta de prueba') $$,
    'Un lector puede crear conversaciones');

-- -----------------------------------------------------------------------------
-- Como anon
-- -----------------------------------------------------------------------------
reset role;
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);

select throws_ok(
    $$ select * from public.sp_building_listar_por_usuario() $$,
    '42501', null,
    'anon no puede ejecutar SP');

select * from finish();
rollback;
