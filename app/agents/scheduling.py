"""Asignación de bloques horarios para el itinerario (RF5: "secuencia de
lugares por bloque de tiempo/día" — el requerimiento ya lo pedía, pero
`scheduled_time` se dejaba siempre en None; esto lo completa).

Cada categoría tiene una duración típica de visita. Se arma la agenda de
cada día en el orden de `order_index`, empezando a las 09:00 y dejando un
colchón de traslado entre una parada y la siguiente — así el plan (y su
narración en voz) puede decir "de 9:00 a 10:30 vas a..." en vez de solo
listar lugares sueltos."""

DAY_START_MINUTES = 9 * 60  # 09:00
TRAVEL_BUFFER_MINUTES = 30  # tiempo estimado de traslado entre paradas

CATEGORY_DURATION_MINUTES = {
    "gastronomía": 90,
    "cultura": 120,
    "naturaleza": 150,
    "vida_nocturna": 120,
}
DEFAULT_DURATION_MINUTES = 90


def _format_minutes(total_minutes: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def assign_schedule(stops: list[dict]) -> list[dict]:
    """Recibe la lista de stops del itinerario (cada uno con al menos
    "day_number", "order_index" y "place" — un dict con "category") y
    devuelve una lista nueva con "scheduled_time" = "HH:MM-HH:MM" calculado
    por día, en el orden de order_index. No muta la lista original."""
    by_day: dict[int, list[dict]] = {}
    for stop in stops:
        by_day.setdefault(stop["day_number"], []).append(stop)

    result = []
    for day_stops in by_day.values():
        day_stops = sorted(day_stops, key=lambda s: s["order_index"])
        cursor = DAY_START_MINUTES
        for i, stop in enumerate(day_stops):
            if i > 0:
                # Traslado real (OSRM/estimación) si el stop lo trae; si no, el
                # colchón fijo de siempre.
                cursor += stop.get("travel_minutes") or TRAVEL_BUFFER_MINUTES
            category = stop["place"].get("category")
            duration = CATEGORY_DURATION_MINUTES.get(category, DEFAULT_DURATION_MINUTES)
            start, end = cursor, cursor + duration
            result.append({**stop, "scheduled_time": f"{_format_minutes(start)}-{_format_minutes(end)}"})
            cursor = end
    return result
