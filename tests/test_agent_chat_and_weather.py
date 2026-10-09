"""Agente conversacional (chat que modifica el plan) y ajuste por clima."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import assistant
from app.db import repository
from app.db.session import Base, get_db
from app.main import app


def _place(pid, name, category, lat=10.40, lon=-75.55):
    return {
        "id": pid, "name": name, "category": category, "latitude": lat, "longitude": lon,
        "avg_rating": 4.5, "price_level": 2, "open_now": True, "review_sentiment": "positivo",
        "review_topics": [], "score": 0.8, "reason": f"Te recomendamos {name}.",
    }


@pytest.fixture
def ctx(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override

    db = Session()
    stops = [
        {"day_number": 1, "order_index": 0, "scheduled_time": None, "place": _place("a", "Restaurante Nami", "gastronomía")},
        {"day_number": 1, "order_index": 1, "scheduled_time": None, "place": _place("b", "Museo Naval", "cultura", 10.41, -75.54)},
        {"day_number": 2, "order_index": 0, "scheduled_time": None, "place": _place("c", "Playa Blanca", "naturaleza", 10.39, -75.56)},
        {"day_number": 2, "order_index": 1, "scheduled_time": None, "place": _place("d", "Café del Mar", "gastronomía", 10.40, -75.55)},
    ]
    plan = repository.save_trip_plan(db, "demo", "Cartagena", stops)
    plan_id = plan.id
    db.close()

    def set_llm(payload):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content=payload if isinstance(payload, str) else json.dumps(payload))
        monkeypatch.setattr("app.agents.nodes._llm", lambda model=None: llm)

    yield TestClient(app), plan_id, set_llm
    app.dependency_overrides.clear()


def _names(plan):
    return {s["place"]["name"] for s in plan["stops"]}


def test_chat_removes_a_place_and_keeps_other_days(ctx):
    client, plan_id, set_llm = ctx
    set_llm({"reply": "Listo, quité el museo.", "actions": [{"type": "remove_place", "name": "museo naval"}]})
    res = client.post(f"/plan/{plan_id}/chat", json={"message": "quita el museo"}).json()
    assert res["plan_changed"] is True
    assert "Museo Naval" not in _names(res["plan"])
    days = {s["place"]["name"]: s["day_number"] for s in res["plan"]["stops"]}
    assert days["Playa Blanca"] == 2 and days["Restaurante Nami"] == 1  # nadie cambió de día
    assert res["reply"] == "Listo, quité el museo."


def test_chat_excludes_a_category(ctx):
    client, plan_id, set_llm = ctx
    set_llm({"reply": "Sin naturaleza.", "actions": [{"type": "exclude_category", "category": "naturaleza"}]})
    res = client.post(f"/plan/{plan_id}/chat", json={"message": "nada de naturaleza"}).json()
    assert "Playa Blanca" not in _names(res["plan"])
    assert len(res["plan"]["stops"]) == 3


def test_chat_reports_unknown_place_without_changing_plan(ctx):
    client, plan_id, set_llm = ctx
    set_llm({"reply": "Listo.", "actions": [{"type": "remove_place", "name": "Torre Eiffel"}]})
    res = client.post(f"/plan/{plan_id}/chat", json={"message": "quita la torre"}).json()
    assert res["plan_changed"] is False
    assert "Torre Eiffel" in res["reply"]
    assert len(res["plan"]["stops"]) == 4


def test_chat_ignores_actions_outside_the_whitelist(ctx):
    client, plan_id, set_llm = ctx
    set_llm({"reply": "ok", "actions": [{"type": "delete_everything"}, {"type": "exclude_category", "category": "inventada"}]})
    res = client.post(f"/plan/{plan_id}/chat", json={"message": "borra todo"}).json()
    assert res["plan_changed"] is False and len(res["plan"]["stops"]) == 4


def test_chat_survives_garbage_from_the_llm(ctx):
    client, plan_id, set_llm = ctx
    set_llm("esto no es json")
    res = client.post(f"/plan/{plan_id}/chat", json={"message": "hola"})
    assert res.status_code == 200 and res.json()["plan_changed"] is False


def test_chat_regenerate_builds_new_plan_with_new_filters(ctx, monkeypatch):
    client, plan_id, set_llm = ctx
    set_llm({"reply": "Más barato.", "actions": [{"type": "regenerate", "max_price_level": 1, "taste": {"gastronomía": 1.0}}]})
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = lambda state: {
        "taste_profile": state["taste_profile"],
        "plan_stops": [{"day_number": 1, "order_index": 0, "scheduled_time": "09:00-10:30", "place": _place("z", "Barato", "gastronomía")}],
        "_seen": state,
    }
    monkeypatch.setattr("app.api.plan.get_compiled_graph", lambda: fake_graph)
    context = {"traveler_id": "demo", "city": "Cartagena", "latitude": 10.4, "longitude": -75.55, "days": 1}
    res = client.post(f"/plan/{plan_id}/chat", json={"message": "algo más barato", "context": context}).json()
    state = fake_graph.invoke.call_args[0][0]
    assert state["max_price_level"] == 1 and state["taste_profile"]["gastronomía"] == 1.0
    assert res["plan_changed"] is True and _names(res["plan"]) == {"Barato"}
    assert res["plan"]["plan_id"] != plan_id


def test_sanitize_clamps_values():
    action = assistant._sanitize_action({"type": "regenerate", "min_rating": 9, "max_price_level": 7, "taste": {"cultura": 5, "x": 1}})
    assert action == {"type": "regenerate", "taste": {"cultura": 1.0}}


def test_weather_flags_and_removes_outdoor_stops_on_rainy_days(ctx, monkeypatch):
    client, plan_id, _ = ctx
    forecast = [
        {"day_number": 1, "date": "2026-10-09", "rain_probability": 10, "temp_max": 31.0, "rainy": False},
        {"day_number": 2, "date": "2026-10-10", "rain_probability": 85, "temp_max": 28.0, "rainy": True},
    ]
    monkeypatch.setattr("app.api.plan.fetch_daily_forecast", lambda lat, lon, days: forecast)

    weather = client.get(f"/plan/{plan_id}/weather").json()
    assert weather["available"] is True
    assert [r["name"] for r in weather["at_risk"]] == ["Playa Blanca"]

    adjusted = client.post(f"/plan/{plan_id}/weather-adjust").json()
    assert "Playa Blanca" not in _names(adjusted)
    assert len(adjusted["stops"]) == 3


def test_weather_unavailable_is_graceful(ctx, monkeypatch):
    client, plan_id, _ = ctx
    monkeypatch.setattr("app.api.plan.fetch_daily_forecast", lambda lat, lon, days: [])
    weather = client.get(f"/plan/{plan_id}/weather").json()
    assert weather["available"] is False and weather["at_risk"] == []
    assert len(client.post(f"/plan/{plan_id}/weather-adjust").json()["stops"]) == 4


def test_route_endpoint_returns_a_path_per_day(ctx):
    client, plan_id, _ = ctx
    routes = client.get(f"/plan/{plan_id}/route").json()
    assert [r["day_number"] for r in routes] == [1, 2]
    assert routes[0]["source"] == "estimate"  # sin red en tests
    assert len(routes[0]["geometry"]) >= 2
