"""Pruebas unitarias de los nodos que no dependen de llamadas al LLM
(perfil, descubrimiento, ranking) — analyze_reviews sí llama a Anthropic y
se prueba aparte con la API key configurada."""

from app.agents.nodes import build_taste_profile, discover_places, rank_places
from app.agents.tools import haversine_m


def test_haversine_zero_distance():
    assert haversine_m(10.4, -75.5, 10.4, -75.5) == 0


def test_haversine_known_distance_is_positive():
    # Bocagrande vs Getsemaní, Cartagena — deben quedar a un par de km
    d = haversine_m(10.3997, -75.5548, 10.4236, -75.5486)
    assert 1000 < d < 6000


def test_build_taste_profile_defaults_when_none():
    state = {"taste_profile": None}
    result = build_taste_profile(state)
    assert "gastronomía" in result["taste_profile"]


def test_discover_places_filters_by_profile_categories():
    state = {
        "taste_profile": {"gastronomía": 0.9, "vida_nocturna": 0.0},
        "latitude": 10.4,
        "longitude": -75.55,
        "radius_m": 2000,
    }
    result = discover_places(state)
    categories = {p["category"] for p in result["candidate_places"]}
    assert "vida_nocturna" not in categories


def test_rank_places_orders_by_score_descending():
    state = {
        "taste_profile": {"gastronomía": 0.9, "cultura": 0.1},
        "latitude": 10.4,
        "longitude": -75.55,
        "radius_m": 2000,
        "candidate_places": [
            {
                "id": "a",
                "name": "Restaurante afín",
                "category": "gastronomía",
                "latitude": 10.4005,
                "longitude": -75.5505,
                "avg_rating": 4.5,
                "review_sentiment": "positivo",
                "review_topics": [],
                "score": None,
                "reason": None,
            },
            {
                "id": "b",
                "name": "Museo lejano",
                "category": "cultura",
                "latitude": 10.42,
                "longitude": -75.53,
                "avg_rating": 4.5,
                "review_sentiment": "neutro",
                "review_topics": [],
                "score": None,
                "reason": None,
            },
        ],
    }
    result = rank_places(state)
    scores = [p["score"] for p in result["ranked_places"]]
    assert scores == sorted(scores, reverse=True)
    assert result["ranked_places"][0]["id"] == "a"
