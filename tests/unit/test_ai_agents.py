from datetime import datetime
from decimal import Decimal
import json
import hashlib

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.ai import AiProviderWrite, AiTaskCreate, AiTaskExecute
from steuerreport_v2.contracts.ai_agents import AiAgentsWrite
from steuerreport_v2.contracts.ai_changes import AiChangeGenerate, AiDataQuery
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.ai_corrections import FIELDS
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.ai import AiService
from steuerreport_v2.domain.ai_agents import AiAgentError, AiAgentService
from steuerreport_v2.domain.ai_changes import AiChangeService
from steuerreport_v2.domain.ai_provider import AiProviderService


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr("steuerreport_v2.domain.ai_provider.private_value", lambda _key: "")
    store = DuckDbStore(tmp_path / "agents.duckdb")
    provider = AiProviderService(store)
    provider.save(AiProviderWrite(revision=provider.status().revision, base_url="http://127.0.0.1:18901/v1", model="base-fixture"))
    return store, AiAgentService(store), provider


def test_seven_portable_roles_no_implicit_writes_or_network(setup):
    store, agents, _provider = setup
    before = store.list_admin_settings()
    status = agents.status()
    assert len(status.profiles) == 7
    assert all(not any(profile.models.model_dump().values()) for profile in status.profiles)
    assert status.knowledge["tools"]["propose_corrections"] == {key: sorted(value) for key, value in FIELDS.items()}
    assert agents.status() == status and store.list_admin_settings() == before


def test_profile_save_revision_and_models_do_not_modify_provider_settings(setup):
    _store, agents, provider = setup
    before = provider.status()
    profiles = agents.status()
    profiles.profiles[0].models.local = "local-fixture"
    profiles.profiles[0].models.openrouter = "cloud-fixture"
    result = agents.save(AiAgentsWrite(revision=profiles.revision, profiles=profiles.profiles))
    assert result.revision != profiles.revision and provider.status() == before
    assert agents.bundle("coordinator", provider="local")[2] == "local-fixture"
    assert agents.bundle("coordinator", provider="openrouter")[2] == "cloud-fixture"
    assert agents.bundle("coordinator", provider="cloud", default_model="default")[0]["requested_model"] == "default"
    with pytest.raises(AiAgentError, match="ai_agent_revision_conflict"):
        agents.save(AiAgentsWrite(revision=profiles.revision, profiles=profiles.profiles))


def test_role_model_and_versioned_knowledge_are_used_in_real_adapter_request(setup, monkeypatch):
    store, agents, provider = setup
    status = agents.status()
    role = next(item for item in status.profiles if item.agent_id == "wallet_fifo")
    role.models.local = "fifo-fixture-model"
    status = agents.save(AiAgentsWrite(revision=status.revision, profiles=status.profiles))
    calls = []

    def request(_self, _config, _token, _path, body):
        calls.append(body)
        return {"model": body["model"], "choices": [{"message": {"content": "Fixture-Pruefhinweis ohne steuerliche Freigabe."}, "finish_reason": "stop"}]}

    monkeypatch.setattr(AiProviderService, "_request", request)
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="Pruefe den bereitgestellten FIFO-Hinweis.", agent_id="wallet_fifo", agent_revision=status.revision))
    result = provider.execute(task.task_id, AiTaskExecute(provider_revision=provider.status().revision))
    assert result.status == "done" and len(calls) == 1
    assert calls[0]["model"] == "fifo-fixture-model"
    assert "Wallet- und FIFO-Pruefung" in calls[0]["messages"][0]["content"]
    assert "canonical_events" in calls[0]["messages"][0]["content"]
    assert "tools" not in calls[0] and len(calls[0]["messages"]) == 2
    assert json.loads(result.result_json)["agent"]["revision"] == status.revision
    assert provider.status().config.model == "base-fixture"


def test_changed_or_disabled_role_blocks_before_model_call(setup, monkeypatch):
    store, agents, provider = setup
    status = agents.status()
    task = AiService(store).create_task(AiTaskCreate(task_type="review", prompt="Fixture-Pruefauftrag", agent_id="coordinator", agent_revision=status.revision))
    status.profiles[0].enabled = False
    agents.save(AiAgentsWrite(revision=status.revision, profiles=status.profiles))
    monkeypatch.setattr(AiProviderService, "_request", lambda *_args: pytest.fail("No provider call for stale agent"))
    result = provider.execute(task.task_id, AiTaskExecute())
    assert result.status == "failed" and json.loads(result.result_json)["error"] == "ai_agent_revision_conflict"
    with pytest.raises(AiAgentError, match="ai_agent_unavailable"):
        agents.bundle("coordinator")


def test_change_proposals_include_selected_agent_and_knowledge_in_audit(setup, monkeypatch):
    store, agents, provider = setup
    store.add_canonical_event(CanonicalEventCreate(source="fixture", event_time=datetime(2025, 1, 1), event_type="reward", asset="BTC", quantity=Decimal("1")))
    service = AiChangeService(store)
    context = service.context(AiDataQuery())
    row = context.rows[0]
    used_system = []

    def request(_self, _config, _token, _path, body):
        used_system.append(body["messages"][0]["content"])
        assert "Steuer-, Mining- und Reward-Pruefung" in body["messages"][0]["content"]
        assert "Keine eigenen Tools" in body["messages"][0]["content"]
        draft = {"summary": "Fixture-Belegklassifikation", "changes": [{"kind": "event", "target_id": row.target_id, "before_sha256": row.revision,
                 "patch": {"event_type": "mining"}, "reason": "Der vorliegende Fixture-Beleg dokumentiert Mining.", "evidence_ref": "fixture:receipt"}]}
        return {"model": body["model"], "choices": [{"message": {"content": json.dumps(draft)}, "finish_reason": "stop"}]}

    monkeypatch.setattr(AiProviderService, "_request", request)
    item = service.generate(AiChangeGenerate(query=AiDataQuery(), selected_ids=[row.target_id], context_sha256=context.context_sha256,
        instruction="Mining-Klassifikation anhand des vorliegenden Fixture-Belegs vorschlagen.", provider_revision=provider.status().revision,
        agent_id="tax_rewards", agent_revision=agents.status().revision))
    assert item.generation["agent"]["agent_id"] == "tax_rewards"
    assert item.generation["agent"]["knowledge_sha256"] == agents.status().knowledge_sha256
    assert item.generation["system_prompt_sha256"] == hashlib.sha256(used_system[0].encode()).hexdigest()
    assert store.list_canonical_events()[0].event_type == "reward"


def test_agent_api_rejects_missing_duplicate_and_unknown_roles_without_echo(setup):
    store, agents, _provider = setup
    client = TestClient(create_app(store))
    status = client.get("/api/v1/ai/agents").json()["data"]
    status["profiles"][0]["agent_id"] = "execute_sql"
    response = client.put("/api/v1/ai/agents", json={"revision": status["revision"], "profiles": status["profiles"]})
    assert response.status_code == 422 and response.json() == {"detail": "ai_request_invalid"}
    status = agents.status()
    status.profiles[0] = status.profiles[1]
    response = client.put("/api/v1/ai/agents", json={"revision": status.revision, "profiles": [profile.model_dump() for profile in status.profiles]})
    assert response.status_code == 400 and response.json()["detail"] == "ai_agents_config_invalid"
