"""Construcción del grafo LangGraph de consultas RAG.

START -> recibir_consulta -> cargar_contexto -> [reformular_consulta] -> recuperar_fragmentos
      -> evaluar_relevancia -> (sin contexto) responder_sin_informacion -> finalizar
                            -> (con contexto) generar_respuesta -> validar_fuentes
                                  -> reintento (1 vez) -> generar_respuesta
                                  -> sin citas válidas -> responder_sin_informacion
                                  -> finalizar -> END
"""
from langgraph.graph import END, START, StateGraph

from app.rag.pipelines.nodes import RagNodes
from app.rag.pipelines.state import RagState


class RagGraphBuilder:
    def __init__(self, nodes: RagNodes):
        self._n = nodes

    def build(self):
        g = StateGraph(RagState)
        n = self._n
        g.add_node("recibir_consulta", n.recibir_consulta)
        g.add_node("cargar_contexto", n.cargar_contexto)
        g.add_node("reformular_consulta", n.reformular_consulta)
        g.add_node("recuperar_fragmentos", n.recuperar_fragmentos)
        g.add_node("evaluar_relevancia", n.evaluar_relevancia)
        g.add_node("generar_respuesta", n.generar_respuesta)
        g.add_node("validar_fuentes", n.validar_fuentes)
        g.add_node("responder_sin_informacion", n.responder_sin_informacion)
        g.add_node("finalizar", n.finalizar)

        g.add_edge(START, "recibir_consulta")
        g.add_edge("recibir_consulta", "cargar_contexto")
        g.add_conditional_edges(
            "cargar_contexto", lambda s: "reformular_consulta" if s.get("history") else "recuperar_fragmentos",
            ["reformular_consulta", "recuperar_fragmentos"])
        g.add_edge("reformular_consulta", "recuperar_fragmentos")
        g.add_edge("recuperar_fragmentos", "evaluar_relevancia")
        g.add_conditional_edges(
            "evaluar_relevancia", lambda s: "generar_respuesta" if s.get("fragments") else "responder_sin_informacion",
            ["generar_respuesta", "responder_sin_informacion"])
        g.add_conditional_edges(
            "generar_respuesta", lambda s: "finalizar" if s.get("refusal") else "validar_fuentes",
            ["finalizar", "validar_fuentes"])
        g.add_conditional_edges("validar_fuentes", self._after_validation,
                                ["generar_respuesta", "responder_sin_informacion", "finalizar"])
        g.add_edge("responder_sin_informacion", "finalizar")
        g.add_edge("finalizar", END)
        return g.compile()

    @staticmethod
    def _after_validation(state: RagState) -> str:
        if state.get("needs_retry"):
            return "generar_respuesta"
        if state.get("no_info"):
            return "responder_sin_informacion"
        return "finalizar"
