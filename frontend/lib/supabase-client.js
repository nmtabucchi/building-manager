"use client";
// Solo autenticación. Usa la clave pública (anon/publishable); nunca claves privadas.
import { createClient } from "@supabase/supabase-js";

let client = null;

export function getSupabase() {
  if (!client) {
    client = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
  }
  return client;
}
