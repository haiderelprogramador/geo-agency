# Geo Agentic Travel

Sistema agéntico de recomendación geográfica personalizada: dado el perfil de
gustos de un viajero y su ubicación, descubre lugares cercanos, valida su
calidad analizando reseñas reales, y arma con eso un plan de viaje/itinerario.

Idea original del profesor: "sistema geográfico agéntico de las cosas que te
gusten que estén cerca, de acuerdo a tus gustos, con las reseñas de esas
cosas, a través de un plan de viaje".

## Arquitectura

Pipeline lineal de 5 etapas (LangGraph), no un supervisor con enrutamiento:

```
Perfil de gustos → Descubrimiento geográfico → Análisis de reseñas
    → Ranking personalizado → Construcción del itinerario
```

Ver `docs/patrones-diseno.md` para el árbol de patrones de diseño y
`docs/requerimientos.md` para requerimientos funcionales/no funcionales y
clientes potenciales.

## Stack

- **Orquestación**: LangGraph (patrón Pipeline)
- **LLM**: Claude API (Haiku para análisis de reseñas, Sonnet para lo que requiera más razonamiento)
- **Backend**: FastAPI
- **Base de datos**: PostgreSQL (+ pgvector) + Redis
- **Fuentes geográficas**: Google Places API (pendiente de conectar; hoy hay datos de ejemplo)
- **Infra**: Docker Compose

## Estructura del repo

```
app/
  agents/      # Estado, herramientas y nodos del pipeline (LangGraph)
  api/         # Endpoint /plan/generate
  db/          # Modelos SQLAlchemy
  schemas/     # Pydantic schemas
  main.py
docs/          # Patrones de diseño y requerimientos
tests/         # Pruebas unitarias (ranking, haversine, perfil)
```

## Setup local

```bash
cp .env.example .env          # completa ANTHROPIC_API_KEY y GOOGLE_PLACES_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload # crea geo_agentic_travel.db (SQLite) solo si no existe
pytest
```

No hace falta Docker ni Postgres para correr esto: por defecto usa SQLite
(un archivo `geo_agentic_travel.db` en la carpeta del proyecto). Si no hay
`GOOGLE_PLACES_API_KEY` configurada, el pipeline cae a datos de ejemplo
automáticamente (degradación controlada, RNF7) — así que también se puede
probar sin esa key.

## Endpoints

| Método | Ruta | Para qué |
|---|---|---|
| POST | `/plan/generate` | Corre el pipeline completo y guarda el plan (RF1-RF5, RF8, RF9, RF11) |
| GET | `/plan/{plan_id}` | Recupera un plan ya guardado |
| GET | `/plan?traveler_id=...` | Lista los planes de un traveler |
| DELETE | `/plan/{plan_id}/stops/{place_id}` | Quita una parada a mano (RF6) |
| PATCH | `/plan/{plan_id}/stops/reorder` | Reordena las paradas a mano (RF6) |
| POST | `/plan/{plan_id}/events` | Reporta un cambio de contexto y recalcula (RF7, patrón Observer) |
| POST | `/travelers/{traveler_id}/feedback` | Like/dislike que ajusta el perfil de gustos (RF10) |

Ejemplo del flujo completo:

```bash
# 1. Generar un plan (en inglés, solo 4+ estrellas)
curl -X POST http://127.0.0.1:8000/plan/generate -H "Content-Type: application/json" \
  -d '{"traveler_id": "demo", "city": "Cartagena", "latitude": 10.4, "longitude": -75.55, "days": 2, "language": "en", "min_rating": 4.0}'

# 2. Reportar que un lugar cerró -> recalcula el mismo plan sin él
curl -X POST http://127.0.0.1:8000/plan/<plan_id>/events -H "Content-Type: application/json" \
  -d '{"event_type": "place_closed", "place_id": "<id del lugar>", "reason": "cerrado por reforma"}'

# 3. Dar feedback -> ajusta el perfil para el próximo plan
curl -X POST http://127.0.0.1:8000/travelers/demo/feedback -H "Content-Type: application/json" \
  -d '{"place_id": "<id del lugar>", "liked": true}'
```

## Estado del proyecto

Los 11 requerimientos funcionales (`docs/requerimientos.md`) están
implementados: perfil de gustos persistente (RF1), descubrimiento geográfico
vía Google Places (RF2), análisis de sentimiento de reseñas (RF3), ranking
por afinidad/cercanía/reseñas (RF4), itinerario por días (RF5), edición
manual del plan (RF6), recálculo dinámico ante cambios de contexto vía
Observer (RF7), filtro explícito de calidad mínima (RF8), explicación en
lenguaje natural (RF9), feedback que retroalimenta el perfil (RF10), e
inglés/español (RF11).

Pendiente para producción (fuera del alcance de esta demo): autenticación
real de travelers, caché de llamadas a Google Places/LLM (RNF5), y
optimización de ruta entre paradas dentro de un mismo día (hoy el orden
es por score, no por distancia real entre paradas consecutivas).
