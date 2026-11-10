"use client";
import { useEffect, useRef } from "react";
import { CATEGORIAS, ESTADOS } from "@/lib/format";

export function StatusBadge({ status }) {
  return <span className={`badge ${status}`}>{ESTADOS[status] || status}</span>;
}

export function ErrorAlert({ message }) {
  return message ? <div className="alert" role="alert">{message}</div> : null;
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

export function BuildingSelect({ buildings, value, onChange, id = "building" }) {
  return (
    <div style={{ minWidth: 240 }}>
      <label htmlFor={id}>Edificio</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {buildings.map((b) => <option key={b.id} value={b.id}>{b.nombre}</option>)}
      </select>
    </div>
  );
}

export function CategorySelect({ value, onChange, id = "categoria" }) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {Object.entries(CATEGORIAS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
    </select>
  );
}

// Diálogo modal nativo.
export function Modal({ open, onClose, title, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const dlg = ref.current;
    if (!dlg) return;
    if (open && !dlg.open) dlg.showModal();
    if (!open && dlg.open) dlg.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose}>
      <h2>{title}</h2>
      {children}
    </dialog>
  );
}
