"use client";
import { useEffect, useState } from "react";
import { getSupabase } from "@/lib/supabase-client";

// session: undefined = cargando, null = sin sesión, objeto = autenticado
export function useSession() {
  const [session, setSession] = useState(undefined);

  useEffect(() => {
    const supabase = getSupabase();
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  return session;
}
