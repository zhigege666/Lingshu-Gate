# syntax=docker/dockerfile:1.7

ARG NODE_BASE_IMAGE=node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5
ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579

FROM ${NODE_BASE_IMAGE} AS console-builder

WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY src/lingshu_gate/_version.py /app/src/lingshu_gate/_version.py
COPY web ./
RUN --mount=type=bind,source=scripts/release/stage_npm_licenses.mjs,target=/tmp/stage_npm_licenses.mjs,ro \
    --mount=type=bind,source=packaging/licenses/npm,target=/tmp/reviewed-npm-licenses,ro \
    npm run build \
    && npm prune --omit=dev --no-audit --no-fund \
    && node /tmp/stage_npm_licenses.mjs \
      /app/web/node_modules /app/licenses/npm /tmp/reviewed-npm-licenses


FROM ${PYTHON_BASE_IMAGE} AS core

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LINGSHU_GATE_HOST=0.0.0.0 \
    LINGSHU_GATE_PORT=8000 \
    LINGSHU_GATE_ALLOWED_ROOT=/workspace \
    LINGSHU_GATE_CONFIG_DIR=/config/mcp.d \
    LINGSHU_GATE_DATA_DIR=/data \
    LINGSHU_GATE_AUTH_ENABLED=true \
    LINGSHU_GATE_IN_CONTAINER=1 \
    LINGSHU_GATE_RUNTIME_ROLE=core \
    HOME=/data/home \
    XDG_CACHE_HOME=/data/cache

WORKDIR /app

RUN groupadd --gid "${APP_GID}" gate \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home \
      --home-dir /data/home --shell /usr/sbin/nologin gate \
    && install -d /workspace \
    && install -d -o "${APP_UID}" -g "${APP_GID}" \
      /config /config/mcp.d /data /data/home /data/cache

COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=scripts/release/stage_installed_python_licenses.py,target=/tmp/stage_python_licenses.py,ro \
    pip install --require-hashes --requirement requirements.lock \
    && python /tmp/stage_python_licenses.py /app/licenses/third-party/python

COPY src ./src
COPY --from=console-builder \
    /app/src/lingshu_gate/static/console \
    ./src/lingshu_gate/static/console
COPY --from=console-builder /app/licenses/npm ./licenses/third-party/npm
COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md ./licenses/

LABEL org.opencontainers.image.title="Lingshu Gate" \
      org.opencontainers.image.description="Unprivileged Lingshu Gate core service and MCP gateway" \
      org.opencontainers.image.source="https://github.com/zhigege666/Lingshu-Gate" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.lingshu.gate.image.role="core"

USER ${APP_UID}:${APP_GID}

EXPOSE 8000

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2).read()"]

CMD ["python", "-m", "lingshu_gate.cli"]
