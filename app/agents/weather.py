"""Clima real para el agente (Open-Meteo: gratis y sin API key).

Si el servicio no responde devuelve una lista vacía y el resto de la app
sigue igual — el clima es un extra del agente, nunca un requisito."""

from __future__ import annotations

import logging
from datetime import date
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 5.0
RAIN_THRESHOLD_PCT = 60  # a partir de esta probabilidad el día cuenta como lluvioso
OUTDOOR_CATEGORIES = {"naturaleza"}  # categorías que se arruinan con lluvia (ver tools.CATEGORY_TO_GOOGLE_TYPES)
MAX_FORECAST_DAYS = 16  # límite del pronóstico de Open-Meteo


@lru_cache(maxsize=64)
def _fetch_cached(lat: float, lon: float, days: int, today: str) -> tuple:
    """`today` va en la clave para que el caché no sobreviva al cambio de día."""
    resp = httpx.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "precipitation_probability_max,temperature_2m_max",
            "forecast_days": min(max(days, 1), MAX_FORECAST_DAYS),
            "timezone": "auto",
        },
        timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]
    out = []
    for i, day in enumerate(daily["time"]):
        rain = daily["precipitation_probability_max"][i]
        temp = daily["temperature_2m_max"][i]
        out.append(
            {
                "day_number": i + 1,
                "date": day,
                "rain_probability": rain,
                "temp_max": temp,
                "rainy": rain is not None and rain >= RAIN_THRESHOLD_PCT,
            }
        )
    return tuple(tuple(d.items()) for d in out)


def fetch_daily_forecast(lat: float, lon: float, days: int) -> list[dict]:
    """Pronóstico día a día; el día 1 del plan es hoy. Los fallos NO se
    cachean (la excepción atraviesa lru_cache), así un error puntual no deja
    el clima caído todo el día."""
    try:
        raw = _fetch_cached(round(lat, 2), round(lon, 2), days, date.today().isoformat())
    except Exception as exc:
        logger.warning("Open-Meteo no disponible: %s", exc)
        return []
    return [dict(item) for item in raw]


def outdoor_stops_on_rainy_days(stops: list[dict], forecast: list[dict]) -> list[dict]:
    """stops: dicts con day_number y place{id,name,category}. Devuelve los que
    están al aire libre en un día con lluvia probable."""
    rainy_days = {f["day_number"] for f in forecast if f["rainy"]}
    return [
        s
        for s in stops
        if s["day_number"] in rainy_days and s["place"]["category"] in OUTDOOR_CATEGORIES
    ]
