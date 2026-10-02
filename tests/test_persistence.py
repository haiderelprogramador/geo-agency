"""Pruebas del repositorio (capa de persistencia) usando SQLite en memoria —
no dependen de archivos ni de la configuración real de la app."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import repository
from app.db.session import Base


@pytest.fixture
def db():
    # Una base en memoria nueva por test: aislada, rápida, sin tocar disco.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


def _sample_place(place_id: str, name: str, category: str) -> dict:
    return {
        "id": place_id,
        "name": name,
        "category": category,
        "latitude": 10.4,
        "longitude": -75.55,
        "avg_rating": 4.5,
        "review_sentiment": "positivo",
        "review_topics": ["buena atención"],
        "score": 0.8,
        "reason": f"Te recomendamos {name}.",
    }


def test_get_or_create_traveler_is_idempotent(db):
    t1 = repository.get_or_create_traveler(db, "demo")
    t2 = repository.get_or_create_traveler(db, "demo")
    assert t1.id == t2.id


def test_save_trip_plan_persists_stops_and_places(db):
    plan_stops = [
        {"day_number": 1, "order_index": 0, "scheduled_time": None, "place": _sample_place("g1", "Restaurante X", "gastronomía")},
        {"day_number": 1, "order_index": 1, "scheduled_time": None, "place": _sample_place("g2", "Museo Y", "cultura")},
    ]
    trip_plan = repository.save_trip_plan(db, traveler_id="demo", city="Cartagena", plan_stops=plan_stops)

    assert trip_plan.id is not None
    assert len(trip_plan.stops) == 2
    assert {s.place.external_id for s in trip_plan.stops} == {"g1", "g2"}
    assert trip_plan.stops[0].score == 0.8
    assert trip_plan.stops[0].review_sentiment == "positivo"


def test_upsert_place_does_not_duplicate_same_external_id(db):
    place = _sample_place("g1", "Restaurante X", "gastronomía")
    first = repository.upsert_place(db, place, city="Cartagena")
    updated_place = {**place, "avg_rating": 5.0}
    second = repository.upsert_place(db, updated_place, city="Cartagena")

    assert first.id == second.id
    assert second.avg_rating == 5.0


def test_list_trip_plans_returns_only_that_traveler(db):
    repository.save_trip_plan(
        db, traveler_id="demo", city="Cartagena",
        plan_stops=[{"day_number": 1, "order_index": 0, "scheduled_time": None, "place": _sample_place("g1", "A", "gastronomía")}],
    )
    repository.save_trip_plan(
        db, traveler_id="otro", city="Bogotá",
        plan_stops=[{"day_number": 1, "order_index": 0, "scheduled_time": None, "place": _sample_place("g2", "B", "cultura")}],
    )

    plans = repository.list_trip_plans(db, "demo")
    assert len(plans) == 1
    assert plans[0].city == "Cartagena"


def test_get_trip_plan_returns_none_when_missing(db):
    assert repository.get_trip_plan(db, "no-existe") is None
