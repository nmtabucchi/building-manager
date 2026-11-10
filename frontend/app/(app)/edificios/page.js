"use client";
import Link from "next/link";
import { useBuildings } from "@/hooks/useBuildings";
import { ROLES } from "@/lib/format";
import { Empty, ErrorAlert } from "@/components/ui";

export default function BuildingsPage() {
  const { buildings, loading, error } = useBuildings();
  return (
    <>
      <div className="page-head">
        <div><h1>Edificios</h1><p className="muted">Consorcios que administras o en los que participas</p></div>
        <Link className="btn primary" href="/edificios/nuevo">Nuevo edificio</Link>
      </div>
      <ErrorAlert message={error} />
      {loading ? <p className="muted">Cargando…</p> : buildings.length === 0 ? (
        <div className="card"><Empty>Todavía no tienes edificios. <Link href="/edificios/nuevo">Registra el primero</Link>.</Empty></div>
      ) : (
        <div className="card table-wrap">
          <table>
            <thead><tr><th>Nombre</th><th>Dirección</th><th>Documentos</th><th>Tu rol</th></tr></thead>
            <tbody>
              {buildings.map((b) => (
                <tr key={b.id}>
                  <td><Link href={`/edificios/${b.id}`}><strong>{b.nombre}</strong></Link></td>
                  <td>{b.direccion}, {b.localidad}, {b.provincia}</td>
                  <td>{b.total_documentos}</td>
                  <td>{ROLES[b.rol]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
