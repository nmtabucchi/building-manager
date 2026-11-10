"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase-client";
import { useSession } from "@/hooks/useSession";

export default function LoginPage() {
  const router = useRouter();
  const session = useSession();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    if (session) router.replace("/dashboard");
  }, [session, router]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");
    const supabase = getSupabase();
    try {
      if (mode === "login") {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password });
        if (err) throw err;
      } else {
        const { data, error: err } = await supabase.auth.signUp({
          email, password, options: { data: { full_name: fullName } },
        });
        if (err) throw err;
        if (!data.session) setInfo("Cuenta creada. Revisa tu correo para confirmarla y luego inicia sesión.");
      }
    } catch (err) {
      setError(err.message || "No se pudo completar la operación");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <h1>Building Manager</h1>
        <p className="muted">{mode === "login" ? "Inicia sesión para continuar" : "Crea tu cuenta"}</p>
        {error && <div className="alert">{error}</div>}
        {info && <div className="notice">{info}</div>}
        {mode === "signup" && (
          <div className="field">
            <label htmlFor="name">Nombre</label>
            <input id="name" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
          </div>
        )}
        <div className="field">
          <label htmlFor="email">Correo electrónico</label>
          <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </div>
        <div className="field">
          <label htmlFor="password">Contraseña</label>
          <input id="password" type="password" required minLength={6} value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </div>
        <button className="primary" type="submit" disabled={busy} style={{ width: "100%" }}>
          {busy ? "Procesando…" : mode === "login" ? "Ingresar" : "Crear cuenta"}
        </button>
        <p className="small muted" style={{ textAlign: "center", marginBottom: 0 }}>
          {mode === "login" ? "¿No tienes cuenta? " : "¿Ya tienes cuenta? "}
          <button type="button" className="link" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); setInfo(""); }}>
            {mode === "login" ? "Registrarse" : "Iniciar sesión"}
          </button>
        </p>
      </form>
    </div>
  );
}
