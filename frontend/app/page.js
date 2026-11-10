"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/hooks/useSession";

export default function Home() {
  const session = useSession();
  const router = useRouter();
  useEffect(() => {
    if (session === undefined) return;
    router.replace(session ? "/dashboard" : "/login");
  }, [session, router]);
  return <p className="muted" style={{ padding: 24 }}>Cargando…</p>;
}
