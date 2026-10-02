"""Ensambla el pipeline como un grafo lineal de LangGraph:

  perfil -> descubrimiento -> reseñas -> ranking -> itinerario

A diferencia de un sistema supervisor/router, aquí no hay enrutamiento
condicional: cada recomendación pasa por las cinco etapas en orden fijo
(patrón Pipeline / Chain of Responsibility)."""

from functools import lru_cache

from langgraph.graph import END, StateGraph

from app.agents.nodes import build_itinerary, build_taste_profile, discover_places, analyze_reviews, rank_places
from app.agents.state import GraphState


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("perfil", build_taste_profile)
    graph.add_node("descubrimiento", discover_places)
    graph.add_node("reseñas", analyze_reviews)
    graph.add_node("ranking", rank_places)
    graph.add_node("itinerario", build_itinerary)

    graph.set_entry_point("perfil")
    graph.add_edge("perfil", "descubrimiento")
    graph.add_edge("descubrimiento", "reseñas")
    graph.add_edge("reseñas", "ranking")
    graph.add_edge("ranking", "itinerario")
    graph.add_edge("itinerario", END)

    return graph.compile()


@lru_cache
def get_compiled_graph():
    return build_graph()
