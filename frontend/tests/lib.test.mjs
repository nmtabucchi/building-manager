import test from "node:test";
import assert from "node:assert/strict";
import { ApiError, buildUrl, parseResponse } from "../lib/api-core.js";
import { formatBytes, formatDate, formatPages, canWriteDocs, isAdmin, hasPendingDocs } from "../lib/format.js";

test("buildUrl omite parámetros vacíos y normaliza la base", () => {
  assert.equal(buildUrl("http://x/api/", "/a", { b: 1, c: "", d: null, e: undefined }), "http://x/api/a?b=1");
  assert.equal(buildUrl("http://x", "/a"), "http://x/a");
});

test("parseResponse devuelve JSON, null en 204 y ApiError con el formato del backend", async () => {
  assert.deepEqual(await parseResponse(new Response(JSON.stringify({ ok: 1 }), { status: 200 })), { ok: 1 });
  assert.equal(await parseResponse(new Response(null, { status: 204 })), null);
  await assert.rejects(
    parseResponse(new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "Edificio no encontrado" } }), { status: 404 })),
    (e) => e instanceof ApiError && e.status === 404 && e.code === "NOT_FOUND" && e.message === "Edificio no encontrado");
  await assert.rejects(parseResponse(new Response("<html>", { status: 502 })), (e) => e.code === "HTTP_ERROR" && e.status === 502);
});

test("formatos", () => {
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(2048), "2.0 KB");
  assert.equal(formatBytes(5 * 1024 * 1024), "5.0 MB");
  assert.equal(formatPages(3, null), "3");
  assert.equal(formatPages(3, 4), "3-4");
  assert.equal(formatPages(null, null), "s/n");
  assert.equal(formatDate(null), "—");
  assert.match(formatDate("2024-05-10"), /2024/);
});

test("permisos de UI reflejan la matriz de roles", () => {
  assert.ok(canWriteDocs("administrador") && canWriteDocs("colaborador") && !canWriteDocs("lector"));
  assert.ok(isAdmin("administrador") && !isAdmin("colaborador"));
  assert.ok(hasPendingDocs([{ status: "procesado" }, { status: "procesando" }]));
  assert.ok(!hasPendingDocs([{ status: "error" }]));
});
