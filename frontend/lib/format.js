export const CATEGORIAS = {
  reglamento: "Reglamento",
  acta_asamblea: "Acta de asamblea",
  acta_reunion: "Acta de reunión",
  comunicacion: "Comunicación",
  contrato: "Contrato",
  presupuesto: "Presupuesto",
  manual_tecnico: "Manual técnico",
  otro: "Otro",
};

export const ESTADOS = {
  pendiente: "Pendiente",
  procesando: "Procesando",
  procesado: "Procesado",
  error: "Error",
};

export const ROLES = { administrador: "Administrador", colaborador: "Colaborador", lector: "Lector" };

export function formatBytes(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(value) {
  if (!value) return "—";
  const d = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("es-AR", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatPages(start, end) {
  if (start == null) return "s/n";
  return end && end !== start ? `${start}-${end}` : String(start);
}

export const canWriteDocs = (rol) => rol === "administrador" || rol === "colaborador";
export const isAdmin = (rol) => rol === "administrador";
export const hasPendingDocs = (docs) => docs.some((d) => d.status === "pendiente" || d.status === "procesando");
