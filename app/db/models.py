"""Modelos SQLAlchemy."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Traveler(Base):
    """Un usuario/turista y su perfil de gustos (memoria de largo plazo, RF1)."""

    __tablename__ = "travelers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(5), default="es")
    # Perfil de gustos construido con Builder: categorías con peso (ej. {"gastronomía": 0.9, "vida_nocturna": 0.2})
    taste_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    budget_level: Mapped[str | None] = mapped_column(String(20), nullable=True)  # bajo, medio, alto
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    feedback: Mapped[list["Feedback"]] = relationship(back_populates="traveler")
    trip_plans: Mapped[list["TripPlan"]] = relationship(back_populates="traveler")


class Place(Base):
    """Un lugar normalizado desde alguna fuente externa (Adapter aplicado antes de guardar)."""

    __tablename__ = "places"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    external_source: Mapped[str] = mapped_column(String(30))  # google_places, osm, tripadvisor
    external_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))  # gastronomía, cultura, naturaleza, vida_nocturna...
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    city: Mapped[str] = mapped_column(String(100))
    avg_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_level: Mapped[int | None] = mapped_column(nullable=True)  # 1-4
    opening_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Señal de contexto simple (Observer, RF: recálculo dinámico): si el
    # lugar se reporta cerrado, cualquier plan que lo use debe recalcularse
    # sin él. No reemplaza horarios reales (opening_hours), es un flag manual
    # para esta demo (ej. "reportan que este lugar cerró hoy").
    is_open: Mapped[bool] = mapped_column(default=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    reviews: Mapped[list["Review"]] = relationship(back_populates="place")


class Review(Base):
    """Reseña de un lugar, recolectada y analizada por el agente de reseñas (RF3)."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    place_id: Mapped[str] = mapped_column(ForeignKey("places.id"), index=True)
    source: Mapped[str] = mapped_column(String(30))
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    place: Mapped["Place"] = relationship(back_populates="reviews")


class TripPlan(Base):
    """Un plan de viaje/itinerario generado para un traveler (RF5)."""

    __tablename__ = "trip_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    traveler_id: Mapped[str] = mapped_column(ForeignKey("travelers.id"), index=True)
    city: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "completed", name="plan_status"), default="draft"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    traveler: Mapped["Traveler"] = relationship(back_populates="trip_plans")
    stops: Mapped[list["PlanStop"]] = relationship(back_populates="plan", order_by="PlanStop.order_index")


class PlanStop(Base):
    """Una parada dentro de un plan — nodo del Composite día/bloque/lugar."""

    __tablename__ = "plan_stops"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("trip_plans.id"), index=True)
    place_id: Mapped[str] = mapped_column(ForeignKey("places.id"))
    day_number: Mapped[int] = mapped_column(default=1)
    order_index: Mapped[int] = mapped_column(default=0)
    scheduled_time: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "09:00-10:30"
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # explicación (RF9)
    # Snapshot del momento del plan: el score y el sentimiento dependen del
    # perfil de gustos de ESE plan y de las reseñas vigentes en ese momento,
    # no son propiedades fijas del lugar — por eso viven en la parada y no
    # en Place (que sí es compartido entre planes).
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)

    plan: Mapped["TripPlan"] = relationship(back_populates="stops")
    place: Mapped["Place"] = relationship()


class Feedback(Base):
    """Feedback del usuario sobre un lugar recomendado (RF10) — retroalimenta el perfil."""

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    traveler_id: Mapped[str] = mapped_column(ForeignKey("travelers.id"), index=True)
    place_id: Mapped[str] = mapped_column(ForeignKey("places.id"))
    liked: Mapped[bool] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    traveler: Mapped["Traveler"] = relationship(back_populates="feedback")


class AgentEventLog(Base):
    """Bitácora de cada decisión/acción del agente — auditoría (RNF9)."""

    __tablename__ = "agent_event_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    traveler_id: Mapped[str | None] = mapped_column(ForeignKey("travelers.id"), nullable=True, index=True)
    agent: Mapped[str] = mapped_column(String(30))  # perfil, descubrimiento, resenas, ranking, itinerario
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
