# Abnahmeprotokoll API-Einrichtung und Abrufsteuerung

Datum: 26.10.2026. Ausgangscommit `4800837`, Branch `feat/bedienkonzept-20261026`.
Unveröffentlichte Weiterentwicklung, keine fachliche oder produktive Freigabe.

Die [Umsetzungsbeschreibung](../../API_EINRICHTUNG_ABRUFLIMITS_2026-10-26.md)
enthält Datenformat, Request-Inventar, Quellen, Migrationsverhalten und Grenzen.
Alle Testidentitäten und Screenshots sind synthetisch. Kein echter API-Key wurde
eingegeben, kein Anbieter belastet und keine steuerliche Review-Entscheidung gespeichert.

## Abschlussergebnis

- **1.381 Tests bestanden, 4 übersprungen**, null Fehler; alle 1.385 aktuell
  eingesammelten Tests aus 126 Dateien genau einmal in den finalen Teilprotokollen.
- Frontend-Build, Ruff, URL-/Präzisionschecks unter UTC und Europe/Berlin sowie
  OpenAPI-/Endpointreferenzprüfung erfolgreich. Bestehende Chunkwarnung bleibt.
- Vollständiger synthetischer UX-Browserlauf einschließlich A01–A23, R1 und der
  neuen Admin-Fälle erfolgreich; keine JavaScript-Fehler oder externen Requests.
- Echte synthetische LAN-Vorschau in 390/768/1280/1440 Pixel lesend geprüft;
  Statusabfrage HTTP 200, gesperrte Limitänderung HTTP 403, Datenbankhash unverändert.
- Gitleaks: neun unveränderte, einzeln geprüfte Nicht-Secrets; kein ungeprüfter Fund.
  Bekannte private Kennungen: null Treffer im Arbeitsbaum und lokalen Git-Objekten.
- Keine produktive Änderung, kein Push und keine vollständige Produktfreigabe.

## Anforderung und Implementierung

| Bereich | Dateien | Nachweis |
| --- | --- | --- |
| Installationsdiagnose | `domain/installation.py`, `contracts/installation.py`, `frontend/src/InstallationSettings.tsx` | Rechte-/Neustarttests; Demo-/Vault-Browserfälle |
| Mehrere Konten, Secrets, explizite Jobs | `contracts/connections.py`, `domain/connections.py`, `api/connections.py`, `domain/admin.py` | Kontentrennung, AES-GCM, frischer Python-Prozess, Abbruch und Doppelstart |
| Profile und persistente Koordination | `contracts/request_limits.py`, `domain/request_limits.py`, `api/request_limits.py` | kontrollierte Uhr, echte Prozesse, gemeinsame rollierende Budgets |
| Durchsetzung vor HTTP-Start | `domain/external_http.py`, bestehende Connectoren und lesende CLI-Adapter | Retry, Signierung nach Wartezeit, Redirect, Headerpause und AST-Pfadtest |
| Einrichtung und Telemetrie | `frontend/src/ConnectionSettings.tsx`, `connection-settings.css`, `main.tsx` | echte Oberfläche mit Mock-API in drei Zuständen, vier Breiten |
| Herstellerreferenzen | `configs/provider_request_references.json` | offizielle Quellen mit Prüfdatum, keine automatische Tarifbestätigung |
| Bestehende Fachlogik | unveränderte Steuer-/FIFO-/Gate-Regeln | vollständige Backend-Suite und erneute UX-Regressionen |

## Testmatrix des ergänzenden Auftrags

Die Nummern entsprechen den 14 geforderten Tests, nicht der früheren A01–A24-Matrix.
„Bestanden“ bezeichnet den konkret angegebenen Testumfang, keine reale Anbieterzusage.

| Nr. | Ergebnis | Tatsächlicher Nachweis / Grenze |
| --- | --- | --- |
| 1 | Bestanden, isoliert | `test_settings_get_is_readonly_and_configuration_survives_application_restart`; zwei verschlüsselte Konten werden zusätzlich durch einen frischen Python-Prozess entschlüsselt |
| 2 | Bestanden | Fehlender/falscher Vault, Verschlüsselungsfehler, Dateirechte und geschütztes Profil; kein Klartextfallback. UI-Fälle Demo und kein Vault |
| 3 | Bestanden | Zwei Binance-Konten mit separaten Secrets/Snapshots; `test_two_accounts_share_project_budget_and_separate_identity`; zwingende Anbieter-/IP-Gruppen |
| 4 | Bestanden | `test_two_per_second_and_sixty_per_minute_rolling_boundaries`; zusätzliche Prüfung tatsächlicher Dispatchzeiten nach langsamem Signierer |
| 5 | Bestanden, lokale Kosten | Unterschiedliche Endpunktgewichte und RPC-Batches; atomar gemeinsames Kostenbudget. Keine unbestätigte CU-/Creditumrechnung |
| 6 | Bestanden, ein Host | Echte Prozesse teilen Fenster, Kosten und Parallelität; Jobclaims konkurrieren über Dateisperren. Mehrhostbetrieb ausdrücklich nicht zugesagt |
| 7 | Bestanden, Mock | Verbindungstest, Bestandsabruf, Redirect, Retry und Folgeseiten nutzen gemeinsame HTTP-Schicht; AST-Test verhindert direkte Clientkonstruktion im Anwendungspaket |
| 8 | Bestanden | Echte Prozesskonkurrenz, langsame/aktive Leases und Exceptions; Slot bleibt bis einschließlich Response-Body belegt |
| 9 | Bestanden | Kontrollierte Retry-After-Antworten, Jitter, Versuchslimit, monotone Gesamtdeadline; Pause vor Leasefreigabe gespeichert |
| 10 | Bestanden | 401/403 werden nicht blind wiederholt; sichere feste Fehlercodes und konkrete UI-Hinweise |
| 11 | Bestanden, defensiver Umfang | Abbruch vor Folgeanfragen, späte Ergebnisse verworfen; Neustart/Crash erhält belegte Slots; Defekt fail closed; Profilwechsel ohne Budgetreset. Kein automatischer Wiederanlauf und kein Mehrhostnachweis |
| 12 | Bestanden im Prüfbereich | Maskierte Felder, leere Felder behalten Secrets, eigene Löschaktion, redigierte Antworten/Fehler/Logs, Cross-Origin-Redirect gesperrt; Repository- und Privacy-Scan separat protokolliert |
| 13 | Teilweise | Backendstatus klar getrennt. Lokale Queue, aktive Leases, Anbieterpause und nächster möglicher Start sind pro Budgetgruppe sichtbar. Jobs haben queued/running/succeeded/failed/cancelled; noch kein eigener persistierter Jobzustand „pausiert nach Anbieterlimit“ und keine garantiert exakte Request-Queue pro Verbindung |
| 14 | Bestanden | Drei vollständig gemockte UI-Zustände; echte Port-18014-Vorschau mit blockierten externen Sockets und API-Schreibwegen, lesender LAN-Browsernachweis |

## Nicht als fertig ausgegeben

- Kein aktivierter periodischer Sync-Zeitplan. Das Feld zeigt deaktiviert, nicht
  eine wirksame Automatisierung. Tages-/Monatsabrechnungsbudgets fehlen ebenfalls.
- Die lokalen Fenster ersetzen keine anders definierten Herstellerfenster.
  Unbekannte Anbietergrenzen bleiben unbekannt; konservative lokale Grenzen gelten.
- Kein neuer vollständiger Historienimport für jede neue Kontoverbindung und keine
  automatische Aktivierung einer steuerlichen Quelle.
- Nur hostlokale Koordination auf geeignetem persistentem Volume; kein verteiltes
  Mehrhostsystem und kein neuer paralleler DuckDB-Schreibbetrieb.
- Nach Workercrash ist eine geprüfte administrative Wiederherstellung erforderlich.
  Keine automatische Leasefreigabe durch Zeitablauf oder Löschen des Koordinators.
- Kein realer Anbieter-/Tarif-/Berechtigungstest und keine produktive Secret-Persistenz-
  freigabe aus der absichtlich gesperrten Vorschau.
- Die bestehende große Vite-Hauptdatei bleibt eine Buildwarnung, kein hier behobener Fehler.

## Browsernachweise

- `admin-mock/result.json`: Demo ohne Writes, schreibfähige Mockinstallation mit
  neun ausdrücklich ausgelösten Testaktionen, Installation ohne Vault ohne Writes.
  Keine JavaScript-Fehler. Die Mockaktionen sind kein Nachweis der Verschlüsselung.
- `admin-mock/*-connections-{390,1440}.png`: getrennte gleichartige Konten und Aktionen.
- `admin-mock/*-limits-{390,768,1280,1440}.png`: Profile, Herstellerdeklarationen,
  lokale Messwerte und tatsächliche Anbieterheader, jeweils eigener Viewport.
- `lan/verification.json`, `lan/admin-*.png`: echte FastAPI-Antworten der synthetischen
  Vorschau, ausschließlich GET, vier Viewports, kein horizontaler Seitenoverflow.
- `regression/workspace-verification.json`: A01–A23 im jeweiligen synthetischen
  Browserumfang; A24 separat durch die vollständige Backend-Suite.
- `regression/review-panel-verification.json`: R1 mit kontrollierter Verzögerung,
  Fehler/Wiederholen, fehlender Aufgabe und Kontextwechsel.
- `regression/review-backend-verification.json`: F1–F3 gegen echtes isoliertes Backend,
  einschließlich disponibler Testdatenkorrektur, ohne fachliche Review-Freigabe.

Die mobile Admin-Aufnahme wartet auf das Ende des Navigationsübergangs. Ein zuvor
zu früh erstellter Animations-Screenshot wurde ersetzt; kein bestätigter Produktfehler.
Ein erster LAN-Test wurde vor Startbereitschaft ausgeführt und mit ECONNREFUSED
abgebrochen; nach erfolgreichem Bereitschaftscheck wurde derselbe Ablauf wiederholt.

Zwei abschließende ungeteilte Backendläufe mit vier beziehungsweise acht Workern
endeten mit Signal/Exitcode 143, ohne zuvor einen fehlgeschlagenen Test zu melden.
Die Signalursache ist nicht belegt; dies wird nicht als Produkterfolg gewertet.
Deshalb wurde die identische gesamte Sammlung nach sortierten Testdateien in vier
disjunkte Teile (`dateien[teil::4]`) geteilt. Die vollständigen Teilprotokolle und
die geprüfte Gesamtzahl werden beigefügt. Ein älterer erfolgreicher Vollsuite-Lauf
vor den letzten Regressionstests ersetzt diesen finalen Nachweis nicht.

## Reproduktion

Im Repository mit installierten Entwicklungsabhängigkeiten:

```sh
env PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/steuerreport-limits-pycache STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 pytest -q -n 4 --junitxml=artifacts/api-setup-20261026/backend-junit.xml
ruff check src tests scripts
npm --prefix frontend run build
env TZ=UTC node scripts/check_workspace_state_v2.cjs
env TZ=Europe/Berlin node scripts/check_workspace_state_v2.cjs
env PYTHONPATH=src python3 scripts/export_openapi_v2.py --check
env PYTHONPATH=src python3 scripts/generate_api_endpoint_reference_v2.py --check
python3 scripts/check_ux_browser_v2.py --browser-executable /pfad/zu/chromium --output artifacts/api-setup-20261026/ux
python3 scripts/check_admin_browser_v2.py --browser-executable /pfad/zu/chromium --output artifacts/api-setup-20261026/ux/admin
python3 scripts/check_admin_preview_browser_v2.py --base-url http://192.168.2.122:18014 --browser-executable /pfad/zu/chromium --output artifacts/api-setup-20261026/lan
```

Auf diesem Host ergänzen `/tmp/steuerreport-release-tools-20261025` den
Pythonpfad für pytest-xdist und `/tmp/steuerreport-browser-tools` für Playwright.
`PYTHONPYCACHEPREFIX` isoliert den Cache vom gemeinsam eingebundenen Checkout.
`test-results.json` enthält die tatsächlich ausgeführten Ergebnisse;
`backend-part-1.xml` bis `backend-part-4.xml` die vollständigen finalen Einzelfälle.
Die verwendete Aufteilung lässt sich mit folgendem Befehl reproduzieren
(`0` durch `1`, `2`, `3` für die weiteren Teile ersetzen):

```sh
env PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/steuerreport-limits-pycache STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python3 -c 'from pathlib import Path; import subprocess,sys; part=int(sys.argv[1]); files=sorted(str(p) for p in Path("tests").rglob("test_*.py")); sys.exit(subprocess.call([sys.executable,"-m","pytest","-q","-n","8",f"--junitxml=artifacts/api-setup-20261026/backend-part-{part+1}.xml",*files[part::4]]))' 0
```

`manifest.json` bindet
die beigefügten generierten Nachweise mit SHA256.

## Vorschau und Produktion

Vorschau: <http://192.168.2.122:18014/#admin>. Sie verwendet ein neues,
disponibles Datenverzeichnis außerhalb des Repositorys. Vorhandene Vorschau-
Datenbanken bleiben erhalten. Produktiver Container auf Port 18010 unverändert;
kein Push, Tag, Draft Release oder Containerwechsel in diesem Auftrag.

Auch mit verschlüsselten Secrets ersetzt diese Anwendung keine globale
Benutzerauthentifizierung. Produktiv nur im vertrauenswürdigen LAN/VPN oder
hinter angemessenem TLS-/Authentifizierungszugang betreiben.
