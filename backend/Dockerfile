# syntax=docker/dockerfile:1.7
#
# TripWise backend - production image (single-instance sample-mode profile).
#
# * Python and the base image are pinned by digest.
# * Dependencies come from backend/requirements.lock with --require-hashes (reproducible;
#   regenerate with `make lock`).
# * The image contains application code only. It contains NO secrets, NO databases, NO
#   .env files and NO regional catalogs (those are untracked, ~140 MB, and mounted
#   read-only at /app/catalogs when available - see docs/DEPLOYMENT.md).
# * Runs as a non-root user; the only writable paths are the data volume (/data) and /tmp.
ARG PYTHON_IMAGE=python:3.14-slim-trixie@sha256:00ebdcac87ebf7fd62576d8bbe8f8f1e94198befcc4e38c4db9671e61e0dfcfe

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY requirements.lock /tmp/requirements.lock
RUN /opt/venv/bin/pip install --require-hashes -r /tmp/requirements.lock

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/opt/venv/bin:$PATH \
    TRIPWISE_ENV=production \
    TRIPWISE_DATA_DIR=/data
RUN groupadd --system --gid 10001 tripwise \
 && useradd --system --uid 10001 --gid tripwise --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin tripwise \
 && mkdir -p /data \
 && chown tripwise:tripwise /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
# Application code is root-owned and read-only to the runtime user.
COPY core ./core
COPY accounts ./accounts
COPY planning ./planning
COPY welcome ./welcome
COPY agents ./agents
COPY api ./api
COPY gateway ./gateway
COPY --chmod=0755 docker-entrypoint.sh ./docker-entrypoint.sh
USER tripwise
VOLUME ["/data"]
EXPOSE 8000
# Readiness, not just liveness: an instance that cannot open its persistence is not healthy.
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD ["python", "-c", "import sys, urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status == 200 else 1)"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
