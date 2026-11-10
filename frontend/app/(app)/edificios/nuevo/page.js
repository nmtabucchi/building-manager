"use client";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api-client";
import BuildingForm from "@/components/BuildingForm";

export default function NewBuildingPage() {
  const router = useRouter();
  return (
    <>
      <div className="page-head"><div><h1>Nuevo edificio</h1><p className="muted">Serás su administrador</p></div></div>
      <div className="card">
        <BuildingForm
          submitLabel="Crear edificio"
          onCancel={() => router.push("/edificios")}
          onSubmit={async (values) => {
            const created = await api.post("/buildings", values);
            router.push(`/edificios/${created.id}`);
          }}
        />
      </div>
    </>
  );
}
