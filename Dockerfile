FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY migraciones ./migraciones

RUN useradd --create-home --uid 10001 asistente
USER asistente

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn visagassist.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
