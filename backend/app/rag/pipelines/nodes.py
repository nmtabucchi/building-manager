"""Nodos del grafo RAG: un método por nodo, sin estado propio."""
import logging
import re
import time
from typing import Any

from app.core.config import Settings
from app.domain.entities import RetrievedChunk
from app.domain.exceptions import DomainError, LLMRefusalError, ValidationError
from app.infrastructure.llm.llm_provider import LLMProvider, LLMResult
from app.rag.pipelines.state import RagState
from app.rag.prompts import prompts
from app.rag.retrieval.retriever import SupabaseRetriever
from app.repositories.document_and_conversation_repositories import MessageRepository

logger = logging.getLogger(__name__)

_MARK = re.compile(r"\[F(\d+)\]")
_COVERAGES = {"completa", "parcial", "sin_informacion"}


def _add_usage(state: RagState, result: LLMResult) -> dict[str, Any]:
    total = dict(state.get("usage") or {})
    for k, v in result.usage.items():
        total[k] = total.get(k, 0) + v
    return {"usage": total, "model": result.model}


class RagNodes:
    def __init__(self, settings: Settings, messages: MessageRepository, retriever: SupabaseRetriever,
                 llm: LLMProvider):
        self._s = settings
        self._messages = messages
        self._retriever = retriever
        self._llm = llm

    # 1 ------------------------------------------------------------------ recepción
    async def recibir_consulta(self, state: RagState) -> RagState:
        question = " ".join((state.get("question") or "").split())
        if not question:
            raise ValidationError("La pregunta no puede estar vacía")
        if len(question) > self._s.rag_max_question_chars:
            raise ValidationError(f"La pregunta no puede superar {self._s.rag_max_question_chars} caracteres")
        return {"question": question, "intent": "consulta_documental", "retries": 0, "feedback": None,
                "needs_retry": False, "no_info": False, "refusal": False, "usage": {},
                "started_at": time.perf_counter()}

    # 2 ---------------------------------------------------------------- contexto
    async def cargar_contexto(self, state: RagState) -> RagState:
        n = self._s.rag_history_messages
        if n == 0:
            return {"history": []}
        history = await self._messages.listar_por_conversacion(state["auth"], state["conversation_id"], n + 1)
        # el mensaje de la pregunta actual ya pudo haberse persistido: no es "historial"
        if history and history[-1].role.value == "user" and " ".join(history[-1].content.split()) == state["question"]:
            history = history[:-1]
        return {"history": history[-n:]}

    # 3 ---------------------------------------------------------- reformulación
    async def reformular_consulta(self, state: RagState) -> RagState:
        history = [(m.role.value, m.content) for m in state["history"]]
        try:
            result = await self._llm.generate_text(
                prompts.REFORMULATE_SYSTEM, prompts.build_reformulate_prompt(history, state["question"]),
                max_tokens=300, effort="low")
        except DomainError:
            logger.warning("Reformulación fallida; se usa la pregunta original")
            return {"standalone_question": state["question"]}
        text = " ".join(result.text.split()).strip("\"' ")
        if not text or len(text) > self._s.rag_max_question_chars:
            text = state["question"]
        return {"standalone_question": text, **_add_usage(state, result)}

    # 4 ---------------------------------------------------------- recuperación
    async def recuperar_fragmentos(self, state: RagState) -> RagState:
        question = state.get("standalone_question") or state["question"]
        chunks = await self._retriever.retrieve(
            state["auth"], state["building_id"], question,
            top_k=self._s.rag_top_k, min_similarity=self._s.rag_min_similarity)
        return {"retrieved_chunks": chunks, "standalone_question": question}

    # 5 ------------------------------------------------------------- relevancia
    async def evaluar_relevancia(self, state: RagState) -> RagState:
        budget_chars = self._s.rag_context_token_budget * 4
        selected: list[RetrievedChunk] = []
        seen_keys: set[tuple] = set()
        seen_text: set[str] = set()
        used = 0
        for c in sorted(state.get("retrieved_chunks", []), key=lambda c: c.similarity, reverse=True):
            if c.similarity < self._s.rag_min_similarity:
                continue
            key, norm = (c.document_id, c.chunk_index), " ".join(c.content.split()).lower()
            if key in seen_keys or norm in seen_text:
                continue
            if selected and used + len(c.content) > budget_chars:
                break
            seen_keys.add(key)
            seen_text.add(norm)
            selected.append(c)
            used += len(c.content)
        return {"fragments": [(f"F{i}", c) for i, c in enumerate(selected, 1)]}

    # 6 ------------------------------------------------------------- generación
    async def generar_respuesta(self, state: RagState) -> RagState:
        user = prompts.build_user_prompt(
            state["building_nombre"], state["standalone_question"], state["fragments"], state.get("feedback"))
        try:
            result = await self._llm.generate_structured(
                prompts.SYSTEM_PROMPT, user, prompts.ANSWER_SCHEMA,
                max_tokens=self._s.claude_max_tokens, effort=self._s.claude_effort)
        except LLMRefusalError:
            return {"refusal": True}
        return {"draft": self._normalize_draft(result.data or {}), "needs_retry": False, **_add_usage(state, result)}

    @staticmethod
    def _normalize_draft(data: dict[str, Any]) -> dict[str, Any]:
        respuesta = data.get("respuesta")
        citas = [c for c in data.get("citas", []) if isinstance(c, dict) and isinstance(c.get("fragmento_id"), str)]
        interpretaciones = [i for i in data.get("interpretaciones", []) if isinstance(i, str)]
        cobertura = data.get("cobertura") if data.get("cobertura") in _COVERAGES else "parcial"
        return {"respuesta": respuesta if isinstance(respuesta, str) else "", "cobertura": cobertura,
                "citas": citas, "interpretaciones": interpretaciones}

    # 7 ------------------------------------------------------------- validación
    async def validar_fuentes(self, state: RagState) -> RagState:
        draft = dict(state["draft"])
        valid_ids = {fid for fid, _ in state["fragments"]}
        text_ids = {f"F{n}" for n in _MARK.findall(draft["respuesta"])}
        cited = text_ids | {c["fragmento_id"] for c in draft["citas"]}
        invalid = cited - valid_ids
        needs_citas = draft["cobertura"] != "sin_informacion"

        problem = None
        if not draft["respuesta"].strip():
            problem = "la respuesta está vacía"
        elif invalid:
            problem = f"citaste fragmentos inexistentes {sorted(invalid)}"
        elif needs_citas and not (cited & valid_ids):
            problem = "no citaste ningún fragmento con la marca [F#]"

        if problem and state.get("retries", 0) < 1:
            return {"needs_retry": True, "retries": state.get("retries", 0) + 1,
                    "feedback": f"{problem}. Cita solo ids presentes en <fragmentos> ({', '.join(sorted(valid_ids))})."}

        if not problem:
            return {"validation": "ok", "needs_retry": False}

        # reintento agotado: se depura lo inválido; sin respaldo documental no se afirma nada
        draft["respuesta"] = _MARK.sub(lambda m: m.group(0) if f"F{m.group(1)}" in valid_ids else "", draft["respuesta"])
        draft["citas"] = [c for c in draft["citas"] if c["fragmento_id"] in valid_ids]
        still_cited = {f"F{n}" for n in _MARK.findall(draft["respuesta"])} | {c["fragmento_id"] for c in draft["citas"]}
        if not draft["respuesta"].strip() or (needs_citas and not still_cited):
            return {"needs_retry": False, "no_info": True, "validation": "sin_citas_validas"}
        return {"draft": draft, "needs_retry": False, "validation": "parcial"}

    # 8 ------------------------------------------------------- sin información
    async def responder_sin_informacion(self, state: RagState) -> RagState:
        return {"no_info": True, "answer": prompts.no_info_message(state["building_nombre"]),
                "coverage": "sin_informacion", "sources": []}

    # 9 ------------------------------------------------------------- finalizar
    async def finalizar(self, state: RagState) -> RagState:
        sources: list[dict[str, Any]] = []
        meta: dict[str, Any] = {}
        if state.get("refusal"):
            answer, coverage = prompts.refusal_message(), "rechazada"
        elif state.get("no_info"):
            answer, coverage = prompts.no_info_message(state["building_nombre"]), "sin_informacion"
        else:
            draft = state["draft"]
            answer, coverage = draft["respuesta"].strip(), draft["cobertura"]
            meta["interpretaciones"] = draft["interpretaciones"]
            if coverage != "sin_informacion":
                sources = self._build_sources(draft, dict(state["fragments"]))

        retrieved = state.get("retrieved_chunks", [])
        meta.update({
            "cobertura": coverage,
            "validacion": state.get("validation", "n/a"),
            "model": state.get("model"),
            "usage": state.get("usage", {}),
            "latency_ms": round((time.perf_counter() - state.get("started_at", time.perf_counter())) * 1000),
            "top_k": self._s.rag_top_k,
            "fragmentos_recuperados": len(retrieved),
            "fragmentos_enviados": len(state.get("fragments", [])),
            "similitud_max": round(max((c.similarity for c in retrieved), default=0.0), 4),
        })
        if state.get("standalone_question") and state["standalone_question"] != state["question"]:
            meta["pregunta_reformulada"] = state["standalone_question"]
        return {"answer": answer, "sources": sources, "coverage": coverage, "metadata": meta}

    @staticmethod
    def _build_sources(draft: dict[str, Any], by_id: dict[str, RetrievedChunk]) -> list[dict[str, Any]]:
        order: list[str] = []
        for fid in [f"F{n}" for n in _MARK.findall(draft["respuesta"])] + [c["fragmento_id"] for c in draft["citas"]]:
            if fid in by_id and fid not in order:
                order.append(fid)
        quotes = {c["fragmento_id"]: c.get("cita_textual", "") for c in draft["citas"]}
        out = []
        for fid in order:
            c = by_id[fid]
            quote = " ".join((quotes.get(fid) or "").split())
            verbatim = quote and quote.lower() in " ".join(c.content.split()).lower()
            out.append({
                "fragmento_id": fid, "chunk_id": str(c.chunk_id), "document_id": str(c.document_id),
                "file_name": c.file_name, "titulo": c.titulo, "categoria": c.categoria.value,
                "fecha_documento": c.fecha_documento.isoformat() if c.fecha_documento else None,
                "page_number": c.page_number, "page_end": c.page_end, "similarity": round(c.similarity, 4),
                "extracto": (quote if verbatim else " ".join(c.content.split()))[:300],
            })
        return out
