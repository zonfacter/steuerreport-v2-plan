"""Isolierte MEXC-UI-Vertragsprobe mit rein synthetischen Daten.

Zuerst frontend bauen. Ohne --base-url wird frontend/dist auf einem freien
Loopback-Port bereitgestellt. Alle APIs sind gemockt; Fremdverkehr wird blockiert.
Keine Aussage ueber echte XLSX-Normalisierung, Persistenz oder Steuerfreigaben.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from ux_workspace_fixtures import WorkspaceFixture


PREFIX = "/api/v1/import/assistant/"
ACCOUNT = "SYNTHETIC-ACCOUNT"
SECRET = "SYNTHETIC_SECRET_MUST_NOT_RENDER"
KINDS = ["spot_statement", "funding_other", "asset_snapshot", "futures_capital_flow",
         "futures_statement", "earn_fixed", "earn_flexible", "send_history"]
ZONES = ["UTC", "UTC+01:00", "UTC+08:00", "Europe/Berlin"]


class Fixture:
    def __init__(self):
        self.workspace = WorkspaceFixture()
        self.calls, self.unexpected = [], []
        self.mode = "ready"
        self.error = None
        self.executed = 0
        self.skipped_raw_objects = 0
        self.candidate_revision = 0
        self.same_provider_id = False
        self.multi_sheet = False
        self.last_rows = []

    def row_digest(self, payload, row):
        config = payload.get("mexc", {})
        inputs = {"content_base64": payload["content_base64"], "source": payload["source"],
                  "sheet": payload.get("sheet_name") or "Sheet1", "account": config.get("account"),
                  "export_kind": config.get("export_kind"), "timezone": config.get("timezone"),
                  "row_number": row["row_number"], "candidates": row["candidates"], "same_provider_id": self.same_provider_id}
        return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()

    def posts(self, operation):
        return [call["body"] for call in self.calls if call["path"] == PREFIX + operation]

    def preview(self, payload):
        config = payload.get("mexc", {})
        kind = config.get("export_kind")
        selected_sheet = payload.get("sheet_name")
        missing = []
        if payload["source"] == "mexc":
            if not config.get("account") or not kind:
                missing.append("Konto und Exportart ausdruecklich bestaetigen.")
            if kind == "funding_other" and not config.get("timezone"):
                missing.append("Time ohne Offset: Zeitbasis fehlt.")
        detected_kind = kind
        sheet_selection_required = False
        if self.multi_sheet:
            detected_kind = "funding_other" if selected_sheet == "Funding" else "spot_statement"
            if not selected_sheet:
                detected_kind = None
                sheet_selection_required = True
                missing.append("Mehrere Tabellenblaetter vorhanden; ein MEXC-Tabellenblatt ausdruecklich auswaehlen.")
            elif kind != detected_kind:
                missing.append("Die bestaetigte Exportart passt nicht zum ausgewaehlten Tabellenblatt.")
        count = 2003 if self.mode == "candidate" else 1
        if sheet_selection_required:
            count = 0
        candidates = [{"raw_object_id": "synthetic-raw-A", "filename": "synthetic-origin.xlsx", "row_number": 8, "export_kind": "spot_statement"},
                      {"raw_object_id": "synthetic-raw-B", "filename": None, "row_number": None, "export_kind": "funding_other"}]
        if self.candidate_revision:
            candidates[0]["filename"] = f"synthetic-origin-revision-{self.candidate_revision}.xlsx"
        rows = [{"row_number": index + 2, "status": "ready", "reason": "Synthetische Kontobewegung, Klassifikation offen.",
                 "asset": "DEMOCOIN", "quantity": "2.500000000000000001", "event_time": "2031-07-09T11:00:00Z", "candidates": []}
                for index in range(count)]
        decisions = config.get("decisions", {})
        if rows and payload["source"] == "mexc" and (self.mode in {"candidate", "linked"} or (self.mode == "multi" and self.executed)):
            rows[0].update(status="duplicate_candidate", reason="Weitere Ansicht derselben Buchung moeglich.", candidates=candidates)
            if "2" in decisions:
                decision = decisions["2"]
                assert len(decision["reason"].strip()) >= 10
                assert decision["action"] in {"link_existing", "separate"}
                if decision["action"] == "link_existing":
                    assert decision["target_raw_object_id"] in {item["raw_object_id"] for item in candidates}
                else:
                    assert "target_raw_object_id" not in decision
                rows[0]["status"] = "linked" if decision["action"] == "link_existing" else "ready"
            else:
                missing.append("Doppelbeleg in physischer Zeile 2 zuordnen.")
        if rows and self.mode == "candidate":
            rows[1].update(status="review", reason="Synthetischer Vorgang fachlich zu pruefen.")
        disposition = "transactions"
        if self.mode == "empty":
            count, rows, disposition = 0, [], "empty"
        elif rows and detected_kind == "asset_snapshot":
            disposition = "evidence_only"
            rows[0].update(status="evidence_only", reason="Bestandsnachweis, kein Erwerb.")
        elif rows and self.mode == "unsupported":
            disposition = "unsupported"
            missing.append("Dieses Produkt ist fachlich noch nicht unterstuetzt.")
            rows[0].update(status="invalid", reason="Synthetische Richtung widerspruechlich.")
        if sheet_selection_required:
            disposition = "unsupported"
        for row in rows:
            row.update(input_digest=self.row_digest(payload, row), decision_stale=False)
            decision = decisions.get(str(row["row_number"]))
            if decision and decision.get("input_digest") != row["input_digest"]:
                reason = "Zuordnung veraltet: Originalbytes, Kontext oder Kandidatenfakten geaendert. Erneut bestaetigen."
                row.update(status="invalid", reason=reason, decision_stale=True)
                missing.append(reason)
            elif decision and self.same_provider_id and decision["action"] == "separate":
                reason = "Identische echte Provider-ID: keine eigenstaendige Buchung; bestehenden Beleg verknuepfen."
                row.update(status="invalid", reason=reason)
                missing.append(reason)
        self.last_rows = rows
        linked = int(bool(rows) and rows[0]["status"] == "linked")
        mexc = {"detected_kind": detected_kind, "disposition": disposition, "raw_rows": count,
                # Belegte Mengen koennen zugleich eine offene Fachklassifikation haben.
                "bookable_rows": sum(row["status"] in {"ready", "review"} for row in rows) if disposition == "transactions" else 0,
                "linked_rows": linked, "review_rows": sum(row["status"] in {"review", "invalid", "duplicate_candidate"} for row in rows),
                "snapshot_rows": count if detected_kind == "asset_snapshot" else 0,
                "bonus_rows": count if detected_kind == "futures_capital_flow" else 0,
                "blocking_reasons": missing, "warnings": ["Airdrop bleibt Quellbezeichnung, keine Mining-Freigabe."], "rows": rows}
        return {"can_execute": not missing, "warnings": ["Synthetischer allgemeiner Dateihinweis."],
                "preview": {"row_count": count, "columns": ["Crypto", "Quantity"],
                            "sample_rows": [{"Crypto": "DEMOCOIN", "Quantity": "2.5"}] if count else [],
                            "sheet_name": selected_sheet if selected_sheet else None if self.multi_sheet else "Sheet1",
                            "sheet_names": ["Spot", "Funding"] if self.multi_sheet else ["Sheet1"],
                            "file_sha256": "a" * 64, "import_fingerprint": payload["filename"],
                            "missing_required_groups": [], "profile_label": "MEXC nativ",
                            **({"mexc": mexc} if payload["source"] == "mexc" else {})}}

    def handle(self, route):
        path = urlparse(route.request.url).path
        method = route.request.method
        body = route.request.post_data_json if route.request.post_data else None
        self.calls.append({"method": method, "path": path, "body": body})
        if path == "/api/v1/import/profiles" and method == "GET":
            self.workspace.send(route, [{"source": "mexc", "label": "MEXC"}, {"source": "manual-csv", "label": "Manuelle CSV"}])
        elif path == "/api/v1/import/batches/synthetic-batch/original" and method == "GET":
            route.fulfill(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          headers={"Content-Disposition": 'attachment; filename="synthetic-original.xlsx"'},
                          body=b"SYNTHETIC-UI-ONLY-ORIGINAL")
        elif path == "/api/v1/import/batches/synthetic-batch/trace.json" and method == "GET":
            route.fulfill(content_type="application/json", headers={"Content-Disposition": 'attachment; filename="synthetic-trace.json"'},
                          body=json.dumps({"mexc_evidence": []}))
        elif path in {PREFIX + "preview", PREFIX + "execute"} and method == "POST":
            assert body["source"] in {"mexc", "manual-csv"}
            assert body["import_mode"] == "file" and body["content_base64"]
            if body.get("mexc"):
                assert set(body["mexc"]) <= {"export_kind", "account", "timezone", "decisions"}
                assert body["mexc"]["export_kind"] in KINDS
                assert 0 < len(body["mexc"]["account"]) <= 128
                for decision in body["mexc"]["decisions"].values():
                    if "input_digest" in decision:
                        assert re.fullmatch(r"[0-9a-fA-F]{64}", decision["input_digest"])
            if self.error:
                if self.error == "network":
                    route.abort("failed")
                else:
                    route.fulfill(status=503 if self.error == "http" else 200, content_type="application/json",
                                  body=json.dumps({"status": "error", "errors": [{"message": SECRET}], "detail": SECRET}))
            elif path.endswith("preview"):
                self.workspace.send(route, self.preview(body))
            elif self.mode == "multi" and self.executed:
                route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": SECRET}))
            elif body["source"] == "mexc" and not self.preview(body)["can_execute"]:
                route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": SECRET}))
            else:
                self.executed += 1
                self.workspace.send(route, {"batch": {"batch_id": "synthetic-batch"},
                                            "run": {"imported_rows": 1, "normalized_events": 0, "skipped_raw_objects": self.skipped_raw_objects}})
        elif method == "GET" and path == "/api/v1/health":
            self.workspace.send(route, {"app_version": "synthetic", "status": "ok"})
        elif method == "GET" and self.workspace.handle(route):
            pass
        else:
            self.unexpected.append({"method": method, "path": path})
            route.abort("blockedbyclient")


def area(page):
    return page.get_by_role("region", name="Dateiimport", exact=True)


def file_row(page, filename="synthetic.xlsx"):
    return area(page).locator(".importFile").filter(has=page.get_by_text(filename, exact=True))


def select_files(page, names=("synthetic.xlsx",)):
    area(page).get_by_label("Importdateien auswaehlen", exact=True).set_input_files([
        {"name": name, "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "buffer": b"SYNTHETIC-UI-ONLY; not a real workbook"} for name in names])


def configure(page, kind="spot_statement", filename="synthetic.xlsx", zone=None):
    area(page).get_by_label("MEXC-Konto", exact=True).fill(ACCOUNT)
    file_row(page, filename).get_by_label(f"MEXC-Exportart fuer {filename}", exact=True).select_option(kind)
    if zone:
        file_row(page, filename).get_by_label(f"MEXC-Zeitbasis fuer {filename}", exact=True).select_option(zone)


def check(page):
    area(page).get_by_role("button", name="Dateien pruefen", exact=True).click()
    expect(area(page).get_by_role("button", name="Dateien pruefen", exact=True)).to_be_enabled()


def approve(page):
    return area(page).get_by_role("checkbox", name=re.compile("Gepruefte Dateien freigeben"))


def review(page, filename="synthetic.xlsx"):
    return file_row(page, filename).get_by_role("region", name=f"MEXC-Pruefung fuer {filename}", exact=True)


def decision_fields(page):
    block = review(page)
    block.locator("summary").click()
    choice = block.get_by_label("Belegzuordnung Zeile 2 fuer synthetic.xlsx", exact=True)
    return block, choice


def scenarios(output):
    def missing(page, fixture):
        select_files(page, ("MEXC Spot Statement filename-is-not-proof.xlsx",))
        row = file_row(page, "MEXC Spot Statement filename-is-not-proof.xlsx")
        expect(row.get_by_label(re.compile("MEXC-Exportart"))).to_have_value("")
        expect(area(page).get_by_role("link", name="CSV-Vorlage", exact=True)).to_have_attribute("href", "/import-vorlagen/mexc.csv")
        check(page)
        assert "mexc" not in fixture.posts("preview")[-1]
        expect(row).to_contain_text("Konto und Exportart ausdruecklich bestaetigen")
        expect(approve(page)).to_be_disabled()
        account = area(page).get_by_label("MEXC-Konto", exact=True)
        expect(account).to_have_attribute("maxlength", "128")
        account.fill(ACCOUNT)
        check(page)
        assert "mexc" not in fixture.posts("preview")[-1]
        expect(area(page)).to_contain_text("keine Erwerbsbasis")
        tip = area(page).get_by_role("button", name="Hilfe: MEXC Exportart und Zeitbasis", exact=True)
        tip.focus()
        expect(page.get_by_role("tooltip")).to_contain_text("UTC+01:00 ist ein fester Offset")
        page.keyboard.press("Escape")
        expect(page.get_by_role("tooltip")).to_have_count(0)
        assert not fixture.posts("execute")

    def timezone_errors(page, fixture):
        select_files(page)
        configure(page, "funding_other")
        check(page)
        expect(review(page)).to_contain_text("Time ohne Offset: Zeitbasis fehlt")
        assert "timezone" not in fixture.posts("preview")[-1]["mexc"]
        expect(approve(page)).to_be_disabled()
        for zone in ZONES:
            file_row(page).get_by_label("MEXC-Zeitbasis fuer synthetic.xlsx", exact=True).select_option(zone)
            expect(approve(page)).not_to_be_checked()
            expect(review(page)).to_have_count(0)
            check(page)
            assert fixture.posts("preview")[-1]["mexc"]["timezone"] == zone
            approve(page).check()
        for error in ("http", "envelope", "network"):
            fixture.error = error
            check(page)
            expect(file_row(page).get_by_role("alert")).to_contain_text("Anfrage fehlgeschlagen")
            expect(area(page)).not_to_contain_text(SECRET)
            expect(area(page).get_by_label("MEXC-Konto", exact=True)).to_have_value(ACCOUNT)
            expect(file_row(page).get_by_label("MEXC-Exportart fuer synthetic.xlsx", exact=True)).to_have_value("funding_other")
            expect(file_row(page).get_by_label("MEXC-Zeitbasis fuer synthetic.xlsx", exact=True)).to_have_value("Europe/Berlin")
            expect(approve(page)).to_be_disabled()
        fixture.error = None
        check(page)
        expect(approve(page)).to_be_enabled()
        assert not fixture.posts("execute")

    def explicit_multisheet(page, fixture):
        fixture.multi_sheet = True
        select_files(page)
        configure(page)
        check(page)
        row = file_row(page)
        sheet = row.get_by_label("Tabellenblatt fuer synthetic.xlsx", exact=True)
        expect(sheet).to_have_value("")
        expect(sheet.locator("option").first).to_have_text("Tabellenblatt auswaehlen")
        expect(row.locator(".statusPill")).to_have_text("Nicht importierbar")
        expect(review(page)).to_contain_text("Tabellenblatt noch nicht ausgewaehlt")
        expect(review(page).get_by_label("MEXC-Gesamtzahlen")).to_have_count(0)
        expect(approve(page)).to_be_disabled()
        assert not fixture.posts("execute")

        sheet.select_option("Funding")
        row.get_by_label("MEXC-Exportart fuer synthetic.xlsx", exact=True).select_option("funding_other")
        row.get_by_label("MEXC-Zeitbasis fuer synthetic.xlsx", exact=True).select_option("UTC+01:00")
        check(page)
        expect(row.get_by_label("Tabellenblatt fuer synthetic.xlsx", exact=True)).to_have_value("Funding")
        expect(row.locator(".statusPill")).to_have_text("Importierbar")
        expect(review(page).get_by_label("MEXC-Gesamtzahlen")).to_contain_text("Rohzeilen")
        approve(page).check()
        area(page).get_by_role("button", name="1 Datei(en) importieren", exact=True).click()
        expect(row.locator(".statusPill")).to_have_text("Importiert")
        assert fixture.posts("execute")[-1]["sheet_name"] == "Funding"

    def candidates(page, fixture):
        fixture.mode = "candidate"
        select_files(page)
        configure(page)
        check(page)
        initial_digest = fixture.last_rows[0]["input_digest"]
        block, choice = decision_fields(page)
        expect(block.get_by_label("MEXC-Gesamtzahlen")).to_contain_text("2003")
        expect(block.get_by_label("MEXC-Gesamtzahlen").locator("div").filter(has_text="Doppelbeleg-Kandidaten").locator("dd")).to_have_text("1")
        expect(block.get_by_label("MEXC-Gesamtzahlen").locator("div").filter(has_text="Mengenbuchungen").locator("dd")).to_have_text("2002")
        expect(block.get_by_label("MEXC-Gesamtzahlen").locator("div").filter(has_text="fachlich offen").locator("dd")).to_have_text("2")
        expect(block.get_by_text("Zaehler sind nicht additiv: Mengenbuchungen koennen fachlich offen sein.", exact=True)).to_be_visible()
        expect(block).to_contain_text("koennen sich ueberschneiden")
        expect(block).to_contain_text("ungeklaerter Vorgang (unknown)")
        expect(block.locator("strong")).to_have_count(25)
        expect(block).to_contain_text("Zeile 3: Fachlich zu pruefen")
        expect(block).to_contain_text("Seite 1 von 81 / 2003 Zeilen")
        block.get_by_role("button", name="Naechste Zeilenseite", exact=True).click()
        expect(block).to_contain_text("Zeile 27: Mengenbewegung buchbar")
        expect(block.locator("strong")).to_have_count(25)
        block.get_by_role("button", name="Vorherige Zeilenseite", exact=True).click()
        choice.select_option("raw:synthetic-raw-B")
        reason = block.get_by_label("Begruendung Zeile 2 fuer synthetic.xlsx", exact=True)
        reason.fill("kurz")
        expect(reason).to_have_attribute("aria-invalid", "true")
        before = len(fixture.posts("preview"))
        check(page)
        assert len(fixture.posts("preview")) == before
        reason.fill("Synthetischer Zweitbeleg aus gleichem Konto.")
        expect(reason).to_be_focused()
        expect(reason).to_have_attribute("aria-invalid", "false")
        expect(approve(page)).to_be_disabled()
        expect(block).to_contain_text("Vorschau nicht mehr aktuell")
        check(page)
        decision = fixture.posts("preview")[-1]["mexc"]["decisions"]["2"]
        assert decision == {"action": "link_existing", "target_raw_object_id": "synthetic-raw-B", "reason": reason.input_value(), "input_digest": initial_digest}
        expect(block).to_contain_text("Zeile 2: Verknuepft")
        approve(page).check()
        choice.select_option("separate")
        expect(approve(page)).not_to_be_checked()
        expect(approve(page)).to_be_disabled()
        check(page)
        assert fixture.posts("preview")[-1]["mexc"]["decisions"]["2"]["action"] == "separate"
        assert fixture.posts("preview")[-1]["mexc"]["decisions"]["2"]["input_digest"] == initial_digest
        assert "target_raw_object_id" not in fixture.posts("preview")[-1]["mexc"]["decisions"]["2"]
        fixture.error = "envelope"
        check(page)
        expect(choice).to_have_value("separate")
        expect(reason).to_have_value("Synthetischer Zweitbeleg aus gleichem Konto.")
        expect(area(page)).not_to_contain_text(SECRET)
        expect(approve(page)).to_be_disabled()
        fixture.error = None
        check(page)
        approve(page).check()
        preview_payload = fixture.posts("preview")[-1]
        area(page).get_by_role("button", name="1 Datei(en) importieren", exact=True).click()
        expect(file_row(page).locator(".statusPill")).to_have_text("Importiert")
        assert fixture.posts("execute") == [preview_payload]
        expect(reason).to_be_disabled()
        original = file_row(page).get_by_role("link", name="Originaldatei", exact=True)
        trace = file_row(page).get_by_role("link", name="Belegspur (JSON)", exact=True)
        expect(original).to_have_attribute("href", re.compile(r"/api/v1/import/batches/synthetic-batch/original$"))
        expect(trace).to_have_attribute("href", re.compile(r"/api/v1/import/batches/synthetic-batch/trace.json$"))
        expect(original).to_have_attribute("download", "")
        expect(trace).to_have_attribute("download", "")
        # Native Download-Klicks umgehen in manchen Chromium-Versionen context.route.
        # Nur abgefangene Fetches der echten Linkziele, keine Weitergabe an lokale Backends.
        downloads = page.evaluate("""async urls => {
          const results = [];
          for (const url of urls) {
            const response = await fetch(url);
            results.push({status: response.status, body: await response.text(), disposition: response.headers.get('Content-Disposition')});
          }
          return results;
        }""", [original.get_attribute("href"), trace.get_attribute("href")])
        assert downloads[0] == {"status": 200, "body": "SYNTHETIC-UI-ONLY-ORIGINAL", "disposition": 'attachment; filename="synthetic-original.xlsx"'}, downloads
        assert downloads[1]["status"] == 200 and json.loads(downloads[1]["body"]) == {"mexc_evidence": []}, downloads

    def resets(page, fixture):
        fixture.mode = "candidate"
        select_files(page)
        configure(page)
        check(page)
        for field, value in (("MEXC-Zeitbasis fuer synthetic.xlsx", "UTC+01:00"),
                             ("MEXC-Exportart fuer synthetic.xlsx", "funding_other"),
                             ("MEXC-Konto", "SYNTHETIC-SECOND")):
            block = review(page)
            if block.locator("details").get_attribute("open") is None:
                block.locator("summary").click()
            choice = block.get_by_label("Belegzuordnung Zeile 2 fuer synthetic.xlsx", exact=True)
            choice.select_option("separate")
            block.get_by_label("Begruendung Zeile 2 fuer synthetic.xlsx", exact=True).fill("Zwei echte synthetische Buchungen.")
            check(page)
            approve(page).check()
            control = area(page).get_by_label(field, exact=True)
            control.fill(value) if field == "MEXC-Konto" else control.select_option(value)
            expect(approve(page)).not_to_be_checked()
            expect(approve(page)).to_be_disabled()
            expect(review(page)).to_have_count(0)
            check(page)
            assert fixture.posts("preview")[-1]["mexc"]["decisions"] == {}
        area(page).get_by_label("Importquelle", exact=True).select_option("manual-csv")
        expect(area(page).get_by_label("MEXC-Konto", exact=True)).to_have_count(0)
        expect(review(page)).to_have_count(0)
        check(page)
        assert "mexc" not in fixture.posts("preview")[-1]
        approve(page).check()
        area(page).get_by_role("button", name="1 Datei(en) importieren", exact=True).click()
        expect(file_row(page).locator(".statusPill")).to_have_text("Importiert")
        assert "mexc" not in fixture.posts("execute")[-1]
        expect(file_row(page).get_by_role("link", name="Originaldatei", exact=True)).to_have_count(0)

    def dispositions(page, fixture):
        select_files(page)
        configure(page)
        fixture.mode = "empty"
        check(page)
        expect(file_row(page).locator(".statusPill")).to_have_text("Leer (kein Import)")
        expect(review(page)).to_contain_text("kein erfolgreicher Import")
        expect(approve(page)).to_be_disabled()
        expect(area(page)).to_contain_text("Leere Exporte enthalten keine Datenzeilen")
        fixture.mode = "ready"
        file_row(page).get_by_label("MEXC-Exportart fuer synthetic.xlsx", exact=True).select_option("asset_snapshot")
        check(page)
        expect(review(page)).to_contain_text("keine neuen Erwerbe")
        expect(review(page).get_by_label("MEXC-Gesamtzahlen")).to_contain_text("Bestandszeilen")
        file_row(page).get_by_label("MEXC-Exportart fuer synthetic.xlsx", exact=True).select_option("futures_capital_flow")
        check(page)
        expect(review(page).get_by_label("MEXC-Gesamtzahlen").locator("div").filter(has_text="BONUS-Zeilen").locator("dd")).to_have_text("1")
        fixture.mode = "unsupported"
        for kind in KINDS[4:]:
            file_row(page).get_by_label("MEXC-Exportart fuer synthetic.xlsx", exact=True).select_option(kind)
            check(page)
            expect(review(page)).to_contain_text("fachlich nicht unterstuetzt")
            expect(approve(page)).to_be_disabled()
        review(page).locator("summary").click()
        expect(review(page)).to_contain_text("Zeile 2: Ungueltig")
        assert not fixture.posts("execute")

    def invalid_files(page, fixture):
        select_files(page, ("synthetic.txt",))
        expect(file_row(page, "synthetic.txt").get_by_role("alert")).to_contain_text("MEXC unterstuetzt nur CSV oder XLSX")
        expect(area(page).get_by_role("button", name="Dateien pruefen", exact=True)).to_be_disabled()
        expect(approve(page)).to_be_disabled()
        assert not fixture.posts("preview") and not fixture.posts("execute")

    def source_formats(page, fixture):
        source = area(page).get_by_label("Importquelle", exact=True)
        files = area(page).get_by_label("Importdateien auswaehlen", exact=True)
        drop_label = area(page).locator(".fileDropZone > span")
        expect(files).to_have_attribute("accept", ".csv,.xlsx")
        expect(drop_label).to_have_text("CSV / XLSX")
        select_files(page, ("synthetic.xls",))
        expect(file_row(page, "synthetic.xls").locator(".statusPill")).to_have_text("Fehler")
        expect(area(page).get_by_role("button", name="Dateien pruefen", exact=True)).to_be_disabled()
        area(page).get_by_role("button", name="Neuer Import", exact=True).click()

        source.select_option("")
        select_files(page, ("synthetic.xls",))
        expect(file_row(page, "synthetic.xls").locator(".statusPill")).to_have_text("Ungeprueft")
        expect(file_row(page, "synthetic.xls").get_by_role("alert")).to_have_count(0)
        expect(area(page).get_by_role("button", name="Hilfe: MEXC Exportart und Zeitbasis", exact=True)).to_have_count(0)
        source.select_option("mexc")
        expect(file_row(page, "synthetic.xls").locator(".statusPill")).to_have_text("Fehler")
        expect(file_row(page, "synthetic.xls").get_by_role("alert")).to_contain_text("kein XLS")
        expect(approve(page)).to_be_disabled()
        assert not fixture.posts("preview")

        source.select_option("manual-csv")
        expect(files).to_have_attribute("accept", ".csv,.xlsx,.xls")
        expect(drop_label).to_have_text("CSV / XLSX / XLS")
        expect(file_row(page, "synthetic.xls").get_by_role("alert")).to_have_count(0)
        expect(area(page).locator("#mexc-import-effect")).to_have_count(0)
        check(page)
        approve(page).check()
        source.select_option("mexc")
        expect(file_row(page, "synthetic.xls").locator(".statusPill")).to_have_text("Fehler")
        expect(approve(page)).not_to_be_checked()
        expect(approve(page)).to_be_disabled()
        expect(approve(page)).to_have_accessible_name("Gepruefte Dateien freigeben (0)")
        expect(area(page).get_by_role("button", name="Dateien pruefen", exact=True)).to_be_disabled()
        expect(file_row(page, "synthetic.xls").get_by_role("button", name="Vorschau", exact=True)).to_have_count(0)

        area(page).get_by_role("button", name="Neuer Import", exact=True).click()
        page.evaluate("""() => {
          const data = new DataTransfer();
          data.items.add(new File(['SYNTHETIC-UI-ONLY'], 'synthetic-drop.xls'));
          document.querySelector('.fileDropZone').dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: data}));
        }""")
        expect(file_row(page, "synthetic-drop.xls").locator(".statusPill")).to_have_text("Fehler")
        area(page).get_by_role("button", name="Neuer Import", exact=True).click()
        names = ("synthetic.csv", "synthetic.XLSX")
        select_files(page, names)
        for name in names:
            configure(page, filename=name)
        check(page)
        expect(approve(page)).to_have_accessible_name("Gepruefte Dateien freigeben (2)")
        expect(approve(page)).to_be_enabled()
        assert [call["source"] for call in fixture.posts("preview")] == ["manual-csv", "mexc", "mexc"]
        assert not fixture.posts("execute")

    def approval_effect(page, fixture):
        for kind in ("spot_statement", "asset_snapshot"):
            select_files(page)
            configure(page, kind=kind)
            check(page)
            effect = area(page).locator("#mexc-import-effect")
            expect(effect).to_be_visible()
            expect(effect).to_contain_text("speichert Rohbelege")
            expect(effect).to_contain_text("bestehende Ledger-/Steuervorschau-Pipeline")
            expect(effect).to_contain_text("keine fachliche oder steuerliche Freigabe")
            expect(approve(page)).not_to_be_checked()
            expect(approve(page)).to_have_attribute("aria-describedby", "mexc-import-effect")
            assert effect.evaluate("el => !!(el.compareDocumentPosition(el.parentElement.querySelector('input[type=checkbox]')) & Node.DOCUMENT_POSITION_FOLLOWING)")
            if kind == "spot_statement":
                for width in (390, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    effect.scroll_into_view_if_needed()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                    page.screenshot(path=str(output / f"synthetic-mexc-import-effect-{width}.png"), animations="disabled")
            before = len(fixture.calls)
            approve(page).check()
            assert len(fixture.posts("execute")) == fixture.executed
            area(page).get_by_role("button", name="1 Datei(en) importieren", exact=True).click()
            expect(file_row(page).locator(".statusPill")).to_have_text("Importiert")
            assert [call["path"] for call in fixture.calls[before:] if call["method"] == "POST"] == [PREFIX + "execute"]
            if kind == "asset_snapshot":
                expect(review(page)).to_contain_text("keine neuen Erwerbe")
                expect(file_row(page).locator(".importOutcome")).to_contain_text("0 Ereignisse")
            area(page).get_by_role("button", name="Neuer Import", exact=True).click()

    def multi(page, fixture):
        fixture.mode = "multi"
        select_files(page, ("synthetic.xlsx", "synthetic-second.xlsx"))
        configure(page)
        file_row(page, "synthetic-second.xlsx").get_by_label("MEXC-Exportart fuer synthetic-second.xlsx", exact=True).select_option("funding_other")
        file_row(page, "synthetic-second.xlsx").get_by_label("MEXC-Zeitbasis fuer synthetic-second.xlsx", exact=True).select_option("UTC+01:00")
        expect(area(page)).to_contain_text("neu entstandenen Dublettenkandidaten")
        check(page)
        expect(approve(page)).to_be_enabled()
        approve(page).check()
        area(page).get_by_role("button", name="2 Datei(en) importieren", exact=True).click()
        expect(file_row(page).locator(".statusPill")).to_have_text("Importiert")
        expect(file_row(page, "synthetic-second.xlsx").locator(".statusPill")).to_have_text("Fehler")
        expect(area(page)).not_to_contain_text(SECRET)
        assert len(fixture.posts("execute")) == 2
        assert fixture.posts("execute")[0]["mexc"] == {"export_kind": "spot_statement", "account": ACCOUNT, "decisions": {}}
        assert fixture.posts("execute")[1]["mexc"] == {"export_kind": "funding_other", "account": ACCOUNT, "timezone": "UTC+01:00", "decisions": {}}
        check(page)
        expect(review(page, "synthetic-second.xlsx")).to_contain_text("Doppelbeleg in physischer Zeile 2")
        expect(approve(page)).to_be_disabled()
        assert len(fixture.posts("execute")) == 2

    def outcome_labels(page, fixture):
        fixture.skipped_raw_objects = 1
        cases = (("mexc", "asset_snapshot", "ready"), ("mexc", "spot_statement", "linked"), ("manual-csv", None, "ready"))
        for source, kind, mode in cases:
            fixture.mode = mode
            area(page).get_by_label("Importquelle", exact=True).select_option(source)
            select_files(page)
            if kind:
                configure(page, kind=kind)
            check(page)
            if mode == "linked":
                block, choice = decision_fields(page)
                choice.select_option("raw:synthetic-raw-A")
                block.get_by_label("Begruendung Zeile 2 fuer synthetic.xlsx", exact=True).fill("Synthetischer Zweitbeleg, keine eigene Ereignisbuchung.")
                check(page)
                expect(block).to_contain_text("Zeile 2: Verknuepft")
            approve(page).check()
            area(page).get_by_role("button", name="1 Datei(en) importieren", exact=True).click()
            expect(file_row(page).locator(".statusPill")).to_have_text("Importiert")
            outcome = file_row(page).locator(".importOutcome > span")
            label = "Rohzeilen ohne eigene Ereignisbuchung (Beleg/Review)" if source == "mexc" else "nicht zugeordnet"
            expect(outcome).to_have_text(f"1 Rohzeilen / 0 Ereignisse / 1 {label}")
            if source == "mexc":
                expect(outcome).not_to_contain_text("nicht zugeordnet")
                page.set_viewport_size({"width": 320, "height": 900})
                outcome.scroll_into_view_if_needed()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(output / f"synthetic-mexc-outcome-{kind}-320.png"), animations="disabled")
            if mode == "linked":
                assert fixture.posts("execute")[-1]["mexc"]["decisions"]["2"] == {
                    "action": "link_existing", "target_raw_object_id": "synthetic-raw-A",
                    "reason": "Synthetischer Zweitbeleg, keine eigene Ereignisbuchung.", "input_digest": fixture.last_rows[0]["input_digest"]}
            area(page).get_by_role("button", name="Neuer Import", exact=True).click()

    def digest_binding(page, fixture):
        """Dateibytes werden adversarial im Request getauscht, nicht durch ein neues UI-Dateiaustauschfeature."""
        fixture.mode = "linked"
        page.evaluate(r"""() => {
          const original = window.fetch;
          window.__mexcReplacement = '';
          window.fetch = (input, options = {}) => {
            if (window.__mexcReplacement && options.body && /\/api\/v1\/import\/assistant\/(preview|execute)$/.test(String(input))) {
              const body = JSON.parse(options.body);
              if (body.source === 'mexc') options = {...options, body: JSON.stringify({...body, content_base64: window.__mexcReplacement})};
            }
            return original(input, options);
          };
        }""")
        for change in ("file", "candidates"):
            select_files(page)
            configure(page)
            check(page)
            old_digest = fixture.last_rows[0]["input_digest"]
            assert re.fullmatch(r"[0-9a-f]{64}", old_digest)
            block, choice = decision_fields(page)
            target = "raw:synthetic-raw-A" if change == "file" else "separate"
            choice.select_option(target)
            reason = block.get_by_label("Begruendung Zeile 2 fuer synthetic.xlsx", exact=True)
            reason.fill("Synthetischer Zweitbeleg mit belegtem Ursprung.")
            check(page)
            original_payload = fixture.posts("preview")[-1]
            assert original_payload["mexc"]["decisions"]["2"]["input_digest"] == old_digest
            approve(page).check()
            if change == "file":
                page.evaluate("window.__mexcReplacement = btoa('SYNTHETIC-REPLACED-ORIGINAL-BYTES')")
            else:
                fixture.candidate_revision += 1
            check(page)
            new_digest = fixture.last_rows[0]["input_digest"]
            assert new_digest != old_digest and fixture.last_rows[0]["decision_stale"]
            expect(block).to_contain_text("Zeile 2: Ungueltig")
            expect(block).to_contain_text("Zuordnung veraltet")
            expect(choice).to_be_enabled()
            expect(reason).to_be_enabled()
            expect(approve(page)).not_to_be_checked()
            expect(approve(page)).to_be_disabled()
            renew = block.get_by_role("button", name="Zuordnung erneut bestaetigen, Zeile 2 fuer synthetic.xlsx", exact=True)
            expect(renew).to_be_enabled()
            expect(renew.locator("svg")).to_have_count(1)
            if change == "file":
                assert fixture.posts("preview")[-1]["content_base64"] != original_payload["content_base64"]
            else:
                assert fixture.posts("preview")[-1]["content_base64"] == original_payload["content_base64"]
                expect(choice.locator('option[value="raw:synthetic-raw-A"]')).to_contain_text("revision-1")
            reason.fill("Begruendung geprueft; Belegstand noch nicht neu bestaetigt.")
            for _ in range(2):
                check(page)
                assert fixture.posts("preview")[-1]["mexc"]["decisions"]["2"]["input_digest"] == old_digest
                assert fixture.last_rows[0]["decision_stale"]
                expect(approve(page)).to_be_disabled()
            page.set_viewport_size({"width": 390, "height": 900})
            renew.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(output / f"synthetic-stale-{change}-390.png"), animations="disabled")
            renew.focus()
            expect(renew).to_be_focused()
            page.keyboard.press("Enter")
            expect(renew).to_be_disabled()
            expect(block).to_contain_text("Vorschau nicht mehr aktuell")
            expect(choice).to_have_value(target)
            expect(reason).to_have_value("Begruendung geprueft; Belegstand noch nicht neu bestaetigt.")
            expect(approve(page)).to_be_disabled()
            check(page)
            expected = {"action": "link_existing" if change == "file" else "separate",
                        "reason": reason.input_value(), "input_digest": new_digest}
            if change == "file":
                expected["target_raw_object_id"] = "synthetic-raw-A"
            assert fixture.posts("preview")[-1]["mexc"]["decisions"]["2"] == expected
            assert not fixture.last_rows[0]["decision_stale"]
            expect(renew).to_have_count(0)
            expect(approve(page)).to_be_enabled()
            expect(approve(page)).not_to_be_checked()
            approve(page).check()
            area(page).get_by_role("button", name="1 Datei(en) importieren", exact=True).click()
            expect(file_row(page).locator(".statusPill")).to_have_text("Importiert")
            assert fixture.posts("execute")[-1]["mexc"]["decisions"]["2"] == expected
            area(page).get_by_role("button", name="Neuer Import", exact=True).click()
            page.evaluate("window.__mexcReplacement = ''")

    def provider_id_requires_link(page, fixture):
        fixture.mode = "linked"
        fixture.same_provider_id = True
        select_files(page)
        configure(page)
        check(page)
        block, choice = decision_fields(page)
        # Die eigene Provider-ID ist nicht im Row-Vertrag: keine lokale Schlussfolgerung.
        expect(choice.locator('option[value="separate"]')).to_be_enabled()
        choice.select_option("separate")
        reason = block.get_by_label("Begruendung Zeile 2 fuer synthetic.xlsx", exact=True)
        reason.fill("Eigenstaendigkeit zur serverseitigen Pruefung vorgelegt.")
        check(page)
        expect(block).to_contain_text("Identische echte Provider-ID")
        expect(block).to_contain_text("Zeile 2: Ungueltig")
        expect(approve(page)).to_be_disabled()
        expect(choice).to_be_enabled()
        expect(reason).to_be_enabled()
        choice.select_option("raw:synthetic-raw-A")
        expect(reason).to_have_value("Eigenstaendigkeit zur serverseitigen Pruefung vorgelegt.")
        check(page)
        expect(block).to_contain_text("Zeile 2: Verknuepft")
        expect(approve(page)).to_be_enabled()
        assert fixture.posts("preview")[-1]["mexc"]["decisions"]["2"]["input_digest"] == fixture.last_rows[0]["input_digest"]
        assert not fixture.posts("execute")

    def mobile(page, fixture):
        fixture.mode = "candidate"
        select_files(page)
        configure(page)
        check(page)
        block, choice = decision_fields(page)
        choice.select_option("raw:synthetic-raw-A")
        reason = block.get_by_label("Begruendung Zeile 2 fuer synthetic.xlsx", exact=True)
        reason.fill("Synthetischer Belegabgleich, keine Steuerfreigabe.")
        for width in (320, 390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            reason.focus()
            page.keyboard.press("End")
            page.keyboard.type(".")
            expect(reason).to_be_focused()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Seitenoverflow {width}"
            outside = area(page).evaluate("""root => [...root.querySelectorAll('button, input:not([hidden]), select, summary')].filter(el => {
                const r = el.getBoundingClientRect();
                return r.width && r.height && (r.left < -1 || r.right > innerWidth + 1);
              }).map(el => el.outerHTML.slice(0, 180))""")
            assert not outside, (width, outside)
            assert reason.evaluate("el => !!el.labels.length && !!document.getElementById(el.getAttribute('aria-describedby'))")
            reason.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f"synthetic-mexc-{width}.png"), animations="disabled")
        previous = block.get_by_role("button", name="Vorherige Zeilenseite", exact=True)
        following = block.get_by_role("button", name="Naechste Zeilenseite", exact=True)
        expect(previous).to_be_disabled()
        following.focus()
        expect(following).to_be_focused()
        page.keyboard.press("Enter")
        expect(block).to_contain_text("Seite 2 von 81")
        expect(previous).to_be_enabled()
        expect(following).to_have_attribute("title", "Naechste Zeilenseite")
        assert not fixture.posts("execute")

    return {"source-missing-config": missing, "timebasis-safe-errors": timezone_errors,
            "explicit-multisheet-selection": explicit_multisheet, "candidate-pager-confirm": candidates,
            "config-reset-manual-regression": resets, "empty-evidence-unsupported": dispositions,
            "sequential-import-revalidation": multi, "invalid-files-disabled": invalid_files, "source-specific-formats": source_formats,
            "approval-import-effect": approval_effect, "source-specific-outcomes": outcome_labels,
            "decision-digest-binding": digest_binding, "provider-id-requires-link": provider_id_requires_link, "mobile-form-accessibility": mobile}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path, default=Path("artifacts/mexc-import-browser"))
    parser.add_argument("--scenario", action="append")
    args = parser.parse_args()
    if args.base_url:
        parsed = urlparse(args.base_url)
        try:
            local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            local = False
        if not local or parsed.scheme != "http" or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
            parser.error("Nur lokale HTTP-Frontend-URL ohne Pfad, Query oder Zugangsdaten erlaubt.")
        args.base_url = args.base_url.rstrip("/")
    args.output.mkdir(parents=True, exist_ok=True)
    checks = scenarios(args.output)
    if args.scenario and set(args.scenario) - checks.keys():
        parser.error("Unbekannte Szenarien.")
    results = {}
    expect.set_options(timeout=7000)
    with ExitStack() as stack:
        if not args.base_url:
            root = Path(__file__).resolve().parents[1] / "frontend/dist"
            if not (root / "index.html").is_file():
                parser.error("Zuerst npm run build im Frontend ausfuehren.")

            class QuietHandler(SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    path = urlparse(self.path).path
                    if path == "/api" or path.startswith("/api/"):
                        self.send_error(451, "API darf nur vom Browser-Mock beantwortet werden.")
                        return
                    super().do_GET()

            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            stack.callback(server.server_close)
            stack.callback(worker.join)
            stack.callback(server.shutdown)
            args.base_url = f"http://127.0.0.1:{server.server_port}"
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
        for name, test in checks.items():
            if args.scenario and name not in args.scenario:
                continue
            fixture = Fixture()
            external, errors = [], []
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
            context.set_default_timeout(7000)
            origin = urlparse(args.base_url)

            def guard(route):
                parsed = urlparse(route.request.url)
                if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                    external.append(route.request.url)
                    route.abort("blockedbyclient")
                elif parsed.path == "/api" or parsed.path.startswith("/api/"):
                    try:
                        fixture.handle(route)
                    except Exception as error:
                        fixture.unexpected.append({"path": parsed.path, "fixture_contract_error": str(error)})
                        route.fulfill(status=500, content_type="application/json", body='{"status":"error"}')
                elif route.request.method != "GET":
                    fixture.unexpected.append({"method": route.request.method, "path": parsed.path})
                    route.abort("blockedbyclient")
                else:
                    route.continue_()

            context.route("**/*", guard)
            context.route_web_socket("**", lambda socket: socket.close())
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(args.base_url + "/#import", wait_until="networkidle")
                expect(area(page)).to_be_visible()
                area(page).get_by_label("Importquelle", exact=True).select_option("mexc")
                test(page, fixture)
                assert not external, external
                assert not errors, errors
                assert not fixture.unexpected, fixture.unexpected
                results[name] = {"passed": True}
            except Exception as error:
                results[name] = {"passed": False, "error": str(error) or type(error).__name__}
                page.screenshot(path=str(args.output / f"synthetic-failure-{name}.png"), animations="disabled")
            finally:
                results[name].update(calls=fixture.calls, unexpected_api=fixture.unexpected, external_requests=external, javascript_errors=errors)
                context.close()
            print(f"{name}: {'bestanden' if results[name]['passed'] else results[name]['error']}", flush=True)
    result = {"passed": all(row["passed"] for row in results.values()), "synthetic_only": True, "all_api_intercepted": True,
              "actual_backend_tested": False, "complete_suite": not args.scenario, "scenarios": results,
              "limitations": ["Keine Backend-, XLSX-, Persistenz- oder Steuerpruefung.", "Chromium, kein echter Touch-/Screenreader-Test.",
                              "Downloadattribute und Linkziele mit abgefangenen Fetches; native Downloadoberflaeche nicht getestet."]}
    (args.output / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
