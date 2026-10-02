"""Este archivo se ejecuta ANTES que cualquier submódulo de app/ (incluyendo
el primer `from sqlalchemy import ...`), así que es el lugar correcto para
desactivar la extensión Cython opcional de SQLAlchemy (_collections_cy,
_immutabledict_cy, etc.). En algunos Windows con políticas de "Control de
aplicaciones" (WDAC / Smart App Control / antivirus corporativo), cargar ese
.pyd compilado queda bloqueado y SQLAlchemy no cae de vuelta a Python puro
por sí solo. Esto fuerza el modo puro-Python, que funciona igual de bien
(solo un poco más lento, imperceptible para este proyecto)."""

import os

os.environ.setdefault("DISABLE_SQLALCHEMY_CEXT_RUNTIME", "1")
