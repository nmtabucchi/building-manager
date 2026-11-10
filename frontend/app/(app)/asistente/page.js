"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api-client";
import { useBuildings } from "@/hooks/useBuildings";
import { formatDate } from "@/lib/format";
import { BuildingSelect, Empty, ErrorAlert } from "@/components/ui";
import ChatMessage from "@/components/ChatMessage";

const EJEMPLOS = [
  "¿Qué establece el reglamento sobre las mascotas?",
  "¿Cuál es el horario permitido para trabajos de mantenimiento?",
  "¿Qué se resolvió en la última asamblea?",
  "¿Cómo se distribuyen los gastos comunes?",
];

export default function AssistantPage() {
  const { buildings, selectedId, setSelectedId, loading, error: bError } = useBuildings();
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);

  const loadConversations = useCallback(async () => {
    if (!selectedId) return;
    try { setConversations(await api.get("/conversations", { building_id: selectedId, limit: 50 })); }
    catch (e) { setError(e.message); }
  }, [selectedId]);

  // al cambiar de edificio se limpia el chat: nunca se mezclan conversaciones de distintos edificios
  useEffect(() => { setActiveId(null); setMessages([]); setError(""); loadConversations(); }, [loadConversations]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, sending]);

  async function openConversation(id) {
    setActiveId(id); setError("");
    try { setMessages(await api.get(`/conversations/${id}/messages`, { limit: 200 })); }
    catch (e) { setError(e.message); }
  }

  function newChat() { setActiveId(null); setMessages([]); setError(""); }

  async function send(text) {
    const content = text.trim();
    if (!content || sending || !selectedId) return;
    setSending(true); setError(""); setInput("");
    const temp = { id: `tmp-${Date.now()}`, role: "user", content, sources: [], metadata: {} };
    setMessages((m) => [...m, temp]);
    let convId = activeId;
    try {
      if (!convId) {
        const conv = await api.post("/conversations", { building_id: selectedId });
        convId = conv.id;
        setActiveId(convId);
      }
      const { user_message, assistant_message } = await api.post(`/conversations/${convId}/messages`, { content });
      setMessages((m) => [...m.filter((x) => x.id !== temp.id), user_message, assistant_message]);
    } catch (e) {
      setError(e.message);
      setInput(content);
      setMessages((m) => m.filter((x) => x.id !== temp.id));
      // si la pregunta llegó a guardarse (p. ej. falló Claude), se recarga el historial real
      if (convId) { try { setMessages(await api.get(`/conversations/${convId}/messages`, { limit: 200 })); } catch {} }
    } finally {
      setSending(false);
      loadConversations();
    }
  }

  if (loading) return <p className="muted">Cargando…</p>;
  if (!buildings.length) return <div className="card"><Empty>Primero <Link href="/edificios/nuevo">registra un edificio</Link> y carga su documentación.</Empty></div>;

  return (
    <>
      <div className="page-head">
        <div><h1>Asistente IA</h1><p className="muted">Respuestas basadas únicamente en la documentación del edificio, con sus fuentes</p></div>
        <BuildingSelect buildings={buildings} value={selectedId} onChange={setSelectedId} />
      </div>
      <ErrorAlert message={bError || error} />
      <div className="chat-layout">
        <div className="card" style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10, minHeight: 0 }}>
          <button className="primary" onClick={newChat}>Nueva conversación</button>
          <div className="conv-list">
            {conversations.length === 0 && <span className="small muted">Sin conversaciones previas.</span>}
            {conversations.map((c) => (
              <button key={c.id} className={`conv-item ${c.id === activeId ? "active" : ""}`} onClick={() => openConversation(c.id)}>
                <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.titulo || "Conversación"}</div>
                <div className="small muted">{formatDate(c.ultimo_mensaje_at || c.created_at)} · {c.total_mensajes} msj.</div>
              </button>
            ))}
          </div>
        </div>
        <div className="card chat-panel">
          <div className="messages" aria-live="polite">
            {messages.length === 0 && !sending && (
              <div className="empty">
                <p>Pregunta sobre reglamentos, actas, contratos y más.</p>
                <div className="stack" style={{ alignItems: "center" }}>
                  {EJEMPLOS.map((q) => <button key={q} className="small" onClick={() => send(q)}>{q}</button>)}
                </div>
              </div>
            )}
            {messages.map((m) => <ChatMessage key={m.id} message={m} />)}
            {sending && <div className="msg assistant muted">Buscando en la documentación…</div>}
            <div ref={endRef} />
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
            <textarea rows={2} maxLength={2000} placeholder="Escribe tu pregunta…" value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
              aria-label="Pregunta" />
            <button className="primary" disabled={sending || !input.trim()}>Enviar</button>
          </form>
        </div>
      </div>
    </>
  );
}
