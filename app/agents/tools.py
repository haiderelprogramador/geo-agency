"""Herramientas usadas por los nodos del pipeline. La integración con Google
Places (Nearby Search + Place Details para reseñas) vive aquí, aislada del
resto de la lógica de agentes — así se puede cambiar de proveedor (OSM,
TripAdvisor) sin tocar los nodos (patrón Adapter)."""

import math

import httpx

from app.agents.state import Place
from app.config import get_settings

GOOGLE_PLACES_BASE = "https://places.googleapis.com/v1"

# Traduce nuestras categorías internas a tipos de Google Places (API New).
# https://developers.google.com/maps/documentation/places/web-service/place-types
CATEGORY_TO_GOOGLE_TYPES = {
    "gastronomía": ["restaurant", "cafe", "bakery"],
    "cultura": ["museum", "tourist_attraction", "art_gallery", "church"],
    "naturaleza": ["park", "beach"],
    "vida_nocturna": ["night_club", "bar"],
}
GOOGLE_TYPE_TO_CATEGORY = {t: cat for cat, types in CATEGORY_TO_GOOGLE_TYPES.items() for t in types}

# Google Places API (New) devuelve el nivel de precio como string enum, no
# como número — lo traducimos a una escala 0-4 para poder filtrar por
# "max_price_level" con un simple <=.
PRICE_LEVEL_TO_INT = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas (fórmula de Haversine)."""
    r = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _demo_places(latitude: float, longitude: float, categories: list[str]) -> list[Place]:
    """Datos de ejemplo — se usan solo si no hay GOOGLE_PLACES_API_KEY configurada,
    para poder seguir probando el pipeline sin esa dependencia."""
    demo_places = [
        {"id": "p1", "name": "Café del Mar (demo)", "category": "gastronomía", "latitude": latitude + 0.001, "longitude": longitude + 0.001, "avg_rating": 4.5, "price_level": 2, "open_now": True},
        {"id": "p2", "name": "Museo Naval (demo)", "category": "cultura", "latitude": latitude - 0.002, "longitude": longitude + 0.0005, "avg_rating": 4.2, "price_level": 1, "open_now": True},
        {"id": "p3", "name": "Playa Blanca (demo)", "category": "naturaleza", "latitude": latitude + 0.003, "longitude": longitude - 0.002, "avg_rating": 4.7, "price_level": 0, "open_now": None},
        {"id": "p4", "name": "Bar La Movida (demo)", "category": "vida_nocturna", "latitude": latitude - 0.001, "longitude": longitude - 0.001, "avg_rating": 4.0, "price_level": 3, "open_now": False},
    ]
    return [
        Place(
            id=p["id"], name=p["name"], category=p["category"],
            latitude=p["latitude"], longitude=p["longitude"], avg_rating=p["avg_rating"],
            price_level=p["price_level"], open_now=p["open_now"],
            review_sentiment=None, review_topics=[], score=None, reason=None,
        )
        for p in demo_places
        if not categories or p["category"] in categories
    ]


def search_nearby_places(latitude: float, longitude: float, radius_m: int, categories: list[str]) -> list[Place]:
    """Busca lugares cercanos por categoría vía Google Places API (Nearby Search).
    Si no hay API key configurada, cae de vuelta a datos de ejemplo."""
    settings = get_settings()
    if not settings.google_places_api_key:
        return _demo_places(latitude, longitude, categories)

    included_types = sorted({t for cat in categories for t in CATEGORY_TO_GOOGLE_TYPES.get(cat, [])})
    if not included_types:
        return []

    body = {
        "includedTypes": included_types,
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {"center": {"latitude": latitude, "longitude": longitude}, "radius": min(radius_m, 50_000)}
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.location,places.types,"
            "places.primaryType,places.rating,places.priceLevel,"
            "places.currentOpeningHours.openNow"
        ),
    }

    try:
        resp = httpx.post(f"{GOOGLE_PLACES_BASE}/places:searchNearby", json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        # Ante un fallo de la API externa no tumbamos el pipeline: seguimos con
        # datos de ejemplo para esa búsqueda (degradación controlada, RNF7).
        # TODO: reemplazar este print por logging real una vez conectado un logger.
        body_text = getattr(getattr(exc, "response", None), "text", "")
        print(f"[search_nearby_places] Google Places falló: {exc!r} body={body_text}")
        return _demo_places(latitude, longitude, categories)

    results: list[Place] = []
    for raw in data.get("places", []):
        # Solo confiamos en "primaryType" (el tipo más representativo del lugar
        # según Google). NO caemos de vuelta a escanear la lista completa de
        # "types": esa lista trae etiquetas secundarias/incidentales (ej. un
        # supermercado con un bar en el mismo centro comercial queda tageado
        # también con "bar") y usarla como respaldo producía categorías falsas.
        primary_type = raw.get("primaryType")
        category = GOOGLE_TYPE_TO_CATEGORY.get(primary_type)
        if category is None:
            # El tipo principal del lugar no es ninguna de nuestras categorías
            # de interés (ej. un supermercado, una farmacia, un banco) —
            # lo descartamos en vez de etiquetarlo con un tipo secundario.
            continue
        location = raw.get("location", {})
        results.append(
            Place(
                id=raw["id"],
                name=raw.get("displayName", {}).get("text", "Sin nombre"),
                category=category,
                latitude=location.get("latitude", latitude),
                longitude=location.get("longitude", longitude),
                avg_rating=raw.get("rating"),
                price_level=PRICE_LEVEL_TO_INT.get(raw.get("priceLevel")),
                open_now=raw.get("currentOpeningHours", {}).get("openNow"),
                review_sentiment=None,
                review_topics=[],
                score=None,
                reason=None,
            )
        )
    return results


def fetch_reviews_for_place(place_id: str) -> list[str]:
    """Trae texto de reseñas de un lugar vía Google Places Details.
    Si no hay API key o el id no es de Google (viene de datos demo), usa un
    par de reseñas de ejemplo para no romper el análisis."""
    settings = get_settings()
    if not settings.google_places_api_key or place_id.startswith("p"):
        return [
            "Excelente atención y buena relación precio-calidad.",
            "Un poco concurrido en la tarde pero vale la pena.",
        ]

    headers = {
        "X-Goog-Api-Key": settings.google_places_api_key,
        "X-Goog-FieldMask": "reviews",
    }
    try:
        resp = httpx.get(f"{GOOGLE_PLACES_BASE}/places/{place_id}", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError:
        return []

    return [r.get("text", {}).get("text", "") for r in data.get("reviews", []) if r.get("text", {}).get("text")]
