from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/configure_openwebui_steuerreport_agents.py"


def load_config_module():
    spec = importlib.util.spec_from_file_location("openwebui_agent_config", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_ids_are_unique_and_cover_all_specialist_roles():
    module = load_config_module()
    ids = [agent["id"] for agent in module.AGENTS]

    assert len(ids) == 7
    assert len(ids) == len(set(ids))
    assert ids == [
        "steuerreport-koordinator",
        "steuerreport-bmf-steuerprofi",
        "steuerreport-wallet-fifo-pruefer",
        "steuerreport-krypto-forensik",
        "steuerreport-stichtag-zugewinn",
        "steuerreport-bmf-web-recherche",
        "steuerreport-bmf-deep-research",
    ]


def test_case_agents_use_native_readonly_tool_and_curated_knowledge():
    module = load_config_module()

    for agent in module.AGENTS[:5]:
        payload = module.model_payload(agent, "knowledge-id")
        assert payload["base_model_id"] == "qwen3.8-27b-balanced-xt7900"
        assert payload["params"]["function_calling"] == "native"
        assert payload["params"]["temperature"] == 0.1
        assert payload["params"]["chat_template_kwargs"] == {"enable_thinking": False}
        assert payload["meta"]["toolIds"] == ["steuerreport_readonly"]
        assert payload["meta"]["knowledge"] == [
            {
                "id": "knowledge-id",
                "name": "Steuerreport V2 - Agenten-Handbuch",
                "type": "collection",
            }
        ]
        builtins = payload["meta"]["builtinTools"]
        assert builtins["web_search"] is False
        assert payload["meta"]["capabilities"]["web_search"] is False
        assert payload["meta"]["capabilities"]["file_upload"] is True
        assert payload["meta"]["capabilities"]["file_context"] is False
        assert payload["meta"]["defaultFeatureIds"] == []
        assert builtins["code_interpreter"] is False
        assert builtins["automations"] is False
        assert builtins["memory"] is False

        expected_max_tokens = 4096 if agent["id"] == "steuerreport-stichtag-zugewinn" else 8192
        assert payload["params"]["max_tokens"] == expected_max_tokens


def test_bmf_research_agent_is_web_only_and_has_no_case_data_access():
    module = load_config_module()
    agent = next(item for item in module.AGENTS if item["id"] == "steuerreport-bmf-web-recherche")

    payload = module.model_payload(agent, "knowledge-id")

    assert payload["base_model_id"] == "qwen3.8-27b-balanced-xt7900"
    assert payload["params"]["function_calling"] == "legacy"
    assert payload["params"]["temperature"] == 0.0
    assert payload["meta"]["toolIds"] == []
    assert payload["meta"]["knowledge"] == []
    assert payload["meta"]["builtinTools"]["web_search"] is True
    assert payload["meta"]["capabilities"]["web_search"] is True
    assert payload["meta"]["capabilities"]["file_upload"] is False
    assert payload["meta"]["capabilities"]["file_context"] is True
    assert payload["meta"]["defaultFeatureIds"] == ["web_search"]
    assert payload["meta"]["builtinTools"]["knowledge"] is False
    assert payload["meta"]["builtinTools"]["memory"] is False
    assert payload["meta"]["builtinTools"]["code_interpreter"] is False
    assert "Wallet-Adressen" in payload["params"]["system"]
    assert "Primaerquellen" in payload["params"]["system"]
    assert "6. Maerz 2025" in payload["params"]["system"]
    assert "Randnummer 87" in payload["params"]["system"]
    assert "Paragraph 150 Absatz 2" in payload["params"]["system"]
    assert "Randnummern 100 bis 105" in payload["params"]["system"]
    assert "Paragraph 97 AO nicht als Aufzeichnungspflicht" in payload["params"]["system"]
    assert "Source retrieved at UTC:" in payload["params"]["system"]
    assert "Paragraph 93 die Auskunft" in payload["params"]["system"]
    assert "konkret in Randnummer 102" in payload["params"]["system"]
    assert "vollstaendig als Liste" in payload["params"]["system"]
    assert "Randnummern 93 bis 99" in payload["params"]["system"]
    assert "Randnummer 101 betrifft" in payload["params"]["system"]
    assert "erlaeutere Randnummern 93 bis 99 ueberhaupt nicht" in payload["params"]["system"]
    assert "Randnummer 29a zu" in payload["params"]["system"]


def test_bmf_deep_research_agent_uses_native_web_tools_and_thinking():
    module = load_config_module()
    agent = next(item for item in module.AGENTS if item["id"] == "steuerreport-bmf-deep-research")

    payload = module.model_payload(agent, "knowledge-id")

    assert payload["base_model_id"] == "qwen3.8-27b-balanced-xt7900"
    assert payload["params"]["function_calling"] == "native"
    assert payload["params"]["temperature"] == 0.1
    assert payload["params"]["max_tokens"] == 12288
    assert payload["params"]["chat_template_kwargs"] == {"enable_thinking": True}
    assert payload["meta"]["toolIds"] == []
    assert payload["meta"]["knowledge"] == []
    assert payload["meta"]["builtinTools"]["web_search"] is True
    assert payload["meta"]["capabilities"]["web_search"] is True
    assert payload["meta"]["capabilities"]["file_upload"] is False
    assert payload["meta"]["defaultFeatureIds"] == ["web_search"]
    system = payload["params"]["system"]
    assert "mehrere kurze, getrennte `search_web`-Suchen" in system
    assert "`fetch_url`" in system
    assert "Aktualitaet nicht bestaetigt" in system
    assert "Ein Gesetzentwurf darf niemals als geltendes Recht" in system
    assert "hoechstens zehn Toolaufrufe" in system
    assert "hoechstens fuenf Originalquellen" in system
    assert "mindestens 3000 Ausgabetoken" in system
    assert "BFH IX B 24/26" in system
    assert "Ausschussmeldung vom 20. Mai 2026" in system
    assert "darf es nirgends als laufend bezeichnet werden" in system


def test_only_coordinator_enables_subagent_category():
    module = load_config_module()
    enabled = []

    for agent in module.AGENTS:
        payload = module.model_payload(agent, "knowledge-id")
        if payload["meta"]["builtinTools"]["subagents"]:
            enabled.append(agent["id"])

    assert enabled == ["steuerreport-koordinator"]
