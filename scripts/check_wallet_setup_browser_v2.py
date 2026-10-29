"""Wallet-Bootstrap am echten Frontend/Backend, nur in wegwerfbaren synthetischen Daten."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from playwright.sync_api import expect, sync_playwright


def base58(content):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, result = int.from_bytes(content, "big"), ""
    while number:
        number, remainder = divmod(number, 58)
        result = alphabet[remainder] + result
    return "1" * (len(content) - len(content.lstrip(b"\0"))) + result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ux-browser/wallet-setup"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=15000)
    root = Path(__file__).resolve().parents[1]
    with ExitStack() as stack:
        state = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="steuerreport-wallet-browser-")))
        retained = {name: value for name, value in os.environ.items() if name in {"PATH", "HOME", "LANG", "PYTHONPATH", "PYTHONPYCACHEPREFIX", "LD_LIBRARY_PATH"}}
        os.environ.clear()
        os.environ.update(retained, STEUERREPORT_V2_ROOT=str(root), STEUERREPORT_STATE_DIR=str(state),
                          STEUERREPORT_PRIVATE_PROFILE=str(state / "profile.json"), STEUERREPORT_V2_DB=str(state / "synthetic.duckdb"),
                          STEUERREPORT_V2_SECRET_VAULT_KEY_FILE=str(state / "vault.key"),
                          STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"), STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"))
        (state / "vault.key").write_bytes(bytes(range(32)))
        (state / "profile.json").write_text("{}")
        from fastapi.testclient import TestClient
        from steuerreport_v2.container_entrypoint import initialize_state
        from steuerreport_v2.domain.connector_bootstrap import initialize_token, read_token
        from steuerreport_v2.domain.connectors import ConnectorService
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        initialize_state()
        assert not read_token(), "Existing installation was silently enabled"
        from steuerreport_v2.api.app import create_app
        store = DuckDbStore(state / "synthetic.duckdb")
        client = stack.enter_context(TestClient(create_app(store)))
        original_connect = socket.socket.connect
        def connect(sock, address):
            if sock.family in {socket.AF_INET, socket.AF_INET6}:
                try:
                    local = ipaddress.ip_address(address[0]).is_loopback
                except ValueError:
                    local = address[0] == "localhost"
                assert local, "External request forbidden"
            return original_connect(sock, address)
        socket.socket.connect = connect
        stack.callback(setattr, socket.socket, "connect", original_connect)
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root / "frontend/dist")))
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        stack.callback(server.server_close)
        stack.callback(worker.join)
        stack.callback(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
        errors, calls = [], []
        private_key = Ed25519PrivateKey.generate()
        address = base58(private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        def bridge(route):
            request = route.request
            parsed = urlparse(request.url)
            assert parsed.netloc == urlparse(base).netloc
            if not parsed.path.startswith("/api/"):
                route.continue_()
                return
            allowed_post = {"/api/v1/activity/query", "/api/v1/workspace/review/query", "/api/v1/workspace/wallets", "/api/v1/connectors/wallet/challenges", "/api/v1/connectors/wallet/verifications"}
            source_sync = parsed.path.startswith("/api/v1/workspace/sources/") and parsed.path.endswith("/sync")
            assert request.method == "GET" or request.method == "POST" and (parsed.path in allowed_post or source_sync)
            headers = {"Content-Type": "application/json"}
            if request.headers.get("authorization"):
                headers["Authorization"] = request.headers["authorization"]
            response = client.request(request.method, parsed.path + ("?" + parsed.query if parsed.query else ""), content=request.post_data, headers=headers)
            assert not read_token() or read_token() not in response.text
            calls.append({"method": request.method, "path": parsed.path, "http": response.status_code})
            route.fulfill(status=response.status_code, content_type="application/json", body=response.content)
        context.route("**/*", bridge)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/#admin")
        setup = page.get_by_role("region", name="Wallet-Eigentumsnachweis", exact=True)
        expect(setup.get_by_text("Das lokale Einrichtungspasswort ist noch nicht vorbereitet.", exact=False)).to_be_visible()
        for width in (390, 768, 1280, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_function("innerWidth > 820 || getComputedStyle(document.querySelector('.sidebar')).visibility === 'hidden'")
            setup.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output / f"synthetic-setup-disabled-{width}.png"), animations="disabled")
        page.goto(base + "/#sources")
        page.get_by_role("button", name="Quelle hinzufügen", exact=True).click()
        panel = page.get_by_role("dialog")
        panel.get_by_label("Anbieter für neue Quelle").select_option("solana-wallet")
        assert panel.get_by_label("Eingabeart").input_value() == "public"
        panel.get_by_role("button", name="Weiter", exact=True).click()
        expect(panel.get_by_label("Connector-Setup-Token", exact=True)).to_have_count(0)
        panel.get_by_label("Name der neuen Wallet").fill("Browser Test Wallet")
        panel.get_by_label("Neue Wallet-Adresse").fill(address)
        for width in (390, 768, 1280, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_function("innerWidth > 820 || getComputedStyle(document.querySelector('.sidebar')).visibility === 'hidden'")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output / f"synthetic-public-address-{width}.png"), animations="disabled")
        panel.get_by_role("button", name="Weiter", exact=True).click()
        assert not ConnectorService(store).connections()
        panel.get_by_role("button", name="Adresse speichern", exact=True).click()
        expect(panel.get_by_role("status")).to_contain_text("Öffentliche Solana-Adresse gespeichert")
        saved = ConnectorService(store).connections()[0]
        assert saved.status == "address_saved" and saved.verified_at is None and not read_token()
        panel.get_by_role("button", name="Fertig", exact=True).click()
        page.reload()
        expect(page.get_by_role("button", name="Browser Test Wallet", exact=True)).to_be_visible()
        page.get_by_role("button", name="Browser Test Wallet", exact=True).click()
        expect(page.get_by_role("dialog").get_by_text(address, exact=True)).to_be_visible()
        page.get_by_role("dialog").get_by_role("button", name="Details schließen", exact=True).click()
        page.get_by_role("button", name="Quelle hinzufügen", exact=True).click()
        panel = page.get_by_role("dialog")
        panel.get_by_label("Anbieter für neue Quelle").select_option("solana-wallet")
        panel.get_by_role("button", name="Weiter", exact=True).click()
        panel.get_by_label("Neue Wallet-Adresse").fill(address)
        panel.get_by_role("button", name="Weiter", exact=True).click()
        panel.get_by_role("button", name="Adresse speichern", exact=True).click()
        expect(panel.get_by_role("status")).to_contain_text("bereits gespeichert")
        assert len(ConnectorService(store).connections()) == 1
        assert ConnectorService(store).connections()[0].connection_id == saved.connection_id
        panel.get_by_role("button", name="Fertig", exact=True).click()
        page.goto(base + "/#admin")
        initialize_token()
        setup.get_by_role("button", name="Connector-Einrichtung neu prüfen").click()
        expect(setup.get_by_text("Einrichtungspasswort vorhanden.", exact=False)).to_be_visible()
        page.goto(base + "/#sources")
        page.get_by_role("button", name="Quelle hinzufügen", exact=True).click()
        panel = page.get_by_role("dialog")
        panel.get_by_label("Anbieter für neue Quelle").select_option("solana-wallet")
        panel.get_by_label("Eingabeart").select_option("wallet")
        panel.get_by_role("button", name="Weiter", exact=True).click()
        panel.get_by_label("Neue Wallet-Adresse").fill(address)
        token = panel.get_by_label("Connector-Setup-Token", exact=True)
        assert token.get_attribute("type") == "password"
        command = panel.get_by_role("button", name="Nachricht für Eigentumsnachweis anfordern")
        expect(command).to_be_disabled()
        token.fill("synthetic-invalid")
        command.click()
        expect(panel.get_by_role("alert")).to_contain_text("Einrichtungspasswort fehlt, ist ungültig")
        token.fill(read_token())
        command.click()
        expect(panel.get_by_label("Öffentliche Wallet-Signatur")).to_be_visible()
        message = panel.locator("pre").inner_text()
        signature = base58(private_key.sign(message.encode("utf-8")))
        panel.get_by_label("Öffentliche Wallet-Signatur").fill(signature)
        panel.get_by_role("button", name="Weiter", exact=True).click()
        panel.get_by_role("button", name="Signatur prüfen und speichern", exact=True).click()
        expect(panel.get_by_role("status")).to_contain_text("Steuerliche Aktivierung")
        page.screenshot(path=str(args.output / "synthetic-wallet-verified-1440.png"), animations="disabled")
        row = ConnectorService(store).connections()[0]
        assert row.status == "ownership_verified_pending_registry"
        assert row.tax_activation == "review_required"
        assert row.connection_id == saved.connection_id
        panel.get_by_role("button", name="Fertig", exact=True).click()

        from steuerreport_v2.domain.portfolio import PortfolioService
        stack.enter_context(patch.object(PortfolioService, "PRIMARY_SOLANA_WALLET", address))
        stack.enter_context(patch.object(PortfolioService, "V1_CONNECTOR_BASE_URL", ""))
        rpc_state = {"valid": False, "calls": 0}
        def rpc(_service, method, params, timeout_seconds):
            assert params[0] == address and timeout_seconds == 45
            rpc_state["calls"] += 1
            if method == "getBalance":
                return {"value": 1_250_000_000 if rpc_state["valid"] else None}
            tokens = [{"account": {"data": {"parsed": {"info": {"mint": f"synthetic-token-mint-{index:02}",
                "tokenAmount": {"uiAmountString": "2.123456789012345678"}}}}}} for index in range(17)]
            return {"value": tokens if params[1]["programId"] == PortfolioService.SOLANA_TOKEN_PROGRAM_IDS[0] else []}
        stack.enter_context(patch.object(PortfolioService, "_solana_rpc", rpc))

        def sync_wallet():
            page.goto(base + "/#sources")
            page.get_by_role("button", name="Ansicht aktualisieren", exact=True).click()
            page.get_by_role("button", name=row.display_label, exact=True).click()
            page.get_by_role("dialog").get_by_role("button", name="Bestand aktualisieren", exact=True).click()
            page.get_by_role("dialog").get_by_role("button", name="Bestätigen und starten", exact=True).click()
        sync_wallet()
        expect(page.get_by_role("alert")).to_contain_text("noch kein erfolgreicher Bestandsabruf")
        assert "vorherige erfolgreiche" not in page.get_by_role("alert").inner_text()
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output / f"synthetic-rpc-first-failure-{width}.png"), animations="disabled")
        page.get_by_role("dialog").get_by_role("button", name="Abbrechen", exact=True).click()
        page.get_by_role("dialog").get_by_role("tab", name="Hinweise / Abgleich", exact=True).click()
        expect(page.get_by_role("dialog").get_by_text("Solana-Liveabruf fehlgeschlagen: getBalance: unvollstaendige oder ungueltige RPC-Antwort", exact=True)).to_be_visible()
        expect(page.get_by_role("dialog").get_by_role("link", name="Datenanbieter und RPC einrichten")).to_have_attribute("href", "#admin")
        page.screenshot(path=str(args.output / "synthetic-rpc-concrete-error-1440.png"), animations="disabled")
        page.get_by_role("dialog").get_by_role("button", name="Details schließen", exact=True).click()
        rpc_state["valid"] = True
        sync_wallet()
        expect(page.get_by_role("dialog").get_by_role("status")).to_contain_text("Abruf abgeschlossen")
        page.get_by_role("dialog").get_by_role("button", name="Schließen", exact=True).click()
        panel = page.get_by_role("dialog")
        panel.get_by_role("tab", name="Bestände", exact=True).click()
        balance = panel.get_by_role("region", name="Gespeicherter Wallet-Anbieterbestand")
        expect(balance.locator("tbody tr")).to_have_count(18)
        expect(balance.get_by_text("EUR-Preis fehlt", exact=True)).to_have_count(18)
        expect(balance).to_contain_text("18 Positionen ohne EUR-Bewertung")
        expect(panel.get_by_text("Noch keine Transaktionshistorie importiert.", exact=False)).to_be_visible()
        for width in (390, 768, 1280, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output / f"synthetic-unpriced-wallet-holdings-{width}.png"), animations="disabled")
        page.get_by_role("dialog").get_by_role("button", name="Details schließen", exact=True).click()
        page.goto(base + "/#dashboard")
        overview = page.get_by_role("region", name="Gespeicherte Wallet-Bestände")
        expect(overview).to_contain_text("18 Bestandspositionen")
        expect(overview).to_contain_text("Noch nicht verfügbar")
        live_summary = page.locator(".wsSummaryLine").filter(has_text="Gespeicherter Live-Vergleich")
        expect(live_summary).to_contain_text("Noch nicht verfügbar")
        assert "0,00 EUR" not in live_summary.inner_text()
        for width in (390, 768, 1280, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output / f"synthetic-unpriced-wallet-dashboard-{width}.png"), animations="disabled")
        overview.get_by_role("button", name="Anbieterbestand ansehen").click()
        expect(page.get_by_role("dialog").get_by_role("tab", name="Bestände", exact=True)).to_have_attribute("aria-selected", "true")
        expect(page.get_by_role("dialog").locator("tbody tr")).to_have_count(18)
        page.get_by_role("dialog").get_by_role("button", name="Details schließen", exact=True).click()
        rpc_state["valid"] = False
        sync_wallet()
        expect(page.get_by_role("alert")).to_contain_text("Der vorherige erfolgreiche Datenstand bleibt erhalten")
        assert "noch kein erfolgreicher" not in page.get_by_role("alert").inner_text()
        assert rpc_state["calls"] == 5
        balances = PortfolioService(store)._stored_live_balance_snapshots("solana_wallet")
        assert len(balances) == 18 and balances["SOL"] == Decimal("1.25")
        with store.connect() as connection:
            for name in ("canonical_events", "balance_ledger", "tax_lots", "tax_lines"):
                assert connection.execute(f"select count(*) from {name}").fetchone()[0] == 0
        assert not errors, errors
        result = {"synthetic_only": True, "actual_fastapi_bridge": True, "existing_install_not_auto_enabled": True,
                  "local_explicit_setup": True, "wrong_bearer_rejected": True, "masked_token": True,
                  "public_address_without_token_or_signature": True, "public_address_persisted_after_reload": True,
                  "duplicate_address_idempotent": True, "proof_upgrades_same_connection": True,
                  "real_ed25519_signature_verified": True, "tax_activation": "review_required", "financial_rows_written": 0,
                  "rpc_first_failure_not_reported_as_previous_success": True, "rpc_concrete_error_and_setup_link": True,
                  "rpc_retry_recovers_and_preserves_snapshot_on_later_failure": True, "rpc_responses_mocked": True,
                  "eighteen_unpriced_positions_visible_without_history": True, "unknown_eur_not_displayed_as_zero": True,
                  "dashboard_links_directly_to_saved_wallet_holdings": True,
                  "viewports": [390, 768, 1280, 1440], "external_requests": 0, "javascript_errors": errors,
                  "calls": calls}
        (args.output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key != "calls"}))
        context.unroute_all(behavior="ignoreErrors")
        context.close()


if __name__ == "__main__":
    main()
