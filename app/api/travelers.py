"""Endpoints sobre el traveler mismo — hoy solo feedback (RF10), que
retroalimenta su perfil de gustos para futuras recomendaciones."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import repository
from app.db.session import get_db
from app.schemas.traveler import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/travelers", tags=["travelers"])


@router.post("/{traveler_id}/feedback", response_model=FeedbackResponse)
def give_feedback(traveler_id: str, req: FeedbackRequest, db: Session = Depends(get_db)) -> FeedbackResponse:
    try:
        traveler = repository.save_feedback(db, traveler_id, req.place_id, req.liked, req.note)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FeedbackResponse(traveler_id=traveler.id, taste_profile=traveler.taste_profile or {})
