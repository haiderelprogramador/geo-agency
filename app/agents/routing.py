"""Rutas entre paradas (RF5: "optimizando la ruta entre paradas").

Tres piezas, de la más barata a la más cara:
1. `optimize_day_order`: reordena las paradas de un día con el heurístico del
   vecino más cercano (solo geometría, sin red).
2. `fetch_route`: pide a OSRM la ruta real (tiempos por tramo + trazado para el
   mapa). Si OSRM no responde, cae a una estimación con distancia en línea
   recta — el plan nunca falla por culpa del servicio de rutas.
3. `plan_itinerary`: junta todo (orden -> tiempos de traslado -> horarios).

OSRM público (router.project-osrm.org) es un servidor de demostración: sirve
para este proyecto, pero en producción real conviene uno propio o la Routes
API de Google. Solo calcula en auto; para tramos cortos en ciudad el tiempo es
una aproximación razonable."""

from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from app.agents.scheduling import assign_schedule
from app.agents.tools import haversine_m

logger = logging.getLogger(__name__)

OSRM_BASE = "http://router.project-osrm.org/route/v1/driving"
OSRM_TIMEOUT_S = 4.0
MIN_TRAVEL_MINUTES = 5
CITY_SPEED_KMH = 25.0  # velocidad media urbana para la estimación de respaldo
DETOUR_FACTOR = 1.3  # las calles no son línea recta


def _round_up_5(minutes: float) -> int:
    return max(MIN_TRAVEL_MINUTES, int(-(-minutes // 5) * 5))


def estimate_travel_minutes(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    meters = haversine_m(lat1, lon1, lat2, lon2) * DETOUR_FACTOR
    return _round_up_5(meters / 1000 / CITY_SPEED_KMH * 60)


def optimize_day_order(stops: list[dict]) -> list[dict]:
    """Vecino más cercano partiendo de la primera parada (la mejor rankeada).
    Devuelve las mismas paradas con `order_index` reasignado 0..n-1."""
    if len(stops) <= 2:
        return stops
    remaining = sorted(stops, key=lambda s: s["order_index"])
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1]["place"]
        nxt = min(
            remaining,
            key=lambda s: haversine_m(last["latitude"], last["longitude"], s["place"]["latitude"], s["place"]["longitude"]),
        )
        remaining.remove(nxt)
        ordered.append(nxt)
    return [{**s, "order_index": i} for i, s in enumerate(ordered)]


@lru_cache(maxsize=256)
def _fetch_route_cached(coords: tuple[tuple[float, float], ...]) -> dict:
    """coords = ((lat, lon), ...). Cacheado: el mismo recorrido no se pide dos veces."""
    fallback = {
        "geometry": [[lat, lon] for lat, lon in coords],
        "legs_minutes": [
            estimate_travel_minutes(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:])
        ],
        "source": "estimate",
    }
    if len(coords) < 2:
        return fallback
    path = ";".join(f"{lon},{lat}" for lat, lon in coords)
    try:
        resp = httpx.get(
            f"{OSRM_BASE}/{path}",
            params={"overview": "full", "geometries": "geojson"},
            timeout=OSRM_TIMEOUT_S,
        )
        resp.raise_for_status()
        route = resp.json()["routes"][0]
        return {
            "geometry": [[lat, lon] for lon, lat in route["geometry"]["coordinates"]],
            "legs_minutes": [_round_up_5(leg["duration"] / 60) for leg in route["legs"]],
            "source": "osrm",
        }
    except Exception as exc:  # red caída, timeout, respuesta inesperada...
        logger.warning("OSRM no disponible, uso estimación: %s", exc)
        return fallback


def fetch_route(points: list[tuple[float, float]]) -> dict:
    """points: [(lat, lon), ...] en el orden de visita. Devuelve
    {"geometry": [[lat, lon], ...], "legs_minutes": [...], "source": "osrm"|"estimate"}."""
    return _fetch_route_cached(tuple((round(lat, 6), round(lon, 6)) for lat, lon in points))


def annotate_travel(stops: list[dict]) -> list[dict]:
    """Agrega `travel_minutes` (desde la parada anterior del mismo día) a cada
    parada menos la primera de cada día. No muta la lista original."""
    by_day: dict[int, list[dict]] = {}
    for s in stops:
        by_day.setdefault(s["day_number"], []).append(s)

    result = []
    for day_stops in by_day.values():
        day_stops = sorted(day_stops, key=lambda s: s["order_index"])
        route = fetch_route([(s["place"]["latitude"], s["place"]["longitude"]) for s in day_stops])
        for i, s in enumerate(day_stops):
            leg = None if i == 0 else route["legs_minutes"][i - 1]
            result.append({**s, "travel_minutes": leg})
    return result


def plan_itinerary(stops: list[dict], optimize: bool = True) -> list[dict]:
    """Paradas con day_number/order_index/place -> paradas con orden
    optimizado (opcional), tiempos de traslado y horarios."""
    if optimize:
        by_day: dict[int, list[dict]] = {}
        for s in stops:
            by_day.setdefault(s["day_number"], []).append(s)
        stops = [s for day in by_day.values() for s in optimize_day_order(day)]
    return assign_schedule(annotate_travel(stops))
