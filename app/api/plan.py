"""Endpoint principal: recibe ubicación + preferencias, corre el pipeline
completo (perfil -> descubrimiento -> reseñas -> ranking -> itinerario) y
persiste el resultado. También expone lectura de planes ya guardados."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.graph import get_compiled_graph
from app.agents import assistant
from app.agents.routing import fetch_route
from app.agents.weather import fetch_daily_forecast, outdoor_stops_on_rainy_days
from app.agents.observers import ContextEvent, PlanContextSubject, make_recalculate_observer
from app.db import repository
from app.db.models import TripPlan
from app.db.session import get_db
from app.schemas.plan import (
    AtRiskStopOut,
    ChatRequest,
    ChatResponse,
    ContextEventRequest,
    DayRouteOut,
    PlanRequest,
    PlanResponse,
    PlanSummaryOut,
    PlanStopOut,
    PlaceOut,
    ReorderStopsRequest,
    WeatherDayOut,
    WeatherOut,
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
            travel_minutes=stop.travel_minutes,
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
    return _generate(req, db)


def _generate(req: PlanRequest, db: Session) -> PlanResponse:
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


@router.get("/{plan_id}/route", response_model=list[DayRouteOut])
def get_plan_route(plan_id: str, db: Session = Depends(get_db)) -> list[DayRouteOut]:
    """Recorrido por día (calles reales vía OSRM, o línea recta si no hay
    servicio) para dibujarlo en el mapa."""
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    by_day: dict[int, list] = {}
    for stop in sorted(trip_plan.stops, key=lambda s: (s.day_number, s.order_index)):
        by_day.setdefault(stop.day_number, []).append(stop)

    routes = []
    for day_number, stops in by_day.items():
        route = fetch_route([(s.place.latitude, s.place.longitude) for s in stops])
        routes.append(
            DayRouteOut(
                day_number=day_number,
                geometry=route["geometry"],
                source=route["source"],
                total_travel_minutes=sum(route["legs_minutes"]),
            )
        )
    return routes


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


# --- Agente conversacional y clima ------------------------------------------

def _plan_stops_as_dicts(trip_plan: TripPlan) -> list[dict]:
    return [
        {
            "day_number": s.day_number,
            "scheduled_time": s.scheduled_time,
            "place": repository.stop_to_place_dict(s),
        }
        for s in sorted(trip_plan.stops, key=lambda s: (s.day_number, s.order_index))
    ]


def _find_stop_by_name(trip_plan: TripPlan, name: str):
    wanted = name.casefold()
    for stop in trip_plan.stops:
        have = stop.place.name.casefold()
        if wanted in have or have in wanted:
            return stop
    return None


@router.post("/{plan_id}/chat", response_model=ChatResponse)
def chat_with_agent(plan_id: str, req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """El agente interpreta un mensaje y modifica el plan. El LLM solo
    propone acciones de una lista cerrada; acá se validan y ejecutan."""
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    en = req.language == "en"
    decision = assistant.interpret_message(req.message, _plan_stops_as_dicts(trip_plan), req.language)
    reply = decision["reply"]
    applied: list[str] = []
    regenerate = None
    excluded: list[str] = []

    for action in decision["actions"]:
        if action["type"] == "remove_place":
            stop = _find_stop_by_name(trip_plan, action["name"])
            if stop is None:
                reply += f" I couldn't find “{action['name']}” in your plan." if en else f" No encontré «{action['name']}» en tu plan."
                continue
            name = stop.place.name
            trip_plan = repository.drop_stops(db, trip_plan, [stop.place.external_id])
            applied.append(f"Removed {name}" if en else f"Quité {name}")
        elif action["type"] == "exclude_category":
            subject = PlanContextSubject()
            subject.subscribe(make_recalculate_observer(db))
            subject.notify(
                ContextEvent(plan_id=plan_id, event_type="category_unavailable", category=action["category"], reason="pedido en el chat")
            )
            db.refresh(trip_plan)
            excluded.append(action["category"])
            applied.append(f"Excluded {action['category']}" if en else f"Excluí {action['category']}")
        elif action["type"] == "regenerate":
            regenerate = action

    if regenerate is not None:
        if req.context is None:
            reply += " To build a new plan I need the search form data." if en else " Para armar un plan nuevo necesito los datos del formulario de búsqueda."
        else:
            traveler = repository.get_or_create_traveler(db, req.context.traveler_id)
            taste = {**(req.context.taste_profile or traveler.taste_profile or {}), **regenerate["taste"]}
            for cat in excluded:  # lo excluido en este mismo mensaje no debe volver al regenerar
                taste[cat] = 0.0
            updates = {k: regenerate[k] for k in ("min_rating", "max_price_level", "open_now") if k in regenerate}
            new_req = req.context.model_copy(update={**updates, "taste_profile": taste or None, "language": req.language})
            plan = _generate(new_req, db)
            applied.append("Built a new plan" if en else "Armé un plan nuevo")
            return ChatResponse(reply=reply, plan=plan, plan_changed=True, applied=applied)

    return ChatResponse(reply=reply, plan=_trip_plan_to_response(trip_plan), plan_changed=bool(applied), applied=applied)


def _weather_for_plan(trip_plan: TripPlan):
    stops = _plan_stops_as_dicts(trip_plan)
    if not stops:
        return [], []
    lat = sum(s["place"]["latitude"] for s in stops) / len(stops)
    lon = sum(s["place"]["longitude"] for s in stops) / len(stops)
    forecast = fetch_daily_forecast(lat, lon, max(s["day_number"] for s in stops))
    return forecast, outdoor_stops_on_rainy_days(stops, forecast)


@router.get("/{plan_id}/weather", response_model=WeatherOut)
def get_plan_weather(plan_id: str, db: Session = Depends(get_db)) -> WeatherOut:
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    forecast, at_risk = _weather_for_plan(trip_plan)
    return WeatherOut(
        available=bool(forecast),
        forecast=[WeatherDayOut(**f) for f in forecast],
        at_risk=[
            AtRiskStopOut(day_number=s["day_number"], place_id=s["place"]["id"], name=s["place"]["name"]) for s in at_risk
        ],
    )


@router.post("/{plan_id}/weather-adjust", response_model=PlanResponse)
def adjust_plan_for_weather(plan_id: str, db: Session = Depends(get_db)) -> PlanResponse:
    """Quita las paradas al aire libre de los días con lluvia probable. Las
    demás paradas conservan su día."""
    trip_plan = repository.get_trip_plan(db, plan_id)
    if trip_plan is None:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    _, at_risk = _weather_for_plan(trip_plan)
    if at_risk:
        trip_plan = repository.drop_stops(db, trip_plan, [s["place"]["id"] for s in at_risk])
        repository.log_agent_event(
            db, trip_plan.traveler_id, "weather", "ajuste_clima", {"plan_id": plan_id, "removed": [s["place"]["name"] for s in at_risk]}
        )
    return _trip_plan_to_response(trip_plan)
