FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CINENODE_HOME=/data \
    CINENODE_HOST=0.0.0.0 \
    CINENODE_PORT=8787 \
    CINENODE_ALLOW_LOOPBACK_PROXY=1 \
    CINENODE_ALLOW_SHUTDOWN=0
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY README.md /app/README.md
COPY source/backend /app/source/backend
RUN python -m pip install /app/source/backend
VOLUME ["/data"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)"
CMD ["python", "-m", "cinenode", "run", "--no-browser"]
