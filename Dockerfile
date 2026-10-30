FROM node:22-bookworm-slim@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    STEUERREPORT_V2_ROOT=/app \
    STEUERREPORT_V2_DB=/state/data/steuerreport_v2.duckdb \
    STEUERREPORT_USERTRANSFER_ROOT=/state/imports \
    STEUERREPORT_STATE_DIR=/state \
    STEUERREPORT_PRIVATE_PROFILE=/state/private_profile.json \
    STEUERREPORT_PRIVATE_CONFIG_DIR=/state/configs \
    STEUERREPORT_V2_SECRET_VAULT_KEY_FILE=/state/keys/vault.key \
    STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS=true
WORKDIR /app
COPY requirements-runtime.lock ./
RUN pip install --no-cache-dir -r requirements-runtime.lock
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps . \
    && pip check \
    && groupadd --gid 10001 steuerreport \
    && useradd --uid 10001 --gid 10001 --no-create-home steuerreport \
    && mkdir -p /state/data /state/var /state/keys /state/imports /state/configs \
    && chown -R 10001:10001 /state \
    && ln -s /state/data /app/data \
    && ln -s /state/var /app/var
COPY configs/ ./configs/
COPY --from=frontend /build/frontend/dist/ ./frontend/dist/
USER 10001:10001
EXPOSE 8010
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/v1/health', timeout=4)"]
ENTRYPOINT ["python", "-m", "steuerreport_v2.container_entrypoint"]
