#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx


DEFAULT_SEARXNG_URL = "http://searxng:8080/search"
PRIMARY_SOURCE_DOMAINS = [
    "bundesfinanzministerium.de",
    "gesetze-im-internet.de",
    "bundesfinanzhof.de",
    "bundesverfassungsgericht.de",
    "rechtsprechung-im-internet.de",
    "bundesgesetzblatt.de",
    "bundestag.de",
    "bundesrat.de",
    "eur-lex.europa.eu",
    "curia.europa.eu",
]

DESIRED_WEB_SETTINGS: dict[str, Any] = {
    "ENABLE_WEB_SEARCH": True,
    "ENABLE_WEB_SEARCH_CONFIRMATION": True,
    "WEB_SEARCH_CONFIRMATION_CONTENT": (
        "Die Suchanfrage wird an die lokale SearXNG-Instanz und deren "
        "oeffentliche Suchquellen gesendet. Keine persoenlichen Falldaten uebermitteln."
    ),
    "WEB_SEARCH_ENGINE": "searxng",
    "WEB_SEARCH_TRUST_ENV": False,
    "WEB_SEARCH_RESULT_COUNT": 5,
    "WEB_SEARCH_CONCURRENT_REQUESTS": 1,
    "WEB_FETCH_MAX_CONTENT_LENGTH": 200_000,
    "WEB_LOADER_CONCURRENT_REQUESTS": 2,
    "WEB_SEARCH_DOMAIN_FILTER_LIST": PRIMARY_SOURCE_DOMAINS,
    "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL": False,
    "BYPASS_WEB_SEARCH_WEB_LOADER": False,
    "SEARXNG_QUERY_URL": DEFAULT_SEARXNG_URL,
    "SEARXNG_LANGUAGE": "de-DE",
}

DESIRED_RAG_SETTINGS: dict[str, Any] = {
    "TOP_K": 8,
    "TOP_K_RERANKER": 8,
}

RAG_LINK_GUIDANCE_MARKER = "### Direct source URLs"
RAG_LINK_GUIDANCE = """

### Direct source URLs:
- A source may contain a line beginning with `Source URL:` and a matching `url` attribute.
- When the user requests links, copy that exact URL into a Markdown link in addition to the inline `[id]` citation.
- Never replace an available direct URL with only a numeric citation or with invented link text.
"""

PUBLIC_SETTING_KEYS = (
    "ENABLE_WEB_SEARCH",
    "ENABLE_WEB_SEARCH_CONFIRMATION",
    "WEB_SEARCH_ENGINE",
    "WEB_SEARCH_RESULT_COUNT",
    "WEB_SEARCH_CONCURRENT_REQUESTS",
    "WEB_SEARCH_DOMAIN_FILTER_LIST",
    "WEB_FETCH_MAX_CONTENT_LENGTH",
    "WEB_LOADER_CONCURRENT_REQUESTS",
    "BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL",
    "BYPASS_WEB_SEARCH_WEB_LOADER",
    "SEARXNG_QUERY_URL",
    "SEARXNG_LANGUAGE",
)


def desired_settings(searxng_url: str = DEFAULT_SEARXNG_URL) -> dict[str, Any]:
    settings = dict(DESIRED_WEB_SETTINGS)
    settings["SEARXNG_QUERY_URL"] = searxng_url.rstrip("/")
    return settings


def build_update_payload(
    current_config: dict[str, Any],
    searxng_url: str = DEFAULT_SEARXNG_URL,
) -> dict[str, Any]:
    current_web = current_config.get("web")
    if not isinstance(current_web, dict):
        raise ValueError("OpenWebUI retrieval config has no web section")

    # OpenWebUI assigns every WebConfig field during an update. Round-trip all
    # current fields so unrelated provider credentials are never cleared.
    merged = dict(current_web)
    merged.update(desired_settings(searxng_url))
    current_template = current_config.get("RAG_TEMPLATE")
    if not isinstance(current_template, str) or not current_template.strip():
        raise ValueError("OpenWebUI retrieval config has no RAG template")
    rag_template = current_template
    if RAG_LINK_GUIDANCE_MARKER not in rag_template:
        rag_template = rag_template.rstrip() + RAG_LINK_GUIDANCE
    return {
        "web": merged,
        **DESIRED_RAG_SETTINGS,
        "RAG_TEMPLATE": rag_template,
    }


def public_status(config: dict[str, Any], searxng_url: str) -> dict[str, Any]:
    current_web = config.get("web") or {}
    expected = desired_settings(searxng_url)
    visible = {key: current_web.get(key) for key in PUBLIC_SETTING_KEYS}
    visible.update({key: config.get(key) for key in DESIRED_RAG_SETTINGS})
    visible["RAG_DIRECT_SOURCE_URL_GUIDANCE"] = (
        RAG_LINK_GUIDANCE_MARKER in str(config.get("RAG_TEMPLATE") or "")
    )
    visible["matches_expected"] = all(
        current_web.get(key) == value for key, value in expected.items()
    ) and all(config.get(key) == value for key, value in DESIRED_RAG_SETTINGS.items()) and visible[
        "RAG_DIRECT_SOURCE_URL_GUIDANCE"
    ]
    return visible


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure privacy-separated SearXNG web search in OpenWebUI"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENWEBUI_BASE_URL", "http://127.0.0.1:8082"),
    )
    parser.add_argument("--token", default=os.getenv("OPENWEBUI_API_TOKEN"))
    parser.add_argument(
        "--searxng-url",
        default=os.getenv("OPENWEBUI_SEARXNG_URL", DEFAULT_SEARXNG_URL),
    )
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        print("OPENWEBUI_API_TOKEN or --token is required", file=sys.stderr)
        return 2

    headers = {
        "Authorization": f"Bearer {args.token}",
        "Accept": "application/json",
        "User-Agent": "steuerreport-openwebui-web-config/1.0",
    }
    base_url = args.base_url.rstrip("/")
    with httpx.Client(timeout=60, headers=headers) as client:
        response = client.get(f"{base_url}/api/v1/retrieval/config")
        response.raise_for_status()
        current = response.json()

        if not args.verify_only:
            payload = build_update_payload(current, args.searxng_url)
            response = client.post(
                f"{base_url}/api/v1/retrieval/config/update",
                json=payload,
            )
            response.raise_for_status()

        response = client.get(f"{base_url}/api/v1/retrieval/config")
        response.raise_for_status()
        status = public_status(response.json(), args.searxng_url)

    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0 if status["matches_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
