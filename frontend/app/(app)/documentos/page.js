"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api-client";
import { useBuildings } from "@/hooks/useBuildings";
import { CATEGORIAS, canWriteDocs, formatBytes, formatDate, hasPendingDocs } from "@/lib/format";
import { BuildingSelect, CategorySelect, Empty, ErrorAlert, Modal, StatusBadge } from "@/components/ui";

const MAX_MB = 20;

function UploadForm({ buildingId, onUploaded }) {
  const [file, setFile] = useState(null);
  const [categoria, setCategoria] = useState("reglamento");
  const [titulo, setTitulo] = useState("");
  const [fecha, setFecha] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  function pick(e) {
    const f = e.target.files[0] || null;
    setError("");
    if (f && f.size > MAX_MB * 1024 * 1024) { setError(`El archivo supera el máximo de ${MAX_MB} MB`); setFile(null); return; }
    if (f && !/\.(pdf|docx)$/i.test(f.name)) { setError("Solo se admiten archivos PDF y DOCX"); setFile(null); return; }
    setFile(f);
  }

  async function submit(e) {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("categoria", categoria);
    if (titulo.trim()) form.append("titulo", titulo.trim());
    if (fecha) form.append("fecha_documento", fecha);
    try {
      await api.upload(`/buildings/${buildingId}/documents`, form);
      setFile(null); setTitulo(""); setFecha("");
      if (inputRef.current) inputRef.current.value = "";
      onUploaded();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Cargar documento</h2>
      <ErrorAlert message={error} />
      <div className="form-grid">
        <div className="field"><label htmlFor="u-file">Archivo (PDF o DOCX, máx. {MAX_MB} MB)</label>
          <input id="u-file" ref={inputRef} type="file" accept=".pdf,.docx" onChange={pick} required /></div>
        <div className="field"><label htmlFor="categoria">Tipo de documento</label>
          <CategorySelect value={categoria} onChange={setCategoria} /></div>
        <div className="field"><label htmlFor="u-titulo">Título (opcional)</label>
          <input id="u-titulo" maxLength={255} value={titulo} onChange={(e) => setTitulo(e.target.value)} /></div>
        <div className="field"><label htmlFor="u-fecha">Fecha del documento (opcional)</label>
          <input id="u-fecha" type="date" max={new Date().toISOString().slice(0, 10)} value={fecha} onChange={(e) => setFecha(e.target.value)} /></div>
      </div>
      <button className="primary" disabled={!file || busy}>{busy ? "Subiendo…" : "Subir"}</button>
    </form>
  );
}

function EditDialog({ doc, onClose, onSaved }) {
  const [categoria, setCategoria] = useState(doc.categoria);
  const [titulo, setTitulo] = useState(doc.titulo || "");
  const [fecha, setFecha] = useState(doc.fecha_documento || "");
  const [error, setError] = useState("");

  async function save(e) {
    e.preventDefault();
    try {
      await api.put(`/documents/${doc.id}`, { categoria, titulo: titulo.trim() || null, fecha_documento: fecha || null });
      onSaved();
    } catch (err) { setError(err.message); }
  }
  return (
    <form onSubmit={save}>
      <ErrorAlert message={error} />
      <div className="field"><label htmlFor="e-cat">Tipo de documento</label><CategorySelect id="e-cat" value={categoria} onChange={setCategoria} /></div>
      <div className="field"><label htmlFor="e-tit">Título</label><input id="e-tit" maxLength={255} value={titulo} onChange={(e) => setTitulo(e.target.value)} /></div>
      <div className="field"><label htmlFor="e-fec">Fecha del documento</label><input id="e-fec" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} /></div>
      <div className="row"><button className="primary">Guardar</button><button type="button" onClick={onClose}>Cancelar</button></div>
    </form>
  );
}

export default function DocumentsPage() {
  const { buildings, selected, selectedId, setSelectedId, loading, error: bError } = useBuildings();
  const [docs, setDocs] = useState([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    if (!selectedId) return;
    try { setDocs(await api.get(`/buildings/${selectedId}/documents`, { status: filter })); setError(""); }
    catch (e) { setError(e.message); }
  }, [selectedId, filter]);

  useEffect(() => { setDocs([]); load(); }, [load]);

  // sondeo cada 5 s mientras haya documentos en proceso
  useEffect(() => {
    if (!hasPendingDocs(docs)) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [docs, load]);

  async function act(fn) { setError(""); try { await fn(); await load(); } catch (e) { setError(e.message); } }
  const remove = (d) => confirm(`¿Eliminar "${d.file_name}"? Esta acción no se puede deshacer.`) && act(() => api.del(`/documents/${d.id}`));
  const reprocess = (d) => act(() => api.post(`/documents/${d.id}/reprocess`));
  async function download(d) {
    try { const { url } = await api.get(`/documents/${d.id}/download-url`); window.open(url, "_blank", "noopener"); }
    catch (e) { setError(e.message); }
  }

  if (loading) return <p className="muted">Cargando…</p>;
  if (!buildings.length) return <div className="card"><Empty>Primero <Link href="/edificios/nuevo">registra un edificio</Link>.</Empty></div>;
  const writable = canWriteDocs(selected?.rol);

  return (
    <>
      <div className="page-head">
        <div><h1>Documentación</h1><p className="muted">Los documentos procesados alimentan al asistente</p></div>
        <BuildingSelect buildings={buildings} value={selectedId} onChange={setSelectedId} />
      </div>
      <ErrorAlert message={bError || error} />
      <div className="stack">
        {writable
          ? <UploadForm buildingId={selectedId} onUploaded={load} />
          : <div className="notice">Tu rol en este edificio es de solo lectura: puedes consultar documentos pero no cargarlos.</div>}
        <div className="card">
          <div className="row between">
            <h2>Documentos ({docs.length})</h2>
            <div style={{ width: 180 }}>
              <label htmlFor="f-status" className="small">Estado</label>
              <select id="f-status" value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="">Todos</option><option value="pendiente">Pendientes</option><option value="procesando">Procesando</option>
                <option value="procesado">Procesados</option><option value="error">Con error</option>
              </select>
            </div>
          </div>
          {docs.length === 0 ? <Empty>No hay documentos para mostrar.</Empty> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Documento</th><th>Tipo</th><th>Cargado</th><th>Estado</th><th /></tr></thead>
                <tbody>
                  {docs.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <strong>{d.titulo || d.file_name}</strong>
                        <div className="small muted">{d.file_name} · {d.file_type.toUpperCase()} · {formatBytes(d.size_bytes)}
                          {d.page_count ? ` · ${d.page_count} pág.` : ""}{d.chunk_count ? ` · ${d.chunk_count} fragmentos` : ""}</div>
                        {d.fecha_documento && <div className="small muted">Fecha del documento: {formatDate(d.fecha_documento)}</div>}
                      </td>
                      <td>{CATEGORIAS[d.categoria]}</td>
                      <td>{formatDate(d.created_at)}<div className="small muted">{d.uploaded_by_email}</div></td>
                      <td><StatusBadge status={d.status} />{d.error_message && <div className="small" style={{ color: "var(--danger)", maxWidth: 260 }}>{d.error_message}</div>}</td>
                      <td>
                        <div className="row">
                          <button className="small" onClick={() => download(d)}>Descargar</button>
                          {writable && <button className="small" onClick={() => setEditing(d)}>Editar</button>}
                          {writable && (d.status === "error" || d.status === "procesado") && <button className="small" onClick={() => reprocess(d)}>Reprocesar</button>}
                          {writable && <button className="small danger" onClick={() => remove(d)}>Eliminar</button>}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      <Modal open={!!editing} onClose={() => setEditing(null)} title="Editar metadatos">
        {editing && <EditDialog doc={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
      </Modal>
    </>
  );
}
