"use client";
import { useState } from "react";
import { ErrorAlert } from "@/components/ui";

const EMPTY = { nombre: "", direccion: "", localidad: "", provincia: "", informacion_general: "" };

export default function BuildingForm({ initial, submitLabel, onSubmit, onCancel }) {
  const [values, setValues] = useState({ ...EMPTY, ...(initial || {}), informacion_general: initial?.informacion_general || "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (k) => (e) => setValues((v) => ({ ...v, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit({ ...values, informacion_general: values.informacion_general.trim() || null });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <ErrorAlert message={error} />
      <div className="form-grid">
        <div className="field"><label htmlFor="b-nombre">Nombre</label>
          <input id="b-nombre" required minLength={2} maxLength={150} value={values.nombre} onChange={set("nombre")} /></div>
        <div className="field"><label htmlFor="b-dir">Dirección</label>
          <input id="b-dir" required minLength={3} maxLength={250} value={values.direccion} onChange={set("direccion")} /></div>
        <div className="field"><label htmlFor="b-loc">Localidad</label>
          <input id="b-loc" required minLength={2} maxLength={120} value={values.localidad} onChange={set("localidad")} /></div>
        <div className="field"><label htmlFor="b-prov">Provincia</label>
          <input id="b-prov" required minLength={2} maxLength={120} value={values.provincia} onChange={set("provincia")} /></div>
      </div>
      <div className="field"><label htmlFor="b-info">Información general</label>
        <textarea id="b-info" rows={4} maxLength={5000} value={values.informacion_general} onChange={set("informacion_general")} /></div>
      <div className="row">
        <button className="primary" type="submit" disabled={busy}>{busy ? "Guardando…" : submitLabel}</button>
        {onCancel && <button type="button" onClick={onCancel}>Cancelar</button>}
      </div>
    </form>
  );
}
