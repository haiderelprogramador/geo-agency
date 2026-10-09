"""Engine y sesión de SQLAlchemy.

El engine se crea de forma perezosa (al primer uso) en vez de al importar el
módulo, para que importar `app.db.models` o correr la API/tests no requiera
tener el driver de Postgres instalado ni una base de datos disponible.
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        # SQLite: cada conexión por defecto solo se puede usar en el hilo que
        # la creó; FastAPI puede manejar un request en otro hilo, así que
        # relajamos esa restricción (es seguro porque cada request abre su
        # propia Session vía get_db()).
        connect_args = {"check_same_thread": False}
    return create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_session_factory() -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI: una sesión por request."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def ensure_columns(engine: Engine) -> None:
    """Migración mínima sin Alembic: `create_all` crea tablas que faltan pero
    NO agrega columnas nuevas a tablas que ya existen, así que una base
    SQLite creada con una versión anterior fallaría al leer/escribir. Acá se
    agregan las columnas posteriores a la primera versión si no están."""
    from sqlalchemy import inspect, text

    additions = {"plan_stops": {"travel_minutes": "INTEGER"}}
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in additions.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl_type in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
