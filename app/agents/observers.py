"""Patrón Observer: recalcula el plan de viaje cuando cambian las
condiciones (un lugar cerró, mal clima...) — ver docs/patrones-diseno.md.

`PlanContextSubject` es el sujeto observable: no sabe nada de SQLAlchemy ni
de itinerarios, solo mantiene una lista de observadores y los notifica. Hoy
el único observador suscrito recalcula el itinerario, pero el punto del
patrón es poder sumar otros (loggear, avisar al usuario, recalcular el
perfil) sin tocar esta clase ni el endpoint que dispara el evento."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.agents.scheduling import assign_schedule
from app.db import repository
from app.db.models import TripPlan


@dataclass
class ContextEvent:
    """Un cambio de contexto reportado sobre un plan ya generado."""

    plan_id: str
    event_type: str  # "place_closed" | "category_unavailable" (ej. mal clima)
    place_external_id: str | None = None  # para "place_closed"
    category: str | None = None  # para "category_unavailable"
    reason: str | None = None  # texto libre para la bitácora (ej. "lluvia fuerte")


Observer = Callable[[ContextEvent], None]


class PlanContextSubject:
    """Sujeto observable del patrón Observer."""

    def __init__(self) -> None:
        self._observers: list[Observer] = []

    def subscribe(self, observer: Observer) -> None:
        self._observers.append(observer)

    def notify(self, event: ContextEvent) -> None:
        for observer in self._observers:
            observer(event)


def _repack_stops_without(ranked_places: list[dict], days: int) -> list[dict]:
    """Reconstruye las paradas del itinerario a partir de los lugares que
    sobreviven al evento de contexto, repartidos en los mismos `days` del
    plan original (misma lógica round-robin que build_itinerary)."""
    stops = [{"day_number": (i % days) + 1, "order_index": i // days, "place": place} for i, place in enumerate(ranked_places)]
    return assign_schedule(stops)


def make_recalculate_observer(db) -> Observer:
    """Fábrica del observador principal: dado un ContextEvent, recalcula y
    persiste el plan afectado. Recibe la Session ya abierta del request
    (misma transacción que el resto del endpoint)."""

    def on_context_event(event: ContextEvent) -> None:
        trip_plan: TripPlan | None = repository.get_trip_plan(db, event.plan_id)
        if trip_plan is None:
            return

        days = max((stop.day_number for stop in trip_plan.stops), default=1)

        if event.event_type == "place_closed" and event.place_external_id:
            repository.mark_place_closed(db, event.place_external_id)
            survivors = [
                repository.stop_to_place_dict(stop)
                for stop in sorted(trip_plan.stops, key=lambda s: (s.score or 0), reverse=True)
                if stop.place.external_id != event.place_external_id
            ]
        elif event.event_type == "category_unavailable" and event.category:
            survivors = [
                repository.stop_to_place_dict(stop)
                for stop in sorted(trip_plan.stops, key=lambda s: (s.score or 0), reverse=True)
                if stop.place.category != event.category
            ]
        else:
            return

        new_stops = _repack_stops_without(survivors, days)
        repository.replace_trip_plan_stops(db, trip_plan, new_stops)
        repository.log_agent_event(
            db,
            traveler_id=trip_plan.traveler_id,
            agent="itinerario",
            event_type=f"recalculo:{event.event_type}",
            payload={
                "plan_id": event.plan_id,
                "place_external_id": event.place_external_id,
                "category": event.category,
                "reason": event.reason,
                "stops_restantes": len(new_stops),
            },
        )

    return on_context_event
