from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/configure_openwebui_web_search.py"


def load_config_module():
    spec = importlib.util.spec_from_file_location("openwebui_web_search_config", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_payload_preserves_unrelated_provider_credentials():
    module = load_config_module()
    current = {
        "status": True,
        "RAG_TEMPLATE": "base template",
        "web": {
            "ENABLE_WEB_SEARCH": False,
            "WEB_SEARCH_ENGINE": "brave",
            "BRAVE_SEARCH_API_KEY": "must-remain-present",
            "TAVILY_API_KEY": "also-preserved",
        },
    }

    payload = module.build_update_payload(current)

    assert payload["web"]["BRAVE_SEARCH_API_KEY"] == "must-remain-present"
    assert payload["web"]["TAVILY_API_KEY"] == "also-preserved"
    assert payload["web"]["ENABLE_WEB_SEARCH"] is True
    assert payload["web"]["WEB_SEARCH_ENGINE"] == "searxng"
    assert payload["web"]["SEARXNG_QUERY_URL"] == "http://searxng:8080/search"
    assert payload["web"]["WEB_SEARCH_DOMAIN_FILTER_LIST"] == module.PRIMARY_SOURCE_DOMAINS
    assert payload["TOP_K"] == 8
    assert payload["TOP_K_RERANKER"] == 8
    assert module.RAG_LINK_GUIDANCE_MARKER in payload["RAG_TEMPLATE"]


def test_public_status_never_includes_provider_secrets():
    module = load_config_module()
    config = {
        **module.DESIRED_RAG_SETTINGS,
        "RAG_TEMPLATE": "base template" + module.RAG_LINK_GUIDANCE,
        "web": {
            **module.desired_settings(),
            "BRAVE_SEARCH_API_KEY": "secret-value",
            "TAVILY_API_KEY": "secret-value",
        }
    }

    status = module.public_status(config, module.DEFAULT_SEARXNG_URL)

    assert status["matches_expected"] is True
    assert "BRAVE_SEARCH_API_KEY" not in status
    assert "TAVILY_API_KEY" not in status
    assert status["WEB_SEARCH_DOMAIN_FILTER_LIST"] == module.PRIMARY_SOURCE_DOMAINS
    assert status["TOP_K"] == 8
    assert status["TOP_K_RERANKER"] == 8
    assert status["RAG_DIRECT_SOURCE_URL_GUIDANCE"] is True


def test_build_update_payload_requires_web_section():
    module = load_config_module()

    try:
        module.build_update_payload({"status": True})
    except ValueError as exc:
        assert "web section" in str(exc)
    else:
        raise AssertionError("missing web config must be rejected")
