"use client";
import { ApiError, buildUrl, parseResponse } from "./api-core";
import { getSupabase } from "./supabase-client";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

async function request(method, path, { query, json, form } = {}) {
  const { data } = await getSupabase().auth.getSession();
  const token = data.session && data.session.access_token;
  if (!token) throw new ApiError(401, "UNAUTHENTICATED", "Sesión no iniciada");

  const headers = { Authorization: `Bearer ${token}` };
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form; // el navegador fija el boundary de multipart
  }

  let res;
  try {
    res = await fetch(buildUrl(BASE, path, query), { method, headers, body });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "No se pudo conectar con el servidor");
  }
  try {
    return await parseResponse(res);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      await getSupabase().auth.signOut();
      if (typeof window !== "undefined") window.location.assign("/login");
    }
    throw err;
  }
}

export const api = {
  get: (path, query) => request("GET", path, { query }),
  post: (path, json) => request("POST", path, { json: json ?? {} }),
  put: (path, json) => request("PUT", path, { json }),
  del: (path) => request("DELETE", path),
  upload: (path, form) => request("POST", path, { form }),
};
