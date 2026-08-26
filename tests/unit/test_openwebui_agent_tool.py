from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "integrations/openwebui/steuerreport_readonly_tool.py"


def load_tools_class():
    spec = importlib.util.spec_from_file_location("steuerreport_readonly_tool", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Tools


def recording_tool():
    tool = load_tools_class()()
    calls = []

    def fake_get(path, query=None, **kwargs):
        calls.append((path, query))
        tool._last_get_options = kwargs
        return {"ok": True, "endpoint": path, "query": query}

    tool._get = fake_get
    return tool, calls


def test_tax_and_fifo_routes_are_fixed_by_whitelist():
    tool, calls = recording_tool()

    assert tool.get_tax_year(2025, "filing_summary")["ok"] is True
    assert tool.get_fifo_status(2025, "provenance_closure")["ok"] is True

    assert calls == [
        ("/tax-years/2025/filing-summary", None),
        ("/tax-years/2025/wallet-fifo-provenance-closure", None),
    ]


def test_legal_research_routes_are_fixed_and_read_only():
    tool, calls = recording_tool()

    assert tool.get_legal_research_status("freshness")["ok"] is True
    assert tool.get_legal_research_status("sources")["ok"] is True
    assert tool.get_legal_research_status("unknown")["error"]["kind"] == "invalid_view"

    assert calls == [
        ("/tax-methodology/legal-research/freshness", None),
        ("/tax-methodology/legal-research/sources", None),
    ]


def test_invalid_year_asset_source_and_dates_never_reach_http_layer():
    tool, calls = recording_tool()

    assert tool.get_tax_year(2020)["error"]["kind"] == "invalid_year"
    assert tool.get_asset_fifo(2025, "../../secrets")["error"]["kind"] == "invalid_asset"
    assert tool.get_source_status("../../admin")["error"]["kind"] == "invalid_source_id"
    assert tool.get_portfolio_as_of("15.06.2026")["error"]["kind"] == "invalid_date"
    assert calls == []


def test_source_and_asset_parameters_are_encoded_as_data_only():
    tool, calls = recording_tool()

    tool.get_source_status("binance:Spot", "reconciliation")
    tool.get_asset_fifo(2025, "hnt", 25)

    assert calls == [
        ("/sources/binance:Spot/reconciliation", None),
        ("/tax-years/2025/asset-fifo-drilldown", {"asset": "HNT", "limit": 25}),
    ]


def test_equalization_uses_explicit_iso_dates_and_bounded_threshold():
    tool, calls = recording_tool()

    result = tool.get_equalization_summary("2025-06-13", "2026-07-24", 1.0)

    assert result["ok"] is True
    assert calls == [
        (
            "/divorce/equalization-summary",
            {
                "separation_date": "2025-06-13",
                "end_asset_date": "2026-07-24",
                "materiality_threshold_eur": "1.00",
            },
        )
    ]
    assert tool._last_get_options["read_limit"] == 524288
    assert tool._last_get_options["transform"] == tool._compact_equalization_payload


def test_equalization_projection_keeps_totals_and_material_reconciliation_only():
    Tools = load_tools_class()
    payload = {
        "status": "ok",
        "data": {
            "valuation_portfolio_value_eur": "6604.35",
            "inheritance_origin_gate": {"status": "review", "findings": ["proof"]},
            "accounts": [
                {
                    "account": "Wallet A",
                    "valuation_value_eur": "100",
                    "cutoff_assets": [
                        {"asset": "DUST", "value_eur": "0.01"},
                        {"asset": "HNT", "value_eur": "99.99"},
                    ],
                    "valuation_assets": [{"asset": "JUP", "value_eur": "100"}],
                }
            ],
            "marital_pre_cutoff": {
                "open_value_eur": "50",
                "assets": [{"asset": "SOL", "total_value_or_proceeds_eur": "50"}],
            },
            "post_cutoff_direct_eur_invest": {"assets": []},
            "post_cutoff_all_lots": {"assets": []},
            "live_reconciliation": [
                {"asset": "SOL", "severity": "info", "status": "ok", "delta_value_eur": "0.20"},
                {
                    "asset": "JUP",
                    "severity": "warning",
                    "status": "live_anchor_delta",
                    "delta_value_eur": "-200",
                },
            ],
        },
        "errors": [],
        "warnings": [],
    }

    compact = Tools._compact_equalization_payload(payload)

    assert compact["data"]["valuation_portfolio_value_eur"] == "6604.35"
    assert compact["data"]["inheritance_origin_gate"]["findings"] == ["proof"]
    account = compact["data"]["accounts"][0]
    assert "cutoff_assets" not in account
    assert account["asset_detail_projection"] == {
        "cutoff_rows_omitted": 2,
        "valuation_rows_omitted": 1,
        "detail_endpoint": "/portfolio/as-of",
    }
    reconciliation = compact["data"]["live_reconciliation"]
    assert reconciliation["total_count"] == 2
    assert [item["asset"] for item in reconciliation["material_items"]] == ["JUP"]
    assert compact["data"]["agent_projection"]["kind"] == "equalization_summary_compact_v1"


def test_portfolio_as_of_projection_keeps_totals_accounts_and_bounded_details():
    Tools = load_tools_class()
    payload = {
        "status": "ok",
        "data": {
            "as_of": "2026-07-24T23:59:59Z",
            "total_value_eur": "100.00",
            "account_summary": [{"account": "Wallet A", "value_eur": "100.00"}],
            "excluded_account_summary": [
                {
                    "account": "binance",
                    "value_eur": "9000.00",
                    "exclusion_reason_code": "historical_binance_evidence_account",
                    "exclusion_reason": "Audit-only",
                    "included_in_portfolio_total": False,
                }
            ],
            "excluded_value_eur": "9000.00",
            "excluded_value_semantics": "Kein Bestand und nicht addieren.",
            "missing_price_assets": [],
            "asset_summary": [
                {"asset": "DUST", "value_eur": "0.01"},
                {"asset": "HNT", "value_eur": "99.99"},
            ],
            "positions": [
                {"account": "Wallet A", "asset": "DUST", "value_eur": "0.01"},
                {"account": "Wallet A", "asset": "HNT", "value_eur": "99.99"},
            ],
        },
        "errors": [],
        "warnings": [],
    }

    compact = Tools._compact_portfolio_as_of_payload(payload)

    assert compact["data"]["total_value_eur"] == "100.00"
    assert compact["data"]["account_summary"][0]["account"] == "Wallet A"
    assert "positions" not in compact["data"]
    assert compact["data"]["positions_top"]["items"][0]["asset"] == "HNT"
    assert compact["data"]["asset_summary_top"]["items"][0]["asset"] == "HNT"
    assert compact["data"]["excluded_balance_notice"] == {
        "account_count": 1,
        "included_in_portfolio_total": False,
        "may_be_added_to_portfolio_total": False,
        "semantics": "Kein Bestand und nicht addieren.",
    }
    assert compact["data"]["agent_projection"]["kind"] == "portfolio_as_of_compact_v2"


def test_portfolio_as_of_defaults_to_berlin_day_end_and_can_use_utc():
    tool, calls = recording_tool()

    berlin = tool.get_portfolio_as_of("2025-06-13")
    assert calls[-1] == (
        "/portfolio/as-of",
        {"as_of": "2025-06-13T21:59:59.999999Z"},
    )
    assert berlin["request_context"] == {
        "requested_local_date": "2025-06-13",
        "timezone_mode": "Europe/Berlin",
        "resolved_as_of_utc": "2025-06-13T21:59:59.999999Z",
    }

    utc = tool.get_portfolio_as_of("2025-06-13", "UTC")
    assert calls[-1] == (
        "/portfolio/as-of",
        {"as_of": "2025-06-13T23:59:59.999999Z"},
    )
    assert utc["request_context"]["timezone_mode"] == "UTC"


def test_api_base_url_rejects_credentials_and_non_api_paths():
    Tools = load_tools_class()
    tool = Tools()

    tool.valves.API_BASE_URL = "http://user:pass@localhost:8010/api/v1"
    assert tool.get_operational_status("health")["error"]["kind"] == "invalid_configuration"

    tool.valves.API_BASE_URL = "http://localhost:8010/"
    assert tool.get_operational_status("health")["error"]["kind"] == "invalid_configuration"
