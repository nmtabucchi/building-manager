"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api-client";

const KEY = "bm.selectedBuilding";

// Carga los edificios del usuario y recuerda el seleccionado (preferencia por usuario, solo en el navegador).
export function useBuildings() {
  const [buildings, setBuildings] = useState([]);
  const [selectedId, setSelectedIdState] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      const list = await api.get("/buildings");
      setBuildings(list);
      let saved = "";
      try { saved = localStorage.getItem(KEY) || ""; } catch {}
      setSelectedIdState((cur) => {
        const wanted = cur || saved;
        return list.some((b) => b.id === wanted) ? wanted : list[0]?.id || "";
      });
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const setSelectedId = (id) => {
    setSelectedIdState(id);
    try { localStorage.setItem(KEY, id); } catch {}
  };

  const selected = buildings.find((b) => b.id === selectedId) || null;
  return { buildings, selected, selectedId, setSelectedId, loading, error, reload };
}
