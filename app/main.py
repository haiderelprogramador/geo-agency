from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.plan import router as plan_router
from app.api.travelers import router as travelers_router
from app.db import models  # noqa: F401 - registra las tablas en Base.metadata
from app.db.session import Base, get_engine

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sin Alembic todavía (TODO si el esquema empieza a cambiar seguido):
    # para el alcance actual basta con crear las tablas que falten al
    # arrancar. No borra ni migra datos existentes.
    Base.metadata.create_all(bind=get_engine())
    yield


app = FastAPI(title="Geo Agentic Travel", version="0.1.0", lifespan=lifespan)

app.include_router(plan_router)
app.include_router(travelers_router)

# Leaflet (mapa del itinerario) va empaquetado localmente en vez de desde un
# CDN — así la app funciona sin depender de que esa red externa esté
# disponible (redes corporativas restrictivas, sin internet, etc.).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def serve_frontend() -> FileResponse:
    """Frontend estático (un solo archivo HTML+CSS+JS, sin build step) que
    consume esta misma API. No reemplaza /docs (Swagger sigue disponible
    ahí para probar endpoints sueltos) — esta es la cara "de app" para
    demostrar el flujo completo: generar, dar feedback, reportar un lugar
    cerrado, reordenar."""
    return FileResponse(STATIC_DIR / "index.html")
