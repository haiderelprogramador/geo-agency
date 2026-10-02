FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /code/app

# Forma shell (no array) para que ${PORT} se expanda: Render (y otros PaaS)
# asignan el puerto dinámicamente vía esa variable de entorno; localmente
# (docker run sin -e PORT) cae al 8000 de siempre.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
