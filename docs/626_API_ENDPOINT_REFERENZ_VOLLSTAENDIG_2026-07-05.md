# Vollstaendige API Endpoint Referenz

Stand: 2026-11-15

Diese Referenz wird mit `scripts/generate_api_endpoint_reference_v2.py` direkt aus `src/steuerreport_v2/api/app.py` und seinen statisch eingebundenen Routermodulen erzeugt. Sie inventarisiert deren statisch deklarierte FastAPI-Routen. Fachliche Request-/Response- und Sicherheitsdetails stehen in `docs/API_CONTRACTS_V2.md` und zur Laufzeit in `/docs` bzw. `/openapi.json`.

## Nutzung

- `GET` ist read-only, sofern der Fachcontract nicht ausdruecklich einen externen   Live-Abruf beschreibt.
- Schreibende Methoden koennen Decisions, Imports, Preise, Jobs oder lokale   Belegartefakte erzeugen. Vor produktiver Nutzung den Fachcontract pruefen.
- Echte Steuerdaten und Secrets gehoeren nicht in Git, Dokumentation oder   Beispielrequests.

## Statistik

- Endpunkte gesamt: `481`
- GET: `334`
- POST: `127`
- PUT: `10`
- PATCH: `1`
- DELETE: `9`

## Health und API Meta

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/health` | Health | read-only | `app.py:963` `health` |
| `GET` | `/api/v1/meta/capabilities` | Api capabilities | read-only | `app.py:967` `api_capabilities` |
| `GET` | `/health` | Health | read-only | `app.py:963` `health` |

## Administration und Secrets

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/admin/cex-credentials` | Save cex credentials | kann Daten oder Artefakte schreiben | `app.py:1276` `save_cex_credentials` |
| `GET` | `/api/v1/admin/cex-credentials/v1-takeover` | V1 cex credentials takeover report | read-only | `app.py:1448` `v1_cex_credentials_takeover_report` |
| `POST` | `/api/v1/admin/cex-credentials/v1-takeover` | Import v1 cex credentials | kann Daten oder Artefakte schreiben | `app.py:1454` `import_v1_cex_credentials` |
| `GET` | `/api/v1/admin/connections` | Connections | read-only | `connections.py:52` `connections` |
| `POST` | `/api/v1/admin/connections` | Create | kann Daten oder Artefakte schreiben | `connections.py:56` `create` |
| `GET` | `/api/v1/admin/connections/jobs` | Jobs | read-only | `connections.py:60` `jobs` |
| `POST` | `/api/v1/admin/connections/jobs/{job_id}/cancel` | Cancel | kann Daten oder Artefakte schreiben | `connections.py:64` `cancel` |
| `PUT` | `/api/v1/admin/connections/{connection_id}` | Update | schreibt | `connections.py:68` `update` |
| `DELETE` | `/api/v1/admin/connections/{connection_id}/credentials` | Delete credentials | loescht | `connections.py:72` `delete_credentials` |
| `GET` | `/api/v1/admin/connections/{connection_id}/snapshots` | Snapshots | read-only | `connections.py:76` `snapshots` |
| `POST` | `/api/v1/admin/connections/{connection_id}/sync` | Sync | kann Daten oder Artefakte schreiben | `connections.py:84` `sync` |
| `POST` | `/api/v1/admin/connections/{connection_id}/test` | Test | kann Daten oder Artefakte schreiben | `connections.py:80` `test` |
| `GET` | `/api/v1/admin/database` | Database status | read-only | `app.py:977` `database_status` |
| `GET` | `/api/v1/admin/installation` | Read installation | read-only | `app.py:854` `read_installation` |
| `PUT` | `/api/v1/admin/installation` | Write installation | schreibt | `app.py:861` `write_installation` |
| `GET` | `/api/v1/admin/installation/configs/{filename}` | Read installation config | read-only | `app.py:884` `read_installation_config` |
| `PUT` | `/api/v1/admin/installation/configs/{filename}` | Write installation config | schreibt | `app.py:891` `write_installation_config` |
| `DELETE` | `/api/v1/admin/installation/providers/{provider}` | Delete installation provider | loescht | `app.py:876` `delete_installation_provider` |
| `PUT` | `/api/v1/admin/installation/providers/{provider}` | Write installation provider | schreibt | `app.py:868` `write_installation_provider` |
| `POST` | `/api/v1/admin/jupiter/api-key` | Save jupiter api key | kann Daten oder Artefakte schreiben | `app.py:1307` `save_jupiter_api_key` |
| `GET` | `/api/v1/admin/provider-references` | References | read-only | `request_limits.py:133` `references` |
| `GET` | `/api/v1/admin/request-limits` | Read limits | read-only | `request_limits.py:69` `read_limits` |
| `PUT` | `/api/v1/admin/request-limits` | Write limits | schreibt | `request_limits.py:73` `write_limits` |
| `GET` | `/api/v1/admin/request-limits/endpoints` | Endpoints | read-only | `request_limits.py:88` `endpoints` |
| `GET` | `/api/v1/admin/request-limits/presets` | Presets | read-only | `request_limits.py:95` `presets` |
| `POST` | `/api/v1/admin/request-limits/presets/solana_public_free` | Apply preset | kann Daten oder Artefakte schreiben | `request_limits.py:123` `apply_preset` |
| `GET` | `/api/v1/admin/request-limits/status` | Status | read-only | `request_limits.py:82` `status` |
| `GET` | `/api/v1/admin/settings` | List admin settings | read-only | `app.py:1238` `list_admin_settings` |
| `PATCH` | `/api/v1/admin/settings` | Update admin setting | schreibt | `app.py:1242` `update_admin_setting` |
| `DELETE` | `/api/v1/admin/settings/{key}` | Delete admin setting | loescht | `app.py:1258` `delete_admin_setting` |
| `GET` | `/api/v1/admin/status` | Admin status | read-only | `app.py:981` `admin_status` |

## Cockpit und Product Readiness

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/cockpit/summary` | Cockpit summary | read-only | `app.py:985` `cockpit_summary` |
| `GET` | `/api/v1/product/readiness` | Product readiness | read-only | `app.py:993` `product_readiness` |

## Contracts

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/contracts/event-types` | Event types | read-only | `app.py:1487` `event_types` |

## Import und Preflight

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/import/assistant/execute` | Execute import assistant | kann Daten oder Artefakte schreiben | `app.py:2077` `execute_import_assistant` |
| `POST` | `/api/v1/import/assistant/preview` | Preview import assistant | kann Daten oder Artefakte schreiben | `app.py:2046` `preview_import_assistant` |
| `GET` | `/api/v1/import/batches` | List import batches | read-only | `app.py:1684` `list_import_batches` |
| `POST` | `/api/v1/import/batches` | Create import batch | kann Daten oder Artefakte schreiben | `app.py:1680` `create_import_batch` |
| `DELETE` | `/api/v1/import/batches/{batch_id}` | Delete import batch | loescht | `app.py:1704` `delete_import_batch` |
| `GET` | `/api/v1/import/batches/{batch_id}` | Get import batch | read-only | `app.py:1688` `get_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/normalize` | Normalize import batch | kann Daten oder Artefakte schreiben | `app.py:2104` `normalize_import_batch` |
| `GET` | `/api/v1/import/batches/{batch_id}/original` | Download mexc original | read-only | `app.py:1860` `download_mexc_original` |
| `POST` | `/api/v1/import/batches/{batch_id}/run` | Run import pipeline | kann Daten oder Artefakte schreiben | `app.py:2130` `run_import_pipeline` |
| `GET` | `/api/v1/import/batches/{batch_id}/trace.json` | Download import batch trace | read-only | `app.py:1834` `download_import_batch_trace` |
| `GET` | `/api/v1/import/blockpit-solana/preflight` | Blockpit solana preflight | read-only | `app.py:1541` `blockpit_solana_preflight` |
| `POST` | `/api/v1/import/blockpit-solana/price-probe` | Blockpit solana price probe | kann Daten oder Artefakte schreiben | `app.py:1559` `blockpit_solana_price_probe` |
| `GET` | `/api/v1/import/coverage` | Import coverage | read-only | `app.py:1509` `import_coverage` |
| `POST` | `/api/v1/import/csv/preview` | Preview csv import | kann Daten oder Artefakte schreiben | `app.py:1935` `preview_csv_import` |
| `POST` | `/api/v1/import/csv/raw` | Import csv raw | kann Daten oder Artefakte schreiben | `app.py:1881` `import_csv_raw` |
| `POST` | `/api/v1/import/file/preview` | Preview file import | kann Daten oder Artefakte schreiben | `app.py:1962` `preview_file_import` |
| `POST` | `/api/v1/import/file/raw` | Import file raw | kann Daten oder Artefakte schreiben | `app.py:1990` `import_file_raw` |
| `GET` | `/api/v1/import/jup-perps/preview` | Jup perps preview | read-only | `app.py:1666` `jup_perps_preview` |
| `GET` | `/api/v1/import/parser-preflight` | Parser preflight | read-only | `app.py:1529` `parser_preflight` |
| `GET` | `/api/v1/import/policy/audit` | Import policy audit | read-only | `app.py:1523` `import_policy_audit` |
| `GET` | `/api/v1/import/profiles` | Import profiles | read-only | `app.py:1505` `import_profiles` |
| `GET` | `/api/v1/import/solscan/evidence-trace` | Solscan evidence trace | read-only | `app.py:1616` `solscan_evidence_trace` |
| `GET` | `/api/v1/import/solscan/helium-reward-evidence` | Solscan helium reward evidence | read-only | `app.py:1636` `solscan_helium_reward_evidence` |
| `POST` | `/api/v1/import/solscan/rpc-probe` | Solscan rpc probe | kann Daten oder Artefakte schreiben | `app.py:1600` `solscan_rpc_probe` |
| `GET` | `/api/v1/import/solscan/token-preflight` | Solscan token preflight | read-only | `app.py:1580` `solscan_token_preflight` |
| `GET` | `/api/v1/import/wallet-monthly/preflight` | Wallet monthly preflight | read-only | `app.py:1648` `wallet_monthly_preflight` |

## Raw und Canonical Events

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/events/canonical` | List canonical events | read-only | `app.py:1729` `list_canonical_events` |
| `GET` | `/api/v1/raw/objects` | List raw objects | read-only | `app.py:1722` `list_raw_objects` |

## Ledger

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ledger/balances` | List balance positions | read-only | `app.py:2155` `list_balance_positions` |
| `POST` | `/api/v1/ledger/balances/rebuild` | Rebuild balance ledger | kann Daten oder Artefakte schreiben | `app.py:2151` `rebuild_balance_ledger` |

## Quellen und Connectoren

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/connectors/catalog` | Connector catalog | read-only | `app.py:1001` `connector_catalog` |
| `GET` | `/api/v1/connectors/connections` | Connector connections | read-only | `app.py:1005` `connector_connections` |
| `GET` | `/api/v1/connectors/mobile/documents` | Mobile connector documents | read-only | `app.py:1132` `mobile_connector_documents` |
| `POST` | `/api/v1/connectors/mobile/documents` | Upload mobile connector document | kann Daten oder Artefakte schreiben | `app.py:1073` `upload_mobile_connector_document` |
| `GET` | `/api/v1/connectors/mobile/documents/{document_id}/content` | Mobile connector document content | read-only | `app.py:1143` `mobile_connector_document_content` |
| `POST` | `/api/v1/connectors/mobile/pairings` | Create mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:1009` `create_mobile_connector_pairing` |
| `GET` | `/api/v1/connectors/mobile/session` | Current mobile connector session | read-only | `app.py:1054` `current_mobile_connector_session` |
| `GET` | `/api/v1/connectors/mobile/sessions` | Mobile connector sessions | read-only | `app.py:1047` `mobile_connector_sessions` |
| `POST` | `/api/v1/connectors/mobile/sessions` | Exchange mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:1029` `exchange_mobile_connector_pairing` |
| `DELETE` | `/api/v1/connectors/mobile/sessions/{session_id}` | Revoke mobile connector session | loescht | `app.py:1171` `revoke_mobile_connector_session` |
| `POST` | `/api/v1/connectors/wallet/challenges` | Create wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1193` `create_wallet_ownership_challenge` |
| `POST` | `/api/v1/connectors/wallet/verifications` | Verify wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1214` `verify_wallet_ownership_challenge` |
| `GET` | `/api/v1/sources/binance/asset-dividend-api-preview` | Binance asset dividend api preview | read-only | `app.py:3704` `binance_asset_dividend_api_preview` |
| `POST` | `/api/v1/sources/binance/asset-dividend-api/import` | Binance asset dividend api import | kann Daten oder Artefakte schreiben | `app.py:3832` `binance_asset_dividend_api_import` |
| `GET` | `/api/v1/sources/binance/earn-history-api-preview` | Binance earn history api preview | read-only | `app.py:3640` `binance_earn_history_api_preview` |
| `POST` | `/api/v1/sources/binance/earn-history-api/import` | Binance earn history api import | kann Daten oder Artefakte schreiben | `app.py:3777` `binance_earn_history_api_import` |
| `POST` | `/api/v1/sources/binance/earn-history-harvest/import` | Binance earn history harvest import | kann Daten oder Artefakte schreiben | `app.py:3766` `binance_earn_history_harvest_import` |
| `GET` | `/api/v1/sources/binance/earn-history-preflight` | Binance earn history preflight | read-only | `app.py:3634` `binance_earn_history_preflight` |
| `GET` | `/api/v1/sources/binance/reconciliation/evidence` | Binance reconciliation evidence | read-only | `app.py:3602` `binance_reconciliation_evidence` |
| `GET` | `/api/v1/sources/binance/withdraw-history-api-preview` | Binance withdraw history api preview | read-only | `app.py:3673` `binance_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/binance/withdraw-history-api/import` | Binance withdraw history api import | kann Daten oder Artefakte schreiben | `app.py:3805` `binance_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/bitget/withdraw-history-api-preview` | Bitget withdraw history api preview | read-only | `app.py:3735` `bitget_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/bitget/withdraw-history-api/import` | Bitget withdraw history api import | kann Daten oder Artefakte schreiben | `app.py:3859` `bitget_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/connector-diagnostics` | Sources connector diagnostics | read-only | `app.py:3523` `sources_connector_diagnostics` |
| `GET` | `/api/v1/sources/jupiter/tokens/metadata-cache` | Jupiter token metadata cache | read-only | `app.py:1364` `jupiter_token_metadata_cache` |
| `POST` | `/api/v1/sources/jupiter/tokens/metadata-cache/refresh` | Refresh jupiter token metadata cache | kann Daten oder Artefakte schreiben | `app.py:1382` `refresh_jupiter_token_metadata_cache` |
| `GET` | `/api/v1/sources/jupiter/tokens/risk-review` | Jupiter token risk review | read-only | `app.py:1416` `jupiter_token_risk_review` |
| `GET` | `/api/v1/sources/jupiter/tokens/search` | Jupiter token search | read-only | `app.py:1324` `jupiter_token_search` |
| `GET` | `/api/v1/sources/overview` | Sources overview | read-only | `app.py:3519` `sources_overview` |
| `GET` | `/api/v1/sources/registry/config` | Sources registry config | read-only | `app.py:3529` `sources_registry_config` |
| `POST` | `/api/v1/sources/registry/runs` | Sources registry run | kann Daten oder Artefakte schreiben | `app.py:3539` `sources_registry_run` |
| `GET` | `/api/v1/sources/registry/runs/latest` | Sources registry run latest | read-only | `app.py:3550` `sources_registry_run_latest` |
| `GET` | `/api/v1/sources/{source_id}` | Source detail | read-only | `app.py:3568` `source_detail` |
| `GET` | `/api/v1/sources/{source_id}/reconciliation` | Source reconciliation | read-only | `app.py:3584` `source_reconciliation` |

## Portfolio

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/portfolio/as-of` | Portfolio as of | read-only | `app.py:2665` `portfolio_as_of` |
| `GET` | `/api/v1/portfolio/fiat-deposits/binance` | Portfolio binance fiat deposits | read-only | `app.py:2775` `portfolio_binance_fiat_deposits` |
| `POST` | `/api/v1/portfolio/jup-wallet/import-history` | Portfolio jup wallet import history | kann Daten oder Artefakte schreiben | `app.py:2757` `portfolio_jup_wallet_import_history` |
| `GET` | `/api/v1/portfolio/reconciliation` | Portfolio reconciliation | read-only | `app.py:2717` `portfolio_reconciliation` |
| `POST` | `/api/v1/portfolio/reconciliation/refresh` | Portfolio reconciliation refresh | kann Daten oder Artefakte schreiben | `app.py:2721` `portfolio_reconciliation_refresh` |
| `GET` | `/api/v1/portfolio/separation-report` | Portfolio separation report | read-only | `app.py:2771` `portfolio_separation_report` |
| `GET` | `/api/v1/portfolio/snapshot` | Portfolio snapshot | read-only | `app.py:2653` `portfolio_snapshot` |
| `GET` | `/api/v1/portfolio/sources` | Portfolio sources | read-only | `app.py:2690` `portfolio_sources` |
| `GET` | `/api/v1/portfolio/token-risk` | Portfolio token risk | read-only | `app.py:2694` `portfolio_token_risk` |
| `GET` | `/api/v1/portfolio/valuation-audit` | Portfolio valuation audit | read-only | `app.py:2661` `portfolio_valuation_audit` |
| `GET` | `/api/v1/portfolio/value-history` | Portfolio value history | read-only | `app.py:2669` `portfolio_value_history` |

## Preise

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/prices` | List price points | read-only | `app.py:2174` `list_price_points` |
| `POST` | `/api/v1/prices` | Add price point | kann Daten oder Artefakte schreiben | `app.py:2168` `add_price_point` |
| `GET` | `/api/v1/prices/as-of-gate` | Prices as of gate | read-only | `app.py:2356` `prices_as_of_gate` |
| `POST` | `/api/v1/prices/as-of-gate/backfill` | Prices as of gate backfill | kann Daten oder Artefakte schreiben | `app.py:2372` `prices_as_of_gate_backfill` |
| `POST` | `/api/v1/prices/as-of-gate/token-review-decisions` | Akzeptiert eine mint- und stichtagsgebundene Risikotoken-Bewertung | kann Daten oder Artefakte schreiben | `app.py:2384` `accept_as_of_token_valuation` |
| `GET` | `/api/v1/prices/as-of-gate/token-review-decisions.csv` | Liefert die Stichtags-Risikotoken-Entscheidungen als Beleg-CSV | read-only | `app.py:2395` `as_of_token_valuation_decisions_csv` |
| `POST` | `/api/v1/prices/backfill/current-portfolio` | Backfill current portfolio prices | kann Daten oder Artefakte schreiben | `app.py:2292` `backfill_current_portfolio_prices` |
| `POST` | `/api/v1/prices/backfill/current-portfolio/status` | Liest dokumentiertes Ergebnis oder unklaren Ausgang eines Preisauftrags ohne Anbieterabruf, Preisspeicherung oder Neuberechnung | kann Daten oder Artefakte schreiben | `app.py:2340` `current_portfolio_price_request_status` |
| `POST` | `/api/v1/prices/backfill/external` | Backfill external prices | kann Daten oder Artefakte schreiben | `app.py:2248` `backfill_external_prices` |
| `GET` | `/api/v1/prices/coverage` | Price coverage | read-only | `app.py:2414` `price_coverage` |
| `POST` | `/api/v1/prices/coverage/decisions` | Add price gap decision | kann Daten oder Artefakte schreiben | `app.py:2609` `add_price_gap_decision` |
| `POST` | `/api/v1/prices/historical/manual-previews` | Prueft einen einzelnen manuellen EUR- oder USD/FX-Originalbeleg in einer isolierten Vorschau ohne Anbieterabruf | speichert private Originalbelege und isolierte Vorschauartefakte; keine externe Anfrage oder produktive Preisuebernahme | `historical_prices.py:125` `manual_preview` |
| `GET` | `/api/v1/prices/historical/mappings` | Mappings | read-only | `historical_prices.py:52` `mappings` |
| `PUT` | `/api/v1/prices/historical/mappings` | Save mapping | schreibt | `historical_prices.py:56` `save_mapping` |
| `POST` | `/api/v1/prices/historical/plan` | Plant historische Tagespreise lokal mit Jahresuebersicht und reiner Listenpagination | read-only; keine Anbieterabfrage | `historical_prices.py:48` `plan` |
| `GET` | `/api/v1/prices/historical/previews` | Recent | read-only | `historical_prices.py:60` `recent` |
| `POST` | `/api/v1/prices/historical/previews` | Sammelt bestaetigte Preisbelege und berechnet eine isolierte Vorschau | externer Abruf und private Vorschauartefakte; keine produktive Preisuebernahme | `historical_prices.py:121` `fetch` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}` | Get | read-only | `historical_prices.py:64` `get` |
| `POST` | `/api/v1/prices/historical/previews/{request_id}/apply` | Uebernimmt bestaetigte Preise und Neuberechnung bei unveraenderten Quellen | bestaetigte Preis-/Ledger-Neuberechnung und Auditspur; keine Ereignisumklassifikation | `historical_prices.py:130` `apply` |
| `POST` | `/api/v1/prices/historical/previews/{request_id}/continue` | Ergaenzt eine kumulative Preisvorschau nach erneuter externer Bestaetigung | externer Abruf und private Vorschauartefakte; keine produktive Preisuebernahme | `historical_prices.py:72` `continue_preview` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/evidence/{sha}` | Evidence | read-only | `historical_prices.py:105` `evidence` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/report.json` | Exportiert die vollstaendige Preisvorschau und Belegbindung als JSON | read-only | `historical_prices.py:76` `json_report` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/report.md` | Exportiert die vollstaendige Jahresauswertung als Markdown | read-only | `historical_prices.py:83` `markdown_report` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/report.zip` | Exportiert saemtliche Jahreszeilen und gepruefte Originalbelege als ZIP | read-only | `historical_prices.py:89` `zip_report` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/status` | Liest laufenden oder gespeicherten Preisabrufstatus ohne Anbieterabfrage | read-only | `historical_prices.py:68` `status` |
| `POST` | `/api/v1/prices/import/csv` | Import price csv | kann Daten oder Artefakte schreiben | `app.py:2191` `import_price_csv` |
| `POST` | `/api/v1/prices/import/csv/preview` | Preview price csv | kann Daten oder Artefakte schreiben | `app.py:2182` `preview_price_csv` |
| `POST` | `/api/v1/prices/import/v1-fx-cache` | Blockiert direkte V1-Cache-Uebernahme ohne geprueften Vertrag | HTTP 409; kein Preisimport und keine Pipeline-Neuberechnung | `app.py:2234` `import_v1_fx_cache` |
| `POST` | `/api/v1/prices/import/v1-fx-cache/preview` | Zeigt unverbindliche V1-Cache-Kandidaten ohne Uebernahmefreigabe | Kandidaten ohne Finanzimport; kalter Store kann Schema initialisieren oder migrieren | `app.py:2221` `preview_v1_fx_cache_import` |
| `GET` | `/api/v1/prices/latest` | List latest price points | read-only | `app.py:2178` `list_latest_price_points` |
| `GET` | `/api/v1/prices/quality` | Price quality | read-only | `app.py:2418` `price_quality` |
| `GET` | `/api/v1/prices/quality/binance-normalizer-review` | Price quality binance normalizer review | read-only | `app.py:2548` `price_quality_binance_normalizer_review` |
| `GET` | `/api/v1/prices/quality/closure-candidates` | Price quality closure candidates | read-only | `app.py:2564` `price_quality_closure_candidates` |
| `POST` | `/api/v1/prices/quality/decisions` | Add price quality decision | kann Daten oder Artefakte schreiben | `app.py:2570` `add_price_quality_decision` |
| `GET` | `/api/v1/prices/quality/event-quote-evidence-review` | Price quality event quote evidence review | read-only | `app.py:2556` `price_quality_event_quote_evidence_review` |
| `GET` | `/api/v1/prices/quality/group` | Price quality group | read-only | `app.py:2422` `price_quality_group` |
| `GET` | `/api/v1/prices/quality/manual-review` | Price quality manual review | read-only | `app.py:2438` `price_quality_manual_review` |
| `GET` | `/api/v1/prices/quality/solscan-signature-review` | Price quality solscan signature review | read-only | `app.py:2540` `price_quality_solscan_signature_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-apply` | Apply price quality stablecoin fx anchor prices | kann Daten oder Artefakte schreiben | `app.py:2530` `apply_price_quality_stablecoin_fx_anchor_prices` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions` | Add price quality stablecoin fx anchor preview decision | kann Daten oder Artefakte schreiben | `app.py:2518` `add_price_quality_stablecoin_fx_anchor_preview_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest` | Price quality stablecoin fx anchor preview latest | read-only | `app.py:2508` `price_quality_stablecoin_fx_anchor_preview_latest` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-impact` | Price quality stablecoin fx replacement impact | read-only | `app.py:2466` `price_quality_stablecoin_fx_replacement_impact` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-preview` | Price quality stablecoin fx replacement preview | read-only | `app.py:2454` `price_quality_stablecoin_fx_replacement_preview` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-review` | Price quality stablecoin fx review | read-only | `app.py:2446` `price_quality_stablecoin_fx_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions` | Add price quality stablecoin fx tax impact decision | kann Daten oder Artefakte schreiben | `app.py:2496` `add_price_quality_stablecoin_fx_tax_impact_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-latest` | Price quality stablecoin fx tax impact latest | read-only | `app.py:2482` `price_quality_stablecoin_fx_tax_impact_latest` |
| `GET` | `/api/v1/prices/requirements` | Price requirements | read-only | `app.py:2605` `price_requirements` |
| `DELETE` | `/api/v1/prices/{price_id}` | Delete price point | loescht | `app.py:2634` `delete_price_point` |

## Flows und Transfers

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/flows/net` | Net flows | read-only | `app.py:6843` `net_flows` |
| `POST` | `/api/v1/flows/rebuild` | Rebuild flows | kann Daten oder Artefakte schreiben | `app.py:6839` `rebuild_flows` |
| `GET` | `/api/v1/transfers/candidates` | Transfer candidates | read-only | `app.py:2159` `transfer_candidates` |

## Review

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/review/decision-suggestions` | Review decision suggestions | read-only | `app.py:3916` `review_decision_suggestions` |
| `POST` | `/api/v1/review/decision-suggestions/{suggestion_id}/accept` | Accept review decision suggestion | kann Daten oder Artefakte schreiben | `app.py:3934` `accept_review_decision_suggestion` |
| `GET` | `/api/v1/review/decisions` | List review decisions | read-only | `app.py:3912` `list_review_decisions` |
| `POST` | `/api/v1/review/decisions` | Add review decision | kann Daten oder Artefakte schreiben | `app.py:3904` `add_review_decision` |
| `GET` | `/api/v1/review/evidence-traces` | Review evidence traces | read-only | `app.py:3920` `review_evidence_traces` |
| `POST` | `/api/v1/review/evidence-traces/canonicalize` | Canonicalize review evidence traces | kann Daten oder Artefakte schreiben | `app.py:3924` `canonicalize_review_evidence_traces` |
| `GET` | `/api/v1/review/gates` | Review gates | read-only | `app.py:3886` `review_gates` |
| `GET` | `/api/v1/review/tasks` | Review tasks | read-only | `app.py:3892` `review_tasks` |

## Steuer, BMF und Steuerjahre

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/tax-filing-snapshots` | Liefert das append-only Register hashgebundener Abgabe- und Referenzpakete | read-only | `app.py:9781` `tax_filing_snapshots` |
| `GET` | `/api/v1/tax-filing-snapshots/{snapshot_id}/package.zip` | Liefert ein erneut SHA-256-geprueftes unveraenderliches Abgabepaket | read-only | `app.py:10085` `download_tax_filing_snapshot_package` |
| `POST` | `/api/v1/tax-filing-snapshots/{snapshot_id}/usage-confirmation` | Confirm tax filing snapshot usage | kann Daten oder Artefakte schreiben | `app.py:9829` `confirm_tax_filing_snapshot_usage` |
| `GET` | `/api/v1/tax-methodology/bmf-action-plan` | Tax methodology bmf action plan | read-only | `app.py:5019` `tax_methodology_bmf_action_plan` |
| `GET` | `/api/v1/tax-methodology/bmf-amendment-worklist` | Tax methodology bmf amendment worklist | read-only | `app.py:5208` `tax_methodology_bmf_amendment_worklist` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog` | Tax methodology bmf closure backlog | read-only | `app.py:5036` `tax_methodology_bmf_closure_backlog` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog-snapshot` | Tax methodology bmf closure backlog snapshot | read-only | `app.py:5044` `tax_methodology_bmf_closure_backlog_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-compliance-matrix` | Tax methodology bmf compliance matrix | read-only | `app.py:4997` `tax_methodology_bmf_compliance_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness` | Tax methodology bmf filing readiness | read-only | `app.py:5052` `tax_methodology_bmf_filing_readiness` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness-snapshot` | Tax methodology bmf filing readiness snapshot | read-only | `app.py:5067` `tax_methodology_bmf_filing_readiness_snapshot` |
| `POST` | `/api/v1/tax-methodology/bmf-filing-readiness-snapshot` | Erzeugt ausdruecklich den gebundenen BMF-Methoden-Pruefstand fuer den Umfang 2021-2025 ohne Steuerdatenkorrektur oder finale Freigabe | kann Daten oder Artefakte schreiben | `app.py:5079` `tax_methodology_bmf_filing_readiness_snapshot_refresh` |
| `GET` | `/api/v1/tax-methodology/bmf-finalization-matrix` | Tax methodology bmf finalization matrix | read-only | `app.py:5172` `tax_methodology_bmf_finalization_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-comparison` | Tax methodology bmf prior filing comparison | read-only | `app.py:5196` `tax_methodology_bmf_prior_filing_comparison` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | Tax methodology bmf prior filing declared amounts | read-only | `app.py:5300` `tax_methodology_bmf_prior_filing_declared_amounts` |
| `PUT` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | Tax methodology write bmf prior filing declared amounts | schreibt | `app.py:5308` `tax_methodology_write_bmf_prior_filing_declared_amounts` |
| `GET` | `/api/v1/tax-methodology/bmf-submission-guide` | Tax methodology bmf submission guide | read-only | `app.py:5186` `tax_methodology_bmf_submission_guide` |
| `GET` | `/api/v1/tax-methodology/legal-research/freshness` | Legal research freshness | read-only | `app.py:3564` `legal_research_freshness` |
| `GET` | `/api/v1/tax-methodology/legal-research/sources` | Legal research sources | read-only | `app.py:3554` `legal_research_sources` |
| `GET` | `/api/v1/tax-methodology/summary` | Tax methodology summary | read-only | `app.py:4985` `tax_methodology_summary` |
| `GET` | `/api/v1/tax-methodology/time-precision-audit` | Tax methodology time precision audit | read-only | `app.py:5007` `tax_methodology_time_precision_audit` |
| `GET` | `/api/v1/tax-years/business-reward-inventory-review` | Tax years business reward inventory review | read-only | `app.py:4754` `tax_years_business_reward_inventory_review` |
| `GET` | `/api/v1/tax-years/correction-map` | Tax years correction map | read-only | `app.py:4909` `tax_years_correction_map` |
| `GET` | `/api/v1/tax-years/filing-closure-overview` | Tax years filing closure overview | read-only | `app.py:4730` `tax_years_filing_closure_overview` |
| `GET` | `/api/v1/tax-years/filing-matrix` | Tax years filing matrix | read-only | `app.py:4720` `tax_years_filing_matrix` |
| `GET` | `/api/v1/tax-years/helium-swap-alchemy-audit` | Tax years helium swap alchemy audit | read-only | `app.py:8026` `tax_years_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/helium-swap-context` | Tax years helium swap context | read-only | `app.py:4939` `tax_years_helium_swap_context` |
| `GET` | `/api/v1/tax-years/helium-swap-evidence-review` | Tax years helium swap evidence review | read-only | `app.py:4947` `tax_years_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/payment-overview` | Tax years payment overview | read-only | `app.py:4710` `tax_years_payment_overview` |
| `GET` | `/api/v1/tax-years/reward-bmf-recheck` | Tax years reward bmf recheck | read-only | `app.py:5318` `tax_years_reward_bmf_recheck` |
| `GET` | `/api/v1/tax-years/reward-trading-separation` | Tax years reward trading separation | read-only | `app.py:4742` `tax_years_reward_trading_separation` |
| `GET` | `/api/v1/tax-years/solana-program-income-review` | Tax years solana program income review | read-only | `app.py:4931` `tax_years_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-fx-review` | Tax years solana stablecoin fx review | read-only | `app.py:4977` `tax_years_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-swap-context` | Tax years solana stablecoin swap context | read-only | `app.py:4969` `tax_years_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/stablecoin-fifo-review` | Tax years stablecoin fifo review | read-only | `app.py:4955` `tax_years_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/stablecoin-quote-leg-review` | Tax years stablecoin quote leg review | read-only | `app.py:4961` `tax_years_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/summary` | Tax years summary | read-only | `app.py:4700` `tax_years_summary` |
| `GET` | `/api/v1/tax-years/turnover-audit-summary` | Tax years turnover audit summary | read-only | `app.py:4919` `tax_years_turnover_audit_summary` |
| `GET` | `/api/v1/tax-years/{year}` | Tax year detail | read-only | `app.py:5322` `tax_year_detail` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-correction-review` | Tax year asset fifo correction review | read-only | `app.py:6736` `tax_year_asset_fifo_correction_review` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-drilldown` | Tax year asset fifo drilldown | read-only | `app.py:6712` `tax_year_asset_fifo_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-plausibility` | Tax year asset fifo plausibility | read-only | `app.py:6722` `tax_year_asset_fifo_plausibility` |
| `GET` | `/api/v1/tax-years/{year}/bmf-closure-appendix` | Tax year bmf closure appendix | read-only | `app.py:6794` `tax_year_bmf_closure_appendix` |
| `GET` | `/api/v1/tax-years/{year}/cex-deposit-transfer-evidence` | Tax year cex deposit transfer evidence | read-only | `app.py:5932` `tax_year_cex_deposit_transfer_evidence` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility` | Tax year cex exchange outflow anchor feasibility | read-only | `app.py:6130` `tax_year_cex_exchange_outflow_anchor_feasibility` |
| `POST` | `/api/v1/tax-years/{year}/cex-exchange-outflow-decisions` | Add tax year cex exchange outflow decision | kann Daten oder Artefakte schreiben | `app.py:6150` `add_tax_year_cex_exchange_outflow_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-evidence` | Tax year cex exchange outflow evidence | read-only | `app.py:6110` `tax_year_cex_exchange_outflow_evidence` |
| `POST` | `/api/v1/tax-years/{year}/cex-sender-ownership-decisions` | Add tax year cex sender ownership decision | kann Daten oder Artefakte schreiben | `app.py:5964` `add_tax_year_cex_sender_ownership_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-sender-ownership-latest` | Tax year cex sender ownership latest | read-only | `app.py:5948` `tax_year_cex_sender_ownership_latest` |
| `GET` | `/api/v1/tax-years/{year}/compliance-status` | Tax year compliance status | read-only | `app.py:5894` `tax_year_compliance_status` |
| `GET` | `/api/v1/tax-years/{year}/correction-map` | Tax year correction map | read-only | `app.py:5545` `tax_year_correction_map` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide` | Tax year declaration guide | read-only | `app.py:5342` `tax_year_declaration_guide` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide.html` | Tax year declaration guide html | read-only | `app.py:5364` `tax_year_declaration_guide_html` |
| `GET` | `/api/v1/tax-years/{year}/drivers` | Tax year drivers | read-only | `app.py:6646` `tax_year_drivers` |
| `GET` | `/api/v1/tax-years/{year}/evidence` | Tax year evidence | read-only | `app.py:6762` `tax_year_evidence` |
| `GET` | `/api/v1/tax-years/{year}/evidence.html` | Tax year evidence html | read-only | `app.py:6782` `tax_year_evidence_html` |
| `GET` | `/api/v1/tax-years/{year}/external-inflows` | Tax year external inflows | read-only | `app.py:6800` `tax_year_external_inflows` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report` | Erzeugt bzw. liefert den read-only Einzelpositions-, Ursachen- und Summenabgleich | read-only | `app.py:9862` `tax_filing_audit_report` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.json` | Liefert das unveraenderliche JSON-Auditartefakt | read-only | `app.py:9870` `tax_filing_audit_report_json` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.md` | Liefert das unveraenderliche Markdown-Auditartefakt | read-only | `app.py:9888` `tax_filing_audit_report_markdown` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison` | Vergleicht den eingereichten bzw. archivierten Stand je Einkunftsart mit der aktuellen Berechnung | read-only | `app.py:9846` `tax_filing_snapshot_comparison` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison.html` | Liefert die druckbare Korrekturpruefungsakte statt einer rohen JSON-Ansicht | read-only | `app.py:10012` `tax_filing_snapshot_comparison_html` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshots` | Liefert das hashgebundene Snapshot-Register fuer ein konkretes Steuerjahr | read-only | `app.py:9787` `tax_year_filing_snapshots` |
| `POST` | `/api/v1/tax-years/{year}/filing-snapshots` | Archiviert den aktuellen Paketstand oder bestaetigt eine konkrete Revision als tatsaechlich eingereicht | kann Daten oder Artefakte schreiben | `app.py:9791` `capture_tax_filing_snapshot` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary` | Tax year filing summary | read-only | `app.py:5376` `tax_year_filing_summary` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary.html` | Tax year filing summary html | read-only | `app.py:5386` `tax_year_filing_summary_html` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-acquisition-event-deltas` | Tax year gain evidence acquisition event deltas | read-only | `app.py:6701` `tax_year_gain_evidence_acquisition_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-event-deltas` | Tax year gain evidence event deltas | read-only | `app.py:6692` `tax_year_gain_evidence_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-price-deltas` | Tax year gain evidence price deltas | read-only | `app.py:6678` `tax_year_gain_evidence_price_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-review` | Tax year gain evidence review | read-only | `app.py:6670` `tax_year_gain_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/gain-loss-reality-check` | Tax year gain loss reality check | read-only | `app.py:6658` `tax_year_gain_loss_reality_check` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-alchemy-audit` | Tax year helium swap alchemy audit | read-only | `app.py:8032` `tax_year_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-context` | Tax year helium swap context | read-only | `app.py:6596` `tax_year_helium_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-evidence-review` | Tax year helium swap evidence review | read-only | `app.py:6604` `tax_year_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/income-guide` | Tax year income guide | read-only | `app.py:6578` `tax_year_income_guide` |
| `GET` | `/api/v1/tax-years/{year}/methodology` | Tax year methodology | read-only | `app.py:5884` `tax_year_methodology` |
| `POST` | `/api/v1/tax-years/{year}/private-disposal-threshold-assessment` | Private disposal threshold assessment | kann Daten oder Artefakte schreiben | `app.py:5332` `private_disposal_threshold_assessment` |
| `GET` | `/api/v1/tax-years/{year}/reports/pdf` | List tax year pdf reports | read-only | `app.py:5406` `list_tax_year_pdf_reports` |
| `POST` | `/api/v1/tax-years/{year}/reports/pdf` | Create tax year pdf report | kann Daten oder Artefakte schreiben | `app.py:5398` `create_tax_year_pdf_report` |
| `GET` | `/api/v1/tax-years/{year}/reports/pdf/{artifact_id}/files/{file_index}` | Download tax year pdf file | read-only | `app.py:5429` `download_tax_year_pdf_file` |
| `GET` | `/api/v1/tax-years/{year}/reports/pdf/{artifact_id}/manifest.json` | Download tax year pdf manifest | read-only | `app.py:5414` `download_tax_year_pdf_manifest` |
| `GET` | `/api/v1/tax-years/{year}/solana-program-income-review` | Tax year solana program income review | read-only | `app.py:6588` `tax_year_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-fx-review` | Tax year solana stablecoin fx review | read-only | `app.py:6638` `tax_year_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-swap-context` | Tax year solana stablecoin swap context | read-only | `app.py:6628` `tax_year_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-fifo-review` | Tax year stablecoin fifo review | read-only | `app.py:6612` `tax_year_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-quote-leg-review` | Tax year stablecoin quote leg review | read-only | `app.py:6620` `tax_year_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/{year}/turnover-audit` | Tax year turnover audit | read-only | `app.py:6750` `tax_year_turnover_audit` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-delta` | Tax year wallet fifo delta | read-only | `app.py:5898` `tax_year_wallet_fifo_delta` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-exchange-evidence-gaps` | Tax year wallet fifo exchange evidence gaps | read-only | `app.py:6384` `tax_year_wallet_fifo_exchange_evidence_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-gaps` | Tax year wallet fifo gaps | read-only | `app.py:5908` `tax_year_wallet_fifo_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-opening-balance-evidence` | Tax year wallet fifo opening balance evidence | read-only | `app.py:6368` `tax_year_wallet_fifo_opening_balance_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-origin-trace` | Tax year wallet fifo origin trace | read-only | `app.py:5916` `tax_year_wallet_fifo_origin_trace` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-closure` | Tax year wallet fifo provenance closure | read-only | `app.py:6319` `tax_year_wallet_fifo_provenance_closure` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-events` | Tax year wallet fifo provenance events | read-only | `app.py:6334` `tax_year_wallet_fifo_provenance_events` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-priorities` | Tax year wallet fifo provenance priorities | read-only | `app.py:6308` `tax_year_wallet_fifo_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-raw-provenance-breakdown` | Tax year wallet fifo raw provenance breakdown | read-only | `app.py:6352` `tax_year_wallet_fifo_raw_provenance_breakdown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-origin` | Tax year wallet fifo solana origin | read-only | `app.py:6551` `tax_year_wallet_fifo_solana_origin` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence` | Tax year wallet fifo solana program settlement evidence | read-only | `app.py:6433` `tax_year_wallet_fifo_solana_program_settlement_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-batch-latest` | Tax year wallet fifo solana provenance batch latest | read-only | `app.py:6422` `tax_year_wallet_fifo_solana_provenance_batch_latest` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-classification` | Tax year wallet fifo solana provenance classification | read-only | `app.py:6400` `tax_year_wallet_fifo_solana_provenance_classification` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-drilldown` | Tax year wallet fifo solana raw bmf evidence drilldown | read-only | `app.py:6499` `tax_year_wallet_fifo_solana_raw_bmf_evidence_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-summary` | Tax year wallet fifo solana raw bmf evidence summary | read-only | `app.py:6483` `tax_year_wallet_fifo_solana_raw_bmf_evidence_summary` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-priorities` | Tax year wallet fifo solana raw provenance priorities | read-only | `app.py:6451` `tax_year_wallet_fifo_solana_raw_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-senders` | Tax year wallet fifo solana raw provenance senders | read-only | `app.py:6467` `tax_year_wallet_fifo_solana_raw_provenance_senders` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-cluster-outflows` | Tax year wallet fifo solana sender cluster outflows | read-only | `app.py:6531` `tax_year_wallet_fifo_solana_sender_cluster_outflows` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-clusters` | Tax year wallet fifo solana sender clusters | read-only | `app.py:6519` `tax_year_wallet_fifo_solana_sender_clusters` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-service-swap-evidence` | Tax year wallet fifo solana service swap evidence | read-only | `app.py:6443` `tax_year_wallet_fifo_solana_service_swap_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps` | Tax year wallet fifo withdrawal gaps | read-only | `app.py:6567` `tax_year_wallet_fifo_withdrawal_gaps` |
| `GET` | `/api/v1/tax/bmf-combined-fifo-staging/latest` | Tax bmf combined fifo staging latest | read-only | `app.py:4804` `tax_bmf_combined_fifo_staging_latest` |
| `POST` | `/api/v1/tax/bmf-combined-fifo-staging/run` | Tax bmf combined fifo staging run | kann Daten oder Artefakte schreiben | `app.py:4816` `tax_bmf_combined_fifo_staging_run` |
| `GET` | `/api/v1/tax/bmf-event-price-remediation/latest` | Tax bmf event price remediation latest | read-only | `app.py:4884` `tax_bmf_event_price_remediation_latest` |
| `POST` | `/api/v1/tax/bmf-event-price-remediation/run` | Tax bmf event price remediation run | kann Daten oder Artefakte schreiben | `app.py:4896` `tax_bmf_event_price_remediation_run` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz` | Tax bmf fifo event evidence events artifact | read-only | `app.py:4836` `tax_bmf_fifo_event_evidence_events_artifact` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/latest` | Tax bmf fifo event evidence latest | read-only | `app.py:4826` `tax_bmf_fifo_event_evidence_latest` |
| `POST` | `/api/v1/tax/bmf-fifo-event-evidence/run` | Tax bmf fifo event evidence run | kann Daten oder Artefakte schreiben | `app.py:4874` `tax_bmf_fifo_event_evidence_run` |
| `GET` | `/api/v1/tax/cross-cex-transfer-evidence` | Tax cross cex transfer evidence | read-only | `app.py:4178` `tax_cross_cex_transfer_evidence` |
| `GET` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/latest` | Tax crypto swap fifo parallel preview latest | read-only | `app.py:4782` `tax_crypto_swap_fifo_parallel_preview_latest` |
| `POST` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/run` | Tax crypto swap fifo parallel preview run | kann Daten oder Artefakte schreiben | `app.py:4794` `tax_crypto_swap_fifo_parallel_preview_run` |
| `GET` | `/api/v1/tax/crypto-swap-valuation-review` | Tax crypto swap valuation review | read-only | `app.py:4766` `tax_crypto_swap_valuation_review` |
| `GET` | `/api/v1/tax/fairspot-staking-reconciliation` | Tax fairspot staking reconciliation | read-only | `app.py:4184` `tax_fairspot_staking_reconciliation` |
| `POST` | `/api/v1/tax/fifo/rebuild` | Rebuild fifo tax | kann Daten oder Artefakte schreiben | `app.py:4118` `rebuild_fifo_tax` |
| `GET` | `/api/v1/tax/holding-periods` | Tax holding periods | read-only | `app.py:4134` `tax_holding_periods` |
| `GET` | `/api/v1/tax/legacy-helium-overview` | Tax legacy helium overview | read-only | `app.py:4686` `tax_legacy_helium_overview` |
| `GET` | `/api/v1/tax/lines` | List tax lines | read-only | `app.py:4122` `list_tax_lines` |
| `GET` | `/api/v1/tax/loss-realization-planner` | Tax loss realization planner | read-only | `app.py:4148` `tax_loss_realization_planner` |
| `GET` | `/api/v1/tax/lots` | List tax lots | read-only | `app.py:4126` `list_tax_lots` |
| `GET` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipts | read-only | `app.py:4190` `tax_moonpay_receipts` |
| `POST` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipt upsert | kann Daten oder Artefakte schreiben | `app.py:4242` `tax_moonpay_receipt_upsert` |
| `GET` | `/api/v1/tax/moonpay-receipts/trade-history.csv` | Tax moonpay trade history document | read-only | `app.py:4196` `tax_moonpay_trade_history_document` |
| `GET` | `/api/v1/tax/moonpay-receipts/{tx_id}/document` | Tax moonpay receipt document | read-only | `app.py:4222` `tax_moonpay_receipt_document` |
| `GET` | `/api/v1/tax/pionex-hnt-reconciliation` | Tax pionex hnt reconciliation | read-only | `app.py:4174` `tax_pionex_hnt_reconciliation` |
| `GET` | `/api/v1/tax/service-swap-mappings` | Tax service swap mappings | read-only | `app.py:4170` `tax_service_swap_mappings` |
| `GET` | `/api/v1/tax/solana-staking-position-reconciliation` | Tax solana staking position reconciliation | read-only | `app.py:4253` `tax_solana_staking_position_reconciliation` |
| `GET` | `/api/v1/tax/summary` | Tax summary | read-only | `app.py:4166` `tax_summary` |
| `GET` | `/api/v1/tax/unmatched-disposals` | List tax unmatched disposals | read-only | `app.py:4130` `list_tax_unmatched_disposals` |
| `GET` | `/api/v1/tax/wallet-fifo-internal-transfer-carry` | Tax wallet fifo internal transfer carry | read-only | `app.py:4268` `tax_wallet_fifo_internal_transfer_carry` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/applies/latest` | Tax wallet fifo migration apply latest | read-only | `app.py:4642` `tax_wallet_fifo_migration_apply_latest` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/apply` | Tax wallet fifo migration apply | kann Daten oder Artefakte schreiben | `app.py:4631` `tax_wallet_fifo_migration_apply` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/apply-readiness` | Tax wallet fifo migration apply readiness | read-only | `app.py:4619` `tax_wallet_fifo_migration_apply_readiness` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/rehearsals` | Tax wallet fifo migration rehearsal | kann Daten oder Artefakte schreiben | `app.py:4590` `tax_wallet_fifo_migration_rehearsal` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/latest` | Tax wallet fifo migration rehearsal latest | read-only | `app.py:4601` `tax_wallet_fifo_migration_rehearsal_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/{rehearsal_id}` | Tax wallet fifo migration rehearsal by id | read-only | `app.py:4607` `tax_wallet_fifo_migration_rehearsal_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-preview` | Tax wallet fifo preview | read-only | `app.py:4259` `tax_wallet_fifo_preview` |
| `POST` | `/api/v1/tax/wallet-fifo-runs` | Tax wallet fifo parallel run | kann Daten oder Artefakte schreiben | `app.py:4280` `tax_wallet_fifo_parallel_run` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest` | Tax wallet fifo parallel run latest | read-only | `app.py:4291` `tax_wallet_fifo_parallel_run_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-acceptance` | Tax wallet fifo latest method acceptance | read-only | `app.py:4527` `tax_wallet_fifo_latest_method_acceptance` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation` | Tax wallet fifo latest method delta explanation | read-only | `app.py:4539` `tax_wallet_fifo_latest_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}` | Tax wallet fifo parallel run by id | read-only | `app.py:4555` `tax_wallet_fifo_parallel_run_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/evidence/{filename}` | Tax wallet fifo parallel run evidence | read-only | `app.py:4671` `tax_wallet_fifo_parallel_run_evidence` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance | read-only | `app.py:4566` `tax_wallet_fifo_method_acceptance` |
| `POST` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance create | kann Daten oder Artefakte schreiben | `app.py:4578` `tax_wallet_fifo_method_acceptance_create` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-delta-explanation` | Tax wallet fifo method delta explanation | read-only | `app.py:4648` `tax_wallet_fifo_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision` | Tax wallet fifo bitget strategy basis decision | read-only | `app.py:4345` `tax_wallet_fifo_bitget_strategy_basis_decision` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run_id}` | Tax wallet fifo bitget strategy basis decision create | kann Daten oder Artefakte schreiben | `app.py:4359` `tax_wallet_fifo_bitget_strategy_basis_decision_create` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps` | Tax wallet fifo bitget strategy gaps | read-only | `app.py:4297` `tax_wallet_fifo_bitget_strategy_gaps` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv` | Tax wallet fifo bitget strategy gaps csv | read-only | `app.py:4309` `tax_wallet_fifo_bitget_strategy_gaps_csv` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction` | Tax wallet fifo bitget strategy reconstruction | read-only | `app.py:4330` `tax_wallet_fifo_bitget_strategy_reconstruction` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv` | Tax wallet fifo bitget strategy reconstruction csv | read-only | `app.py:4374` `tax_wallet_fifo_bitget_strategy_reconstruction_csv` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill` | Tax wallet fifo bitget strategy reference price backfill | kann Daten oder Artefakte schreiben | `app.py:4412` `tax_wallet_fifo_bitget_strategy_reference_price_backfill` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill/latest` | Tax wallet fifo bitget strategy reference price backfill latest | read-only | `app.py:4401` `tax_wallet_fifo_bitget_strategy_reference_price_backfill_latest` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip` | Tax wallet fifo bitget strategy review package | read-only | `app.py:4484` `tax_wallet_fifo_bitget_strategy_review_package` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review.html` | Tax wallet fifo bitget strategy review html | read-only | `app.py:4454` `tax_wallet_fifo_bitget_strategy_review_html` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-support-package.zip` | Tax wallet fifo bitget support package | read-only | `app.py:4426` `tax_wallet_fifo_bitget_support_package` |

## Reports und Exporte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/export/all-transaction-decision-candidates.json` | Download all transaction decision candidates json | read-only | `app.py:7965` `download_all_transaction_decision_candidates_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-closure.json` | Download all transaction evidence closure json | read-only | `app.py:7939` `download_all_transaction_evidence_closure_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-matrix.json` | Download all transaction evidence matrix json | read-only | `app.py:7927` `download_all_transaction_evidence_matrix_json` |
| `GET` | `/api/v1/export/all-transaction-open-detail-review.json` | Download all transaction open detail review json | read-only | `app.py:7951` `download_all_transaction_open_detail_review_json` |
| `POST` | `/api/v1/export/audit` | Export audit | kann Daten oder Artefakte schreiben | `app.py:6955` `export_audit` |
| `GET` | `/api/v1/export/audit.json` | Download audit json | read-only | `app.py:6963` `download_audit_json` |
| `GET` | `/api/v1/export/binance-fiat-deposits.csv` | Download binance fiat deposits csv | read-only | `app.py:7360` `download_binance_fiat_deposits_csv` |
| `GET` | `/api/v1/export/derivative-lines.csv` | Download derivative lines csv | read-only | `app.py:7498` `download_derivative_lines_csv` |
| `POST` | `/api/v1/export/elster-prep` | Export elster prep | kann Daten oder Artefakte schreiben | `app.py:6959` `export_elster_prep` |
| `GET` | `/api/v1/export/evidence-manifest.json` | Download evidence manifest | read-only | `app.py:6871` `download_evidence_manifest` |
| `GET` | `/api/v1/export/evidence-package-index.json` | Download evidence package index | read-only | `app.py:6882` `download_evidence_package_index` |
| `GET` | `/api/v1/export/evidence-package.zip` | Download evidence package zip | read-only | `app.py:8451` `download_evidence_package_zip` |
| `GET` | `/api/v1/export/hnt-provenance-events.csv` | Download hnt provenance events csv | read-only | `app.py:7296` `download_hnt_provenance_events_csv` |
| `GET` | `/api/v1/export/hnt-provenance-timeline.csv` | Download hnt provenance timeline csv | read-only | `app.py:7236` `download_hnt_provenance_timeline_csv` |
| `GET` | `/api/v1/export/packages` | List export packages | read-only | `app.py:6851` `list_export_packages` |
| `DELETE` | `/api/v1/export/packages/{package_id}` | Delete export package | loescht | `app.py:6935` `delete_export_package` |
| `GET` | `/api/v1/export/packages/{package_id}/download.pdf` | Download export package pdf | read-only | `app.py:6895` `download_export_package_pdf` |
| `GET` | `/api/v1/export/parity-diagnostics.csv` | Download parity diagnostics csv | read-only | `app.py:7188` `download_parity_diagnostics_csv` |
| `POST` | `/api/v1/export/pdf` | Create pdf export | kann Daten oder Artefakte schreiben | `app.py:6847` `create_pdf_export` |
| `GET` | `/api/v1/export/price-gaps.csv` | Download price gaps csv | read-only | `app.py:7092` `download_price_gaps_csv` |
| `GET` | `/api/v1/export/price-requirements.csv` | Download price requirements csv | read-only | `app.py:7142` `download_price_requirements_csv` |
| `GET` | `/api/v1/export/readiness` | Export readiness | read-only | `app.py:6855` `export_readiness` |
| `GET` | `/api/v1/export/review-decisions.csv` | Download review decisions csv | read-only | `app.py:6983` `download_review_decisions_csv` |
| `GET` | `/api/v1/export/solana-failed-tx-tax-impact.json` | Download solana failed tx tax impact json | read-only | `app.py:7915` `download_solana_failed_tx_tax_impact_json` |
| `GET` | `/api/v1/export/solana-tx-alchemy-audit.json` | Download solana tx alchemy audit json | read-only | `app.py:7903` `download_solana_tx_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-external-inflows.csv` | Download tax external inflows csv | read-only | `app.py:7644` `download_tax_external_inflows_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-alchemy-audit.json` | Download tax helium swap alchemy audit json | read-only | `app.py:8040` `download_tax_helium_swap_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-helium-swap-context.csv` | Download tax helium swap context csv | read-only | `app.py:8353` `download_tax_helium_swap_context_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-evidence-review.csv` | Download tax helium swap evidence review csv | read-only | `app.py:8434` `download_tax_helium_swap_evidence_review_csv` |
| `GET` | `/api/v1/export/tax-income-guide.csv` | Download tax income guide csv | read-only | `app.py:7562` `download_tax_income_guide_csv` |
| `GET` | `/api/v1/export/tax-lines.csv` | Download tax lines csv | read-only | `app.py:7455` `download_tax_lines_csv` |
| `GET` | `/api/v1/export/tax-methodology/bmf-amendment-worklist.csv` | Download bmf amendment worklist csv | read-only | `app.py:5290` `download_bmf_amendment_worklist_csv` |
| `GET` | `/api/v1/export/tax-payment-overview.json` | Download tax payment overview json | read-only | `app.py:6972` `download_tax_payment_overview_json` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-evidence.csv` | Download tax solana stablecoin swap evidence csv | read-only | `app.py:8157` `download_tax_solana_stablecoin_swap_evidence_csv` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv` | Download tax solana stablecoin swap fifo lines csv | read-only | `app.py:8276` `download_tax_solana_stablecoin_swap_fifo_lines_csv` |
| `GET` | `/api/v1/export/tax-years/correction-map.csv` | Download tax years correction map csv | read-only | `app.py:5814` `download_tax_years_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/correction-map.csv` | Download tax year correction map csv | read-only | `app.py:5824` `download_tax_year_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/evidence-package.zip` | Download tax year evidence package zip | read-only | `app.py:8730` `download_tax_year_evidence_package_zip` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-checklist.csv` | Download tax year filing checklist csv | read-only | `app.py:5874` `download_tax_year_filing_checklist_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-snapshot-comparison.csv` | Liefert den Abgabestand-Delta je Einkunftsart als CSV | read-only | `app.py:10033` `tax_filing_snapshot_comparison_csv` |
| `GET` | `/api/v1/export/token-risk-documentation.csv` | Download token risk documentation csv | read-only | `app.py:7031` `download_token_risk_documentation_csv` |
| `GET` | `/api/v1/reports/center` | Report center | read-only | `app.py:6863` `report_center` |

## Stichtag und Zugewinn

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/divorce/coinbase/connector` | Berechnet Coinbase-Historienabdeckung und Stichtagsbestand | read-only | `app.py:3095` `divorce_coinbase_connector` |
| `GET` | `/api/v1/divorce/coinbase/connector.csv` | Liefert den Coinbase-Historien- und Stichtagsnachweis als CSV | read-only | `app.py:3105` `divorce_coinbase_connector_csv` |
| `POST` | `/api/v1/divorce/coinbase/valuation-decisions` | Bindet den serverseitigen Coinbase-Stichtagswert an das Historienmanifest | kann Daten oder Artefakte schreiben | `app.py:3120` `divorce_coinbase_valuation_decision` |
| `GET` | `/api/v1/divorce/equalization-summary` | Divorce equalization summary | read-only | `app.py:3314` `divorce_equalization_summary` |
| `GET` | `/api/v1/divorce/equalization-summary/accounts.csv` | Divorce equalization accounts csv | read-only | `app.py:3364` `divorce_equalization_accounts_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/capital-flows.csv` | Divorce equalization capital flows csv | read-only | `app.py:3420` `divorce_equalization_capital_flows_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/evidence-package.zip` | Divorce equalization evidence package zip | read-only | `app.py:3448` `divorce_equalization_evidence_package_zip` |
| `GET` | `/api/v1/divorce/equalization-summary/live-reconciliation.csv` | Divorce equalization live reconciliation csv | read-only | `app.py:3392` `divorce_equalization_live_reconciliation_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/valuation-tokens.csv` | Divorce equalization valuation tokens csv | read-only | `app.py:3336` `divorce_equalization_valuation_tokens_csv` |
| `GET` | `/api/v1/divorce/inheritance-credit-candidates` | Liefert datensparsame CAMT-Gutschriften fuer die Erbmittelpruefung | read-only | `app.py:2814` `divorce_inheritance_credit_candidates` |
| `POST` | `/api/v1/divorce/inheritance-credit-decisions` | Klassifiziert eine konkrete CAMT-Gutschrift hashgebunden als Erbmittel | kann Daten oder Artefakte schreiben | `app.py:2843` `divorce_inheritance_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-credits.csv` | Liefert alle freigegebenen Erbmittelzufluesse als Beleg-CSV | read-only | `app.py:2826` `divorce_inheritance_credits_csv` |
| `POST` | `/api/v1/divorce/inheritance-document-credit-decisions` | Bindet einen dokumentierten Netto-Erbmittelzufluss an Beleg und Betrag | kann Daten oder Artefakte schreiben | `app.py:2883` `divorce_inheritance_document_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-documents` | Liefert den datensparsamen Erbnachweis- und Reviewstatus | read-only | `app.py:2973` `divorce_inheritance_documents` |
| `POST` | `/api/v1/divorce/inheritance-documents` | Speichert einen validierten formalen Erbnachweis als Kandidat | kann Daten oder Artefakte schreiben | `app.py:2992` `divorce_inheritance_document_upload` |
| `GET` | `/api/v1/divorce/inheritance-documents.csv` | Liefert den Erbnachweis-Hashindex als CSV | read-only | `app.py:2981` `divorce_inheritance_documents_csv` |
| `POST` | `/api/v1/divorce/inheritance-documents/review-decisions` | Bindet einen gesichteten formalen Erbnachweis an SHA-256 | kann Daten oder Artefakte schreiben | `app.py:3032` `divorce_inheritance_document_review_decision` |
| `GET` | `/api/v1/divorce/inheritance-origin` | Divorce inheritance origin | read-only | `app.py:2781` `divorce_inheritance_origin` |
| `GET` | `/api/v1/divorce/inheritance-origin.csv` | Divorce inheritance origin csv | read-only | `app.py:3068` `divorce_inheritance_origin_csv` |
| `POST` | `/api/v1/divorce/service-route-evidence/decisions` | Bindet eine vollstaendig liquidierte Serviceposition an den Vermoegensfluss | kann Daten oder Artefakte schreiben | `app.py:3278` `divorce_service_route_decision` |
| `POST` | `/api/v1/divorce/service-route-evidence/refresh` | Erzeugt einen SHA-gebundenen Solana-RPC-Lebenszyklusbeleg fuer eine Serviceposition | kann Daten oder Artefakte schreiben | `app.py:3251` `divorce_service_route_evidence_refresh` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}` | Liefert den letzten validen Servicepositions-Lebenszyklusbeleg | read-only | `app.py:3264` `divorce_service_route_evidence` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}/artifacts/{filename}` | Liefert einen SHA-geprueften komprimierten Solana-RPC-Beleg | read-only | `app.py:3292` `divorce_service_route_evidence_artifact` |
| `POST` | `/api/v1/divorce/sparkasse-camt` | Importiert validierte CAMT.052-XML- oder ZIP-Belege | kann Daten oder Artefakte schreiben | `app.py:2925` `divorce_sparkasse_camt_upload` |
| `GET` | `/api/v1/divorce/sparkasse-statements` | Gleicht Sparkassen-PDF-Auszugbelege read-only gegen CAMT.052 ab | read-only | `app.py:2793` `divorce_sparkasse_statements` |
| `GET` | `/api/v1/divorce/sparkasse-statements.csv` | Liefert den datensparsamen PDF-zu-CAMT-Belegabgleich als CSV | read-only | `app.py:2801` `divorce_sparkasse_statements_csv` |
| `GET` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic documents | read-only | `app.py:3085` `divorce_trade_republic_documents` |
| `POST` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic document upload | kann Daten oder Artefakte schreiben | `app.py:3171` `divorce_trade_republic_document_upload` |
| `GET` | `/api/v1/divorce/trade-republic/documents.csv` | Divorce trade republic documents csv | read-only | `app.py:3156` `divorce_trade_republic_documents_csv` |
| `POST` | `/api/v1/divorce/trade-republic/valuation-decisions` | Divorce trade republic valuation decision | kann Daten oder Artefakte schreiben | `app.py:3215` `divorce_trade_republic_valuation_decision` |
| `POST` | `/api/v1/divorce/valuation-runs` | Divorce valuation run | kann Daten oder Artefakte schreiben | `app.py:3476` `divorce_valuation_run` |
| `GET` | `/api/v1/divorce/valuation-runs/latest` | Divorce valuation run latest | read-only | `app.py:3486` `divorce_valuation_run_latest` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}` | Divorce valuation run by id | read-only | `app.py:3490` `divorce_valuation_run_by_id` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}/evidence/{filename}` | Divorce valuation run evidence | read-only | `app.py:3499` `divorce_valuation_run_evidence` |

## KI-Aufgaben

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ai/agents` | Ai agents | read-only | `app.py:10146` `ai_agents` |
| `PUT` | `/api/v1/ai/agents` | Save ai agents | schreibt | `app.py:10150` `save_ai_agents` |
| `GET` | `/api/v1/ai/changes` | Ai change sets | read-only | `app.py:10162` `ai_change_sets` |
| `POST` | `/api/v1/ai/changes` | Create ai change set | kann Daten oder Artefakte schreiben | `app.py:10166` `create_ai_change_set` |
| `POST` | `/api/v1/ai/changes/generate` | Generate ai change set | kann Daten oder Artefakte schreiben | `app.py:10170` `generate_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}` | Ai change set | read-only | `app.py:10174` `ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/apply` | Apply ai change set | kann Daten oder Artefakte schreiben | `app.py:10190` `apply_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}/audit.json` | Ai change audit | read-only | `app.py:10204` `ai_change_audit` |
| `POST` | `/api/v1/ai/changes/{identifier}/preview` | Preview ai change set | kann Daten oder Artefakte schreiben | `app.py:10186` `preview_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/rebase` | Rebase ai change set | kann Daten oder Artefakte schreiben | `app.py:10182` `rebase_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/reject` | Reject ai change set | kann Daten oder Artefakte schreiben | `app.py:10196` `reject_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revert` | Revert ai change set | kann Daten oder Artefakte schreiben | `app.py:10200` `revert_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revise` | Revise ai change set | kann Daten oder Artefakte schreiben | `app.py:10178` `revise_ai_change_set` |
| `POST` | `/api/v1/ai/data-context` | Ai data context | kann Daten oder Artefakte schreiben | `app.py:10154` `ai_data_context` |
| `POST` | `/api/v1/ai/data-context/targets` | Ai data target context | kann Daten oder Artefakte schreiben | `app.py:10158` `ai_data_target_context` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review` | Local ai asset fifo correction review | read-only | `app.py:10265` `local_ai_asset_fifo_correction_review` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review/artifacts/{artifact}` | Download local ai asset fifo correction artifact | read-only | `app.py:10271` `download_local_ai_asset_fifo_correction_artifact` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review` | Local ai wallet fifo provenance review | read-only | `app.py:10298` `local_ai_wallet_fifo_provenance_review` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/{artifact}` | Download local ai wallet fifo provenance artifact | read-only | `app.py:10304` `download_local_ai_wallet_fifo_provenance_artifact` |
| `GET` | `/api/v1/ai/local-year-package-qa` | Local ai year package qa | read-only | `app.py:10234` `local_ai_year_package_qa` |
| `GET` | `/api/v1/ai/local-year-package-qa/artifacts/{artifact}` | Download local ai year package qa artifact | read-only | `app.py:10238` `download_local_ai_year_package_qa_artifact` |
| `GET` | `/api/v1/ai/provider` | Ai provider status | read-only | `app.py:10125` `ai_provider_status` |
| `PUT` | `/api/v1/ai/provider` | Save ai provider | schreibt | `app.py:10210` `save_ai_provider` |
| `POST` | `/api/v1/ai/provider/models` | Ai provider models | kann Daten oder Artefakte schreiben | `app.py:10214` `ai_provider_models` |
| `POST` | `/api/v1/ai/provider/test` | Test ai provider | kann Daten oder Artefakte schreiben | `app.py:10218` `test_ai_provider` |
| `GET` | `/api/v1/ai/tasks` | List ai tasks | read-only | `app.py:10230` `list_ai_tasks` |
| `POST` | `/api/v1/ai/tasks` | Create ai task | kann Daten oder Artefakte schreiben | `app.py:10226` `create_ai_task` |
| `DELETE` | `/api/v1/ai/tasks/{task_id}` | Delete ai task | loescht | `app.py:10331` `delete_ai_task` |
| `POST` | `/api/v1/ai/tasks/{task_id}/execute` | Execute ai task | kann Daten oder Artefakte schreiben | `app.py:10222` `execute_ai_task` |

## V1-Paritaet

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/parity/compare` | Compare v1 v2 parity | read-only | `app.py:4053` `compare_v1_v2_parity` |
| `POST` | `/api/v1/parity/decisions` | Add parity decision | kann Daten oder Artefakte schreiben | `app.py:4093` `add_parity_decision` |
| `GET` | `/api/v1/parity/diagnostics` | Parity diagnostics | read-only | `app.py:4057` `parity_diagnostics` |
| `GET` | `/api/v1/parity/group-detail` | Parity group detail | read-only | `app.py:4065` `parity_group_detail` |
| `GET` | `/api/v1/parity/hnt-fifo-provenance` | Parity hnt fifo provenance | read-only | `app.py:4075` `parity_hnt_fifo_provenance` |
| `GET` | `/api/v1/parity/hnt-wallet-bridge` | Parity hnt wallet bridge | read-only | `app.py:4069` `parity_hnt_wallet_bridge` |
| `GET` | `/api/v1/parity/release-readiness` | Parity release readiness | read-only | `app.py:4061` `parity_release_readiness` |
| `POST` | `/api/v1/parity/v1/import/wiso` | Import wiso v1 references | kann Daten oder Artefakte schreiben | `app.py:4019` `import_wiso_v1_references` |
| `GET` | `/api/v1/parity/v1/references` | List v1 reference metrics | read-only | `app.py:3995` `list_v1_reference_metrics` |
| `POST` | `/api/v1/parity/v1/references` | Add v1 reference metric | kann Daten oder Artefakte schreiben | `app.py:3989` `add_v1_reference_metric` |
| `DELETE` | `/api/v1/parity/v1/references/{reference_id}` | Delete v1 reference metric | loescht | `app.py:3999` `delete_v1_reference_metric` |

## Weitere Endpunkte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/activity/assets` | Activity assets | read-only | `app.py:1779` `activity_assets` |
| `GET` | `/api/v1/activity/events/{event_id}` | Activity detail | read-only | `app.py:1785` `activity_detail` |
| `POST` | `/api/v1/activity/export.csv` | Activity export | kann Daten oder Artefakte schreiben | `app.py:1792` `activity_export` |
| `POST` | `/api/v1/activity/query` | Activity query | kann Daten oder Artefakte schreiben | `app.py:1771` `activity_query` |
| `POST` | `/api/v1/demo/seed` | Seed demo | kann Daten oder Artefakte schreiben | `app.py:6835` `seed_demo` |
| `GET` | `/api/v1/derivatives/lines` | List derivative lines | read-only | `app.py:6816` `list_derivative_lines` |
| `POST` | `/api/v1/derivatives/rebuild` | Rebuild derivatives | kann Daten oder Artefakte schreiben | `app.py:6812` `rebuild_derivatives` |
| `GET` | `/api/v1/derivatives/summary` | Derivative summary | read-only | `app.py:6820` `derivative_summary` |
| `POST` | `/api/v1/pipeline/rebuild` | Rebuild pipeline | kann Daten oder Artefakte schreiben | `app.py:6824` `rebuild_pipeline` |
| `GET` | `/api/v1/updates` | Status | read-only | `updates.py:50` `status` |
| `POST` | `/api/v1/updates/check` | Check | kann Daten oder Artefakte schreiben | `updates.py:58` `check` |
| `POST` | `/api/v1/updates/handoff` | Handoff | kann Daten oder Artefakte schreiben | `updates.py:62` `handoff` |
| `PUT` | `/api/v1/updates/settings` | Settings | schreibt | `updates.py:54` `settings` |
| `GET` | `/api/v1/workspace/environment` | Workspace environment | read-only | `app.py:1735` `workspace_environment` |
| `POST` | `/api/v1/workspace/review/query` | Workspace review | kann Daten oder Artefakte schreiben | `app.py:1767` `workspace_review` |
| `GET` | `/api/v1/workspace/sources` | Workspace sources | read-only | `app.py:1740` `workspace_sources` |
| `GET` | `/api/v1/workspace/sources/{ref}` | Workspace source | read-only | `app.py:1756` `workspace_source` |
| `GET` | `/api/v1/workspace/sources/{ref}/history` | Liest Abruffaehigkeit und gespeicherte Historienauftraege der konkreten Quelle | read-only | `history.py:64` `history` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs` | Startet bestaetigten externen Abruf und isolierte Vorschau ohne produktiven Finanzimport | kann Daten oder Artefakte schreiben | `history.py:68` `start` |
| `GET` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}` | Liest den gespeicherten quellengebundenen Auftragsstatus | read-only | `history.py:72` `job` |
| `GET` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/audit.json` | Liest Quellenbindung, Originalhashes, Vorschau und Importfreigabe | read-only | `history.py:98` `audit` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/binance-spot-matches` | Create binance spot match | kann Daten oder Artefakte schreiben | `history.py:108` `create_binance_spot_match` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/binance-spot-matches/preview` | Preview binance spot matches | kann Daten oder Artefakte schreiben | `history.py:102` `preview_binance_spot_matches` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/cancel` | Bricht Folgeabrufe und Importfreigabe ab; Originalbelege bleiben erhalten | kann Daten oder Artefakte schreiben | `history.py:80` `cancel` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/import` | Uebernimmt unveraenderte Vorschau nach Import- und Berechnungsfreigabe atomar | kann Daten oder Artefakte schreiben | `history.py:88` `apply` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/pause` | Speichert eine Pause fuer den laufenden Abruf | kann Daten oder Artefakte schreiben | `history.py:76` `pause` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/repreview` | Repreview | kann Daten oder Artefakte schreiben | `history.py:94` `repreview` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/resume` | Setzt den Abruf nach ausdruecklicher Anbieterbestaetigung am gespeicherten Cursor fort | kann Daten oder Artefakte schreiben | `history.py:84` `resume` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/spot-matches/{decision_id}/revoke` | Revoke binance spot match | kann Daten oder Artefakte schreiben | `history.py:115` `revoke_binance_spot_match` |
| `POST` | `/api/v1/workspace/sources/{ref}/sync` | Workspace source sync | kann Daten oder Artefakte schreiben | `app.py:1817` `workspace_source_sync` |
| `GET` | `/api/v1/workspace/status` | Workspace status | read-only | `app.py:1763` `workspace_status` |
| `POST` | `/api/v1/workspace/wallets` | Save public wallet address | kann Daten oder Artefakte schreiben | `app.py:1744` `save_public_wallet_address` |
