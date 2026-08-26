# syntax=docker/dockerfile:1.7

# The manifest-list digest and Python package are intentionally version-matched.
ARG PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright/python:v1.62.0-noble@sha256:aa81288e738725378becba5b3e06cb0f3a7f012a610e87e8d767a090ea3f740d

FROM ${PLAYWRIGHT_IMAGE} AS dependency-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# zxing-cpp does not publish a CPython 3.12 ARM64 wheel. Keep its compiler and
# header requirements in this disposable stage rather than the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-backend.txt ./requirements-backend.txt
RUN python -m pip wheel --no-cache-dir --wheel-dir=/wheels \
        -r requirements-backend.txt

FROM ${PLAYWRIGHT_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=8080 \
    APP_ENV=production \
    DEBUG_MODE=false \
    TEMP_DIR=/tmp/slip-automation \
    DOCUMENT_AI_PROVIDER=gemini \
    DOCUMENT_AI_MODEL=gemini-3.7-flash \
    BROWSER_HEADLESS=true \
    BACKEND_EXECUTION_MODE=synchronous \
    BACKEND_MAX_CONCURRENT_JOBS=1 \
    JOB_TTL_MINUTES=30 \
    ALLOW_INSECURE_REPORT_PORTALS=false

WORKDIR /app

USER root

# tini forwards termination signals and reaps Chromium/driver child processes.
# The official image already contains the matching browsers and Linux libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && find /ms-playwright -type f \
        \( -name chrome_sandbox -o -name chrome-sandbox \) \
        -exec chown root:root {} + \
        -exec chmod 4755 {} +

COPY requirements-backend.txt ./requirements-backend.txt
RUN --mount=type=bind,from=dependency-builder,source=/wheels,target=/wheels,ro \
    python -m pip install --no-cache-dir --no-index --find-links=/wheels \
        -r requirements-backend.txt \
    && python -c "from importlib.metadata import version; assert version('playwright') == '1.62.0'"

# Only backend/runtime modules are copied; Streamlit is not part of this process.
COPY backend ./backend
COPY browser_agent ./browser_agent
COPY config ./config
COPY document_understanding ./document_understanding
COPY downloads ./downloads
COPY services ./services
COPY utils ./utils
COPY workflow ./workflow

RUN install -d -o pwuser -g pwuser -m 0700 \
        /tmp/slip-automation /app/temp \
    && test "$(id -u pwuser)" -ne 0

USER pwuser

EXPOSE 8080
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8080') + '/health', timeout=4)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1"]
