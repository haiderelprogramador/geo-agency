"""Repositorio de persistencia (patrón Repository): aísla al resto de la app
de los detalles de SQLAlchemy. El endpoint /plan/generate y cualquier otro
consumidor solo llaman estas funciones, nunca tocan la Session directamente.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.scheduling import assign_schedule
from app.agents.state import Place as PlaceState
from app.db.models import AgentEventLog, Feedback, Place as PlaceModel
from app.db.models import PlanStop, Traveler, TripPlan

# RF10: cuánto se ajusta el peso de una categoría por cada feedback — subir
# rápido en "me gustó" y bajar más fuerte en "no me gustó" (evitar volver a
# recomendar algo que ya rechazaron pesa más que seguir reforzando lo que
# ya les gusta).
FEEDBACK_LIKE_DELTA = 0.05
FEEDBACK_DISLIKE_DELTA = -0.1


def get_or_create_traveler(db: Session, traveler_id: str) -> Traveler:
    """Los traveler_id de hoy vienen del cliente (no hay login todavía, RF1
    pendiente); si no existe el registro lo creamos con perfil vacío."""
    traveler = db.get(Traveler, traveler_id)
    if traveler is None:
        traveler = Traveler(id=traveler_id)
        db.add(traveler)
        db.flush()
    return traveler


def upsert_place(db: Session, place: PlaceState, city: str) -> PlaceModel:
    """Un Place del pipeline (en memoria, viene de Google Places) se guarda
    o actualiza por external_id — así no duplicamos el mismo lugar entre
    distintos planes/búsquedas (RNF: consistencia de datos)."""
    existing = db.scalar(
        select(PlaceModel).where(
            PlaceModel.external_source == "google_places",
            PlaceModel.external_id == place["id"],
        )
    )
    # .get() en vez de [] para price_level/open_now: son campos nuevos (RF8)
    # y dicts de Place más viejos (ej. tests existentes) pueden no traerlos.
    price_level = place.get("price_level")
    opening_hours = {"open_now": place["open_now"]} if place.get("open_now") is not None else None

    if existing:
        existing.name = place["name"]
        existing.category = place["category"]
        existing.latitude = place["latitude"]
        existing.longitude = place["longitude"]
        existing.avg_rating = place["avg_rating"]
        existing.price_level = price_level
        existing.opening_hours = opening_hours
        return existing

    model = PlaceModel(
        external_source="google_places",
        external_id=place["id"],
        name=place["name"],
        category=place["category"],
        latitude=place["latitude"],
        longitude=place["longitude"],
        city=city,
        avg_rating=place["avg_rating"],
        price_level=price_level,
        opening_hours=opening_hours,
    )
    db.add(model)
    db.flush()
    return model


def save_trip_plan(db: Session, traveler_id: str, city: str, plan_stops: list[dict]) -> TripPlan:
    """Guarda el itinerario generado por el pipeline: un TripPlan con sus
    PlanStop (Composite día -> parada -> lugar). Hace upsert de cada Place
    referenciado para no perder el historial de lugares vistos."""
    get_or_create_traveler(db, traveler_id)

    trip_plan = TripPlan(traveler_id=traveler_id, city=city, status="draft")
    db.add(trip_plan)
    db.flush()

    for stop in plan_stops:
        place_model = upsert_place(db, stop["place"], city)
        db.add(
            PlanStop(
                plan_id=trip_plan.id,
                place_id=place_model.id,
                day_number=stop["day_number"],
                order_index=stop["order_index"],
                scheduled_time=stop.get("scheduled_time"),
                reason=stop["place"].get("reason"),
                score=stop["place"].get("score"),
                review_sentiment=stop["place"].get("review_sentiment"),
            )
        )

    db.commit()
    db.refresh(trip_plan)
    return trip_plan


def get_trip_plan(db: Session, plan_id: str) -> TripPlan | None:
    return db.get(TripPlan, plan_id)


def list_trip_plans(db: Session, traveler_id: str) -> list[TripPlan]:
    return list(
        db.scalars(
            select(TripPlan).where(TripPlan.traveler_id == traveler_id).order_by(TripPlan.created_at.desc())
        )
    )


def mark_place_closed(db: Session, external_id: str) -> PlaceModel | None:
    """Flag manual de contexto: un lugar se reporta cerrado. Dispara el
    recálculo (Observer) de cualquier plan que lo incluya."""
    place = db.scalar(
        select(PlaceModel).where(
            PlaceModel.external_source == "google_places",
            PlaceModel.external_id == external_id,
        )
    )
    if place:
        place.is_open = False
        db.flush()
    return place


def replace_trip_plan_stops(db: Session, trip_plan: TripPlan, plan_stops: list[dict]) -> TripPlan:
    """Sustituye las paradas de un plan ya existente — usado por el
    recálculo dinámico (Observer): se descartan las paradas viejas y se
    guardan las nuevas, sin crear un TripPlan distinto (mismo plan_id)."""
    for old_stop in list(trip_plan.stops):
        db.delete(old_stop)
    db.flush()

    for stop in plan_stops:
        place_model = upsert_place(db, stop["place"], trip_plan.city)
        db.add(
            PlanStop(
                plan_id=trip_plan.id,
                place_id=place_model.id,
                day_number=stop["day_number"],
                order_index=stop["order_index"],
                scheduled_time=stop.get("scheduled_time"),
                reason=stop["place"].get("reason"),
                score=stop["place"].get("score"),
                review_sentiment=stop["place"].get("review_sentiment"),
            )
        )

    db.commit()
    db.refresh(trip_plan)
    return trip_plan


def stop_to_place_dict(stop: PlanStop) -> dict:
    return {
        "id": stop.place.external_id,
        "name": stop.place.name,
        "category": stop.place.category,
        "latitude": stop.place.latitude,
        "longitude": stop.place.longitude,
        "avg_rating": stop.place.avg_rating,
        "price_level": stop.place.price_level,
        "open_now": (stop.place.opening_hours or {}).get("open_now"),
        "review_sentiment": stop.review_sentiment,
        "review_topics": [],
        "score": stop.score,
        "reason": stop.reason,
    }


def remove_stop(db: Session, trip_plan: TripPlan, place_external_id: str) -> TripPlan:
    """RF6: el usuario quita una parada a mano (distinto de un lugar que se
    reporta cerrado, PlanContextSubject — ahí sí queda marcado globalmente;
    acá solo se saca de ESTE plan)."""
    days = max((s.day_number for s in trip_plan.stops), default=1)
    survivors = [
        stop_to_place_dict(s)
        for s in sorted(trip_plan.stops, key=lambda s: (s.day_number, s.order_index))
        if s.place.external_id != place_external_id
    ]
    new_stops = assign_schedule(
        [{"day_number": (i % days) + 1, "order_index": i // days, "place": p} for i, p in enumerate(survivors)]
    )
    return replace_trip_plan_stops(db, trip_plan, new_stops)


def reorder_stops(db: Session, trip_plan: TripPlan, ordered_place_external_ids: list[str]) -> TripPlan:
    """RF6: el usuario define el orden que quiere para las paradas de este
    plan. Se mantiene la misma cantidad de días del plan original,
    repartiendo la nueva secuencia round-robin entre ellos."""
    days = max((s.day_number for s in trip_plan.stops), default=1)
    by_external_id = {s.place.external_id: s for s in trip_plan.stops}

    missing = [pid for pid in ordered_place_external_ids if pid not in by_external_id]
    if missing:
        raise ValueError(f"Estos lugares no están en el plan: {missing}")
    if len(ordered_place_external_ids) != len(trip_plan.stops):
        raise ValueError("El nuevo orden debe incluir todas las paradas del plan, sin repetir.")

    ordered_places = [stop_to_place_dict(by_external_id[pid]) for pid in ordered_place_external_ids]
    new_stops = assign_schedule(
        [{"day_number": (i % days) + 1, "order_index": i // days, "place": p} for i, p in enumerate(ordered_places)]
    )
    return replace_trip_plan_stops(db, trip_plan, new_stops)


def log_agent_event(db: Session, traveler_id: str | None, agent: str, event_type: str, payload: dict) -> None:
    """Bitácora de auditoría (RNF9) — qué disparó un recálculo y qué cambió."""
    db.add(AgentEventLog(traveler_id=traveler_id, agent=agent, event_type=event_type, payload=payload))
    db.commit()


def save_feedback(db: Session, traveler_id: str, place_external_id: str, liked: bool, note: str | None) -> Traveler:
    """RF10: guarda el feedback y retroalimenta el taste_profile del
    traveler — sube o baja el peso de la categoría de ESE lugar. Memoria de
    largo plazo (RF1): la próxima vez que genere un plan, build_taste_profile
    reusa este perfil ya ajustado."""
    traveler = get_or_create_traveler(db, traveler_id)
    place = db.scalar(
        select(PlaceModel).where(
            PlaceModel.external_source == "google_places",
            PlaceModel.external_id == place_external_id,
        )
    )
    if place is None:
        raise ValueError(f"Lugar desconocido: {place_external_id} (nunca se recomendó en un plan)")

    db.add(Feedback(traveler_id=traveler_id, place_id=place.id, liked=liked, note=note))

    profile = dict(traveler.taste_profile or {})
    delta = FEEDBACK_LIKE_DELTA if liked else FEEDBACK_DISLIKE_DELTA
    current = profile.get(place.category, 0.5)
    profile[place.category] = round(min(1.0, max(0.0, current + delta)), 3)
    traveler.taste_profile = profile

    db.commit()
    db.refresh(traveler)
    return traveler
