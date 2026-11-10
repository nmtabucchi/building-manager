"use client";
import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "@/hooks/useSession";
import { getSupabase } from "@/lib/supabase-client";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/edificios", label: "Edificios" },
  { href: "/documentos", label: "Documentación" },
  { href: "/asistente", label: "Asistente IA" },
];

export default function AppLayout({ children }) {
  const session = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (session === null) router.replace("/login");
  }, [session, router]);

  if (!session) return <p className="muted" style={{ padding: 24 }}>Cargando…</p>;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">🏢 Building Manager</div>
        <nav className="nav">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={pathname.startsWith(n.href) ? "active" : ""}>{n.label}</Link>
          ))}
        </nav>
        <div className="spacer" />
        <div className="small muted" style={{ padding: "0 10px", overflow: "hidden", textOverflow: "ellipsis" }}>{session.user.email}</div>
        <button className="small" onClick={() => getSupabase().auth.signOut()}>Cerrar sesión</button>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
