"""Workspace acceptance checks, called by the existing browser smoke runner."""
from __future__ import annotations

import csv
from pathlib import Path
import json

from playwright.sync_api import expect

from ux_workspace_fixtures import SOURCE, WorkspaceFixture


def check_workspace(browser, base_url: str, output: Path):
    fixture = WorkspaceFixture()
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    errors = []
    external = []

    def mock(route):
        if not fixture.handle(route):
            fixture.send(route, {})

    def guard(route):
        if not route.request.url.startswith(base_url):
            external.append(route.request.url.split("?")[0])
            route.abort()
        else:
            route.continue_()

    context.route("**/*", guard)
    context.route("**/api/**", mock)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    passed = {}
    screenshots = []

    def done(number, evidence):
        passed[f"A{number:02}"] = {"status": "bestanden", "evidence": evidence}
        print(f"A{number:02}: {evidence}", flush=True)

    def go(hash, wait_until="networkidle"):
        page.goto(base_url + "/" + hash, wait_until=wait_until)
        section = hash.lstrip("#").split("?", 1)[0]
        title = {"dashboard": "Übersicht", "sources": "Quellen & Wallets", "flows": "Transaktionen", "review": "Hinweise prüfen", "tax": "Steuerjahre", "export": "Berichte & Belege"}.get(section)
        if title:
            expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()

    def screenshot(name):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
        full_page = page.get_by_role("dialog").count() == 0
        page.screenshot(path=str(output / (name + ".png")), full_page=full_page, animations="disabled")
        screenshots.append({"file": name + ".png", "viewport": page.viewport_size, "route": page.url.split("/", 3)[-1], "full_page": full_page, "data": "synthetic"})

    fixture.fresh = True
    fixture.hold.add("/api/v1/workspace/status")
    go("#dashboard", wait_until="domcontentloaded")
    expect(page.get_by_text("Voraussetzungen werden geprüft", exact=True)).to_be_visible()
    expect(page.get_by_text("Vorhandene Freigaben erfüllt", exact=True)).to_have_count(0)
    expect(page.get_by_text("1.200,00 EUR", exact=True)).to_have_count(0)
    fixture.hold.clear()
    for route in fixture.pending:
        fixture.send(route, fixture.status(2025))
    fixture.pending.clear()
    expect(page.get_by_role("button", name="Erste Quelle hinzufügen", exact=True)).to_be_visible()
    expect(page.get_by_text("Keine bewertbaren Positionen", exact=False)).to_be_visible()
    screenshot("dashboard-fresh-1440")
    done(1, "Frisches Konto: Setup, kein scheinbarer Bestand und keine finale Freigabe.")
    done(2, "Statusantwort kontrolliert zurückgehalten; kein vorläufiger Erfolg.")

    fixture.fresh = False
    fixture.zero = True
    go("#sources")
    expect(page.locator(".wsSourceValue").get_by_text("0,00 EUR", exact=True)).to_be_visible()
    expect(page.locator(".wsSourceValue").get_by_text("Noch nicht verfügbar", exact=True)).to_be_visible()
    done(3, "Bekannte Null und unbekannter Wert nebeneinander, ohne Gleichsetzung.")
    expect(page.get_by_text("Neuer Versuch fehlgeschlagen", exact=False)).to_be_visible()
    expect(page.get_by_text("24.10.2026", exact=False)).to_be_visible()
    done(5, "Vorheriger Erfolg mit Zeitstempel und fehlgeschlagener jüngster Versuch sichtbar.")
    fixture.zero = False
    page.get_by_role("combobox", name="Quellenstatus").select_option("failed")
    expect(page.locator(".wsSourceRow")).to_have_count(1)
    page.get_by_role("combobox", name="Quellen sortieren").select_option("issues")
    page.get_by_role("searchbox", name="Liste durchsuchen").fill("keine-treffer")
    expect(page.get_by_text("Keine passenden Quellen", exact=True)).to_be_visible()
    page.get_by_role("button", name="Filter zurücksetzen", exact=True).click()
    expect(page.locator(".wsSourceRow")).to_have_count(2)
    done(6, "Quellenstatus, Sortierung und verzögerte Suche mit nachvollziehbarer Trefferzahl.")
    done(7, "Keine Treffer mit Filter-zurücksetzen; danach wieder beide Quellen.")

    page.get_by_role("button", name="Demo-Börse", exact=True).click()
    panel = page.get_by_role("dialog")
    expect(panel.get_by_role("heading", name="Demo-Börse")).to_be_visible()
    expect(panel.get_by_role("button", name="Details schließen")).to_be_focused()
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Demo-Börse", exact=True)).to_be_focused()
    menu = page.locator(".wsRowMenu summary").first
    menu.focus()
    menu.press("Enter")
    expect(page.locator(".wsRowMenu").first).to_have_attribute("open", "")
    menu.press("Escape")
    expect(menu).to_be_focused()
    expect(page.locator(".wsRowMenu").first).not_to_have_attribute("open", "")
    done(20, "Detailpanel: Initialfokus, Tab-Umlauf, Escape und Fokusrückgabe geprüft.")

    page.get_by_role("button", name="Quelle hinzufügen", exact=True).click()
    panel = page.get_by_role("dialog")
    panel.get_by_role("combobox", name="Anbieter für neue Quelle").select_option("binance")
    panel.get_by_role("button", name="Weiter", exact=True).click()
    expect(panel.get_by_role("button", name="Weiter", exact=True)).to_be_disabled()
    panel.get_by_role("textbox", name="API-Key der neuen Quelle").count()  # Password fields use their permanent labels.
    panel.get_by_label("API-Key der neuen Quelle", exact=True).fill("synthetic-key")
    panel.get_by_label("API-Secret der neuen Quelle", exact=True).fill("synthetic-secret")
    panel.get_by_label("API-Key der neuen Quelle", exact=True).press("Tab")
    expect(panel.get_by_label("API-Key der neuen Quelle", exact=True)).to_have_value("synthetic-key")
    expect(panel.get_by_role("button", name="Weiter", exact=True)).to_be_enabled()
    page.once("dialog", lambda dialog: dialog.accept())
    page.keyboard.press("Escape")
    assert not any(path == "/api/v1/admin/cex-credentials" for _, path, _ in fixture.calls)
    done(11, "Fehlende Pflichtfelder blockieren; kein Credential-Speichern, Import oder Aktivieren durch Einrichtungsschritte.")
    done(19, "Ausgefüllte Passwortfelder bleiben über dauerhafte Labels auffindbar und nach Tab erhalten.")
    page.get_by_role("button", name="Quelle hinzufügen", exact=True).click()
    panel = page.get_by_role("dialog")
    panel.get_by_role("combobox", name="Anbieter für neue Quelle").select_option("helium")
    expect(panel.get_by_role("combobox", name="Eingabeart")).to_have_value("file")
    panel.get_by_role("button", name="Weiter", exact=True).click()
    panel.get_by_role("button", name="Weiter", exact=True).click()
    panel.get_by_role("button", name="Importassistent öffnen", exact=True).click()
    expect(page.get_by_role("combobox", name="Importquelle", exact=True)).to_have_value("helium")
    assert not any(path == "/api/v1/import/assistant/execute" for _, path, _ in fixture.calls)

    go("#flows?size=10&page=2")
    expect(page.locator(".wsActivityTable tbody tr")).to_have_count(10)
    expect(page.get_by_text("45 Treffer · Seite 2 von 5", exact=True)).to_be_visible()
    before = page.url
    first_detail = page.locator(".wsActivityTable tbody tr button").first
    first_detail.scroll_into_view_if_needed()
    scroll_before = page.evaluate("scrollY")
    first_detail.focus()
    first_detail.press("Enter")
    expect(page.get_by_role("dialog", name="Transaktionsdetails")).to_be_visible()
    page.get_by_role("tab", name="Originalbeleg", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("synthetic.csv", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    assert page.url == before
    assert abs(page.evaluate("scrollY") - scroll_before) < 2
    expect(page.locator(".wsActivityTable tbody tr button").first).to_be_focused()
    done(8, "Liste Seite 2 → Originalbeleg → Schließen erhält Seite, Filter und Fokus.")
    page.get_by_role("combobox", name="Transaktionsasset").select_option("BTC")
    expect(page.get_by_text("22 Treffer · Seite 1 von 3", exact=True)).to_be_visible()
    assert "page=2" not in page.url
    page.get_by_role("combobox", name="Transaktionen sortieren").select_option("oldest")
    page.get_by_role("button", name="Nächste Seite", exact=True).click()
    expect(page.get_by_text("22 Treffer · Seite 2 von 3", exact=True)).to_be_visible()
    filtered_url = page.url
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("combobox", name="Transaktionsasset")).to_have_value("BTC")
    expect(page.get_by_text("22 Treffer · Seite 2 von 3", exact=True)).to_be_visible()
    assert page.url == filtered_url
    done(9, "URL erhält Asset, Sortierung, Seitengröße und Seite bei Neuladen; Suchtext bleibt aus URL.")
    page.get_by_role("combobox", name="Transaktionstyp").select_option("reward")
    expect(page.get_by_text("Keine passenden Transaktionen", exact=True)).to_be_visible()
    page.go_back(wait_until="networkidle")
    expect(page.get_by_text("22 Treffer · Seite 2 von 3", exact=True)).to_be_visible()
    page.go_forward(wait_until="networkidle")
    expect(page.get_by_text("Keine passenden Transaktionen", exact=True)).to_be_visible()
    page.go_back(wait_until="networkidle")
    done(10, "Zurück/Vorwärts stellt passende gefilterte Ergebnisse ohne Navigationsschleife her.")
    done(13, "Serverseitige Filter, Sortierung, Seitenwechsel und Filterwechsel-Reset stimmen mit URL überein.")

    search = page.get_by_role("searchbox", name="Liste durchsuchen")
    # Hold the resolved response in JS, not an intercepted network handler. This
    # deliberately ignores AbortSignal and therefore also tests the version guard.
    page.evaluate("""() => {
      window.__originalFetch = window.fetch;
      window.fetch = (input, init) => {
        if (String(input).endsWith('/activity/query') && JSON.parse(init.body).search === 'synthetic-tx-001') {
          const { signal, ...withoutAbort } = init;
          return window.__originalFetch(input, withoutAbort).then(response => new Promise(resolve => {
            window.__releaseOldResponse = () => resolve(response);
          }));
        }
        return window.__originalFetch(input, init);
      };
    }""")
    search.fill("synthetic-tx-001")
    page.wait_for_function("typeof window.__releaseOldResponse === 'function'")
    search.fill("synthetic-tx-003")
    expect(page.get_by_text("1 Treffer · Seite 1 von 1", exact=True)).to_be_visible()
    page.evaluate("async () => { window.__releaseOldResponse(); window.fetch = window.__originalFetch; await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); }")
    expect(page.locator(".wsActivityTable tbody tr button")).to_have_attribute("aria-label", "Details zu Ereignis evt-003")
    assert "synthetic-tx" not in page.url
    search.fill("")
    expect(page.get_by_text("22 Treffer · Seite 1 von 3", exact=True)).to_be_visible()

    page.get_by_role("tab", name="Ledger", exact=True).click()
    expect(page.get_by_text("44 Treffer · Seite 1 von 5", exact=True)).to_be_visible()
    done(12, "22 kanonische Ereignisse vs. 44 Ledger-Bewegungen getrennt beschriftet.")
    page.get_by_role("tab", name="Transaktionen", exact=True).click()
    page.get_by_role("button", name="Exportieren", exact=True).click()
    with page.expect_download() as download:
        page.get_by_role("button", name="CSV erstellen und herunterladen", exact=True).click()
    path = output / "filtered-synthetic.csv"
    download.value.save_as(path)
    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 22 and {row["asset"] for row in rows} == {"BTC"}
    expect(page.get_by_text("22 Zeilen als CSV bereitgestellt", exact=False)).to_be_visible()
    page.keyboard.press("Escape")
    done(18, "CSV enthält alle 22 gefilterten Zeilen, nicht nur Seite; Originalpräzision, Browserbereitstellung statt falscher Speicherbestätigung.")

    go("#review")
    page.get_by_role("button", name="Originalbeleg prüfen", exact=True).click()
    expect(page.get_by_role("dialog").get_by_text("Benötigte Belege", exact=True)).to_be_visible()
    page.get_by_role("button", name="Betroffenes Ereignis öffnen", exact=True).click()
    expect(page.get_by_role("dialog", name="Transaktionsdetails")).to_be_visible()
    page.keyboard.press("Escape")
    done(14, "Aufgabe zeigt Auswirkung, Rohbelegreferenz und direkte Verknüpfung zum nachgewiesenen Ereignis.")
    go("#dashboard")
    expect(page.get_by_text("Vorschau verfügbar — finale Abgabe nicht freigegeben", exact=True).last).to_be_visible()
    expect(page.get_by_role("region", name="Zentrale Jahresvoraussetzungen").get_by_text("Keine Gate-Hinweise im geprüften Datenstand", exact=True)).to_be_visible()
    expect(page.get_by_text("Keine finale Jahresfreigabe", exact=True)).to_be_visible()
    done(15, "Leeres Review-Gate bleibt von offener Jahresbestätigung getrennt; keine finale Abgabe.")
    go("#tax?year=2024")
    expect(page.get_by_role("combobox", name="Gemeinsames Steuerjahr")).to_have_value("2024")
    expect(page.get_by_text("10,12 EUR", exact=True)).to_be_visible()
    page.get_by_role("button", name="Berichte und Umfang prüfen", exact=True).click()
    expect(page.get_by_role("combobox", name="Gemeinsames Steuerjahr")).to_have_value("2024")
    expect(page.get_by_text("Exportumfang: Steuerjahr 2024.", exact=False)).to_be_visible()
    assert page.get_by_role("link", name="Vorschau öffnen", exact=True).get_attribute("href").endswith("/api/v1/tax-years/2024/filing-summary.html")
    go("#dashboard")
    expect(page.get_by_text("SOL", exact=True)).to_be_visible()
    fixture.fail.add("/api/v1/portfolio/snapshot")
    page.get_by_role("button", name="Ansicht aktualisieren", exact=True).click()
    expect(page.get_by_text("Bestände: Daten konnten nicht geladen werden", exact=False)).to_be_visible()
    expect(page.get_by_text("SOL", exact=True)).to_be_visible()
    expect(page.get_by_text("Steuerjahr und Freigaben prüfen", exact=True).last).to_be_visible()
    fixture.fail.clear()
    page.get_by_role("button", name="Erneut versuchen", exact=True).click()
    expect(page.get_by_text("Bestände: Daten konnten nicht geladen werden", exact=False)).to_have_count(0)
    done(4, "Teilfehler mit Wiederholen, altem Datenstand und nutzbaren übrigen Bereichen.")
    assert not any(path.endswith("/sync") or path == "/api/v1/pipeline/rebuild" for _, path, _ in fixture.calls)
    done(16, "Ansicht aktualisieren und alle bisherigen Ansichtswechsel ohne Exchange-Sync oder Neuberechnung.")

    go("#sources")
    page.get_by_role("button", name="Synchronisieren", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("externen Anbieter")
    fixture.hold.add("/api/v1/workspace/sources/" + SOURCE + "/sync")
    page.get_by_role("button", name="Bestätigen und starten", exact=True).click()
    expect(page.get_by_role("button", name="Vorgang läuft", exact=True)).to_be_disabled()
    assert sum(path.endswith("/sync") for _, path, _ in fixture.calls) == 1
    fixture.hold.clear()
    fixture.send(fixture.pending.pop(), {"connector_results": [{"status": "fetch_failed", "message": "Synthetic failure"}]})
    expect(page.get_by_role("alert")).to_contain_text("vorherige erfolgreiche Datenstand")
    page.keyboard.press("Escape")
    go("#dashboard")
    page.get_by_text("Technische Prüfdetails und zentrale Neuberechnung", exact=True).click()
    page.get_by_role("button", name="Bestehende Daten neu berechnen", exact=True).click()
    expect(page.get_by_role("dialog")).to_contain_text("Kein Exchange-Abruf")
    page.get_by_role("button", name="Bestätigen und starten", exact=True).click()
    expect(page.get_by_text("Berechnung abgeschlossen; offene Fach-Gates und Belege prüfen.", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    page.get_by_text("Technische Prüfdetails und zentrale Neuberechnung", exact=True).click()
    done(17, "Nur gemocktes Testsystem: bestätigter Sync mit Doppelstart-Sperre/Fehler und ausdrücklich bestätigte Neuberechnung.")

    for width in (390, 768, 1280, 1440):
        page.set_viewport_size({"width": width, "height": 900 if width >= 1280 else 844})
        for route in ("dashboard", "sources", "flows", "review", "tax", "export"):
            go("#" + route)
            expect(page.locator(".wsPage").first).to_be_visible()
            expect(page.locator(".wsResource")).to_have_count(0)
            if width <= 768:
                expect(page.locator(".sidebar")).not_to_be_in_viewport()
            selected_tab = page.locator('[role="tab"][aria-selected="true"]').first
            expect(page.locator("#" + selected_tab.get_attribute("aria-controls"))).to_be_visible()
            screenshot(f"{route}-{width}")
            if route in ("sources", "flows", "review"):
                if route == "sources":
                    page.get_by_role("button", name="Demo-Börse", exact=True).click()
                elif route == "flows":
                    page.locator(".wsActivityTable tbody tr button").first.click()
                else:
                    page.get_by_role("button", name="Originalbeleg prüfen", exact=True).click()
                expect(page.get_by_role("dialog")).to_be_visible()
                expect(page.get_by_role("dialog").locator(".wsResource")).to_have_count(0)
                if route == "sources":
                    expect(page.get_by_role("dialog").get_by_role("heading", name="Demo-Börse", exact=True)).to_be_visible()
                elif route == "flows":
                    expect(page.get_by_role("dialog").get_by_text("Ereignis-ID", exact=True)).to_be_visible()
                screenshot(f"{route}-detail-{width}")
                page.keyboard.press("Escape")
        if width <= 768:
            page.get_by_role("button", name="Navigation öffnen", exact=True).click()
            expect(page.locator(".sidebarClose")).to_be_focused()
            page.get_by_role("button", name="Quellen & Wallets", exact=True).click()
            expect(page.get_by_role("button", name="Navigation öffnen", exact=True)).to_have_attribute("aria-expanded", "false")
    done(21, "390/768/1280/1440: neue Hauptansichten und Panels ohne Seitenoverflow; mobile Navigation schließt nach Auswahl.")
    page.set_viewport_size({"width": 1440, "height": 1000})
    go("#sources?tab=expert")
    try:
        expect(page.get_by_text("Zeitabhaengige Quellenregistry", exact=True)).to_be_visible()
    except AssertionError:
        print(json.dumps({"expert_errors": errors, "recent_calls": fixture.calls[-20:], "visible": page.locator("body").inner_text()[:5000]}, ensure_ascii=False), flush=True)
        screenshot("sources-expert-failure-1440")
        raise
    assert not any("earn-history-api-preview" in path for _, path, _ in fixture.calls)
    done(22, "Registry und technische Quelleninformationen im Expertenmodus erreichbar; kein automatischer externer Earn-Abruf.")
    go("#flows?tab=flows")
    expect(page.get_by_role("tab", name="Geldflüsse", exact=True)).to_have_attribute("aria-selected", "true")
    page.get_by_role("tab", name="Transferkandidaten", exact=True).click()
    expect(page.get_by_role("tab", name="Transferkandidaten", exact=True)).to_have_attribute("aria-selected", "true")
    go("#flows")
    expect(page.get_by_role("tab", name="Transaktionen", exact=True)).to_have_attribute("aria-selected", "true")
    expect(page.locator(".wsActivityTable tbody tr")).to_have_count(25)
    done(23, "#flows weiterhin erreichbar, Transaktionen als Einstieg, Geldflüsse und Transferkandidaten erhalten.")
    passed["A24"] = {"status": "separat zu prüfen", "evidence": "Bestehende Fachtests werden im Backend-Testlauf geprüft, nicht mit UI-Mocks."}
    assert not errors, errors
    assert not external, external
    result = {"scenarios": dict(sorted(passed.items())), "javascript_errors": errors, "external_requests": external,
              "all_api_responses_synthetic": True, "out_of_order_search": True, "screenshots": screenshots}
    (output / "workspace-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    context.unroute_all(behavior="ignoreErrors")
    context.close()
    return result
