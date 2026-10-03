"""El formulario ahora le pregunta a la persona sus gustos en cada búsqueda
(en vez de depender solo del perfil que quedó guardado de una vez anterior).
Verifica que /plan/generate le dé prioridad al taste_profile que llega en el
request sobre el que ya tiene guardado el traveler."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import repository
from app.db.session import Base, get_db
from app.main import app


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # No se necesita LLM/Google real: el grafo completo se reemplaza por uno
    # falso que solo devuelve el taste_profile que recibió, para comprobar
    # cuál ganó sin pagar una llamada real.
    fake_graph = MagicMock()
    fake_graph.invoke.side_effect = lambda state: {
        "taste_profile": state["taste_profile"],
        "plan_stops": [],
    }
    monkeypatch.setattr("app.api.plan.get_compiled_graph", lambda: fake_graph)

    db = TestingSession()
    try:
        traveler = repository.get_or_create_traveler(db, "demo")
        traveler.taste_profile = {"cultura": 0.9}
        db.commit()
    finally:
        db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def _base_payload(**overrides):
    payload = {
        "traveler_id": "demo",
        "city": "Cartagena",
        "latitude": 10.4,
        "longitude": -75.55,
    }
    payload.update(overrides)
    return payload


def test_explicit_taste_profile_overrides_saved_one(client):
    response = client.post(
        "/plan/generate",
        json=_base_payload(taste_profile={"gastronomía": 0.9, "vida_nocturna": 0.1}),
    )
    assert response.status_code == 200
    assert response.json()["taste_profile"] == {"gastronomía": 0.9, "vida_nocturna": 0.1}


def test_missing_taste_profile_falls_back_to_saved_one(client):
    response = client.post("/plan/generate", json=_base_payload())
    assert response.status_code == 200
    assert response.json()["taste_profile"] == {"cultura": 0.9}
