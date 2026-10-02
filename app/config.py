"""Configuración central de la app (pydantic-settings lee de .env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"

    # LLM
    anthropic_api_key: str = ""
    planner_model: str = "claude-sonnet-4-5"
    fast_model: str = "claude-haiku-4-5"

    # Datos
    # SQLite por defecto: cero setup para desarrollo/demo (RNF: facilidad de
    # despliegue). En producción esto apuntaría a Postgres (+ pgvector) vía
    # DATABASE_URL en .env, sin tocar código — el repositorio es agnóstico
    # al motor (patrón Repository).
    database_url: str = "sqlite:///./geo_agentic_travel.db"
    redis_url: str = "redis://localhost:6379/0"

    # Fuentes geográficas / reseñas
    google_places_api_key: str = ""

    # Observabilidad
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "geo-agentic-travel"

    # Parámetros de negocio
    default_search_radius_m: int = 2000


@lru_cache
def get_settings() -> Settings:
    return Settings()
