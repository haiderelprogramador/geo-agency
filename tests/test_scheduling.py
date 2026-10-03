"""RF5: el itinerario debe venir organizado por bloque de tiempo/día, no
solo como una lista de lugares sueltos. Antes `scheduled_time` quedaba
siempre en None (TODO pendiente); esto prueba que ahora sí se calcula."""

from app.agents.scheduling import CATEGORY_DURATION_MINUTES, DEFAULT_DURATION_MINUTES, assign_schedule


def _stop(day, order, category):
    return {"day_number": day, "order_index": order, "place": {"category": category}}


def test_first_stop_of_day_starts_at_nine_am():
    stops = assign_schedule([_stop(1, 0, "gastronomía")])
    assert stops[0]["scheduled_time"] == "09:00-10:30"  # 90 min de gastronomía


def test_stops_are_sequential_with_travel_buffer():
    stops = assign_schedule([_stop(1, 0, "gastronomía"), _stop(1, 1, "cultura")])
    by_order = sorted(stops, key=lambda s: s["order_index"])
    # gastronomía: 09:00-10:30, + 30 min de colchón -> cultura empieza 11:00
    assert by_order[0]["scheduled_time"] == "09:00-10:30"
    assert by_order[1]["scheduled_time"] == "11:00-13:00"  # cultura dura 120 min


def test_each_day_restarts_at_nine_am():
    stops = assign_schedule([_stop(1, 0, "naturaleza"), _stop(2, 0, "cultura")])
    day1 = next(s for s in stops if s["day_number"] == 1)
    day2 = next(s for s in stops if s["day_number"] == 2)
    assert day1["scheduled_time"].startswith("09:00")
    assert day2["scheduled_time"].startswith("09:00")


def test_unknown_category_uses_default_duration():
    stops = assign_schedule([_stop(1, 0, "categoria_rara")])
    start, end = stops[0]["scheduled_time"].split("-")
    start_min = int(start[:2]) * 60 + int(start[3:])
    end_min = int(end[:2]) * 60 + int(end[3:])
    assert end_min - start_min == DEFAULT_DURATION_MINUTES


def test_does_not_mutate_input():
    original = [_stop(1, 0, "gastronomía")]
    assign_schedule(original)
    assert "scheduled_time" not in original[0]
