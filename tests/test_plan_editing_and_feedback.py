"""RF6 (editar plan a mano), RF8 (filtro de rating), RF10 (feedback que
retroalimenta el perfil) y RF11 (explicaciones en el idioma pedido)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.nodes import _explain, discover_places
from app.db import repository
from app.db.session import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


def _place(place_id: str, name: str, category: str, score: float, rating: float = 4.5, price_level=None, open_now=None) -> dict:
    return {
        "id": place_id,
        "name": name,
        "category": category,
        "latitude": 10.4,
        "longitude": -75.55,
        "avg_rating": rating,
        "price_level": price_level,
        "open_now": open_now,
        "review_sentiment": "positivo",
        "review_topics": [],
        "score": score,
        "reason": f"Te recomendamos {name}.",
    }


@pytest.fixture
def seeded_plan(db):
    stops = [
        {"day_number": 1, "order_index": 0, "scheduled_time": None, "place": _place("g1", "Restaurante A", "gastronomía", 0.9)},
        {"day_number": 1, "order_index": 1, "scheduled_time": None, "place": _place("g2", "Museo B", "cultura", 0.8)},
        {"day_number": 2, "order_index": 0, "scheduled_time": None, "place": _place("g3", "Playa C", "naturaleza", 0.7)},
    ]
    return repository.save_trip_plan(db, traveler_id="demo", city="Cartagena", plan_stops=stops)


# --- RF6: editar plan --------------------------------------------------------

def test_remove_stop(db, seeded_plan):
    updated = repository.remove_stop(db, seeded_plan, "g2")
    remaining = {s.place.external_id for s in updated.stops}
    assert remaining == {"g1", "g3"}


def test_reorder_stops(db, seeded_plan):
    updated = repository.reorder_stops(db, seeded_plan, ["g3", "g1", "g2"])
    ordered = sorted(updated.stops, key=lambda s: (s.day_number, s.order_index))
    assert [s.place.external_id for s in ordered][0] == "g3"


def test_reorder_rejects_missing_or_extra_ids(db, seeded_plan):
    with pytest.raises(ValueError):
        repository.reorder_stops(db, seeded_plan, ["g1", "g2"])  # falta g3
    with pytest.raises(ValueError):
        repository.reorder_stops(db, seeded_plan, ["g1", "g2", "g3", "no-existe"])


# --- RF8: filtro de rating mínimo --------------------------------------------

def test_discover_places_filters_by_min_rating(monkeypatch):
    fake_places = [
        _place("a", "Alto rating", "gastronomía", None, rating=4.8),
        _place("b", "Bajo rating", "gastronomía", None, rating=3.0),
    ]
    monkeypatch.setattr("app.agents.nodes.search_nearby_places", lambda **kwargs: fake_places)

    state = {
        "taste_profile": {"gastronomía": 0.9},
        "latitude": 10.4, "longitude": -75.55, "radius_m": 2000,
        "min_rating": 4.0,
    }
    result = discover_places(state)
    names = {p["name"] for p in result["candidate_places"]}
    assert names == {"Alto rating"}


def test_discover_places_filters_by_max_price_level(monkeypatch):
    fake_places = [
        _place("a", "Barato", "gastronomía", None, price_level=1),
        _place("b", "Caro", "gastronomía", None, price_level=4),
        _place("c", "Sin dato", "gastronomía", None, price_level=None),
    ]
    monkeypatch.setattr("app.agents.nodes.search_nearby_places", lambda **kwargs: fake_places)

    state = {
        "taste_profile": {"gastronomía": 0.9},
        "latitude": 10.4, "longitude": -75.55, "radius_m": 2000,
        "max_price_level": 2,
    }
    result = discover_places(state)
    names = {p["name"] for p in result["candidate_places"]}
    # "Sin dato" no se descarta por falta de información — solo se filtra
    # lo que SÍ sabemos que excede el presupuesto.
    assert names == {"Barato", "Sin dato"}


def test_discover_places_filters_by_open_now(monkeypatch):
    fake_places = [
        _place("a", "Abierto", "gastronomía", None, open_now=True),
        _place("b", "Cerrado", "gastronomía", None, open_now=False),
        _place("c", "Sin horario", "gastronomía", None, open_now=None),
    ]
    monkeypatch.setattr("app.agents.nodes.search_nearby_places", lambda **kwargs: fake_places)

    state = {
        "taste_profile": {"gastronomía": 0.9},
        "latitude": 10.4, "longitude": -75.55, "radius_m": 2000,
        "open_now": True,
    }
    result = discover_places(state)
    names = {p["name"] for p in result["candidate_places"]}
    assert names == {"Abierto", "Sin horario"}


def test_discover_places_without_min_rating_keeps_everything(monkeypatch):
    fake_places = [
        _place("a", "Alto rating", "gastronomía", None, rating=4.8),
        _place("b", "Bajo rating", "gastronomía", None, rating=3.0),
    ]
    monkeypatch.setattr("app.agents.nodes.search_nearby_places", lambda **kwargs: fake_places)

    state = {
        "taste_profile": {"gastronomía": 0.9},
        "latitude": 10.4, "longitude": -75.55, "radius_m": 2000,
        "min_rating": None,
    }
    result = discover_places(state)
    assert len(result["candidate_places"]) == 2


# --- RF10: feedback retroalimenta el perfil ----------------------------------

def test_feedback_liked_increases_category_weight(db, seeded_plan):
    traveler = repository.get_or_create_traveler(db, "demo")
    traveler.taste_profile = {"gastronomía": 0.5}
    db.commit()

    updated = repository.save_feedback(db, "demo", "g1", liked=True, note="me encantó")
    assert updated.taste_profile["gastronomía"] > 0.5


def test_feedback_disliked_decreases_category_weight(db, seeded_plan):
    traveler = repository.get_or_create_traveler(db, "demo")
    traveler.taste_profile = {"cultura": 0.5}
    db.commit()

    updated = repository.save_feedback(db, "demo", "g2", liked=False, note=None)
    assert updated.taste_profile["cultura"] < 0.5


def test_feedback_weight_is_clamped_between_0_and_1(db, seeded_plan):
    traveler = repository.get_or_create_traveler(db, "demo")
    traveler.taste_profile = {"gastronomía": 0.98}
    db.commit()
    updated = repository.save_feedback(db, "demo", "g1", liked=True, note=None)
    assert updated.taste_profile["gastronomía"] <= 1.0


def test_feedback_on_unknown_place_raises(db):
    with pytest.raises(ValueError):
        repository.save_feedback(db, "demo", "no-existe", liked=True, note=None)


# --- RF11: explicación en el idioma pedido -----------------------------------

def test_explain_in_spanish_by_default():
    place = _place("g1", "Restaurante A", "gastronomía", 0.9)
    place["review_sentiment"] = "positivo"
    text = _explain(place, {"gastronomía": 0.9})
    assert "recomendamos" in text


def test_explain_in_english_when_requested():
    place = _place("g1", "Restaurante A", "gastronomía", 0.9)
    place["review_sentiment"] = "positivo"
    text = _explain(place, {"gastronomía": 0.9}, language="en")
    assert "recommend" in text
