"""Nodos del pipeline. Cada función es un paso del Pipeline/Chain of
Responsibility: recibe el estado acumulado y devuelve la actualización que
le corresponde a su etapa. En LangGraph esto se compone como un grafo
lineal (ver graph.py)."""

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.scheduling import assign_schedule
from app.agents.state import GraphState, Place
from app.agents.tools import fetch_reviews_for_place, haversine_m, search_nearby_places
from app.config import get_settings

settings = get_settings()


def _llm(model: str | None = None) -> ChatAnthropic:
    return ChatAnthropic(model=model or settings.planner_model, api_key=settings.anthropic_api_key)


def _strip_markdown_json(text: str) -> str:
    """Claude suele envolver el JSON en un bloque ```json ... ``` aunque se le
    pida 'responde SOLO un JSON'. Esto le quita el envoltorio antes de parsear."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # quita la primera línea (``` o ```json) y el ``` final
        lines = cleaned.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines[1:])
    return cleaned.strip()


# --- 1. Perfil de gustos (Builder) -----------------------------------------

def build_taste_profile(state: GraphState) -> dict:
    """TODO: combinar preferencias explícitas guardadas del traveler +
    histórico de Feedback (repository) para construir pesos por categoría.
    Por ahora usa un perfil neutro de ejemplo si no hay uno guardado."""
    profile = state.get("taste_profile") or {
        "gastronomía": 0.8,
        "cultura": 0.6,
        "naturaleza": 0.7,
        "vida_nocturna": 0.3,
    }
    return {"taste_profile": profile}


# --- 2. Descubrimiento geográfico ------------------------------------------

def discover_places(state: GraphState) -> dict:
    profile = state["taste_profile"] or {}
    # Solo busca categorías relevantes para el perfil (evita ruido y costo)
    relevant_categories = [cat for cat, weight in profile.items() if weight > 0.2]
    places = search_nearby_places(
        latitude=state["latitude"],
        longitude=state["longitude"],
        radius_m=state["radius_m"],
        categories=relevant_categories,
    )

    # RF8: filtros explícitos — se aplican aquí (antes de gastar análisis de
    # reseñas en lugares que de todos modos se van a descartar), no en el
    # ranking. Si Google no reporta el dato para un lugar (None), no lo
    # descartamos por falta de información — solo filtramos cuando SÍ hay
    # un valor que no cumple.
    min_rating = state.get("min_rating")
    if min_rating is not None:
        places = [p for p in places if p["avg_rating"] is None or p["avg_rating"] >= min_rating]

    max_price_level = state.get("max_price_level")
    if max_price_level is not None:
        places = [p for p in places if p["price_level"] is None or p["price_level"] <= max_price_level]

    if state.get("open_now"):
        places = [p for p in places if p["open_now"] is None or p["open_now"] is True]

    return {"candidate_places": places}


# --- 3. Análisis de reseñas --------------------------------------------------

def analyze_reviews(state: GraphState) -> dict:
    llm = _llm(settings.fast_model)
    language = state.get("language") or "es"
    enriched: list[Place] = []
    for place in state["candidate_places"]:
        review_texts = fetch_reviews_for_place(place["id"])
        if not review_texts:
            enriched.append(place)
            continue

        # El "topics" sí se traduce (lo lee el usuario final); el valor de
        # "sentiment" se le pide SIEMPRE en español (positivo/neutro/negativo)
        # porque rank_places() lo usa como clave interna de puntaje — así no
        # hace falta traducir ni normalizar nada aguas abajo del LLM.
        topics_language = "español" if language == "es" else "inglés"
        prompt = (
            "Analiza estas reseñas y responde SOLO un JSON con las llaves "
            '"sentiment" (SIEMPRE uno de estos tres valores en español: '
            'positivo/neutro/negativo, sin importar el idioma de las reseñas) y '
            f'"topics" (lista corta de temas recurrentes, escrita en {topics_language}). '
            f"Reseñas: {review_texts}"
        )
        response = llm.invoke([SystemMessage(content="Eres un analista de reseñas turísticas."), HumanMessage(content=prompt)])
        raw_text = response.content
        try:
            parsed = json.loads(_strip_markdown_json(raw_text))
        except (json.JSONDecodeError, TypeError) as exc:
            # TODO: reemplazar por logging real una vez conectado un logger.
            print(f"[analyze_reviews] No se pudo parsear la respuesta del LLM: {exc!r} raw={raw_text!r}")
            parsed = {"sentiment": "neutro", "topics": []}

        place = {**place, "review_sentiment": parsed.get("sentiment"), "review_topics": parsed.get("topics", [])}
        enriched.append(place)

    return {"candidate_places": enriched}


# --- 4. Ranking (Strategy) --------------------------------------------------

def rank_places(state: GraphState) -> dict:
    profile = state["taste_profile"] or {}
    origin_lat, origin_lon = state["latitude"], state["longitude"]

    def score(place: Place) -> float:
        affinity = profile.get(place["category"], 0.1)
        rating = (place["avg_rating"] or 3.0) / 5.0
        distance_m = haversine_m(origin_lat, origin_lon, place["latitude"], place["longitude"])
        proximity = max(0.0, 1 - distance_m / max(state["radius_m"], 1))
        sentiment_bonus = {"positivo": 0.1, "neutro": 0.0, "negativo": -0.2}.get(place["review_sentiment"] or "neutro", 0.0)
        # combinación ponderada: afinidad de gustos pesa más que cercanía o rating crudo
        return round(0.5 * affinity + 0.25 * rating + 0.15 * proximity + sentiment_bonus, 3)

    language = state.get("language") or "es"
    ranked = sorted(
        (
            {**place, "score": score(place), "reason": _explain(place, profile, language)}
            for place in state["candidate_places"]
        ),
        key=lambda p: p["score"],
        reverse=True,
    )
    return {"ranked_places": ranked}


# RF9 + RF11: explicación sin costo de LLM (heurística legible), en el
# idioma pedido por el usuario. Si se agrega un idioma nuevo, solo hay que
# sumar una entrada a este diccionario — no tocar la lógica de selección.
_EXPLANATION_TEMPLATES = {
    "es": {
        "strong_match": "Te recomendamos {name} porque coincide fuertemente con tu interés en {category}.",
        "good_reviews": "{name} tiene buenas reseñas recientes de otros viajeros.",
        "nearby": "{name} está cerca y tiene buena calificación general.",
    },
    "en": {
        "strong_match": "We recommend {name} because it strongly matches your interest in {category}.",
        "good_reviews": "{name} has great recent reviews from other travelers.",
        "nearby": "{name} is nearby and has a solid overall rating.",
    },
}


def _explain(place: Place, profile: dict[str, float], language: str = "es") -> str:
    """RF9: explica la recomendación en lenguaje natural. RF11: en el idioma
    pedido (cae a español si no hay plantilla para ese idioma)."""
    templates = _EXPLANATION_TEMPLATES.get(language, _EXPLANATION_TEMPLATES["es"])
    weight = profile.get(place["category"], 0)
    if weight >= 0.7:
        return templates["strong_match"].format(name=place["name"], category=place["category"])
    if place["review_sentiment"] == "positivo":
        return templates["good_reviews"].format(name=place["name"])
    return templates["nearby"].format(name=place["name"])


# --- 5. Construcción del itinerario (Composite + Template Method) ----------

def build_itinerary(state: GraphState) -> dict:
    days = max(state.get("days", 1), 1)
    ranked = state["ranked_places"]

    stops = []
    for i, place in enumerate(ranked):
        day_number = (i % days) + 1
        order_index = i // days
        stops.append({"day_number": day_number, "order_index": order_index, "place": place})
    return {"plan_stops": assign_schedule(stops)}
