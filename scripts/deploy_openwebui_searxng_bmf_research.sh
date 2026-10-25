#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=${STEUERREPORT_ROOT:-/workspace/steuerreport-v2-plan}
COMPOSE_FILE=${OPENWEBUI_COMPOSE_FILE:-/opt/openclaw/stack/compose.yml}
OPENWEBUI_DB=${OPENWEBUI_DB:-/opt/openwebui/data/webui.db}
SEARXNG_DIR=${SEARXNG_DIR:-/opt/searxng}
STATE_DIR=${STATE_DIR:-/var/lib/openwebui-searxng-bmf-research}
IMAGE_TAG=docker.io/searxng/searxng:latest
OPENWEBUI_DERIVED_IMAGE=local/open-webui:v0.11.3-bmf-web-v1
OPENWEBUI_INTEGRATION_DIR="$ROOT/integrations/openwebui"
SEARCH_QUERY='site:gesetze-im-internet.de EStG 23 private Veraeusserungsgeschaefte'

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/deploy.lock"
flock -n 9 || exit 0

if [[ -f "$STATE_DIR/complete" ]]; then
  exit 0
fi

for required in \
  "$COMPOSE_FILE" \
  "$OPENWEBUI_DB" \
  "$SEARXNG_DIR/settings.yml" \
  "$ROOT/scripts/configure_openwebui_web_search.py" \
  "$ROOT/scripts/configure_openwebui_steuerreport_agents.py" \
  "$OPENWEBUI_INTEGRATION_DIR/Dockerfile.web-loader-charset" \
  "$OPENWEBUI_INTEGRATION_DIR/patch_web_loader_charset.py" \
  "$OPENWEBUI_INTEGRATION_DIR/patch_rag_source_url.py" \
  "$OPENWEBUI_INTEGRATION_DIR/patch_web_rag_raw_query.py"
do
  [[ -f "$required" ]] || { echo "Missing deployment artifact: $required" >&2; exit 3; }
done

current_image=$(python3 - "$COMPOSE_FILE" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    config = yaml.safe_load(handle)
print(config["services"]["searxng"]["image"])
PY
)

openwebui_compose_image=$(python3 - "$COMPOSE_FILE" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    config = yaml.safe_load(handle)
print(config["services"]["open-webui"]["image"])
PY
)
[[ "$openwebui_compose_image" == "$OPENWEBUI_DERIVED_IMAGE" ]] || {
  echo "Compose OpenWebUI image is $openwebui_compose_image, expected $OPENWEBUI_DERIVED_IMAGE" >&2
  exit 4
}

docker build \
  -t "$OPENWEBUI_DERIVED_IMAGE" \
  -f "$OPENWEBUI_INTEGRATION_DIR/Dockerfile.web-loader-charset" \
  "$OPENWEBUI_INTEGRATION_DIR"

if ! docker image inspect "$current_image" >/dev/null 2>&1; then
  echo "SearXNG image is not local; attempting official registry pull"
  if ! timeout 240s docker pull "$current_image"; then
    echo "Registry currently unreachable; deployment remains pending for the next timer run"
    exit 0
  fi
fi

if [[ "$current_image" == *":latest" ]]; then
  pinned_image=$(docker image inspect "$IMAGE_TAG" --format '{{index .RepoDigests 0}}')
  [[ -n "$pinned_image" ]] || { echo "SearXNG image has no repo digest" >&2; exit 4; }
  [[ "$pinned_image" == docker.io/* ]] || pinned_image="docker.io/$pinned_image"
  python3 - "$COMPOSE_FILE" "$pinned_image" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
pinned = sys.argv[2]
text = path.read_text(encoding="utf-8")
updated, count = re.subn(
    r"(?m)^(\s*image:\s*)docker\.io/searxng/searxng:latest\s*$",
    rf"\1{pinned}",
    text,
)
if count != 1:
    raise SystemExit(f"expected one SearXNG image line, found {count}")
path.write_text(updated, encoding="utf-8")
PY
  current_image=$pinned_image
fi

searx_uid=$(docker run --rm --entrypoint sh "$current_image" -c 'id -u searxng 2>/dev/null || id -u' | tail -1)
searx_gid=$(docker run --rm --entrypoint sh "$current_image" -c 'id -g searxng 2>/dev/null || id -g' | tail -1)
chown -R "$searx_uid:$searx_gid" "$SEARXNG_DIR"
chmod 700 "$SEARXNG_DIR"
chmod 600 "$SEARXNG_DIR/settings.yml"

docker compose -f "$COMPOSE_FILE" config --quiet
docker compose -f "$COMPOSE_FILE" up -d searxng

for _ in $(seq 1 60); do
  if docker exec -i open-webui python - <<'PY' >/dev/null 2>&1
import urllib.request

with urllib.request.urlopen("http://searxng:8080/", timeout=3) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
  then
    break
  fi
  sleep 2
done

docker exec -i open-webui python - "$SEARCH_QUERY" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

query = urllib.parse.urlencode(
    {"q": sys.argv[1], "format": "json", "language": "de-DE", "safesearch": 1}
)
with urllib.request.urlopen(f"http://searxng:8080/search?{query}", timeout=45) as response:
    payload = json.load(response)
results = payload.get("results") or []
official = (
    "gesetze-im-internet.de",
    "bundesfinanzministerium.de",
    "bundesfinanzhof.de",
    "eur-lex.europa.eu",
)
if not any(any(domain in str(item.get("url", "")) for domain in official) for item in results):
    raise SystemExit("SearXNG returned no official German/EU primary-source result")
print(f"SearXNG primary-source results: {len(results)}")
PY

docker compose -f "$COMPOSE_FILE" up -d --no-deps open-webui
for _ in $(seq 1 90); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8082/health \
    | grep -Fq '"status":true'; then
    break
  fi
  sleep 2
done
curl --fail --silent --max-time 5 http://127.0.0.1:8082/health \
  | grep -Fq '"status":true'

admin_id=$(sqlite3 "$OPENWEBUI_DB" \
  "select id from user where role='admin' order by created_at limit 1;")
[[ -n "$admin_id" ]] || { echo "OpenWebUI admin user not found" >&2; exit 5; }

token=$(docker exec -i -e OPENWEBUI_TEMP_ADMIN_ID="$admin_id" open-webui python - <<'PY'
from datetime import timedelta
import os

from open_webui.utils.auth import create_token

print(create_token({"id": os.environ["OPENWEBUI_TEMP_ADMIN_ID"]}, timedelta(minutes=30)))
PY
)

OPENWEBUI_API_TOKEN="$token" \
  python3 "$ROOT/scripts/configure_openwebui_web_search.py"
OPENWEBUI_API_TOKEN="$token" \
  python3 "$ROOT/scripts/configure_openwebui_steuerreport_agents.py"

# Model metadata is cached in-process. Reload it before the browser-equivalent
# web research acceptance test.
docker restart open-webui >/dev/null
for _ in $(seq 1 90); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8082/health \
    | grep -Fq '"status":true'; then
    break
  fi
  sleep 2
done
curl --fail --silent --max-time 5 http://127.0.0.1:8082/health \
  | grep -Fq '"status":true'

OPENWEBUI_API_TOKEN="$token" OPENWEBUI_SEARCH_QUERY="$SEARCH_QUERY" python3 - <<'PY'
import os

import httpx

response = httpx.post(
    "http://127.0.0.1:8082/api/v1/retrieval/process/web/search",
    headers={"Authorization": f"Bearer {os.environ['OPENWEBUI_API_TOKEN']}"},
    json={"queries": [os.environ["OPENWEBUI_SEARCH_QUERY"]]},
    timeout=240,
)
response.raise_for_status()
payload = response.json()
if payload.get("status") is not True or int(payload.get("loaded_count", 0)) < 1:
    raise SystemExit("OpenWebUI web-search smoke test did not load a source")
urls = payload.get("filenames") or []
official = (
    "gesetze-im-internet.de",
    "bundesfinanzministerium.de",
    "bundesfinanzhof.de",
    "eur-lex.europa.eu",
)
if not any(any(domain in str(url) for domain in official) for url in urls):
    raise SystemExit("OpenWebUI web-search smoke test loaded no primary source")
print(f"OpenWebUI loaded primary sources: {len(urls)}")
PY

OPENWEBUI_API_TOKEN="$token" \
  python3 "$ROOT/scripts/configure_openwebui_web_search.py" --verify-only
OPENWEBUI_API_TOKEN="$token" \
  python3 "$ROOT/scripts/configure_openwebui_steuerreport_agents.py" --verify-only \
  >/dev/null

OPENWEBUI_API_TOKEN="$token" python3 - <<'PY'
from datetime import datetime, timezone
import os
import uuid

import httpx

question = (
    "Welche Aufzeichnungs- und Mitwirkungspflichten nennt das BMF-Schreiben vom "
    "6. Maerz 2025 fuer private Kryptowerte? Nutze aktuelle Primaerquellen und "
    "nenne direkte Links."
)
response = httpx.post(
    "http://127.0.0.1:8082/api/chat/completions",
    headers={"Authorization": f"Bearer {os.environ['OPENWEBUI_API_TOKEN']}"},
    json={
        "model": "steuerreport-bmf-web-recherche",
        "messages": [{"role": "user", "content": question}],
        "stream": False,
        "features": {"web_search": True},
        "session_id": f"bmf-deployment-acceptance-{uuid.uuid4()}",
    },
    timeout=480,
)
response.raise_for_status()
payload = response.json()
choice = (payload.get("choices") or [{}])[0]
content = ((choice.get("message") or {}).get("content") or "")
lower = content.lower()
required = (
    "bundesfinanzministerium.de",
    "2025-03-06-einzelfragen-kryptowerte",
    "anschaffungskosten",
    "veräußerungserlös",
    "haltedauer",
)
if choice.get("finish_reason") != "stop" or not all(marker in lower for marker in required):
    raise SystemExit("BMF web-research chat acceptance failed")
today = datetime.now(timezone.utc).date().isoformat()
german_today = ".".join(reversed(today.split("-")))
if today not in content and german_today not in content:
    raise SystemExit("BMF web-research response has no current retrieval date")
if "existiert nicht" in lower:
    raise SystemExit("BMF web-research response denied the verified 2025 source")
print("BMF web-research chat acceptance: ok")
PY

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_name="${timestamp}-post-searxng-bmf-research"
local_backup_dir="/opt/openwebui/backups/$backup_name"
remote_backup_dir="/workspace/backups/openwebui/$backup_name"
mkdir -p "$local_backup_dir" "$remote_backup_dir"
chmod 700 "$local_backup_dir" "$remote_backup_dir"
sqlite3 "$OPENWEBUI_DB" ".timeout 10000" ".backup '$local_backup_dir/webui.db'"
install -m 600 "$COMPOSE_FILE" "$local_backup_dir/compose.yml"
install -m 600 /opt/openwebui/openwebui.env "$local_backup_dir/openwebui.env"
install -m 600 "$SEARXNG_DIR/settings.yml" "$local_backup_dir/searxng-settings.yml"
install -m 600 \
  "$ROOT/integrations/openwebui/Dockerfile.web-loader-charset" \
  "$local_backup_dir/Dockerfile.web-loader-charset"
install -m 600 \
  "$ROOT/integrations/openwebui/patch_web_loader_charset.py" \
  "$local_backup_dir/patch_web_loader_charset.py"
install -m 600 \
  "$ROOT/integrations/openwebui/patch_rag_source_url.py" \
  "$local_backup_dir/patch_rag_source_url.py"
install -m 600 \
  "$ROOT/integrations/openwebui/patch_web_rag_raw_query.py" \
  "$local_backup_dir/patch_web_rag_raw_query.py"
(
  cd "$local_backup_dir"
  sha256sum \
    webui.db compose.yml openwebui.env searxng-settings.yml \
    Dockerfile.web-loader-charset patch_web_loader_charset.py \
    patch_rag_source_url.py patch_web_rag_raw_query.py \
    >SHA256SUMS
)

# DuckDB/SQLite online backup directly onto the CIFS workspace can leave a
# zero-byte file. Copy the already validated local artifact instead.
for artifact in \
  webui.db compose.yml openwebui.env searxng-settings.yml \
  Dockerfile.web-loader-charset patch_web_loader_charset.py \
  patch_rag_source_url.py patch_web_rag_raw_query.py
do
  install -m 600 "$local_backup_dir/$artifact" "$remote_backup_dir/$artifact"
done
(
  cd "$remote_backup_dir"
  sha256sum \
    webui.db compose.yml openwebui.env searxng-settings.yml \
    Dockerfile.web-loader-charset patch_web_loader_charset.py \
    patch_rag_source_url.py patch_web_rag_raw_query.py \
    >SHA256SUMS
)

sqlite3 "$OPENWEBUI_DB" 'pragma integrity_check;' | grep -Fxq ok
{
  printf 'completed_at_utc=%s\n' "$timestamp"
  printf 'image=%s\n' "$current_image"
  printf 'openwebui_image=%s\n' "$OPENWEBUI_DERIVED_IMAGE"
  printf 'backup=%s\n' "$backup_name"
} >"$STATE_DIR/complete"

systemctl disable --now openwebui-searxng-bmf-research.timer >/dev/null 2>&1 || true
echo "OpenWebUI SearXNG and BMF research deployment completed"
