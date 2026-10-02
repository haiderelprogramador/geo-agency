"""Estado compartido del pipeline — viaja de un agente al siguiente en orden fijo."""

from typing import TypedDict


class Place(TypedDict):
    id: str
    name: str
    category: str
    latitude: float
    longitude: float
    avg_rating: float | None
    price_level: int | None  # RF8: 0 (gratis) a 4 (muy caro), None si Google no lo reporta
    open_now: bool | None  # RF8: None si Google no reporta horario para este lugar
    review_sentiment: str | None
    review_topics: list[str]
    score: float | None
    reason: str | None


class PlanStop(TypedDict):
    day_number: int
    order_index: int
    place: Place
    scheduled_time: str | None


class GraphState(TypedDict):
    # Entradas del usuario
    traveler_id: str
    city: str
    latitude: float
    longitude: float
    radius_m: int
    days: int
    language: str
    min_rating: float | None  # RF8: filtro explícito de calidad mínima
    max_price_level: int | None  # RF8: presupuesto, 0-4 (ver Place.price_level)
    open_now: bool | None  # RF8: True = solo lugares abiertos ahora mismo

    # Se construye a lo largo del pipeline (patrón Builder + Pipeline)
    taste_profile: dict[str, float] | None
    candidate_places: list[Place]
    ranked_places: list[Place]
    plan_stops: list[PlanStop]
