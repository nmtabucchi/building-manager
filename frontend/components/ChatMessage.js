"use client";
import ReactMarkdown from "react-markdown";
import { CATEGORIAS, formatDate, formatPages } from "@/lib/format";

const COVERAGE = {
  parcial: "Respuesta parcial: la documentación cubre solo una parte de la consulta.",
  sin_informacion: "No hay información suficiente en la documentación cargada.",
  rechazada: "El asistente no pudo responder esta consulta.",
};

function Source({ s }) {
  return (
    <div className="source">
      <span className="tag">[{s.fragmento_id}]</span>{" "}
      <strong>{s.titulo || s.file_name}</strong>
      <span className="muted">
        {" "}· {CATEGORIAS[s.categoria] || s.categoria} · pág. {formatPages(s.page_number, s.page_end)}
        {s.fecha_documento ? ` · ${formatDate(s.fecha_documento)}` : ""}
      </span>
      {s.titulo && <div className="muted">{s.file_name}</div>}
      {s.extracto && <blockquote>{s.extracto}</blockquote>}
    </div>
  );
}

export default function ChatMessage({ message }) {
  const isUser = message.role === "user";
  const meta = message.metadata || {};
  const sources = message.sources || [];
  const note = !isUser && COVERAGE[meta.cobertura];
  const interpretaciones = (!isUser && meta.interpretaciones) || [];

  return (
    <div className={`msg ${isUser ? "user" : "assistant"}`}>
      {isUser ? <div style={{ whiteSpace: "pre-wrap" }}>{message.content}</div> : <ReactMarkdown>{message.content}</ReactMarkdown>}
      {note && <p className="small muted"><em>{note}</em></p>}
      {interpretaciones.length > 0 && (
        <div className="small"><strong>Interpretaciones (no figuran textualmente en los documentos):</strong>
          <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>{interpretaciones.map((t, i) => <li key={i}>{t}</li>)}</ul>
        </div>
      )}
      {sources.length > 0 && (
        <div className="sources">
          <div className="small muted"><strong>Fuentes</strong></div>
          {sources.map((s) => <Source key={s.fragmento_id + s.chunk_id} s={s} />)}
        </div>
      )}
    </div>
  );
}
