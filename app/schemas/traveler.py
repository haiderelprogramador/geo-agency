from pydantic import BaseModel


class FeedbackRequest(BaseModel):
    """RF10: feedback del usuario sobre un lugar recomendado."""

    place_id: str  # id de Google del lugar (el mismo que vino en un PlaceOut)
    liked: bool
    note: str | None = None


class FeedbackResponse(BaseModel):
    traveler_id: str
    taste_profile: dict[str, float]
