"""Los tests no deben depender de internet: OSRM se corta por defecto y el
código cae a la estimación por distancia (el mismo camino que usa en
producción cuando OSRM no responde). Los tests de routing que quieran
simular una respuesta de OSRM sobrescriben esto con su propio monkeypatch."""

import pytest

import app.agents.routing as routing


@pytest.fixture(autouse=True)
def _no_network_for_routing(monkeypatch):
    def _offline(*args, **kwargs):
        raise ConnectionError("sin red en tests")

    monkeypatch.setattr(routing.httpx, "get", _offline)
    routing._fetch_route_cached.cache_clear()
    yield
    routing._fetch_route_cached.cache_clear()
