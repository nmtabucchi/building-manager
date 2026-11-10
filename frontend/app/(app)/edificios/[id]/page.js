"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api-client";
import { ROLES, isAdmin } from "@/lib/format";
import BuildingForm from "@/components/BuildingForm";
import { ErrorAlert, Modal } from "@/components/ui";

function Members({ buildingId, admin }) {
  const [members, setMembers] = useState([]);
  const [email, setEmail] = useState("");
  const [rol, setRol] = useState("lector");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.get(`/buildings/${buildingId}/members`).then(setMembers).catch((e) => setError(e.message)), [buildingId]);
  useEffect(() => { load(); }, [load]);

  async function assign(e) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await api.put(`/buildings/${buildingId}/members`, { email, rol });
      setEmail("");
      await load();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  async function changeRole(m, newRol) {
    setError("");
    try { await api.put(`/buildings/${buildingId}/members`, { email: m.email, rol: newRol }); await load(); }
    catch (err) { setError(err.message); await load(); }
  }

  async function remove(m) {
    if (!confirm(`¿Quitar a ${m.email} del edificio?`)) return;
    setError("");
    try { await api.del(`/buildings/${buildingId}/members/${m.user_id}`); await load(); }
    catch (err) { setError(err.message); }
  }

  return (
    <div className="card">
      <h2>Miembros</h2>
      <ErrorAlert message={error} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>Usuario</th><th>Rol</th>{admin && <th />}</tr></thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.full_name ? `${m.full_name} · ` : ""}{m.email}</td>
                <td>
                  {admin ? (
                    <select aria-label={`Rol de ${m.email}`} value={m.rol} onChange={(e) => changeRole(m, e.target.value)}>
                      {Object.entries(ROLES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                  ) : ROLES[m.rol]}
                </td>
                {admin && <td><button className="small danger" onClick={() => remove(m)}>Quitar</button></td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {admin && (
        <form onSubmit={assign} className="row" style={{ marginTop: 14, alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 200 }}><label htmlFor="m-email">Agregar usuario registrado</label>
            <input id="m-email" type="email" required placeholder="correo@ejemplo.com" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div><label htmlFor="m-rol">Rol</label>
            <select id="m-rol" value={rol} onChange={(e) => setRol(e.target.value)}>
              {Object.entries(ROLES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></div>
          <button className="primary" disabled={busy}>Agregar</button>
        </form>
      )}
    </div>
  );
}

export default function BuildingDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const [building, setBuilding] = useState(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    api.get(`/buildings/${id}`).then((b) => {
      setBuilding(b);
      // los enlaces a Documentación y Asistente abren con este edificio seleccionado
      try { localStorage.setItem("bm.selectedBuilding", b.id); } catch {}
    }).catch((e) => setError(e.message));
  }, [id]);

  async function remove() {
    if (!confirm(`¿Eliminar "${building.nombre}"? Dejará de estar visible para todos sus miembros.`)) return;
    try { await api.del(`/buildings/${id}`); router.push("/edificios"); } catch (e) { setError(e.message); }
  }

  if (error && !building) return <ErrorAlert message={error} />;
  if (!building) return <p className="muted">Cargando…</p>;
  const admin = isAdmin(building.rol);

  return (
    <>
      <div className="page-head">
        <div>
          <p className="small"><Link href="/edificios">← Edificios</Link></p>
          <h1>{building.nombre}</h1>
          <p className="muted">{building.direccion}, {building.localidad}, {building.provincia} · Tu rol: {ROLES[building.rol]}</p>
        </div>
        <div className="row">
          <Link className="btn" href="/documentos">Documentación ({building.total_documentos})</Link>
          <Link className="btn primary" href="/asistente">Consultar al asistente</Link>
        </div>
      </div>
      <ErrorAlert message={error} />
      <div className="stack">
        <div className="card">
          <div className="row between"><h2>Información general</h2>
            {admin && <div className="row"><button className="small" onClick={() => setEditing(true)}>Editar</button><button className="small danger" onClick={remove}>Eliminar</button></div>}
          </div>
          <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{building.informacion_general || <span className="muted">Sin información cargada.</span>}</p>
        </div>
        <Members buildingId={id} admin={admin} />
      </div>
      <Modal open={editing} onClose={() => setEditing(false)} title="Editar edificio">
        {editing && (
          <BuildingForm initial={building} submitLabel="Guardar" onCancel={() => setEditing(false)}
            onSubmit={async (values) => { setBuilding(await api.put(`/buildings/${id}`, values)); setEditing(false); }} />
        )}
      </Modal>
    </>
  );
}
