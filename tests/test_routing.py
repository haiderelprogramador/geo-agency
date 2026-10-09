"""RF5: ruta real entre paradas — orden optimizado, traslados reales en el
horario y recorrido para el mapa, con respaldo si OSRM no responde."""

from unittest.mock import MagicMock

from sqlalchemy import create_engine, text

import app.agents.routing as routing
from app.agents.routing import annotate_travel, fetch_route, optimize_day_order, plan_itinerary
from app.db.session import ensure_columns


def _stop(day, order, lat, lon, category="gastronomía", name="x"):
    return {"day_number": day, "order_index": order, "place": {"latitude": lat, "longitude": lon, "category": category, "name": name}}


def test_optimize_day_order_visits_nearest_next():
    # A en el origen; C queda pegado a A; B lejísimos. Orden rankeado A,B,C -> A,C,B.
    a = _stop(1, 0, 10.00, -75.00, name="A")
    b = _stop(1, 1, 10.50, -75.50, name="B")
    c = _stop(1, 2, 10.001, -75.001, name="C")
    ordered = optimize_day_order([a, b, c])
    assert [s["place"]["name"] for s in ordered] == ["A", "C", "B"]
    assert [s["order_index"] for s in ordered] == [0, 1, 2]


def test_fetch_route_falls_back_to_estimate_when_osrm_fails():
    route = fetch_route([(10.0, -75.0), (10.01, -75.01)])  # conftest corta la red
    assert route["source"] == "estimate"
    assert route["geometry"] == [[10.0, -75.0], [10.01, -75.01]]
    assert len(route["legs_minutes"]) == 1 and route["legs_minutes"][0] >= 5


def test_fetch_route_parses_osrm_response(monkeypatch):
    fake = MagicMock()
    fake.json.return_value = {
        "routes": [
            {
                "geometry": {"coordinates": [[-75.0, 10.0], [-75.005, 10.005], [-75.01, 10.01]]},
                "legs": [{"duration": 14 * 60}],
            }
        ]
    }
    monkeypatch.setattr(routing.httpx, "get", lambda *a, **k: fake)
    route = fetch_route([(10.0, -75.0), (10.01, -75.01)])
    assert route["source"] == "osrm"
    assert route["geometry"][1] == [10.005, -75.005]  # OSRM manda [lon, lat]; se invierte
    assert route["legs_minutes"] == [15]  # 14 min -> redondeo hacia arriba a múltiplos de 5


def test_real_travel_time_shifts_the_schedule(monkeypatch):
    fake = MagicMock()
    fake.json.return_value = {"routes": [{"geometry": {"coordinates": [[-75.0, 10.0], [-75.1, 10.1]]}, "legs": [{"duration": 40 * 60}]}]}
    monkeypatch.setattr(routing.httpx, "get", lambda *a, **k: fake)
    stops = plan_itinerary([_stop(1, 0, 10.0, -75.0), _stop(1, 1, 10.1, -75.1)], optimize=False)
    by_order = sorted(stops, key=lambda s: s["order_index"])
    assert by_order[0]["scheduled_time"] == "09:00-10:30"
    assert by_order[1]["travel_minutes"] == 40
    assert by_order[1]["scheduled_time"].startswith("11:10")  # 10:30 + 40 min de traslado


def test_first_stop_of_each_day_has_no_travel():
    stops = annotate_travel([_stop(1, 0, 10.0, -75.0), _stop(1, 1, 10.01, -75.01), _stop(2, 0, 10.0, -75.0)])
    firsts = [s for s in stops if s["order_index"] == 0]
    assert all(s["travel_minutes"] is None for s in firsts)


def test_ensure_columns_adds_travel_minutes_to_old_database():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE plan_stops (id TEXT PRIMARY KEY, plan_id TEXT)"))
    ensure_columns(engine)
    ensure_columns(engine)  # idempotente
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(plan_stops)"))}
    assert "travel_minutes" in cols
