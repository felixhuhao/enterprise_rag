# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app
ARG INSTALL_LOCAL_EMBEDDING=false
COPY requirements.txt requirements-local-embedding.txt ./
RUN --mount=type=cache,id=enterprise-rag-backend-pip,target=/root/.cache/pip,sharing=locked \
    python -m pip install -r requirements.txt && \
    if [ "$INSTALL_LOCAL_EMBEDDING" = "true" ]; then \
        python -m pip install -r requirements-local-embedding.txt; \
    fi
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data && chown -R appuser:appuser /app
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser scripts/ ./scripts/
EXPOSE 8010
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
