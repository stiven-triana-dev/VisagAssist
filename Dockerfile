# Imagen de VisagAssist para Render (o cualquier servidor con Docker).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Primero solo lo necesario para instalar: si el código cambia, esta capa se reutiliza.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY migraciones ./migraciones

# Sin privilegios de administrador dentro del contenedor.
RUN useradd --create-home --uid 10001 asistente
USER asistente

ENV PORT=8000
EXPOSE 8000

# Al arrancar: aplica las migraciones de la base propia y levanta la API.
# --proxy-headers: la IP real del visitante llega por el proxy de Render (X-Forwarded-For).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn visagassist.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
