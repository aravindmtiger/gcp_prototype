# Backend image for Cloud Run (also used by docker-compose --profile app).
# Build from the backend/ directory:  docker build -t agentflow-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

RUN useradd --create-home --uid 10001 appuser

COPY pyproject.toml ./
COPY app ./app
RUN pip install . && rm -rf /srv/build /srv/*.egg-info

USER appuser

# Cloud Run sends traffic to $PORT (8080 by default). One worker per instance: Cloud Run
# scales by adding instances, and extra workers would split the in-process run tasks.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
