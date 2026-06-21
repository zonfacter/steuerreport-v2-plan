import json
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_jup_solscan_balance_change_v2.py"
SPEC = importlib.util.spec_from_file_location("import_jup_solscan_balance_change_v2", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)


def test_solscan_balance_change_fetch_blocks_without_key_or_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("SOLSCAN_API_KEY", raising=False)
    monkeypatch.delenv("SOLSCAN_PRO_API_KEY", raising=False)
    monkeypatch.setattr(importer.PortfolioService, "_solscan_api_key", lambda _self: "")

    with pytest.raises(RuntimeError, match="solscan_api_key_missing_or_unusable"):
        importer._fetch_balance_changes(
            "wallet-1",
            max_requests=1,
            page_size=10,
            from_time=None,
            to_time=None,
            cache_path=tmp_path / "missing.json",
            refresh=False,
        )


def test_solscan_balance_change_fetch_uses_cache_without_live_request(tmp_path, monkeypatch):
    cache = tmp_path / "balance-change.json"
    cache.write_text(
        json.dumps(
            {
                "warnings": ["cached-test"],
                "data": [
                    {
                        "trans_id": "tx-1",
                        "token_address": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("network must not be called when cache is available")

    monkeypatch.setattr(importer.urllib.request, "urlopen", fail_urlopen)

    rows, meta = importer._fetch_balance_changes(
        "wallet-1",
        max_requests=1,
        page_size=10,
        from_time=None,
        to_time=None,
        cache_path=cache,
        refresh=False,
    )

    assert rows == [
        {
            "trans_id": "tx-1",
            "token_address": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
        }
    ]
    assert meta["status"] == "cache"
    assert meta["requests_used"] == 0
    assert meta["cache_used"] is True


def test_solscan_balance_change_fetch_honors_request_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLSCAN_API_KEY", "dummy")
    requested_urls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "success": True,
                    "data": [
                        {
                            "trans_id": "tx-1",
                            "token_address": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
                            "amount": "1",
                            "token_decimals": 0,
                            "change_type": "inc",
                            "time": "2026-06-19T21:40:23Z",
                        }
                    ],
                }
            ).encode()

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(importer.urllib.request, "urlopen", fake_urlopen)

    rows, meta = importer._fetch_balance_changes(
        "wallet-1",
        max_requests=1,
        page_size=20,
        from_time=1781905200,
        to_time=1781905320,
        cache_path=tmp_path / "cache.json",
        refresh=True,
    )

    assert len(rows) == 1
    assert meta["requests_used"] == 1
    assert len(requested_urls) == 1
    assert "page_size=20" in requested_urls[0]
    assert "from_time=1781905200" in requested_urls[0]
    assert "to_time=1781905320" in requested_urls[0]
