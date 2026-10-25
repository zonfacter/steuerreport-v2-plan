"""Explicit, text-only model calls; never execute model tools or mutate tax data."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import ValidationError

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.ai import AiModel, AiProbeResult, AiProviderConfig, AiProviderStatus, AiProviderWrite, AiTask, AiTaskExecute
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secret_vault import encrypt_secret_setting, load_vault_key
from steuerreport_v2.domain.secrets import resolve_secret_value
from steuerreport_v2.private_settings import private_value


CONFIG_KEY = "ai.provider.config"
SECRET_KEY = "secret.ai.provider.api_key"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
SYSTEM_PROMPT = (
    "Du bist ein deutschsprachiger, vorsichtiger Analyseassistent. Du erhaeltst nur den Text "
    "dieser Anfrage, keinen automatischen Datenbank- oder Dateizugriff. Erfinde keine Belege, "
    "Preise, Transaktionen oder medizinischen/rechtlichen Feststellungen. Benenne fehlende "
    "Nachweise und Unsicherheiten. Deine Antwort ist ein unverbindlicher Review-Hinweis, "
    "keine steuerliche Freigabe. Du kannst keine Buchungen oder Einstellungen aendern."
)


class AiProviderError(ValueError):
    """Only fixed error codes may cross the API boundary."""


def normalize_base_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or any(char.isspace() or ord(char) < 32 for char in value)):
            raise ValueError
        _ = parsed.port
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            path = path.removesuffix("/chat/completions")
        path = path or "/v1"
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))
    except ValueError:
        raise AiProviderError("ai_url_invalid") from None


class AiProviderService:
    def __init__(self, store: DuckDbStore):
        self.store = store

    def _settings(self) -> dict[str, str]:
        return {item.key: item.value_json for item in self.store.list_admin_settings()}

    @staticmethod
    def _enabled(settings: dict[str, str], key: str, default: bool) -> bool:
        try:
            return json.loads(settings.get(key, json.dumps(default))) is True
        except (ValueError, TypeError):
            return False

    def status(self) -> AiProviderStatus:
        settings = self._settings()
        raw = settings.get(CONFIG_KEY, "{}")
        try:
            config = AiProviderConfig.model_validate_json(raw)
        except (ValueError, ValidationError):
            raise AiProviderError("ai_saved_config_invalid") from None
        source = "settings" if CONFIG_KEY in settings else "empty"
        if source == "empty" and (private_value("local_llm_base") or private_value("local_llm_model")):
            config = AiProviderConfig(base_url=private_value("local_llm_base"), model=private_value("local_llm_model"))
            source = "legacy_profile"
        present = SECRET_KEY in settings
        readable = False
        if present:
            try:
                readable = bool(self._secret(config))
            except AiProviderError:
                pass
        return AiProviderStatus(
            config=config, revision=hashlib.sha256(json.dumps({key: settings.get(key) for key in (CONFIG_KEY, SECRET_KEY, "ai.local.enabled", "ai.external.enabled")}, sort_keys=True).encode()).hexdigest(), source=source,
            local_enabled=self._enabled(settings, "ai.local.enabled", True),
            external_enabled=self._enabled(settings, "ai.external.enabled", False),
            api_key_present=present, api_key_readable=readable,
            encrypted_secrets_available=load_vault_key() is not None,
            configured=bool(config.base_url and config.model and (config.provider == "local" or readable)),
        )

    def save(self, payload: AiProviderWrite) -> AiProviderStatus:
        config = AiProviderConfig.model_validate(payload.model_dump(exclude={"api_key"}))
        config.base_url = normalize_base_url(config.base_url)
        config.model = config.model.strip()
        if config.provider == "openrouter":
            config.base_url = config.base_url or OPENROUTER_BASE
            if config.base_url != OPENROUTER_BASE:
                raise AiProviderError("ai_openrouter_url_invalid")
            config.token_parameter = "max_tokens"
        if config.provider != "local" and config.base_url and not config.base_url.startswith("https://"):
            raise AiProviderError("ai_cloud_https_required")
        if config.provider != "local" and config.thinking != "server_default":
            raise AiProviderError("ai_local_thinking_only")
        if any(ord(char) < 32 for char in config.model):
            raise AiProviderError("ai_model_invalid")
        token = payload.api_key.get_secret_value().strip() if payload.api_key is not None else ""
        if len(token) > 8192 or any(char.isspace() or not 33 <= ord(char) <= 126 for char in token):
            raise AiProviderError("ai_key_invalid")
        if token and payload.clear_api_key:
            raise AiProviderError("ai_key_action_conflict")
        with self.store.exclusive_access():
            current = self.status()
            if current.revision != payload.revision:
                raise AiProviderError("ai_config_revision_conflict")
            changed_endpoint = (normalize_base_url(current.config.base_url), current.config.provider) != (config.base_url, config.provider)
            if current.api_key_present and changed_endpoint and not (token or payload.clear_api_key):
                raise AiProviderError("ai_key_endpoint_changed")
            rows = [
                AdminSettingWrite(key=CONFIG_KEY, value_json=config.model_dump_json()),
                AdminSettingWrite(key="ai.local.enabled", value_json=json.dumps(payload.local_enabled)),
                AdminSettingWrite(key="ai.external.enabled", value_json=json.dumps(payload.external_enabled)),
            ]
            if token:
                vault = load_vault_key()
                if vault is None:
                    raise AiProviderError("ai_encrypted_vault_required")
                bound = json.dumps({"provider": config.provider, "base_url": config.base_url, "token": token})
                rows.append(AdminSettingWrite(key=SECRET_KEY, value_json=encrypt_secret_setting(SECRET_KEY, bound, vault)))
            self.store.write_admin_settings_batch(rows, [SECRET_KEY] if payload.clear_api_key else [])
        return self.status()

    def _secret(self, config: AiProviderConfig) -> str:
        try:
            raw = resolve_secret_value(self.store, SECRET_KEY)
            if not raw:
                return ""
            value = json.loads(raw)
            if value["base_url"] != normalize_base_url(config.base_url) or value["provider"] != config.provider:
                raise ValueError
            token = value["token"]
            if not isinstance(token, str) or not token:
                raise ValueError
            return token
        except (ValueError, RuntimeError, KeyError, TypeError, UnicodeDecodeError):
            raise AiProviderError("ai_key_unreadable_or_wrong_endpoint") from None

    def _connection(self, *, require_model: bool = True, expected_revision: str | None = None) -> tuple[AiProviderConfig, str]:
        status = self.status()
        if expected_revision is not None and status.revision != expected_revision:
            raise AiProviderError("ai_config_revision_conflict")
        config = status.config.model_copy()
        config.base_url = normalize_base_url(config.base_url)
        if config.provider != "local" and not status.external_enabled:
            raise AiProviderError("external_ai_disabled")
        if config.provider == "local" and not status.local_enabled:
            raise AiProviderError("local_ai_disabled")
        if not config.base_url or (require_model and not config.model):
            raise AiProviderError("ai_not_configured")
        if config.provider == "openrouter" and config.base_url != OPENROUTER_BASE:
            raise AiProviderError("ai_openrouter_url_invalid")
        if config.provider != "local" and not config.base_url.startswith("https://"):
            raise AiProviderError("ai_cloud_https_required")
        token = self._secret(config)
        if config.provider != "local" and not token:
            raise AiProviderError("ai_api_key_missing")
        if config.provider == "local":
            host = urlsplit(config.base_url).hostname
            try:
                addresses = socket.getaddrinfo(host, urlsplit(config.base_url).port or 80, type=socket.SOCK_STREAM)
                if not addresses:
                    raise OSError
                for address in addresses:
                    ip = ipaddress.ip_address(address[4][0])
                    if not (ip.is_private or ip.is_loopback) or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                        raise AiProviderError("ai_local_endpoint_not_private")
            except OSError:
                raise AiProviderError("ai_connection_failed") from None
        return config, token

    def _request(self, config: AiProviderConfig, token: str, path: str, body: dict | None = None) -> dict:
        deadline = time.monotonic() + config.timeout_seconds
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if config.provider == "openrouter":
            headers["X-OpenRouter-Title"] = "Steuerreport"
        try:
            with httpx.Client(timeout=httpx.Timeout(config.timeout_seconds, connect=10), follow_redirects=False, trust_env=False) as client:
                with client.stream("GET" if body is None else "POST", config.base_url + path, headers=headers, json=body) as response:
                    if response.status_code >= 300:
                        code = {401: "ai_auth_failed", 403: "ai_access_denied", 402: "ai_credit_required", 404: "ai_endpoint_or_model_missing", 429: "ai_rate_limited"}.get(response.status_code, "ai_provider_http_error")
                        raise AiProviderError(code)
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise AiProviderError("ai_timeout")
                        chunks.extend(chunk)
                        if len(chunks) > (8 * 1024 * 1024 if body is None else 2 * 1024 * 1024):
                            raise AiProviderError("ai_response_too_large")
                    data = json.loads(chunks)
            if not isinstance(data, dict) or data.get("error"):
                raise AiProviderError("ai_provider_response_error")
            return data
        except httpx.TimeoutException:
            raise AiProviderError("ai_timeout") from None
        except httpx.HTTPError:
            raise AiProviderError("ai_connection_failed") from None
        except (ValueError, UnicodeDecodeError) as exc:
            if isinstance(exc, AiProviderError):
                raise
            raise AiProviderError("ai_invalid_response") from None

    def models(self) -> list[AiModel]:
        config, token = self._connection(require_model=False)
        data = self._request(config, token, "/models").get("data")
        if not isinstance(data, list):
            raise AiProviderError("ai_invalid_response")
        result = {}
        for row in data[:5000]:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            modalities = (row.get("architecture") or {}).get("output_modalities", ["text"]) if isinstance(row.get("architecture"), dict) else ["text"]
            if not isinstance(modalities, list) or "text" not in modalities:
                continue
            model_id = self._redact(row["id"], token)[:256]
            if model_id:
                model = AiModel(id=model_id, name=self._redact(str(row.get("name") or model_id), token)[:256])
                context = row.get("context_length")
                if type(context) is int and 0 < context <= 1_000_000_000:
                    model.context_length = context
                if config.provider == "openrouter":
                    prices = row.get("pricing") if isinstance(row.get("pricing"), dict) else {}
                    prompt = self._catalog_price(prices.get("prompt"))
                    completion = self._catalog_price(prices.get("completion"))
                    request = self._catalog_price(prices.get("request", "0"))
                    model.prompt_price_usd_per_token = prompt
                    model.completion_price_usd_per_token = completion
                    model.request_price_usd = request
                    known = [Decimal(value) for value in (prompt, completion, request) if value is not None]
                    if any(value > 0 for value in known):
                        model.is_free = False
                    elif len(known) == 3:
                        model.is_free = True
                result[model_id] = model
        return sorted(result.values(), key=lambda item: item.id)

    @staticmethod
    def _catalog_price(value: object) -> str | None:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)) or len(str(value)) > 128:
            return None
        try:
            price = Decimal(str(value))
            return str(price) if price.is_finite() and price >= 0 else None
        except InvalidOperation:
            return None

    @staticmethod
    def _redact(text: str, token: str) -> str:
        return text.replace(token, "[REDACTED]") if token else text

    def complete(self, prompt: str, *, test: bool = False, confirm_external: bool = False, expected_revision: str | None = None, system_prompt: str = SYSTEM_PROMPT, model_override: str | None = None) -> dict:
        if not prompt.strip() or len(prompt) > 32000:
            raise AiProviderError("ai_prompt_invalid")
        config, token = self._connection(expected_revision=expected_revision)
        if model_override is not None:
            if not model_override.strip() or len(model_override) > 256 or any(ord(char) < 32 for char in model_override):
                raise AiProviderError("ai_model_invalid")
            config.model = model_override
        if config.provider != "local" and not confirm_external:
            raise AiProviderError("ai_task_external_not_confirmed")
        body = {"model": config.model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                "stream": False, config.token_parameter: min(config.max_tokens, config.probe_max_tokens) if test else config.max_tokens}
        if config.provider == "local" and config.thinking == "llamacpp_off":
            body["chat_template_kwargs"] = {"enable_thinking": False}
        elif config.provider == "local" and config.thinking == "ollama_off":
            body["reasoning_effort"] = "none"
        data = self._request(config, token, "/chat/completions", body)
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content")
            if isinstance(content, list):
                content = "\n".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
            if not isinstance(content, str) or not content.strip():
                raise AiProviderError("ai_empty_answer")
            usage = data.get("usage") or {}
            return {"answer": self._redact(content, token), "provider": config.provider,
                    "model": config.model, "resolved_model": self._redact(str(data.get("model") or config.model), token),
                    "truncated": choice.get("finish_reason") == "length", "review_only": True,
                    "usage": {key: value for key, value in usage.items() if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(value, int)}}
        except (KeyError, IndexError, TypeError, AttributeError):
            raise AiProviderError("ai_invalid_response") from None

    def probe(self) -> AiProbeResult:
        result = self.complete("Antworte kurz auf Deutsch: Verbindungstest erfolgreich. Keine privaten Daten sind enthalten.", test=True, confirm_external=True)
        return AiProbeResult(model=result["resolved_model"], answer=result["answer"], truncated=result["truncated"])

    def execute(self, task_id: str, payload: AiTaskExecute) -> AiTask:
        from steuerreport_v2.domain.ai_agents import AiAgentError, AiAgentService
        task = self.store.get_ai_task(task_id)
        if task is None:
            raise AiProviderError("ai_task_not_found")
        if task.status == "done":
            return task
        if not self.store.claim_ai_task(task_id):
            raise AiProviderError("ai_task_not_queued")
        try:
            current = self.status()
            if payload.provider_revision is not None and payload.provider_revision != current.revision:
                raise AiProviderError("ai_config_revision_conflict")
            config = current.config
            if config.provider != "local" and not (task.allow_external and payload.confirm_external):
                raise AiProviderError("ai_task_external_not_confirmed")
            options = {}
            agent = (json.loads(task.result_json or "{}") or {}).get("agent_request")
            if agent:
                snapshot, agent_prompt, model = AiAgentService(self.store).bundle(agent["agent_id"], expected_revision=agent["revision"], provider=config.provider, default_model=config.model)
                options = {"system_prompt": SYSTEM_PROMPT + agent_prompt, "model_override": model}
            result = self.complete(task.prompt, confirm_external=task.allow_external and payload.confirm_external, expected_revision=current.revision, **options)
            if agent:
                result["agent"] = snapshot
            result["configuration_sha256"] = current.revision
            status = "done"
        except (AiProviderError, AiAgentError) as exc:
            result = {"error": str(exc), "review_only": True}
            status = "failed"
        except Exception:
            result = {"error": "ai_execution_failed", "review_only": True}
            status = "failed"
        self.store.finish_ai_task(task_id, status=status, result_json=json.dumps(result, ensure_ascii=True, sort_keys=True))
        completed = self.store.get_ai_task(task_id)
        if completed is None:
            raise AiProviderError("ai_task_not_found")
        return completed
