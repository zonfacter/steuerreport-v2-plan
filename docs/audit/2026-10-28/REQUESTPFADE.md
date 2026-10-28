# Requestpfade Und Effekte

Basis: `438cbd3`, 28.10.2026. Statische Verfolgung der Laufzeitpfade plus
gezielte synthetische Services-Tests. Keine echte Providerkommunikation;
kein allgemeines Zertifikat fuer jedes Skript, jeden Fehlerfall oder jeden
spaeteren dynamisch geladenen Connector.

## Gemeinsamer Transport

`domain/external_http.py:managed_client` baut `BudgetHttpClient` mit
`LimitedTransport`. `handle_request` bestimmt Provider/Endpoint/Kosten und
reserviert `RequestLimiter.acquire`; Versand erfolgt nach erneuter
Dispatchpruefung. Signierung erfolgt nach der Wartezeit und pro Retry erneut.
Retry, Folgeseite, Metadatenabfrage und Redirect sind jeweils eigene Starts.
`outbound_scope` traegt Connection-ID, zusaetzliche Gruppen, Abbruch und
Deadline, ersetzt aber nicht die obligatorischen Provider-/IP-Gruppen.

`request_limits.py` persistiert die hostlokale Koordination mit Dateisperren.
Auch getrennte Connection-IDs erhoehen keine Providerquote. Die lokalen
Operatorbudgets sind keine verifizierten Herstellerraten; unbekannte
Gewichte/Credits werden nicht als bekannte Planquoten ausgegeben.
Keine Aussage ueber eine gemeinsame Koordination mehrerer Hosts.

## Pfadmatrix

Alle Dateinamen beziehen sich auf `src/steuerreport_v2`.

| Eingang / Zweck | Servicekette bis Transport | Beobachteter Umfang |
| --- | --- | --- |
| Manuelles Speichern neuer Connection | `api/connections.py` -> `ConnectionService.create/update` -> Vault/DB | Kein Providerrequest |
| Manueller Test / Bestandssync | `ConnectionService.start/_run` -> `outbound_scope` -> `CexBalanceService.test_connection/fetch` -> signierter `_get_json` -> `managed_client` | Binance, Bitget, Pionex und Coinbase; getrennte Credentials, gemeinsame Budgets |
| Balance-Pagination | Binance Earn-Seiten und Coinbase Account-Cursor in `cex_balances.py` -> jeder `_..._get` -> `_get_json` | Nicht ein Start fuer die ganze Schleife; im eigenen Test zwei Earn-Seiten enthalten |
| Historienjob | `api/history.py` -> `HistoryService._run` -> `outbound_scope` -> `_collector` -> `CexHistoryCollector.fetch_page` | Quell-/Credential-/RPC-Bindung wird geprueft; Cursor/Symbol/Zeitfenster keine neue Budgetidentitaet |
| CEX-Folgeseiten / Retry / Metadaten | `history_cex.py:_HistoryBalanceService._get_json`, `_markets`, `_pionex_get` -> vorhandene CEX-Signierer -> `managed_client` | Signierer-Checkpoint auch beim zentralen Retry; Binance/Bitget-Metadaten sind weitere Requests |
| Solana-Historie und Inventar | `history_solana.py` erbt `PortfolioService`; `history_inventory.py` nutzt dessen RPC-Collector -> `_solana_rpc` in `portfolio.py:1910` -> `managed_client(provider=...)` | RPC-Pinning, Signaturen, Owner-Konten und Details laufen ueber dieselbe Transportgrenze; Inventar-/Quotenansicht selbst ist kein Datenabruf |
| Legacy-/manueller Portfolio-Refresh | `api/app.py` POST reconciliation/refresh bzw. workspace sync -> `PortfolioService.refresh_reconciliation_snapshots` -> `CexBalanceService` bzw. RPC/Solscan | Globale Legacy-Providerroute ist nicht neue Multiaccount-Historienroute; Workspace-Connection hat `can_sync=False`, eigene Connection-Syncroute verwenden |
| Binance Earn-/Withdraw-API-Import | `app.py` sources/binance-Routen -> `domain/binance_earn.py` signierte Requestschleifen -> `request_signer` + `managed_client` bei Zeile 1257 | Bestehende spezielle Importer, kein Ersatz fuer generischen Vollhistorienbeweis |
| Bitget Withdraw-API-Import | `app.py` sources/bitget-Routen -> `domain/bitget.py:_...get` -> `request_signer` + `managed_client` bei Zeile 317 | Gesonderter Legacy-Importweg |
| Jupiter Token-/Metadaten-Enrichment | `JupiterTokenService.search` bei Zeile 76 -> `managed_client`; `refresh_metadata_cache` ruft search | GET-Suche kann extern lesen; POST-Cache-Refresh kann zudem lokal schreiben |
| Solscan und Wallet-Provenienz | `portfolio.py:2216/2270` -> `managed_urlopen`; `solscan_preflight.py:328`, `tax_wallet_fifo.py:3506/8211/8281` -> `managed_client`; uebergebene Detailclients kommen aus diesen Clientgrenzen | Historien-/Detail-/Nachladepfade, keine Freistellung von Limits durch Bezeichnung als Review |
| Weitere Enrichment-/Preisleser | `historical_prices.py`, `external_price_backfill.py`, `as_of_price_gate.py`, `bmf_event_price_remediation.py`, `bitget_strategy_reconstruction.py`, `blockpit_solana_preflight.py`, `divorce_service_routes.py` importieren managed-Wrapper | Statisch bis zur Transportgrenze verfolgt; fachliche Bewertung bleibt B/C/F, hier kein Preisregeltest |
| V1-Relay / Credentials-Takeover | `admin.py` -> `managed_post`; Portfolio-Relay -> managed-Wrapper; `managed_urlopen` erkennt private `/api/v1/`-Relays | Interner Relay selbst absichtlich ohne externes Lease und ohne Redirect; nachgelagerter Server muss Providerabruf begrenzen. Keine unabhaengige Pruefung eines fremden V1-Servers |
| Datei-/CSV-/Raw-Import | ImportAssistant/CsvRawImporter/FileRawImporter -> Raw/Normalizer/Pipeline | Kein externer Request allein wegen Dateiimport |

Eine direkte `httpx.Client`-Verwendung in `managed_urlopen` ist die explizite
private Relay-Ausnahme, kein Beleg fuer unlimitierten externen Providerverkehr.
RPC-/AI-Payloads unter privatem `/api/v1/` werden nicht als normales internes
Relay eingestuft. Bestehende Tests in `test_external_http.py` pruefen diese
Unterscheidung, Redirectschutz und Retrybudget. AI selbst wird nicht aufgerufen.

## GET Ist Nicht Gleich Effektlos

- `GET /api/v1/admin/connections`, `/jobs`, `/{id}/snapshots` sind lokale Reads.
  Neue Jobs nur ueber bestaetigte `POST /{id}/test` bzw. `/sync`.
- `GET /api/v1/workspace/sources/{ref}/history` liest View/Capability;
  `GET .../jobs/{id}` und `/audit.json` lesen Zustand/Belege. POST jobs/resume
  kann Requests starten; POST import uebernimmt eine gebundene Vorschau lokal;
  POST repreview nutzt gespeicherte Originale zur Neuberechnung.
- `POST /api/v1/activity/query` ist eine lokale lesende Abfrage. POST allein
  bedeutet hier keinen Import oder Provideraufruf.
- `GET /api/v1/sources/jupiter/tokens/search?query=...` startet bei vorhandenem
  Key tatsaechlich eine externe Suche. Ohne Key wird keine Anfrage gestartet.
  Das ist bewusst NICHT als generisch effektloser GET dokumentiert.
- `GET /api/v1/portfolio/snapshot` ruft den gecachten lokalen Snapshot auf;
  reconciliation-Refresh ist gesonderter POST. Daraus folgt keine Zusage,
  dass alle anderen historischen GET-Review-/API-preview-Endpunkte lokal sind.
- `AdminService.save_cex_credentials` speichert und diagnostiziert lokal;
  eine erfolgreiche Credential-Konfiguration ist kein externer Login-Test.

Diese Aussagen sind aus Dekoratoren, Defaults und tatsaechlichen Aufrufen
gelesen, nicht aus Routennamen abgeleitet. Der eigene Test vergleicht lokale
GET-/POST-Reads mit einem wirklich externen, aber simulierten Jupiter-GET.
Andere Preview-/Review-Endpunkte koennen Requests oder Artefaktschreibeffekte
besitzen; eine komplette API-Effekt-/Auth-Abnahme bleibt ausdruecklich offen.
