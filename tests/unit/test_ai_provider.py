from concurrent.futures import ThreadPoolExecutor
import json
import os
from threading import Event

from fastapi.testclient import TestClient
import httpx
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.ai import AiProviderWrite, AiTaskCreate, AiTaskExecute
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.ai import AiService
from steuerreport_v2.domain.ai_provider import AiProviderError, AiProviderService, CONFIG_KEY, OPENROUTER_BASE, SECRET_KEY, normalize_base_url


TOKEN = "unit" + "-fixture" + "-credential"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    key = tmp_path / "vault.key"
    key.write_bytes(os.urandom(32))
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key))
    monkeypatch.setenv("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "true")
    monkeypatch.setattr("steuerreport_v2.domain.ai_provider.private_value", lambda _name: "")
    store = DuckDbStore(tmp_path / "ai.duckdb")
    return store, AiProviderService(store)


def save(service, **values):
    return service.save(AiProviderWrite(
        **{"revision": service.status().revision, "base_url": "http://127.0.0.1:18799/v1", "model": "fixture-model", **values}
    ))


def transport(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr("steuerreport_v2.domain.ai_provider.httpx.Client", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))


def completion(text="Pruefung als unverbindlicher Hinweis.", **extra):
    return {"model": "fixture-model", "choices": [{"message": {"content": text}, "finish_reason": "stop"}], **extra}


def test_empty_installation_has_no_provider_and_does_not_send_requests(setup, monkeypatch):
    _store, service = setup
    transport(monkeypatch, lambda _request: pytest.fail("No automatic external call"))
    status = service.status()
    assert status.config.provider == "local"
    assert status.config.model == status.config.base_url == ""
    assert not status.configured and not status.external_enabled and not status.api_key_present
    assert status.encrypted_secrets_available
    with pytest.raises(AiProviderError, match="ai_not_configured"):
        service.probe()


def test_save_openrouter_key_encrypted_bound_and_no_echo(setup, monkeypatch):
    store, service = setup
    transport(monkeypatch, lambda _request: pytest.fail("Saving must not contact any provider"))
    status = save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN)
    assert status.configured and status.api_key_readable and not status.external_enabled
    assert TOKEN not in status.model_dump_json()
    rows = {item.key: item.value_json for item in store.list_admin_settings()}
    assert json.loads(rows[SECRET_KEY])["algorithm"] == "AES-256-GCM"
    assert TOKEN not in str(rows)
    assert service._secret(status.config) == TOKEN
    assert AiProviderService(store).status() == status


def test_cloud_without_global_approval_never_contacts_provider(setup, monkeypatch):
    _store, service = setup
    save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN)
    transport(monkeypatch, lambda _request: pytest.fail("Cloud is not approved"))
    for method in (service.models, service.probe):
        with pytest.raises(AiProviderError, match="external_ai_disabled"):
            method()


def test_model_catalog_and_neutral_openrouter_test_use_saved_connection(setup, monkeypatch):
    _store, service = setup
    save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN, external_enabled=True)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.headers["X-OpenRouter-Title"] == "Steuerreport"
        if request.url.path == "/api/v1/models":
            return httpx.Response(200, json={"data": [
                {"id": "vendor/text-model", "name": "Textmodell", "architecture": {"output_modalities": ["text"]}},
                {"id": "vendor/image-model", "architecture": {"output_modalities": ["image"]}},
            ]})
        assert str(request.url) == OPENROUTER_BASE + "/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "fixture-model" and body["max_tokens"] == 128
        assert "Verbindungstest" in body["messages"][1]["content"]
        assert "tools" not in body and "chat_template_kwargs" not in body
        return httpx.Response(200, json=completion("Verbindungstest erfolgreich."))

    transport(monkeypatch, handler)
    assert [item.id for item in service.models()] == ["vendor/text-model"]
    assert service.probe().answer == "Verbindungstest erfolgreich."
    assert len(calls) == 2


@pytest.mark.parametrize("pricing,expected", [
    ({"prompt": "0", "completion": "0", "request": "0"}, True),
    ({"prompt": "0", "completion": "0"}, True),
    ({"prompt": 0, "completion": 0, "request": 0}, True),
    ({"prompt": "0.000001", "completion": "0"}, False),
    ({"prompt": "0", "completion": "0.000002"}, False),
    ({"prompt": "0", "completion": "0", "request": "0.01"}, False),
    ({"prompt": "1e-12", "completion": "0"}, False),
    ({}, None),
    ({"prompt": "NaN", "completion": "0"}, None),
    ({"prompt": "-1", "completion": "0"}, None),
    ({"prompt": True, "completion": "0"}, None),
    ({"prompt": "0", "completion": "Infinity"}, None),
    ({"prompt": "0", "completion": "0", "request": None}, None),
    ({"prompt": "0", "completion": "0", "request": "invalid"}, None),
])
def test_openrouter_free_classification_uses_real_decimal_prices_not_name(setup, monkeypatch, pricing, expected):
    _store, service = setup
    save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN, external_enabled=True)
    transport(monkeypatch, lambda _request: httpx.Response(200, json={"data": [{
        "id": "fixture/misleading:free", "name": "Free im Namen ist kein Preisnachweis",
        "pricing": pricing, "context_length": 131072,
    }]}))
    model = service.models()[0]
    assert model.is_free is expected
    assert model.context_length == 131072
    assert TOKEN not in model.model_dump_json()


def test_non_openrouter_models_do_not_claim_free_pricing(setup, monkeypatch):
    _store, service = setup
    save(service)
    transport(monkeypatch, lambda _request: httpx.Response(200, json={"data": [{
        "id": "local/free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": True,
    }]}))
    model = service.models()[0]
    assert model.is_free is None and model.prompt_price_usd_per_token is None
    assert model.context_length is None


def test_probe_budget_is_configurable_for_reasoning_models(setup, monkeypatch):
    _store, service = setup
    save(service, probe_max_tokens=1024, max_tokens=512)

    def handler(request):
        assert json.loads(request.content)["max_tokens"] == 512
        return httpx.Response(200, json=completion())

    transport(monkeypatch, handler)
    assert service.probe().status == "ok"


@pytest.mark.parametrize("code,error", [(401, "ai_auth_failed"), (402, "ai_credit_required"), (403, "ai_access_denied"), (404, "ai_endpoint_or_model_missing"), (429, "ai_rate_limited"), (503, "ai_provider_http_error"), (302, "ai_provider_http_error")])
def test_provider_errors_are_safe_and_no_redirect_or_retry(setup, monkeypatch, code, error):
    _store, service = setup
    save(service)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(code, json={"error": {"message": TOKEN}}, headers={"Location": "https://other.invalid/"})

    transport(monkeypatch, handler)
    with pytest.raises(AiProviderError, match=error) as raised:
        service.probe()
    assert TOKEN not in str(raised.value) and len(calls) == 1


@pytest.mark.parametrize("thinking,expected", [("server_default", None), ("llamacpp_off", {"enable_thinking": False}), ("ollama_off", None)])
def test_local_completion_and_thinking_controls(setup, monkeypatch, thinking, expected):
    _store, service = setup
    save(service, thinking=thinking)

    def handler(request):
        body = json.loads(request.content)
        assert body.get("chat_template_kwargs") == expected
        assert body.get("reasoning_effort") == ("none" if thinking == "ollama_off" else None)
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=completion())

    transport(monkeypatch, handler)
    assert service.probe().answer


def test_task_execution_stores_visible_result_without_modifying_tax_tables(setup, monkeypatch):
    store, service = setup
    save(service)
    before = store.table_counts(["canonical_events", "raw_objects", "tax_lines", "balance_ledger", "flow_ledger"])
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["messages"][1]["content"] == "Nur diesen synthetischen Text pruefen."
        assert "tools" not in body
        return httpx.Response(200, json=completion(usage={"total_tokens": 20, "private_field": "not-returned"}))

    transport(monkeypatch, handler)
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="Nur diesen synthetischen Text pruefen."))
    assert task.status == "queued"
    result = service.execute(task.task_id, AiTaskExecute())
    assert result.status == "done"
    data = json.loads(result.result_json)
    assert data["review_only"] and data["usage"] == {"total_tokens": 20}
    assert store.table_counts(list(before)) == before
    assert service.execute(task.task_id, AiTaskExecute()) == result
    assert len(calls) == 1


@pytest.mark.parametrize("task_allowed,confirmed", [(False, False), (True, False), (False, True)])
def test_cloud_requires_global_and_both_per_task_approvals(setup, monkeypatch, task_allowed, confirmed):
    store, service = setup
    save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN, external_enabled=True)
    transport(monkeypatch, lambda _request: pytest.fail("Task approval missing"))
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="synthetisch", allow_external=task_allowed))
    result = service.execute(task.task_id, AiTaskExecute(confirm_external=confirmed))
    assert result.status == "failed"
    assert json.loads(result.result_json)["error"] == "ai_task_external_not_confirmed"


def test_explicitly_approved_cloud_task_executes(setup, monkeypatch):
    store, service = setup
    save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN, external_enabled=True)
    transport(monkeypatch, lambda _request: httpx.Response(200, json=completion()))
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="synthetisch", allow_external=True))
    assert service.execute(task.task_id, AiTaskExecute(confirm_external=True)).status == "done"


def test_changed_provider_configuration_requires_renewed_approval(setup, monkeypatch):
    store, service = setup
    approved = save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN, external_enabled=True)
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="synthetisch", allow_external=True))
    save(service, provider="openrouter", base_url=OPENROUTER_BASE, model="different-model", external_enabled=True)
    transport(monkeypatch, lambda _request: pytest.fail("Changed configuration needs renewed approval"))
    result = service.execute(task.task_id, AiTaskExecute(confirm_external=True, provider_revision=approved.revision))
    assert result.status == "failed"
    assert json.loads(result.result_json)["error"] == "ai_config_revision_conflict"


def test_provider_change_does_not_reuse_key_and_saves_atomically(setup):
    _store, service = setup
    status = save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN)
    with pytest.raises(AiProviderError, match="ai_key_endpoint_changed"):
        save(service, provider="cloud", base_url="https://other.invalid/v1", external_enabled=True)
    assert service.status() == status
    cleared = save(service, provider="cloud", base_url="https://other.invalid/v1", clear_api_key=True)
    assert not cleared.api_key_present and not cleared.configured


def test_old_revision_rejected_after_key_only_change(setup):
    _store, service = setup
    old = save(service)
    save(service, api_key=TOKEN)
    with pytest.raises(AiProviderError, match="ai_config_revision_conflict"):
        service.save(AiProviderWrite(**old.config.model_dump(), revision=old.revision))


def test_generic_settings_cannot_forward_bound_key_to_another_endpoint(setup, monkeypatch):
    store, service = setup
    save(service, provider="openrouter", base_url=OPENROUTER_BASE, api_key=TOKEN, external_enabled=True)
    config = service.status().config.model_dump()
    config.update(provider="cloud", base_url="https://other.invalid/v1")
    store.upsert_admin_setting(AdminSettingWrite(key=CONFIG_KEY, value_json=json.dumps(config)))
    transport(monkeypatch, lambda _request: pytest.fail("Key cannot leave its saved origin"))
    with pytest.raises(AiProviderError, match="ai_key_unreadable_or_wrong_endpoint"):
        service.probe()


def test_no_plaintext_fallback_when_vault_missing(setup, monkeypatch):
    store, service = setup
    monkeypatch.delenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE")
    with pytest.raises(AiProviderError, match="ai_encrypted_vault_required"):
        save(service, api_key=TOKEN)
    assert store.list_admin_settings() == []


@pytest.mark.parametrize("url", ["ftp://127.0.0.1", "https://user:password@host.invalid/v1", "https://host.invalid/?key=example", "https://host.invalid/#key", "http://bad host/v1"])
def test_invalid_urls_rejected(url):
    with pytest.raises(AiProviderError, match="ai_url_invalid"):
        normalize_base_url(url)


def test_url_suffixes_normalized_without_double_v1():
    assert normalize_base_url("http://localhost:18799/") == "http://localhost:18799/v1"
    assert normalize_base_url("http://localhost:18799/v1/chat/completions") == "http://localhost:18799/v1"
    assert normalize_base_url(OPENROUTER_BASE) == OPENROUTER_BASE


def test_local_mode_never_calls_public_host(setup, monkeypatch):
    _store, service = setup
    save(service, base_url="https://8.8.8.8/v1")
    transport(monkeypatch, lambda _request: pytest.fail("Public endpoint needs cloud consent"))
    with pytest.raises(AiProviderError, match="ai_local_endpoint_not_private"):
        service.probe()


@pytest.mark.parametrize("response,error", [({"choices": []}, "ai_invalid_response"), ({"choices": [{"message": {"reasoning_content": "private chain"}}]}, "ai_empty_answer"), ({"error": {"message": TOKEN}}, "ai_provider_response_error")])
def test_invalid_or_reasoning_only_response_is_not_success(setup, monkeypatch, response, error):
    _store, service = setup
    save(service)
    transport(monkeypatch, lambda _request: httpx.Response(200, json=response))
    with pytest.raises(AiProviderError, match=error):
        service.probe()


def test_provider_reflected_secret_is_redacted(setup, monkeypatch):
    _store, service = setup
    save(service, api_key=TOKEN)
    transport(monkeypatch, lambda _request: httpx.Response(200, json=completion("Text " + TOKEN)))
    assert TOKEN not in service.probe().model_dump_json()


def test_failed_call_stored_safely_and_not_retried(setup, monkeypatch):
    store, service = setup
    save(service)

    def handler(_request):
        raise httpx.ReadTimeout(TOKEN)

    transport(monkeypatch, handler)
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="synthetisch"))
    result = service.execute(task.task_id, AiTaskExecute())
    assert result.status == "failed" and json.loads(result.result_json)["error"] == "ai_timeout"
    assert TOKEN not in result.result_json
    with pytest.raises(AiProviderError, match="ai_task_not_queued"):
        service.execute(task.task_id, AiTaskExecute())


def test_parallel_execute_claims_exactly_once(setup, monkeypatch):
    store, service = setup
    save(service)
    entered, proceed = Event(), Event()

    def handler(_request):
        entered.set()
        assert proceed.wait(10)
        return httpx.Response(200, json=completion())

    transport(monkeypatch, handler)
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="synthetisch"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.execute, task.task_id, AiTaskExecute())
        assert entered.wait(10)
        try:
            with pytest.raises(AiProviderError, match="ai_task_running"):
                AiService(store).delete_task(task.task_id)
            with pytest.raises(AiProviderError, match="ai_task_not_queued"):
                service.execute(task.task_id, AiTaskExecute())
        finally:
            proceed.set()
        assert first.result().status == "done"


def test_api_validation_and_secrets_never_echo_input(setup):
    store, service = setup
    client = TestClient(create_app(store))
    response = client.put("/api/v1/ai/provider", json={"api_key": TOKEN, "revision": {}, "max_tokens": -10})
    assert response.status_code == 422 and TOKEN not in response.text
    assert response.json()["detail"] == "ai_request_invalid"
    response = client.put("/api/v1/ai/provider", json={"provider": "openrouter", "model": "fixture-model", "api_key": TOKEN, "revision": service.status().revision})
    assert response.status_code == 200 and TOKEN not in response.text
    assert client.get("/api/v1/ai/provider").json()["data"]["api_key_readable"]


def test_api_execute_and_missing_task(setup, monkeypatch):
    store, service = setup
    save(service)
    transport(monkeypatch, lambda _request: httpx.Response(200, json=completion()))
    client = TestClient(create_app(store))
    task = client.post("/api/v1/ai/tasks", json={"task_type": "review", "prompt": "synthetisch"}).json()["data"]
    response = client.post(f"/api/v1/ai/tasks/{task['task_id']}/execute", json={})
    assert response.json()["data"]["status"] == "done"
    assert client.post("/api/v1/ai/tasks/missing/execute", json={}).status_code == 404
