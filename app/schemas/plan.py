from pydantic import BaseModel


class PlanRequest(BaseModel):
    traveler_id: str
    city: str
    latitude: float
    longitude: float
    radius_m: int = 2000
    days: int = 1
    language: str = "es"  # RF11: "es" o "en" (se usa en las explicaciones y temas de reseñas)
    min_rating: float | None = None  # RF8: filtro explícito, ej. 4.0 = solo 4+ estrellas
    max_price_level: int | None = None  # RF8: 0 (gratis) a 4 (muy caro) — presupuesto máximo
    open_now: bool | None = None  # RF8: True = solo lugares abiertos ahora mismo
    taste_profile: dict[str, float] | None = None  # RF1: gustos explícitos del formulario
    # (ej. {"gastronomía": 0.9, "cultura": 0.3}). Si se manda, tiene
    # prioridad sobre el perfil ya guardado del traveler — así la persona
    # puede ajustar sus gustos en cada búsqueda y no queda atada para
    # siempre al primer perfil que generó.


class PlaceOut(BaseModel):
    id: str
    name: str
    category: str
    latitude: float
    longitude: float
    avg_rating: float | None
    price_level: int | None = None  # RF8: 0 (gratis) a 4 (muy caro)
    open_now: bool | None = None  # RF8: None si Google no reporta horario
    review_sentiment: str | None
    score: float | None
    reason: str | None


class PlanStopOut(BaseModel):
    day_number: int
    order_index: int
    scheduled_time: str | None
    travel_minutes: int | None = None  # traslado desde la parada anterior del mismo día
    place: PlaceOut


class PlanResponse(BaseModel):
    plan_id: str
    city: str
    taste_profile: dict[str, float]
    stops: list[PlanStopOut]


class ContextEventRequest(BaseModel):
    """Evento de contexto que dispara el recálculo (Observer): un lugar
    cerró, o una categoría entera deja de estar disponible (ej. mal clima
    descarta todo lo de 'naturaleza' para ese plan)."""

    event_type: str  # "place_closed" | "category_unavailable"
    place_id: str | None = None  # id de Google del lugar cerrado
    category: str | None = None  # categoría afectada
    reason: str | None = None  # ej. "lluvia fuerte", "cerrado por reforma"


class ReorderStopsRequest(BaseModel):
    """RF6: nuevo orden deseado, como lista de ids de Google de los lugares
    (todas las paradas del plan, sin repetir, en el orden que se quiere)."""

    place_ids: list[str]


class PlanSummaryOut(BaseModel):
    """Versión resumida para listar los planes guardados de un traveler."""

    plan_id: str
    city: str
    status: str
    created_at: str
    stop_count: int


class DayRouteOut(BaseModel):
    """Recorrido de un día para dibujarlo en el mapa."""

    day_number: int
    geometry: list[list[float]]  # [[lat, lon], ...] siguiendo las calles (OSRM) o línea recta (estimación)
    source: str  # "osrm" | "estimate"
    total_travel_minutes: int


class ChatRequest(BaseModel):
    message: str
    language: str = "es"
    # Parámetros de búsqueda actuales (ubicación, radio, días...). Solo hacen
    # falta si el mensaje pide armar un plan nuevo ("algo más barato").
    context: PlanRequest | None = None


class ChatResponse(BaseModel):
    reply: str
    plan: PlanResponse
    plan_changed: bool
    applied: list[str]  # qué hizo el agente, en lenguaje humano


class WeatherDayOut(BaseModel):
    day_number: int
    date: str
    rain_probability: int | None
    temp_max: float | None
    rainy: bool


class AtRiskStopOut(BaseModel):
    day_number: int
    place_id: str
    name: str


class WeatherOut(BaseModel):
    available: bool  # False si el servicio de clima no respondió
    forecast: list[WeatherDayOut]
    at_risk: list[AtRiskStopOut]  # paradas al aire libre en días de lluvia probable
