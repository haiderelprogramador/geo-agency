"""Asistente conversacional del plan: traduce un mensaje en lenguaje natural
("quita el museo", "nada de naturaleza", "algo más barato") a acciones
concretas de una lista cerrada. El LLM solo INTERPRETA; quien ejecuta es el
código de la API, que valida cada acción antes de tocar el plan — así un
mensaje raro nunca puede hacer algo fuera de esa lista."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents import nodes
from app.agents.tools import CATEGORY_TO_GOOGLE_TYPES

KNOWN_CATEGORIES = set(CATEGORY_TO_GOOGLE_TYPES)

SYSTEM_PROMPT = """Eres el asistente de un planificador de viajes. La persona te escribe sobre su plan actual.
Responde SOLO con un JSON con esta forma exacta:
{{"reply": "<respuesta corta y amable, en {language_name}>", "actions": [ ... ]}}

Acciones permitidas (puedes devolver varias, o ninguna si solo conversas):
- {{"type": "remove_place", "name": "<nombre de un lugar del plan>"}}
- {{"type": "exclude_category", "category": "<una de: {categories}>"}}
- {{"type": "regenerate", "min_rating": <0-5 o null>, "max_price_level": <0-4 o null>, "open_now": <true/false/null>, "taste": {{"<categoria>": <0.0-1.0>}}}}
  (regenerate arma un plan nuevo; úsalo para "más barato" -> max_price_level bajo, "mejor valorados" -> min_rating, "quiero más X" -> taste)

Reglas: no inventes lugares; no hagas nada que la persona no pidió; si no entiendes, devuelve actions vacío y pídele que lo aclare en reply."""


def _summarize_plan(stops: list[dict]) -> str:
    lines = [
        f"- Día {s['day_number']} {s.get('scheduled_time') or ''}: {s['place']['name']} ({s['place']['category']})"
        for s in stops
    ]
    return "\n".join(lines) or "(plan vacío)"


def _sanitize_action(raw: dict) -> dict | None:
    kind = raw.get("type")
    if kind == "remove_place" and isinstance(raw.get("name"), str) and raw["name"].strip():
        return {"type": kind, "name": raw["name"].strip()}
    if kind == "exclude_category" and raw.get("category") in KNOWN_CATEGORIES:
        return {"type": kind, "category": raw["category"]}
    if kind == "regenerate":
        out: dict = {"type": kind, "taste": {}}
        rating = raw.get("min_rating")
        if isinstance(rating, (int, float)) and not isinstance(rating, bool) and 0 <= rating <= 5:
            out["min_rating"] = float(rating)
        price = raw.get("max_price_level")
        if isinstance(price, int) and not isinstance(price, bool) and 0 <= price <= 4:
            out["max_price_level"] = price
        if isinstance(raw.get("open_now"), bool):
            out["open_now"] = raw["open_now"]
        for cat, weight in (raw.get("taste") or {}).items():
            if cat in KNOWN_CATEGORIES and isinstance(weight, (int, float)) and not isinstance(weight, bool):
                out["taste"][cat] = min(1.0, max(0.0, float(weight)))
        return out
    return None


def interpret_message(message: str, stops: list[dict], language: str = "es") -> dict:
    """Devuelve {"reply": str, "actions": [acciones validadas]}. Nunca lanza:
    si el LLM falla o responde algo ilegible, devuelve una disculpa y cero
    acciones (el plan queda intacto)."""
    language_name = "inglés" if language == "en" else "español"
    system = SYSTEM_PROMPT.format(language_name=language_name, categories=", ".join(sorted(KNOWN_CATEGORIES)))
    user = f"Plan actual:\n{_summarize_plan(stops)}\n\nMensaje de la persona: {message}"
    try:
        response = nodes._llm(nodes.settings.planner_model).invoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        parsed = json.loads(nodes._strip_markdown_json(str(response.content)))
        reply = str(parsed.get("reply") or "").strip()
        actions = [a for a in (_sanitize_action(r) for r in parsed.get("actions", []) if isinstance(r, dict)) if a]
        return {"reply": reply or ("Listo." if actions else "¿Me lo explicas de otra forma?"), "actions": actions}
    except Exception:
        fallback = "I couldn't understand that, could you rephrase?" if language == "en" else "No pude entender eso, ¿puedes decirlo de otra forma?"
        return {"reply": fallback, "actions": []}
