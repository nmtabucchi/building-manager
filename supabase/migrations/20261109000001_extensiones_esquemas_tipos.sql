-- =============================================================================
-- Building Manager AI — Migración 0001
-- Extensiones, esquemas y tipos enumerados
-- =============================================================================
-- Decisiones:
--   * Las TABLAS viven en el esquema privado `app`, que NO se expone por la API
--     REST de Supabase (PostgREST). Así ningún cliente puede leer/escribir tablas
--     directamente por HTTP: la única puerta de entrada son las funciones `sp_*`
--     del esquema `public` (expuesto), invocadas vía RPC.
--   * pgvector se instala en el esquema `extensions` (convención de Supabase).
--   * Los "stored procedures" se implementan como FUNCIONES PL/pgSQL porque
--     PostgREST/Supabase RPC solo puede invocar funciones (no PROCEDURE/CALL) y
--     las funciones pueden devolver conjuntos de filas tipados.
-- =============================================================================

create extension if not exists vector with schema extensions;
create extension if not exists pgcrypto with schema extensions;

create schema if not exists app;
comment on schema app is 'Tablas de dominio de Building Manager. No expuesto en la API REST.';

-- Rol de un usuario dentro de un edificio.
--   administrador : gestiona el edificio, sus miembros y documentos.
--   colaborador   : carga/edita documentos y consulta al asistente.
--   lector        : solo consulta documentos y al asistente (propietarios/inquilinos).
create type app.building_role as enum ('administrador', 'colaborador', 'lector');

-- Estado del pipeline de procesamiento documental.
create type app.document_status as enum ('pendiente', 'procesando', 'procesado', 'error');

-- Formato de archivo soportado en el MVP.
create type app.file_type as enum ('pdf', 'docx');

-- Categoría funcional del documento (sirve para filtrar y, a futuro, para
-- enrutar a agentes especializados).
create type app.document_category as enum (
    'reglamento',
    'acta_asamblea',
    'acta_reunion',
    'comunicacion',
    'contrato',
    'presupuesto',
    'manual_tecnico',
    'otro'
);

-- Autor de un mensaje de conversación.
create type app.message_role as enum ('user', 'assistant');
