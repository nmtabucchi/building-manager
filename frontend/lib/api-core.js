// Utilidades puras del cliente de API (sin dependencias del navegador, testeables con node:test).

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function buildUrl(base, path, query) {
  const url = base.replace(/\/+$/, "") + path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

// Convierte la respuesta HTTP en datos o lanza ApiError con el formato {"error": {code, message}} del backend.
export async function parseResponse(res) {
  if (res.status === 204) return null;
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const err = body && body.error;
    throw new ApiError(res.status, (err && err.code) || "HTTP_ERROR", (err && err.message) || `Error ${res.status}`);
  }
  return body;
}
