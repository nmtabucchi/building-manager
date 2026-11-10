"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api-client";
import { ErrorAlert } from "@/components/ui";

function Stat({ label, value, hint }) {
  return (
    <div className="card">
      <div className="stat">{value ?? "—"}</div>
      <div>{label}</div>
      {hint && <div className="small muted">{hint}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/dashboard").then(setData).catch((e) => setError(e.message));
  }, []);

  const enCurso = data ? data.documentos_pendientes + data.documentos_procesando : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Resumen de tus edificios y su documentación</p>
        </div>
      </div>
      <ErrorAlert message={error} />
      <div className="grid cols-4">
        <Stat label="Edificios" value={data?.total_edificios} />
        <Stat label="Documentos" value={data?.total_documentos} hint={data ? `${data.documentos_procesados} procesados` : ""} />
        <Stat label="Pendientes de procesar" value={enCurso} />
        <Stat label="Con error" value={data?.documentos_con_error} />
      </div>

      <h2 style={{ marginTop: 28 }}>Accesos rápidos</h2>
      <div className="grid cols-2">
        <Link className="card" href="/edificios/nuevo"><strong>Registrar un edificio</strong><div className="muted small">Alta de un nuevo consorcio</div></Link>
        <Link className="card" href="/documentos"><strong>Cargar documentación</strong><div className="muted small">Reglamentos, actas, contratos…</div></Link>
        <Link className="card" href="/asistente"><strong>Consultar al asistente</strong><div className="muted small">Preguntas en lenguaje natural con citas</div></Link>
        <Link className="card" href="/edificios"><strong>Ver edificios</strong><div className="muted small">{data ? `${data.total_conversaciones} conversaciones guardadas` : ""}</div></Link>
      </div>
    </>
  );
}
