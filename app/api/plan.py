"""Endpoint principal: recibe ubicación + preferencias, corre el pipeline
completo (perfil -> descubrimiento -> reseñas -> ranking -> itinerario) y
persiste el resultado. También expone lectura de planes ya guardados."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import get_compiled_graph
from app.agents.observers import ContextEvent, PlanContextSubject, make_recalculate_observer
from app.db import repository
from app.db.models import TripPlan
from app.db.session import get_db
from app.schemas.plan import (
    ContextEventRequest,
    PlanRequest,
    PlanResponse,
    PlanSummaryOut,
    PlanStopOut,
    PlaceOut,
    ReorderStopsRequest,
)

router = APIRouter(prefix="/plan", tags=["plan"])


def _trip_plan_to_response(trip_plan: TripPlan) -> PlanResponse:
    """Reconstruye el PlanResponse a partir del TripPlan guardado en DB —
    usado tanto justo después de generar un plan como al leerlo de vuelta,
    para que ambos caminos devuelvan exactamente la misma forma."""
    stops = [
        PlanStopOut(
            day_number=stop.day_number,
            order_index=stop.order_index,
            scheduled_time=stop.scheduled_time,
            place=PlaceOut(
                id=stop.place.external_id,
                name=stop.place.name,
                category=stop.place.category,
                latitude=stop.place.latitude,
                longitude=stop.place.longitude,
                avg_rating=stop.place.avg_rating,
                price_level=stop.place.price_level,
                open_now=(stop.place.opening_hours or {}).get("open_now"),
                review_sentiment=stop.review_sentiment,
                score=stop.score,
                reason=stop.reason,
            ),
        )
        for stop in trip_plan.stops
    ]
    # El taste_profile usado para este plan no se persiste aparte todavía
    # (TODO: guardarlo en el propio TripPlan si hace falta auditarlo luego);
    # por ahora se recalcula desde el traveler para la respuesta de lectura.
    taste_profile = trip_plan.traveler.taste_profile or {}
    return PlanResponse(plan_id=trip_plan.id, city=trip_plan.city, taste_profile=taste_profile, stops=stops)


@router.post("/generate", response_model=PlanResponse)
def generate_plan(req: PlanRequest, db: Session = Depends(get_db)) -> PlanResponse:
    graph = get_compiled_graph()

    # Si ya existe un perfil de gustos guardado para este traveler, lo
    # reusamos (memoria de largo plazo, RF1) en vez de caer siempre al
    # perfil neutro de ejemplo. Pero si la persona manda gustos explícitos
    # en este request (los eligió a mano en el formulario), esos mandan —
    # así puede ajustar sus preferencias en cada búsqueda.
    traveler = repository.get_or_create_traveler(db, req.traveler_id)
    effective_profile = req.taste_profile or traveler.taste_profile

    result = graph.invoke(
        {
            "traveler_id": req.traveler_id,
            "city": req.city,
            "latitude": req.latitude,
            "longitude": req.longitude,
            "radius_m": req.radius_m,
            "days": req.days,
            "language": req.language,
            "min_rating": req.min_rating,
            "max_price_level": req.max_price_level,
            "open_now": req.open_now,
            "taste_profile": effective_profile,
            "candidate_places": [],
            "ranked_places": [],
            "plan_stops": [],
        }
    )

    # Guarda el perfil de gustos usado (así la próxima vez build_taste_profile
    # puede reusarlo en vez de caer al default).
    traveler.taste_profile = result["taste_profile"]

    trip_plan = repository.save_trip_plan(
        db, traveler_id=req.traveler_id, city=req.city, plan_stops=result["plan_stops"]
    )

    return PlanResponse(
        plan_id=trip_plan.id,
        city=req.city,
        taste_profile=result["taste_profile"],
        stops=result["plan_stops"],
    )


@router.get("/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str, db: Session = Depends(get_db)) -> PlanResponse:
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return _trip_plan_to_response(trip_plan)


@router.post("/{plan_id}/events", response_model=PlanResponse)
def report_context_event(plan_id: str, req: ContextEventRequest, db: Session = Depends(get_db)) -> PlanResponse:
    """Reporta un cambio de contexto (RF: recálculo dinámico, patrón
    Observer) y devuelve el plan ya recalculado y persistido."""
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    subject = PlanContextSubject()
    subject.subscribe(make_recalculate_observer(db))
    subject.notify(
        ContextEvent(
            plan_id=plan_id,
            event_type=req.event_type,
            place_external_id=req.place_id,
            category=req.category,
            reason=req.reason,
        )
    )

    db.refresh(trip_plan)
    return _trip_plan_to_response(trip_plan)


@router.delete("/{plan_id}/stops/{place_id}", response_model=PlanResponse)
def remove_stop(plan_id: str, place_id: str, db: Session = Depends(get_db)) -> PlanResponse:
    """RF6: el usuario quita una parada del plan a mano."""
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    trip_plan = repository.remove_stop(db, trip_plan, place_id)
    return _trip_plan_to_response(trip_plan)


@router.patch("/{plan_id}/stops/reorder", response_model=PlanResponse)
def reorder_stops(plan_id: str, req: ReorderStopsRequest, db: Session = Depends(get_db)) -> PlanResponse:
    """RF6: el usuario reordena las paradas del plan a mano."""
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    try:
        trip_plan = repository.reorder_stops(db, trip_plan, req.place_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _trip_plan_to_response(trip_plan)


@router.get("", response_model=list[PlanSummaryOut])
def list_plans(traveler_id: str, db: Session = Depends(get_db)) -> list[PlanSummaryOut]:
    plans = repository.list_trip_plans(db, traveler_id)
    return [
        PlanSummaryOut(
            plan_id=p.id,
            city=p.city,
            status=p.status,
            created_at=p.created_at.isoformat(),
            stop_count=len(p.stops),
        )
        for p in plans
    ]
