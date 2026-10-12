FROM ghcr.io/astral-sh/uv:0.9.2@sha256:6dbd7c42a9088083fa79e41431a579196a189bcee3ae68ba904ac2bf77765867 AS uv
FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY infra/embedding-manifest.json infra/embedding-manifest.json
COPY scripts/package_embedding.py scripts/package_embedding.py
RUN python scripts/package_embedding.py /opt/embedding

FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
RUN python -m pip uninstall -y setuptools pip
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /opt/embedding /opt/embedding
COPY apps/api/app apps/api/app
COPY apps/api/skills apps/api/skills
COPY fixtures/synthetic_guides fixtures/synthetic_guides
COPY infra/migrations infra/migrations
RUN python -c "import hashlib,pathlib; paths=sorted(p for root in ('apps/api','fixtures','infra/migrations') for p in pathlib.Path(root).rglob('*') if p.is_file()); pathlib.Path('BUILD_REVISION').write_text(hashlib.sha256(b''.join(str(p).encode()+p.read_bytes() for p in paths)).hexdigest())"
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/apps/api PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EMBED_MODEL_PATH=/opt/embedding EMBED_CACHE=/tmp/fastembed HF_HUB_OFFLINE=1 APP_MODE=pilot
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
