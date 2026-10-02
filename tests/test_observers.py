"""Pruebas del patrón Observer: recálculo del plan ante cambios de contexto
(lugar cerrado, categoría no disponible por mal clima)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.observers import ContextEvent, PlanContextSubject, make_recalculate_observer
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


def _place(place_id: str, name: str, category: str, score: float) -> dict:
    return {
        "id": place_id,
        "name": name,
        "category": category,
        "latitude": 10.4,
        "longitude": -75.55,
        "avg_rating": 4.5,
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


def test_place_closed_event_removes_it_and_marks_closed(db, seeded_plan):
    subject = PlanContextSubject()
    subject.subscribe(make_recalculate_observer(db))

    subject.notify(ContextEvent(plan_id=seeded_plan.id, event_type="place_closed", place_external_id="g1"))

    db.refresh(seeded_plan)
    remaining_ids = {stop.place.external_id for stop in seeded_plan.stops}
    assert remaining_ids == {"g2", "g3"}

    closed_place = repository.upsert_place(db, _place("g1", "Restaurante A", "gastronomía", 0.9), city="Cartagena")
    assert closed_place.is_open is False


def test_category_unavailable_event_drops_whole_category(db, seeded_plan):
    subject = PlanContextSubject()
    subject.subscribe(make_recalculate_observer(db))

    subject.notify(ContextEvent(plan_id=seeded_plan.id, event_type="category_unavailable", category="naturaleza", reason="lluvia fuerte"))

    db.refresh(seeded_plan)
    categories = {stop.place.category for stop in seeded_plan.stops}
    assert "naturaleza" not in categories
    assert len(seeded_plan.stops) == 2


def test_recalculate_logs_agent_event(db, seeded_plan):
    subject = PlanContextSubject()
    subject.subscribe(make_recalculate_observer(db))
    subject.notify(ContextEvent(plan_id=seeded_plan.id, event_type="place_closed", place_external_id="g1"))

    from app.db.models import AgentEventLog

    events = db.query(AgentEventLog).all()
    assert len(events) == 1
    assert events[0].event_type == "recalculo:place_closed"
    assert events[0].payload["stops_restantes"] == 2


def test_unknown_event_type_is_a_noop(db, seeded_plan):
    subject = PlanContextSubject()
    subject.subscribe(make_recalculate_observer(db))
    subject.notify(ContextEvent(plan_id=seeded_plan.id, event_type="algo_raro"))

    db.refresh(seeded_plan)
    assert len(seeded_plan.stops) == 3
