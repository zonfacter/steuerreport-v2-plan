# Vollstaendige API Endpoint Referenz

Stand: 2026-11-02

Diese Referenz wird mit `scripts/generate_api_endpoint_reference_v2.py` direkt aus `src/steuerreport_v2/api/app.py` und seinen statisch eingebundenen Routermodulen erzeugt. Sie inventarisiert deren statisch deklarierte FastAPI-Routen. Fachliche Request-/Response- und Sicherheitsdetails stehen in `docs/API_CONTRACTS_V2.md` und zur Laufzeit in `/docs` bzw. `/openapi.json`.

## Nutzung

- `GET` ist read-only, sofern der Fachcontract nicht ausdruecklich einen externen   Live-Abruf beschreibt.
- Schreibende Methoden koennen Decisions, Imports, Preise, Jobs oder lokale   Belegartefakte erzeugen. Vor produktiver Nutzung den Fachcontract pruefen.
- Echte Steuerdaten und Secrets gehoeren nicht in Git, Dokumentation oder   Beispielrequests.

## Statistik

- Endpunkte gesamt: `480`
- GET: `334`
- POST: `126`
- PUT: `10`
- PATCH: `1`
- DELETE: `9`

## Health und API Meta

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/health` | Health | read-only | `app.py:951` `health` |
| `GET` | `/api/v1/meta/capabilities` | Api capabilities | read-only | `app.py:955` `api_capabilities` |
| `GET` | `/health` | Health | read-only | `app.py:951` `health` |

## Administration und Secrets

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/admin/cex-credentials` | Save cex credentials | kann Daten oder Artefakte schreiben | `app.py:1264` `save_cex_credentials` |
| `GET` | `/api/v1/admin/cex-credentials/v1-takeover` | V1 cex credentials takeover report | read-only | `app.py:1436` `v1_cex_credentials_takeover_report` |
| `POST` | `/api/v1/admin/cex-credentials/v1-takeover` | Import v1 cex credentials | kann Daten oder Artefakte schreiben | `app.py:1442` `import_v1_cex_credentials` |
| `GET` | `/api/v1/admin/connections` | Connections | read-only | `connections.py:52` `connections` |
| `POST` | `/api/v1/admin/connections` | Create | kann Daten oder Artefakte schreiben | `connections.py:56` `create` |
| `GET` | `/api/v1/admin/connections/jobs` | Jobs | read-only | `connections.py:60` `jobs` |
| `POST` | `/api/v1/admin/connections/jobs/{job_id}/cancel` | Cancel | kann Daten oder Artefakte schreiben | `connections.py:64` `cancel` |
| `PUT` | `/api/v1/admin/connections/{connection_id}` | Update | schreibt | `connections.py:68` `update` |
| `DELETE` | `/api/v1/admin/connections/{connection_id}/credentials` | Delete credentials | loescht | `connections.py:72` `delete_credentials` |
| `GET` | `/api/v1/admin/connections/{connection_id}/snapshots` | Snapshots | read-only | `connections.py:76` `snapshots` |
| `POST` | `/api/v1/admin/connections/{connection_id}/sync` | Sync | kann Daten oder Artefakte schreiben | `connections.py:84` `sync` |
| `POST` | `/api/v1/admin/connections/{connection_id}/test` | Test | kann Daten oder Artefakte schreiben | `connections.py:80` `test` |
| `GET` | `/api/v1/admin/database` | Database status | read-only | `app.py:965` `database_status` |
| `GET` | `/api/v1/admin/installation` | Read installation | read-only | `app.py:842` `read_installation` |
| `PUT` | `/api/v1/admin/installation` | Write installation | schreibt | `app.py:849` `write_installation` |
| `GET` | `/api/v1/admin/installation/configs/{filename}` | Read installation config | read-only | `app.py:872` `read_installation_config` |
| `PUT` | `/api/v1/admin/installation/configs/{filename}` | Write installation config | schreibt | `app.py:879` `write_installation_config` |
| `DELETE` | `/api/v1/admin/installation/providers/{provider}` | Delete installation provider | loescht | `app.py:864` `delete_installation_provider` |
| `PUT` | `/api/v1/admin/installation/providers/{provider}` | Write installation provider | schreibt | `app.py:856` `write_installation_provider` |
| `POST` | `/api/v1/admin/jupiter/api-key` | Save jupiter api key | kann Daten oder Artefakte schreiben | `app.py:1295` `save_jupiter_api_key` |
| `GET` | `/api/v1/admin/provider-references` | References | read-only | `request_limits.py:133` `references` |
| `GET` | `/api/v1/admin/request-limits` | Read limits | read-only | `request_limits.py:69` `read_limits` |
| `PUT` | `/api/v1/admin/request-limits` | Write limits | schreibt | `request_limits.py:73` `write_limits` |
| `GET` | `/api/v1/admin/request-limits/endpoints` | Endpoints | read-only | `request_limits.py:88` `endpoints` |
| `GET` | `/api/v1/admin/request-limits/presets` | Presets | read-only | `request_limits.py:95` `presets` |
| `POST` | `/api/v1/admin/request-limits/presets/solana_public_free` | Apply preset | kann Daten oder Artefakte schreiben | `request_limits.py:123` `apply_preset` |
| `GET` | `/api/v1/admin/request-limits/status` | Status | read-only | `request_limits.py:82` `status` |
| `GET` | `/api/v1/admin/settings` | List admin settings | read-only | `app.py:1226` `list_admin_settings` |
| `PATCH` | `/api/v1/admin/settings` | Update admin setting | schreibt | `app.py:1230` `update_admin_setting` |
| `DELETE` | `/api/v1/admin/settings/{key}` | Delete admin setting | loescht | `app.py:1246` `delete_admin_setting` |
| `GET` | `/api/v1/admin/status` | Admin status | read-only | `app.py:969` `admin_status` |

## Cockpit und Product Readiness

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/cockpit/summary` | Cockpit summary | read-only | `app.py:973` `cockpit_summary` |
| `GET` | `/api/v1/product/readiness` | Product readiness | read-only | `app.py:981` `product_readiness` |

## Contracts

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/contracts/event-types` | Event types | read-only | `app.py:1475` `event_types` |

## Import und Preflight

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/import/assistant/execute` | Execute import assistant | kann Daten oder Artefakte schreiben | `app.py:2065` `execute_import_assistant` |
| `POST` | `/api/v1/import/assistant/preview` | Preview import assistant | kann Daten oder Artefakte schreiben | `app.py:2034` `preview_import_assistant` |
| `GET` | `/api/v1/import/batches` | List import batches | read-only | `app.py:1672` `list_import_batches` |
| `POST` | `/api/v1/import/batches` | Create import batch | kann Daten oder Artefakte schreiben | `app.py:1668` `create_import_batch` |
| `DELETE` | `/api/v1/import/batches/{batch_id}` | Delete import batch | loescht | `app.py:1692` `delete_import_batch` |
| `GET` | `/api/v1/import/batches/{batch_id}` | Get import batch | read-only | `app.py:1676` `get_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/normalize` | Normalize import batch | kann Daten oder Artefakte schreiben | `app.py:2092` `normalize_import_batch` |
| `GET` | `/api/v1/import/batches/{batch_id}/original` | Download mexc original | read-only | `app.py:1848` `download_mexc_original` |
| `POST` | `/api/v1/import/batches/{batch_id}/run` | Run import pipeline | kann Daten oder Artefakte schreiben | `app.py:2118` `run_import_pipeline` |
| `GET` | `/api/v1/import/batches/{batch_id}/trace.json` | Download import batch trace | read-only | `app.py:1822` `download_import_batch_trace` |
| `GET` | `/api/v1/import/blockpit-solana/preflight` | Blockpit solana preflight | read-only | `app.py:1529` `blockpit_solana_preflight` |
| `POST` | `/api/v1/import/blockpit-solana/price-probe` | Blockpit solana price probe | kann Daten oder Artefakte schreiben | `app.py:1547` `blockpit_solana_price_probe` |
| `GET` | `/api/v1/import/coverage` | Import coverage | read-only | `app.py:1497` `import_coverage` |
| `POST` | `/api/v1/import/csv/preview` | Preview csv import | kann Daten oder Artefakte schreiben | `app.py:1923` `preview_csv_import` |
| `POST` | `/api/v1/import/csv/raw` | Import csv raw | kann Daten oder Artefakte schreiben | `app.py:1869` `import_csv_raw` |
| `POST` | `/api/v1/import/file/preview` | Preview file import | kann Daten oder Artefakte schreiben | `app.py:1950` `preview_file_import` |
| `POST` | `/api/v1/import/file/raw` | Import file raw | kann Daten oder Artefakte schreiben | `app.py:1978` `import_file_raw` |
| `GET` | `/api/v1/import/jup-perps/preview` | Jup perps preview | read-only | `app.py:1654` `jup_perps_preview` |
| `GET` | `/api/v1/import/parser-preflight` | Parser preflight | read-only | `app.py:1517` `parser_preflight` |
| `GET` | `/api/v1/import/policy/audit` | Import policy audit | read-only | `app.py:1511` `import_policy_audit` |
| `GET` | `/api/v1/import/profiles` | Import profiles | read-only | `app.py:1493` `import_profiles` |
| `GET` | `/api/v1/import/solscan/evidence-trace` | Solscan evidence trace | read-only | `app.py:1604` `solscan_evidence_trace` |
| `GET` | `/api/v1/import/solscan/helium-reward-evidence` | Solscan helium reward evidence | read-only | `app.py:1624` `solscan_helium_reward_evidence` |
| `POST` | `/api/v1/import/solscan/rpc-probe` | Solscan rpc probe | kann Daten oder Artefakte schreiben | `app.py:1588` `solscan_rpc_probe` |
| `GET` | `/api/v1/import/solscan/token-preflight` | Solscan token preflight | read-only | `app.py:1568` `solscan_token_preflight` |
| `GET` | `/api/v1/import/wallet-monthly/preflight` | Wallet monthly preflight | read-only | `app.py:1636` `wallet_monthly_preflight` |

## Raw und Canonical Events

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/events/canonical` | List canonical events | read-only | `app.py:1717` `list_canonical_events` |
| `GET` | `/api/v1/raw/objects` | List raw objects | read-only | `app.py:1710` `list_raw_objects` |

## Ledger

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ledger/balances` | List balance positions | read-only | `app.py:2143` `list_balance_positions` |
| `POST` | `/api/v1/ledger/balances/rebuild` | Rebuild balance ledger | kann Daten oder Artefakte schreiben | `app.py:2139` `rebuild_balance_ledger` |

## Quellen und Connectoren

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/connectors/catalog` | Connector catalog | read-only | `app.py:989` `connector_catalog` |
| `GET` | `/api/v1/connectors/connections` | Connector connections | read-only | `app.py:993` `connector_connections` |
| `GET` | `/api/v1/connectors/mobile/documents` | Mobile connector documents | read-only | `app.py:1120` `mobile_connector_documents` |
| `POST` | `/api/v1/connectors/mobile/documents` | Upload mobile connector document | kann Daten oder Artefakte schreiben | `app.py:1061` `upload_mobile_connector_document` |
| `GET` | `/api/v1/connectors/mobile/documents/{document_id}/content` | Mobile connector document content | read-only | `app.py:1131` `mobile_connector_document_content` |
| `POST` | `/api/v1/connectors/mobile/pairings` | Create mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:997` `create_mobile_connector_pairing` |
| `GET` | `/api/v1/connectors/mobile/session` | Current mobile connector session | read-only | `app.py:1042` `current_mobile_connector_session` |
| `GET` | `/api/v1/connectors/mobile/sessions` | Mobile connector sessions | read-only | `app.py:1035` `mobile_connector_sessions` |
| `POST` | `/api/v1/connectors/mobile/sessions` | Exchange mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:1017` `exchange_mobile_connector_pairing` |
| `DELETE` | `/api/v1/connectors/mobile/sessions/{session_id}` | Revoke mobile connector session | loescht | `app.py:1159` `revoke_mobile_connector_session` |
| `POST` | `/api/v1/connectors/wallet/challenges` | Create wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1181` `create_wallet_ownership_challenge` |
| `POST` | `/api/v1/connectors/wallet/verifications` | Verify wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1202` `verify_wallet_ownership_challenge` |
| `GET` | `/api/v1/sources/binance/asset-dividend-api-preview` | Binance asset dividend api preview | read-only | `app.py:3621` `binance_asset_dividend_api_preview` |
| `POST` | `/api/v1/sources/binance/asset-dividend-api/import` | Binance asset dividend api import | kann Daten oder Artefakte schreiben | `app.py:3749` `binance_asset_dividend_api_import` |
| `GET` | `/api/v1/sources/binance/earn-history-api-preview` | Binance earn history api preview | read-only | `app.py:3557` `binance_earn_history_api_preview` |
| `POST` | `/api/v1/sources/binance/earn-history-api/import` | Binance earn history api import | kann Daten oder Artefakte schreiben | `app.py:3694` `binance_earn_history_api_import` |
| `POST` | `/api/v1/sources/binance/earn-history-harvest/import` | Binance earn history harvest import | kann Daten oder Artefakte schreiben | `app.py:3683` `binance_earn_history_harvest_import` |
| `GET` | `/api/v1/sources/binance/earn-history-preflight` | Binance earn history preflight | read-only | `app.py:3551` `binance_earn_history_preflight` |
| `GET` | `/api/v1/sources/binance/reconciliation/evidence` | Binance reconciliation evidence | read-only | `app.py:3519` `binance_reconciliation_evidence` |
| `GET` | `/api/v1/sources/binance/withdraw-history-api-preview` | Binance withdraw history api preview | read-only | `app.py:3590` `binance_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/binance/withdraw-history-api/import` | Binance withdraw history api import | kann Daten oder Artefakte schreiben | `app.py:3722` `binance_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/bitget/withdraw-history-api-preview` | Bitget withdraw history api preview | read-only | `app.py:3652` `bitget_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/bitget/withdraw-history-api/import` | Bitget withdraw history api import | kann Daten oder Artefakte schreiben | `app.py:3776` `bitget_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/connector-diagnostics` | Sources connector diagnostics | read-only | `app.py:3440` `sources_connector_diagnostics` |
| `GET` | `/api/v1/sources/jupiter/tokens/metadata-cache` | Jupiter token metadata cache | read-only | `app.py:1352` `jupiter_token_metadata_cache` |
| `POST` | `/api/v1/sources/jupiter/tokens/metadata-cache/refresh` | Refresh jupiter token metadata cache | kann Daten oder Artefakte schreiben | `app.py:1370` `refresh_jupiter_token_metadata_cache` |
| `GET` | `/api/v1/sources/jupiter/tokens/risk-review` | Jupiter token risk review | read-only | `app.py:1404` `jupiter_token_risk_review` |
| `GET` | `/api/v1/sources/jupiter/tokens/search` | Jupiter token search | read-only | `app.py:1312` `jupiter_token_search` |
| `GET` | `/api/v1/sources/overview` | Sources overview | read-only | `app.py:3436` `sources_overview` |
| `GET` | `/api/v1/sources/registry/config` | Sources registry config | read-only | `app.py:3446` `sources_registry_config` |
| `POST` | `/api/v1/sources/registry/runs` | Sources registry run | kann Daten oder Artefakte schreiben | `app.py:3456` `sources_registry_run` |
| `GET` | `/api/v1/sources/registry/runs/latest` | Sources registry run latest | read-only | `app.py:3467` `sources_registry_run_latest` |
| `GET` | `/api/v1/sources/{source_id}` | Source detail | read-only | `app.py:3485` `source_detail` |
| `GET` | `/api/v1/sources/{source_id}/reconciliation` | Source reconciliation | read-only | `app.py:3501` `source_reconciliation` |

## Portfolio

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/portfolio/as-of` | Portfolio as of | read-only | `app.py:2582` `portfolio_as_of` |
| `GET` | `/api/v1/portfolio/fiat-deposits/binance` | Portfolio binance fiat deposits | read-only | `app.py:2692` `portfolio_binance_fiat_deposits` |
| `POST` | `/api/v1/portfolio/jup-wallet/import-history` | Portfolio jup wallet import history | kann Daten oder Artefakte schreiben | `app.py:2674` `portfolio_jup_wallet_import_history` |
| `GET` | `/api/v1/portfolio/reconciliation` | Portfolio reconciliation | read-only | `app.py:2634` `portfolio_reconciliation` |
| `POST` | `/api/v1/portfolio/reconciliation/refresh` | Portfolio reconciliation refresh | kann Daten oder Artefakte schreiben | `app.py:2638` `portfolio_reconciliation_refresh` |
| `GET` | `/api/v1/portfolio/separation-report` | Portfolio separation report | read-only | `app.py:2688` `portfolio_separation_report` |
| `GET` | `/api/v1/portfolio/snapshot` | Portfolio snapshot | read-only | `app.py:2570` `portfolio_snapshot` |
| `GET` | `/api/v1/portfolio/sources` | Portfolio sources | read-only | `app.py:2607` `portfolio_sources` |
| `GET` | `/api/v1/portfolio/token-risk` | Portfolio token risk | read-only | `app.py:2611` `portfolio_token_risk` |
| `GET` | `/api/v1/portfolio/valuation-audit` | Portfolio valuation audit | read-only | `app.py:2578` `portfolio_valuation_audit` |
| `GET` | `/api/v1/portfolio/value-history` | Portfolio value history | read-only | `app.py:2586` `portfolio_value_history` |

## Preise

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/prices` | List price points | read-only | `app.py:2162` `list_price_points` |
| `POST` | `/api/v1/prices` | Add price point | kann Daten oder Artefakte schreiben | `app.py:2156` `add_price_point` |
| `GET` | `/api/v1/prices/as-of-gate` | Prices as of gate | read-only | `app.py:2273` `prices_as_of_gate` |
| `POST` | `/api/v1/prices/as-of-gate/backfill` | Prices as of gate backfill | kann Daten oder Artefakte schreiben | `app.py:2289` `prices_as_of_gate_backfill` |
| `POST` | `/api/v1/prices/as-of-gate/token-review-decisions` | Akzeptiert eine mint- und stichtagsgebundene Risikotoken-Bewertung | kann Daten oder Artefakte schreiben | `app.py:2301` `accept_as_of_token_valuation` |
| `GET` | `/api/v1/prices/as-of-gate/token-review-decisions.csv` | Liefert die Stichtags-Risikotoken-Entscheidungen als Beleg-CSV | read-only | `app.py:2312` `as_of_token_valuation_decisions_csv` |
| `POST` | `/api/v1/prices/backfill/current-portfolio` | Backfill current portfolio prices | kann Daten oder Artefakte schreiben | `app.py:2254` `backfill_current_portfolio_prices` |
| `POST` | `/api/v1/prices/backfill/external` | Backfill external prices | kann Daten oder Artefakte schreiben | `app.py:2234` `backfill_external_prices` |
| `GET` | `/api/v1/prices/coverage` | Price coverage | read-only | `app.py:2331` `price_coverage` |
| `POST` | `/api/v1/prices/coverage/decisions` | Add price gap decision | kann Daten oder Artefakte schreiben | `app.py:2526` `add_price_gap_decision` |
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
| `POST` | `/api/v1/prices/import/csv` | Import price csv | kann Daten oder Artefakte schreiben | `app.py:2179` `import_price_csv` |
| `POST` | `/api/v1/prices/import/csv/preview` | Preview price csv | kann Daten oder Artefakte schreiben | `app.py:2170` `preview_price_csv` |
| `POST` | `/api/v1/prices/import/v1-fx-cache` | Blockiert direkte V1-Cache-Uebernahme ohne geprueften Vertrag | HTTP 409; kein Preisimport und keine Pipeline-Neuberechnung | `app.py:2222` `import_v1_fx_cache` |
| `POST` | `/api/v1/prices/import/v1-fx-cache/preview` | Zeigt unverbindliche V1-Cache-Kandidaten ohne Uebernahmefreigabe | Kandidaten ohne Finanzimport; kalter Store kann Schema initialisieren oder migrieren | `app.py:2209` `preview_v1_fx_cache_import` |
| `GET` | `/api/v1/prices/latest` | List latest price points | read-only | `app.py:2166` `list_latest_price_points` |
| `GET` | `/api/v1/prices/quality` | Price quality | read-only | `app.py:2335` `price_quality` |
| `GET` | `/api/v1/prices/quality/binance-normalizer-review` | Price quality binance normalizer review | read-only | `app.py:2465` `price_quality_binance_normalizer_review` |
| `GET` | `/api/v1/prices/quality/closure-candidates` | Price quality closure candidates | read-only | `app.py:2481` `price_quality_closure_candidates` |
| `POST` | `/api/v1/prices/quality/decisions` | Add price quality decision | kann Daten oder Artefakte schreiben | `app.py:2487` `add_price_quality_decision` |
| `GET` | `/api/v1/prices/quality/event-quote-evidence-review` | Price quality event quote evidence review | read-only | `app.py:2473` `price_quality_event_quote_evidence_review` |
| `GET` | `/api/v1/prices/quality/group` | Price quality group | read-only | `app.py:2339` `price_quality_group` |
| `GET` | `/api/v1/prices/quality/manual-review` | Price quality manual review | read-only | `app.py:2355` `price_quality_manual_review` |
| `GET` | `/api/v1/prices/quality/solscan-signature-review` | Price quality solscan signature review | read-only | `app.py:2457` `price_quality_solscan_signature_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-apply` | Apply price quality stablecoin fx anchor prices | kann Daten oder Artefakte schreiben | `app.py:2447` `apply_price_quality_stablecoin_fx_anchor_prices` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions` | Add price quality stablecoin fx anchor preview decision | kann Daten oder Artefakte schreiben | `app.py:2435` `add_price_quality_stablecoin_fx_anchor_preview_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest` | Price quality stablecoin fx anchor preview latest | read-only | `app.py:2425` `price_quality_stablecoin_fx_anchor_preview_latest` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-impact` | Price quality stablecoin fx replacement impact | read-only | `app.py:2383` `price_quality_stablecoin_fx_replacement_impact` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-preview` | Price quality stablecoin fx replacement preview | read-only | `app.py:2371` `price_quality_stablecoin_fx_replacement_preview` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-review` | Price quality stablecoin fx review | read-only | `app.py:2363` `price_quality_stablecoin_fx_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions` | Add price quality stablecoin fx tax impact decision | kann Daten oder Artefakte schreiben | `app.py:2413` `add_price_quality_stablecoin_fx_tax_impact_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-latest` | Price quality stablecoin fx tax impact latest | read-only | `app.py:2399` `price_quality_stablecoin_fx_tax_impact_latest` |
| `GET` | `/api/v1/prices/requirements` | Price requirements | read-only | `app.py:2522` `price_requirements` |
| `DELETE` | `/api/v1/prices/{price_id}` | Delete price point | loescht | `app.py:2551` `delete_price_point` |

## Flows und Transfers

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/flows/net` | Net flows | read-only | `app.py:6760` `net_flows` |
| `POST` | `/api/v1/flows/rebuild` | Rebuild flows | kann Daten oder Artefakte schreiben | `app.py:6756` `rebuild_flows` |
| `GET` | `/api/v1/transfers/candidates` | Transfer candidates | read-only | `app.py:2147` `transfer_candidates` |

## Review

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/review/decision-suggestions` | Review decision suggestions | read-only | `app.py:3833` `review_decision_suggestions` |
| `POST` | `/api/v1/review/decision-suggestions/{suggestion_id}/accept` | Accept review decision suggestion | kann Daten oder Artefakte schreiben | `app.py:3851` `accept_review_decision_suggestion` |
| `GET` | `/api/v1/review/decisions` | List review decisions | read-only | `app.py:3829` `list_review_decisions` |
| `POST` | `/api/v1/review/decisions` | Add review decision | kann Daten oder Artefakte schreiben | `app.py:3821` `add_review_decision` |
| `GET` | `/api/v1/review/evidence-traces` | Review evidence traces | read-only | `app.py:3837` `review_evidence_traces` |
| `POST` | `/api/v1/review/evidence-traces/canonicalize` | Canonicalize review evidence traces | kann Daten oder Artefakte schreiben | `app.py:3841` `canonicalize_review_evidence_traces` |
| `GET` | `/api/v1/review/gates` | Review gates | read-only | `app.py:3803` `review_gates` |
| `GET` | `/api/v1/review/tasks` | Review tasks | read-only | `app.py:3809` `review_tasks` |

## Steuer, BMF und Steuerjahre

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/tax-filing-snapshots` | Liefert das append-only Register hashgebundener Abgabe- und Referenzpakete | read-only | `app.py:9698` `tax_filing_snapshots` |
| `GET` | `/api/v1/tax-filing-snapshots/{snapshot_id}/package.zip` | Liefert ein erneut SHA-256-geprueftes unveraenderliches Abgabepaket | read-only | `app.py:10002` `download_tax_filing_snapshot_package` |
| `POST` | `/api/v1/tax-filing-snapshots/{snapshot_id}/usage-confirmation` | Confirm tax filing snapshot usage | kann Daten oder Artefakte schreiben | `app.py:9746` `confirm_tax_filing_snapshot_usage` |
| `GET` | `/api/v1/tax-methodology/bmf-action-plan` | Tax methodology bmf action plan | read-only | `app.py:4936` `tax_methodology_bmf_action_plan` |
| `GET` | `/api/v1/tax-methodology/bmf-amendment-worklist` | Tax methodology bmf amendment worklist | read-only | `app.py:5125` `tax_methodology_bmf_amendment_worklist` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog` | Tax methodology bmf closure backlog | read-only | `app.py:4953` `tax_methodology_bmf_closure_backlog` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog-snapshot` | Tax methodology bmf closure backlog snapshot | read-only | `app.py:4961` `tax_methodology_bmf_closure_backlog_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-compliance-matrix` | Tax methodology bmf compliance matrix | read-only | `app.py:4914` `tax_methodology_bmf_compliance_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness` | Tax methodology bmf filing readiness | read-only | `app.py:4969` `tax_methodology_bmf_filing_readiness` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness-snapshot` | Tax methodology bmf filing readiness snapshot | read-only | `app.py:4984` `tax_methodology_bmf_filing_readiness_snapshot` |
| `POST` | `/api/v1/tax-methodology/bmf-filing-readiness-snapshot` | Erzeugt ausdruecklich den gebundenen BMF-Methoden-Pruefstand fuer den Umfang 2021-2025 ohne Steuerdatenkorrektur oder finale Freigabe | kann Daten oder Artefakte schreiben | `app.py:4996` `tax_methodology_bmf_filing_readiness_snapshot_refresh` |
| `GET` | `/api/v1/tax-methodology/bmf-finalization-matrix` | Tax methodology bmf finalization matrix | read-only | `app.py:5089` `tax_methodology_bmf_finalization_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-comparison` | Tax methodology bmf prior filing comparison | read-only | `app.py:5113` `tax_methodology_bmf_prior_filing_comparison` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | Tax methodology bmf prior filing declared amounts | read-only | `app.py:5217` `tax_methodology_bmf_prior_filing_declared_amounts` |
| `PUT` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | Tax methodology write bmf prior filing declared amounts | schreibt | `app.py:5225` `tax_methodology_write_bmf_prior_filing_declared_amounts` |
| `GET` | `/api/v1/tax-methodology/bmf-submission-guide` | Tax methodology bmf submission guide | read-only | `app.py:5103` `tax_methodology_bmf_submission_guide` |
| `GET` | `/api/v1/tax-methodology/legal-research/freshness` | Legal research freshness | read-only | `app.py:3481` `legal_research_freshness` |
| `GET` | `/api/v1/tax-methodology/legal-research/sources` | Legal research sources | read-only | `app.py:3471` `legal_research_sources` |
| `GET` | `/api/v1/tax-methodology/summary` | Tax methodology summary | read-only | `app.py:4902` `tax_methodology_summary` |
| `GET` | `/api/v1/tax-methodology/time-precision-audit` | Tax methodology time precision audit | read-only | `app.py:4924` `tax_methodology_time_precision_audit` |
| `GET` | `/api/v1/tax-years/business-reward-inventory-review` | Tax years business reward inventory review | read-only | `app.py:4671` `tax_years_business_reward_inventory_review` |
| `GET` | `/api/v1/tax-years/correction-map` | Tax years correction map | read-only | `app.py:4826` `tax_years_correction_map` |
| `GET` | `/api/v1/tax-years/filing-closure-overview` | Tax years filing closure overview | read-only | `app.py:4647` `tax_years_filing_closure_overview` |
| `GET` | `/api/v1/tax-years/filing-matrix` | Tax years filing matrix | read-only | `app.py:4637` `tax_years_filing_matrix` |
| `GET` | `/api/v1/tax-years/helium-swap-alchemy-audit` | Tax years helium swap alchemy audit | read-only | `app.py:7943` `tax_years_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/helium-swap-context` | Tax years helium swap context | read-only | `app.py:4856` `tax_years_helium_swap_context` |
| `GET` | `/api/v1/tax-years/helium-swap-evidence-review` | Tax years helium swap evidence review | read-only | `app.py:4864` `tax_years_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/payment-overview` | Tax years payment overview | read-only | `app.py:4627` `tax_years_payment_overview` |
| `GET` | `/api/v1/tax-years/reward-bmf-recheck` | Tax years reward bmf recheck | read-only | `app.py:5235` `tax_years_reward_bmf_recheck` |
| `GET` | `/api/v1/tax-years/reward-trading-separation` | Tax years reward trading separation | read-only | `app.py:4659` `tax_years_reward_trading_separation` |
| `GET` | `/api/v1/tax-years/solana-program-income-review` | Tax years solana program income review | read-only | `app.py:4848` `tax_years_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-fx-review` | Tax years solana stablecoin fx review | read-only | `app.py:4894` `tax_years_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-swap-context` | Tax years solana stablecoin swap context | read-only | `app.py:4886` `tax_years_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/stablecoin-fifo-review` | Tax years stablecoin fifo review | read-only | `app.py:4872` `tax_years_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/stablecoin-quote-leg-review` | Tax years stablecoin quote leg review | read-only | `app.py:4878` `tax_years_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/summary` | Tax years summary | read-only | `app.py:4617` `tax_years_summary` |
| `GET` | `/api/v1/tax-years/turnover-audit-summary` | Tax years turnover audit summary | read-only | `app.py:4836` `tax_years_turnover_audit_summary` |
| `GET` | `/api/v1/tax-years/{year}` | Tax year detail | read-only | `app.py:5239` `tax_year_detail` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-correction-review` | Tax year asset fifo correction review | read-only | `app.py:6653` `tax_year_asset_fifo_correction_review` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-drilldown` | Tax year asset fifo drilldown | read-only | `app.py:6629` `tax_year_asset_fifo_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-plausibility` | Tax year asset fifo plausibility | read-only | `app.py:6639` `tax_year_asset_fifo_plausibility` |
| `GET` | `/api/v1/tax-years/{year}/bmf-closure-appendix` | Tax year bmf closure appendix | read-only | `app.py:6711` `tax_year_bmf_closure_appendix` |
| `GET` | `/api/v1/tax-years/{year}/cex-deposit-transfer-evidence` | Tax year cex deposit transfer evidence | read-only | `app.py:5849` `tax_year_cex_deposit_transfer_evidence` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility` | Tax year cex exchange outflow anchor feasibility | read-only | `app.py:6047` `tax_year_cex_exchange_outflow_anchor_feasibility` |
| `POST` | `/api/v1/tax-years/{year}/cex-exchange-outflow-decisions` | Add tax year cex exchange outflow decision | kann Daten oder Artefakte schreiben | `app.py:6067` `add_tax_year_cex_exchange_outflow_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-evidence` | Tax year cex exchange outflow evidence | read-only | `app.py:6027` `tax_year_cex_exchange_outflow_evidence` |
| `POST` | `/api/v1/tax-years/{year}/cex-sender-ownership-decisions` | Add tax year cex sender ownership decision | kann Daten oder Artefakte schreiben | `app.py:5881` `add_tax_year_cex_sender_ownership_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-sender-ownership-latest` | Tax year cex sender ownership latest | read-only | `app.py:5865` `tax_year_cex_sender_ownership_latest` |
| `GET` | `/api/v1/tax-years/{year}/compliance-status` | Tax year compliance status | read-only | `app.py:5811` `tax_year_compliance_status` |
| `GET` | `/api/v1/tax-years/{year}/correction-map` | Tax year correction map | read-only | `app.py:5462` `tax_year_correction_map` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide` | Tax year declaration guide | read-only | `app.py:5259` `tax_year_declaration_guide` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide.html` | Tax year declaration guide html | read-only | `app.py:5281` `tax_year_declaration_guide_html` |
| `GET` | `/api/v1/tax-years/{year}/drivers` | Tax year drivers | read-only | `app.py:6563` `tax_year_drivers` |
| `GET` | `/api/v1/tax-years/{year}/evidence` | Tax year evidence | read-only | `app.py:6679` `tax_year_evidence` |
| `GET` | `/api/v1/tax-years/{year}/evidence.html` | Tax year evidence html | read-only | `app.py:6699` `tax_year_evidence_html` |
| `GET` | `/api/v1/tax-years/{year}/external-inflows` | Tax year external inflows | read-only | `app.py:6717` `tax_year_external_inflows` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report` | Erzeugt bzw. liefert den read-only Einzelpositions-, Ursachen- und Summenabgleich | read-only | `app.py:9779` `tax_filing_audit_report` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.json` | Liefert das unveraenderliche JSON-Auditartefakt | read-only | `app.py:9787` `tax_filing_audit_report_json` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.md` | Liefert das unveraenderliche Markdown-Auditartefakt | read-only | `app.py:9805` `tax_filing_audit_report_markdown` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison` | Vergleicht den eingereichten bzw. archivierten Stand je Einkunftsart mit der aktuellen Berechnung | read-only | `app.py:9763` `tax_filing_snapshot_comparison` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison.html` | Liefert die druckbare Korrekturpruefungsakte statt einer rohen JSON-Ansicht | read-only | `app.py:9929` `tax_filing_snapshot_comparison_html` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshots` | Liefert das hashgebundene Snapshot-Register fuer ein konkretes Steuerjahr | read-only | `app.py:9704` `tax_year_filing_snapshots` |
| `POST` | `/api/v1/tax-years/{year}/filing-snapshots` | Archiviert den aktuellen Paketstand oder bestaetigt eine konkrete Revision als tatsaechlich eingereicht | kann Daten oder Artefakte schreiben | `app.py:9708` `capture_tax_filing_snapshot` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary` | Tax year filing summary | read-only | `app.py:5293` `tax_year_filing_summary` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary.html` | Tax year filing summary html | read-only | `app.py:5303` `tax_year_filing_summary_html` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-acquisition-event-deltas` | Tax year gain evidence acquisition event deltas | read-only | `app.py:6618` `tax_year_gain_evidence_acquisition_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-event-deltas` | Tax year gain evidence event deltas | read-only | `app.py:6609` `tax_year_gain_evidence_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-price-deltas` | Tax year gain evidence price deltas | read-only | `app.py:6595` `tax_year_gain_evidence_price_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-review` | Tax year gain evidence review | read-only | `app.py:6587` `tax_year_gain_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/gain-loss-reality-check` | Tax year gain loss reality check | read-only | `app.py:6575` `tax_year_gain_loss_reality_check` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-alchemy-audit` | Tax year helium swap alchemy audit | read-only | `app.py:7949` `tax_year_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-context` | Tax year helium swap context | read-only | `app.py:6513` `tax_year_helium_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-evidence-review` | Tax year helium swap evidence review | read-only | `app.py:6521` `tax_year_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/income-guide` | Tax year income guide | read-only | `app.py:6495` `tax_year_income_guide` |
| `GET` | `/api/v1/tax-years/{year}/methodology` | Tax year methodology | read-only | `app.py:5801` `tax_year_methodology` |
| `POST` | `/api/v1/tax-years/{year}/private-disposal-threshold-assessment` | Private disposal threshold assessment | kann Daten oder Artefakte schreiben | `app.py:5249` `private_disposal_threshold_assessment` |
| `GET` | `/api/v1/tax-years/{year}/reports/pdf` | List tax year pdf reports | read-only | `app.py:5323` `list_tax_year_pdf_reports` |
| `POST` | `/api/v1/tax-years/{year}/reports/pdf` | Create tax year pdf report | kann Daten oder Artefakte schreiben | `app.py:5315` `create_tax_year_pdf_report` |
| `GET` | `/api/v1/tax-years/{year}/reports/pdf/{artifact_id}/files/{file_index}` | Download tax year pdf file | read-only | `app.py:5346` `download_tax_year_pdf_file` |
| `GET` | `/api/v1/tax-years/{year}/reports/pdf/{artifact_id}/manifest.json` | Download tax year pdf manifest | read-only | `app.py:5331` `download_tax_year_pdf_manifest` |
| `GET` | `/api/v1/tax-years/{year}/solana-program-income-review` | Tax year solana program income review | read-only | `app.py:6505` `tax_year_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-fx-review` | Tax year solana stablecoin fx review | read-only | `app.py:6555` `tax_year_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-swap-context` | Tax year solana stablecoin swap context | read-only | `app.py:6545` `tax_year_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-fifo-review` | Tax year stablecoin fifo review | read-only | `app.py:6529` `tax_year_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-quote-leg-review` | Tax year stablecoin quote leg review | read-only | `app.py:6537` `tax_year_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/{year}/turnover-audit` | Tax year turnover audit | read-only | `app.py:6667` `tax_year_turnover_audit` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-delta` | Tax year wallet fifo delta | read-only | `app.py:5815` `tax_year_wallet_fifo_delta` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-exchange-evidence-gaps` | Tax year wallet fifo exchange evidence gaps | read-only | `app.py:6301` `tax_year_wallet_fifo_exchange_evidence_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-gaps` | Tax year wallet fifo gaps | read-only | `app.py:5825` `tax_year_wallet_fifo_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-opening-balance-evidence` | Tax year wallet fifo opening balance evidence | read-only | `app.py:6285` `tax_year_wallet_fifo_opening_balance_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-origin-trace` | Tax year wallet fifo origin trace | read-only | `app.py:5833` `tax_year_wallet_fifo_origin_trace` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-closure` | Tax year wallet fifo provenance closure | read-only | `app.py:6236` `tax_year_wallet_fifo_provenance_closure` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-events` | Tax year wallet fifo provenance events | read-only | `app.py:6251` `tax_year_wallet_fifo_provenance_events` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-priorities` | Tax year wallet fifo provenance priorities | read-only | `app.py:6225` `tax_year_wallet_fifo_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-raw-provenance-breakdown` | Tax year wallet fifo raw provenance breakdown | read-only | `app.py:6269` `tax_year_wallet_fifo_raw_provenance_breakdown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-origin` | Tax year wallet fifo solana origin | read-only | `app.py:6468` `tax_year_wallet_fifo_solana_origin` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence` | Tax year wallet fifo solana program settlement evidence | read-only | `app.py:6350` `tax_year_wallet_fifo_solana_program_settlement_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-batch-latest` | Tax year wallet fifo solana provenance batch latest | read-only | `app.py:6339` `tax_year_wallet_fifo_solana_provenance_batch_latest` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-classification` | Tax year wallet fifo solana provenance classification | read-only | `app.py:6317` `tax_year_wallet_fifo_solana_provenance_classification` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-drilldown` | Tax year wallet fifo solana raw bmf evidence drilldown | read-only | `app.py:6416` `tax_year_wallet_fifo_solana_raw_bmf_evidence_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-summary` | Tax year wallet fifo solana raw bmf evidence summary | read-only | `app.py:6400` `tax_year_wallet_fifo_solana_raw_bmf_evidence_summary` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-priorities` | Tax year wallet fifo solana raw provenance priorities | read-only | `app.py:6368` `tax_year_wallet_fifo_solana_raw_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-senders` | Tax year wallet fifo solana raw provenance senders | read-only | `app.py:6384` `tax_year_wallet_fifo_solana_raw_provenance_senders` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-cluster-outflows` | Tax year wallet fifo solana sender cluster outflows | read-only | `app.py:6448` `tax_year_wallet_fifo_solana_sender_cluster_outflows` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-clusters` | Tax year wallet fifo solana sender clusters | read-only | `app.py:6436` `tax_year_wallet_fifo_solana_sender_clusters` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-service-swap-evidence` | Tax year wallet fifo solana service swap evidence | read-only | `app.py:6360` `tax_year_wallet_fifo_solana_service_swap_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps` | Tax year wallet fifo withdrawal gaps | read-only | `app.py:6484` `tax_year_wallet_fifo_withdrawal_gaps` |
| `GET` | `/api/v1/tax/bmf-combined-fifo-staging/latest` | Tax bmf combined fifo staging latest | read-only | `app.py:4721` `tax_bmf_combined_fifo_staging_latest` |
| `POST` | `/api/v1/tax/bmf-combined-fifo-staging/run` | Tax bmf combined fifo staging run | kann Daten oder Artefakte schreiben | `app.py:4733` `tax_bmf_combined_fifo_staging_run` |
| `GET` | `/api/v1/tax/bmf-event-price-remediation/latest` | Tax bmf event price remediation latest | read-only | `app.py:4801` `tax_bmf_event_price_remediation_latest` |
| `POST` | `/api/v1/tax/bmf-event-price-remediation/run` | Tax bmf event price remediation run | kann Daten oder Artefakte schreiben | `app.py:4813` `tax_bmf_event_price_remediation_run` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz` | Tax bmf fifo event evidence events artifact | read-only | `app.py:4753` `tax_bmf_fifo_event_evidence_events_artifact` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/latest` | Tax bmf fifo event evidence latest | read-only | `app.py:4743` `tax_bmf_fifo_event_evidence_latest` |
| `POST` | `/api/v1/tax/bmf-fifo-event-evidence/run` | Tax bmf fifo event evidence run | kann Daten oder Artefakte schreiben | `app.py:4791` `tax_bmf_fifo_event_evidence_run` |
| `GET` | `/api/v1/tax/cross-cex-transfer-evidence` | Tax cross cex transfer evidence | read-only | `app.py:4095` `tax_cross_cex_transfer_evidence` |
| `GET` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/latest` | Tax crypto swap fifo parallel preview latest | read-only | `app.py:4699` `tax_crypto_swap_fifo_parallel_preview_latest` |
| `POST` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/run` | Tax crypto swap fifo parallel preview run | kann Daten oder Artefakte schreiben | `app.py:4711` `tax_crypto_swap_fifo_parallel_preview_run` |
| `GET` | `/api/v1/tax/crypto-swap-valuation-review` | Tax crypto swap valuation review | read-only | `app.py:4683` `tax_crypto_swap_valuation_review` |
| `GET` | `/api/v1/tax/fairspot-staking-reconciliation` | Tax fairspot staking reconciliation | read-only | `app.py:4101` `tax_fairspot_staking_reconciliation` |
| `POST` | `/api/v1/tax/fifo/rebuild` | Rebuild fifo tax | kann Daten oder Artefakte schreiben | `app.py:4035` `rebuild_fifo_tax` |
| `GET` | `/api/v1/tax/holding-periods` | Tax holding periods | read-only | `app.py:4051` `tax_holding_periods` |
| `GET` | `/api/v1/tax/legacy-helium-overview` | Tax legacy helium overview | read-only | `app.py:4603` `tax_legacy_helium_overview` |
| `GET` | `/api/v1/tax/lines` | List tax lines | read-only | `app.py:4039` `list_tax_lines` |
| `GET` | `/api/v1/tax/loss-realization-planner` | Tax loss realization planner | read-only | `app.py:4065` `tax_loss_realization_planner` |
| `GET` | `/api/v1/tax/lots` | List tax lots | read-only | `app.py:4043` `list_tax_lots` |
| `GET` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipts | read-only | `app.py:4107` `tax_moonpay_receipts` |
| `POST` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipt upsert | kann Daten oder Artefakte schreiben | `app.py:4159` `tax_moonpay_receipt_upsert` |
| `GET` | `/api/v1/tax/moonpay-receipts/trade-history.csv` | Tax moonpay trade history document | read-only | `app.py:4113` `tax_moonpay_trade_history_document` |
| `GET` | `/api/v1/tax/moonpay-receipts/{tx_id}/document` | Tax moonpay receipt document | read-only | `app.py:4139` `tax_moonpay_receipt_document` |
| `GET` | `/api/v1/tax/pionex-hnt-reconciliation` | Tax pionex hnt reconciliation | read-only | `app.py:4091` `tax_pionex_hnt_reconciliation` |
| `GET` | `/api/v1/tax/service-swap-mappings` | Tax service swap mappings | read-only | `app.py:4087` `tax_service_swap_mappings` |
| `GET` | `/api/v1/tax/solana-staking-position-reconciliation` | Tax solana staking position reconciliation | read-only | `app.py:4170` `tax_solana_staking_position_reconciliation` |
| `GET` | `/api/v1/tax/summary` | Tax summary | read-only | `app.py:4083` `tax_summary` |
| `GET` | `/api/v1/tax/unmatched-disposals` | List tax unmatched disposals | read-only | `app.py:4047` `list_tax_unmatched_disposals` |
| `GET` | `/api/v1/tax/wallet-fifo-internal-transfer-carry` | Tax wallet fifo internal transfer carry | read-only | `app.py:4185` `tax_wallet_fifo_internal_transfer_carry` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/applies/latest` | Tax wallet fifo migration apply latest | read-only | `app.py:4559` `tax_wallet_fifo_migration_apply_latest` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/apply` | Tax wallet fifo migration apply | kann Daten oder Artefakte schreiben | `app.py:4548` `tax_wallet_fifo_migration_apply` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/apply-readiness` | Tax wallet fifo migration apply readiness | read-only | `app.py:4536` `tax_wallet_fifo_migration_apply_readiness` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/rehearsals` | Tax wallet fifo migration rehearsal | kann Daten oder Artefakte schreiben | `app.py:4507` `tax_wallet_fifo_migration_rehearsal` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/latest` | Tax wallet fifo migration rehearsal latest | read-only | `app.py:4518` `tax_wallet_fifo_migration_rehearsal_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/{rehearsal_id}` | Tax wallet fifo migration rehearsal by id | read-only | `app.py:4524` `tax_wallet_fifo_migration_rehearsal_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-preview` | Tax wallet fifo preview | read-only | `app.py:4176` `tax_wallet_fifo_preview` |
| `POST` | `/api/v1/tax/wallet-fifo-runs` | Tax wallet fifo parallel run | kann Daten oder Artefakte schreiben | `app.py:4197` `tax_wallet_fifo_parallel_run` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest` | Tax wallet fifo parallel run latest | read-only | `app.py:4208` `tax_wallet_fifo_parallel_run_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-acceptance` | Tax wallet fifo latest method acceptance | read-only | `app.py:4444` `tax_wallet_fifo_latest_method_acceptance` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation` | Tax wallet fifo latest method delta explanation | read-only | `app.py:4456` `tax_wallet_fifo_latest_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}` | Tax wallet fifo parallel run by id | read-only | `app.py:4472` `tax_wallet_fifo_parallel_run_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/evidence/{filename}` | Tax wallet fifo parallel run evidence | read-only | `app.py:4588` `tax_wallet_fifo_parallel_run_evidence` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance | read-only | `app.py:4483` `tax_wallet_fifo_method_acceptance` |
| `POST` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance create | kann Daten oder Artefakte schreiben | `app.py:4495` `tax_wallet_fifo_method_acceptance_create` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-delta-explanation` | Tax wallet fifo method delta explanation | read-only | `app.py:4565` `tax_wallet_fifo_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision` | Tax wallet fifo bitget strategy basis decision | read-only | `app.py:4262` `tax_wallet_fifo_bitget_strategy_basis_decision` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run_id}` | Tax wallet fifo bitget strategy basis decision create | kann Daten oder Artefakte schreiben | `app.py:4276` `tax_wallet_fifo_bitget_strategy_basis_decision_create` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps` | Tax wallet fifo bitget strategy gaps | read-only | `app.py:4214` `tax_wallet_fifo_bitget_strategy_gaps` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv` | Tax wallet fifo bitget strategy gaps csv | read-only | `app.py:4226` `tax_wallet_fifo_bitget_strategy_gaps_csv` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction` | Tax wallet fifo bitget strategy reconstruction | read-only | `app.py:4247` `tax_wallet_fifo_bitget_strategy_reconstruction` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv` | Tax wallet fifo bitget strategy reconstruction csv | read-only | `app.py:4291` `tax_wallet_fifo_bitget_strategy_reconstruction_csv` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill` | Tax wallet fifo bitget strategy reference price backfill | kann Daten oder Artefakte schreiben | `app.py:4329` `tax_wallet_fifo_bitget_strategy_reference_price_backfill` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill/latest` | Tax wallet fifo bitget strategy reference price backfill latest | read-only | `app.py:4318` `tax_wallet_fifo_bitget_strategy_reference_price_backfill_latest` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip` | Tax wallet fifo bitget strategy review package | read-only | `app.py:4401` `tax_wallet_fifo_bitget_strategy_review_package` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review.html` | Tax wallet fifo bitget strategy review html | read-only | `app.py:4371` `tax_wallet_fifo_bitget_strategy_review_html` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-support-package.zip` | Tax wallet fifo bitget support package | read-only | `app.py:4343` `tax_wallet_fifo_bitget_support_package` |

## Reports und Exporte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/export/all-transaction-decision-candidates.json` | Download all transaction decision candidates json | read-only | `app.py:7882` `download_all_transaction_decision_candidates_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-closure.json` | Download all transaction evidence closure json | read-only | `app.py:7856` `download_all_transaction_evidence_closure_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-matrix.json` | Download all transaction evidence matrix json | read-only | `app.py:7844` `download_all_transaction_evidence_matrix_json` |
| `GET` | `/api/v1/export/all-transaction-open-detail-review.json` | Download all transaction open detail review json | read-only | `app.py:7868` `download_all_transaction_open_detail_review_json` |
| `POST` | `/api/v1/export/audit` | Export audit | kann Daten oder Artefakte schreiben | `app.py:6872` `export_audit` |
| `GET` | `/api/v1/export/audit.json` | Download audit json | read-only | `app.py:6880` `download_audit_json` |
| `GET` | `/api/v1/export/binance-fiat-deposits.csv` | Download binance fiat deposits csv | read-only | `app.py:7277` `download_binance_fiat_deposits_csv` |
| `GET` | `/api/v1/export/derivative-lines.csv` | Download derivative lines csv | read-only | `app.py:7415` `download_derivative_lines_csv` |
| `POST` | `/api/v1/export/elster-prep` | Export elster prep | kann Daten oder Artefakte schreiben | `app.py:6876` `export_elster_prep` |
| `GET` | `/api/v1/export/evidence-manifest.json` | Download evidence manifest | read-only | `app.py:6788` `download_evidence_manifest` |
| `GET` | `/api/v1/export/evidence-package-index.json` | Download evidence package index | read-only | `app.py:6799` `download_evidence_package_index` |
| `GET` | `/api/v1/export/evidence-package.zip` | Download evidence package zip | read-only | `app.py:8368` `download_evidence_package_zip` |
| `GET` | `/api/v1/export/hnt-provenance-events.csv` | Download hnt provenance events csv | read-only | `app.py:7213` `download_hnt_provenance_events_csv` |
| `GET` | `/api/v1/export/hnt-provenance-timeline.csv` | Download hnt provenance timeline csv | read-only | `app.py:7153` `download_hnt_provenance_timeline_csv` |
| `GET` | `/api/v1/export/packages` | List export packages | read-only | `app.py:6768` `list_export_packages` |
| `DELETE` | `/api/v1/export/packages/{package_id}` | Delete export package | loescht | `app.py:6852` `delete_export_package` |
| `GET` | `/api/v1/export/packages/{package_id}/download.pdf` | Download export package pdf | read-only | `app.py:6812` `download_export_package_pdf` |
| `GET` | `/api/v1/export/parity-diagnostics.csv` | Download parity diagnostics csv | read-only | `app.py:7105` `download_parity_diagnostics_csv` |
| `POST` | `/api/v1/export/pdf` | Create pdf export | kann Daten oder Artefakte schreiben | `app.py:6764` `create_pdf_export` |
| `GET` | `/api/v1/export/price-gaps.csv` | Download price gaps csv | read-only | `app.py:7009` `download_price_gaps_csv` |
| `GET` | `/api/v1/export/price-requirements.csv` | Download price requirements csv | read-only | `app.py:7059` `download_price_requirements_csv` |
| `GET` | `/api/v1/export/readiness` | Export readiness | read-only | `app.py:6772` `export_readiness` |
| `GET` | `/api/v1/export/review-decisions.csv` | Download review decisions csv | read-only | `app.py:6900` `download_review_decisions_csv` |
| `GET` | `/api/v1/export/solana-failed-tx-tax-impact.json` | Download solana failed tx tax impact json | read-only | `app.py:7832` `download_solana_failed_tx_tax_impact_json` |
| `GET` | `/api/v1/export/solana-tx-alchemy-audit.json` | Download solana tx alchemy audit json | read-only | `app.py:7820` `download_solana_tx_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-external-inflows.csv` | Download tax external inflows csv | read-only | `app.py:7561` `download_tax_external_inflows_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-alchemy-audit.json` | Download tax helium swap alchemy audit json | read-only | `app.py:7957` `download_tax_helium_swap_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-helium-swap-context.csv` | Download tax helium swap context csv | read-only | `app.py:8270` `download_tax_helium_swap_context_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-evidence-review.csv` | Download tax helium swap evidence review csv | read-only | `app.py:8351` `download_tax_helium_swap_evidence_review_csv` |
| `GET` | `/api/v1/export/tax-income-guide.csv` | Download tax income guide csv | read-only | `app.py:7479` `download_tax_income_guide_csv` |
| `GET` | `/api/v1/export/tax-lines.csv` | Download tax lines csv | read-only | `app.py:7372` `download_tax_lines_csv` |
| `GET` | `/api/v1/export/tax-methodology/bmf-amendment-worklist.csv` | Download bmf amendment worklist csv | read-only | `app.py:5207` `download_bmf_amendment_worklist_csv` |
| `GET` | `/api/v1/export/tax-payment-overview.json` | Download tax payment overview json | read-only | `app.py:6889` `download_tax_payment_overview_json` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-evidence.csv` | Download tax solana stablecoin swap evidence csv | read-only | `app.py:8074` `download_tax_solana_stablecoin_swap_evidence_csv` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv` | Download tax solana stablecoin swap fifo lines csv | read-only | `app.py:8193` `download_tax_solana_stablecoin_swap_fifo_lines_csv` |
| `GET` | `/api/v1/export/tax-years/correction-map.csv` | Download tax years correction map csv | read-only | `app.py:5731` `download_tax_years_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/correction-map.csv` | Download tax year correction map csv | read-only | `app.py:5741` `download_tax_year_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/evidence-package.zip` | Download tax year evidence package zip | read-only | `app.py:8647` `download_tax_year_evidence_package_zip` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-checklist.csv` | Download tax year filing checklist csv | read-only | `app.py:5791` `download_tax_year_filing_checklist_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-snapshot-comparison.csv` | Liefert den Abgabestand-Delta je Einkunftsart als CSV | read-only | `app.py:9950` `tax_filing_snapshot_comparison_csv` |
| `GET` | `/api/v1/export/token-risk-documentation.csv` | Download token risk documentation csv | read-only | `app.py:6948` `download_token_risk_documentation_csv` |
| `GET` | `/api/v1/reports/center` | Report center | read-only | `app.py:6780` `report_center` |

## Stichtag und Zugewinn

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/divorce/coinbase/connector` | Berechnet Coinbase-Historienabdeckung und Stichtagsbestand | read-only | `app.py:3012` `divorce_coinbase_connector` |
| `GET` | `/api/v1/divorce/coinbase/connector.csv` | Liefert den Coinbase-Historien- und Stichtagsnachweis als CSV | read-only | `app.py:3022` `divorce_coinbase_connector_csv` |
| `POST` | `/api/v1/divorce/coinbase/valuation-decisions` | Bindet den serverseitigen Coinbase-Stichtagswert an das Historienmanifest | kann Daten oder Artefakte schreiben | `app.py:3037` `divorce_coinbase_valuation_decision` |
| `GET` | `/api/v1/divorce/equalization-summary` | Divorce equalization summary | read-only | `app.py:3231` `divorce_equalization_summary` |
| `GET` | `/api/v1/divorce/equalization-summary/accounts.csv` | Divorce equalization accounts csv | read-only | `app.py:3281` `divorce_equalization_accounts_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/capital-flows.csv` | Divorce equalization capital flows csv | read-only | `app.py:3337` `divorce_equalization_capital_flows_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/evidence-package.zip` | Divorce equalization evidence package zip | read-only | `app.py:3365` `divorce_equalization_evidence_package_zip` |
| `GET` | `/api/v1/divorce/equalization-summary/live-reconciliation.csv` | Divorce equalization live reconciliation csv | read-only | `app.py:3309` `divorce_equalization_live_reconciliation_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/valuation-tokens.csv` | Divorce equalization valuation tokens csv | read-only | `app.py:3253` `divorce_equalization_valuation_tokens_csv` |
| `GET` | `/api/v1/divorce/inheritance-credit-candidates` | Liefert datensparsame CAMT-Gutschriften fuer die Erbmittelpruefung | read-only | `app.py:2731` `divorce_inheritance_credit_candidates` |
| `POST` | `/api/v1/divorce/inheritance-credit-decisions` | Klassifiziert eine konkrete CAMT-Gutschrift hashgebunden als Erbmittel | kann Daten oder Artefakte schreiben | `app.py:2760` `divorce_inheritance_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-credits.csv` | Liefert alle freigegebenen Erbmittelzufluesse als Beleg-CSV | read-only | `app.py:2743` `divorce_inheritance_credits_csv` |
| `POST` | `/api/v1/divorce/inheritance-document-credit-decisions` | Bindet einen dokumentierten Netto-Erbmittelzufluss an Beleg und Betrag | kann Daten oder Artefakte schreiben | `app.py:2800` `divorce_inheritance_document_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-documents` | Liefert den datensparsamen Erbnachweis- und Reviewstatus | read-only | `app.py:2890` `divorce_inheritance_documents` |
| `POST` | `/api/v1/divorce/inheritance-documents` | Speichert einen validierten formalen Erbnachweis als Kandidat | kann Daten oder Artefakte schreiben | `app.py:2909` `divorce_inheritance_document_upload` |
| `GET` | `/api/v1/divorce/inheritance-documents.csv` | Liefert den Erbnachweis-Hashindex als CSV | read-only | `app.py:2898` `divorce_inheritance_documents_csv` |
| `POST` | `/api/v1/divorce/inheritance-documents/review-decisions` | Bindet einen gesichteten formalen Erbnachweis an SHA-256 | kann Daten oder Artefakte schreiben | `app.py:2949` `divorce_inheritance_document_review_decision` |
| `GET` | `/api/v1/divorce/inheritance-origin` | Divorce inheritance origin | read-only | `app.py:2698` `divorce_inheritance_origin` |
| `GET` | `/api/v1/divorce/inheritance-origin.csv` | Divorce inheritance origin csv | read-only | `app.py:2985` `divorce_inheritance_origin_csv` |
| `POST` | `/api/v1/divorce/service-route-evidence/decisions` | Bindet eine vollstaendig liquidierte Serviceposition an den Vermoegensfluss | kann Daten oder Artefakte schreiben | `app.py:3195` `divorce_service_route_decision` |
| `POST` | `/api/v1/divorce/service-route-evidence/refresh` | Erzeugt einen SHA-gebundenen Solana-RPC-Lebenszyklusbeleg fuer eine Serviceposition | kann Daten oder Artefakte schreiben | `app.py:3168` `divorce_service_route_evidence_refresh` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}` | Liefert den letzten validen Servicepositions-Lebenszyklusbeleg | read-only | `app.py:3181` `divorce_service_route_evidence` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}/artifacts/{filename}` | Liefert einen SHA-geprueften komprimierten Solana-RPC-Beleg | read-only | `app.py:3209` `divorce_service_route_evidence_artifact` |
| `POST` | `/api/v1/divorce/sparkasse-camt` | Importiert validierte CAMT.052-XML- oder ZIP-Belege | kann Daten oder Artefakte schreiben | `app.py:2842` `divorce_sparkasse_camt_upload` |
| `GET` | `/api/v1/divorce/sparkasse-statements` | Gleicht Sparkassen-PDF-Auszugbelege read-only gegen CAMT.052 ab | read-only | `app.py:2710` `divorce_sparkasse_statements` |
| `GET` | `/api/v1/divorce/sparkasse-statements.csv` | Liefert den datensparsamen PDF-zu-CAMT-Belegabgleich als CSV | read-only | `app.py:2718` `divorce_sparkasse_statements_csv` |
| `GET` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic documents | read-only | `app.py:3002` `divorce_trade_republic_documents` |
| `POST` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic document upload | kann Daten oder Artefakte schreiben | `app.py:3088` `divorce_trade_republic_document_upload` |
| `GET` | `/api/v1/divorce/trade-republic/documents.csv` | Divorce trade republic documents csv | read-only | `app.py:3073` `divorce_trade_republic_documents_csv` |
| `POST` | `/api/v1/divorce/trade-republic/valuation-decisions` | Divorce trade republic valuation decision | kann Daten oder Artefakte schreiben | `app.py:3132` `divorce_trade_republic_valuation_decision` |
| `POST` | `/api/v1/divorce/valuation-runs` | Divorce valuation run | kann Daten oder Artefakte schreiben | `app.py:3393` `divorce_valuation_run` |
| `GET` | `/api/v1/divorce/valuation-runs/latest` | Divorce valuation run latest | read-only | `app.py:3403` `divorce_valuation_run_latest` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}` | Divorce valuation run by id | read-only | `app.py:3407` `divorce_valuation_run_by_id` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}/evidence/{filename}` | Divorce valuation run evidence | read-only | `app.py:3416` `divorce_valuation_run_evidence` |

## KI-Aufgaben

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ai/agents` | Ai agents | read-only | `app.py:10063` `ai_agents` |
| `PUT` | `/api/v1/ai/agents` | Save ai agents | schreibt | `app.py:10067` `save_ai_agents` |
| `GET` | `/api/v1/ai/changes` | Ai change sets | read-only | `app.py:10079` `ai_change_sets` |
| `POST` | `/api/v1/ai/changes` | Create ai change set | kann Daten oder Artefakte schreiben | `app.py:10083` `create_ai_change_set` |
| `POST` | `/api/v1/ai/changes/generate` | Generate ai change set | kann Daten oder Artefakte schreiben | `app.py:10087` `generate_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}` | Ai change set | read-only | `app.py:10091` `ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/apply` | Apply ai change set | kann Daten oder Artefakte schreiben | `app.py:10107` `apply_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}/audit.json` | Ai change audit | read-only | `app.py:10121` `ai_change_audit` |
| `POST` | `/api/v1/ai/changes/{identifier}/preview` | Preview ai change set | kann Daten oder Artefakte schreiben | `app.py:10103` `preview_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/rebase` | Rebase ai change set | kann Daten oder Artefakte schreiben | `app.py:10099` `rebase_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/reject` | Reject ai change set | kann Daten oder Artefakte schreiben | `app.py:10113` `reject_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revert` | Revert ai change set | kann Daten oder Artefakte schreiben | `app.py:10117` `revert_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revise` | Revise ai change set | kann Daten oder Artefakte schreiben | `app.py:10095` `revise_ai_change_set` |
| `POST` | `/api/v1/ai/data-context` | Ai data context | kann Daten oder Artefakte schreiben | `app.py:10071` `ai_data_context` |
| `POST` | `/api/v1/ai/data-context/targets` | Ai data target context | kann Daten oder Artefakte schreiben | `app.py:10075` `ai_data_target_context` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review` | Local ai asset fifo correction review | read-only | `app.py:10182` `local_ai_asset_fifo_correction_review` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review/artifacts/{artifact}` | Download local ai asset fifo correction artifact | read-only | `app.py:10188` `download_local_ai_asset_fifo_correction_artifact` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review` | Local ai wallet fifo provenance review | read-only | `app.py:10215` `local_ai_wallet_fifo_provenance_review` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/{artifact}` | Download local ai wallet fifo provenance artifact | read-only | `app.py:10221` `download_local_ai_wallet_fifo_provenance_artifact` |
| `GET` | `/api/v1/ai/local-year-package-qa` | Local ai year package qa | read-only | `app.py:10151` `local_ai_year_package_qa` |
| `GET` | `/api/v1/ai/local-year-package-qa/artifacts/{artifact}` | Download local ai year package qa artifact | read-only | `app.py:10155` `download_local_ai_year_package_qa_artifact` |
| `GET` | `/api/v1/ai/provider` | Ai provider status | read-only | `app.py:10042` `ai_provider_status` |
| `PUT` | `/api/v1/ai/provider` | Save ai provider | schreibt | `app.py:10127` `save_ai_provider` |
| `POST` | `/api/v1/ai/provider/models` | Ai provider models | kann Daten oder Artefakte schreiben | `app.py:10131` `ai_provider_models` |
| `POST` | `/api/v1/ai/provider/test` | Test ai provider | kann Daten oder Artefakte schreiben | `app.py:10135` `test_ai_provider` |
| `GET` | `/api/v1/ai/tasks` | List ai tasks | read-only | `app.py:10147` `list_ai_tasks` |
| `POST` | `/api/v1/ai/tasks` | Create ai task | kann Daten oder Artefakte schreiben | `app.py:10143` `create_ai_task` |
| `DELETE` | `/api/v1/ai/tasks/{task_id}` | Delete ai task | loescht | `app.py:10248` `delete_ai_task` |
| `POST` | `/api/v1/ai/tasks/{task_id}/execute` | Execute ai task | kann Daten oder Artefakte schreiben | `app.py:10139` `execute_ai_task` |

## V1-Paritaet

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/parity/compare` | Compare v1 v2 parity | read-only | `app.py:3970` `compare_v1_v2_parity` |
| `POST` | `/api/v1/parity/decisions` | Add parity decision | kann Daten oder Artefakte schreiben | `app.py:4010` `add_parity_decision` |
| `GET` | `/api/v1/parity/diagnostics` | Parity diagnostics | read-only | `app.py:3974` `parity_diagnostics` |
| `GET` | `/api/v1/parity/group-detail` | Parity group detail | read-only | `app.py:3982` `parity_group_detail` |
| `GET` | `/api/v1/parity/hnt-fifo-provenance` | Parity hnt fifo provenance | read-only | `app.py:3992` `parity_hnt_fifo_provenance` |
| `GET` | `/api/v1/parity/hnt-wallet-bridge` | Parity hnt wallet bridge | read-only | `app.py:3986` `parity_hnt_wallet_bridge` |
| `GET` | `/api/v1/parity/release-readiness` | Parity release readiness | read-only | `app.py:3978` `parity_release_readiness` |
| `POST` | `/api/v1/parity/v1/import/wiso` | Import wiso v1 references | kann Daten oder Artefakte schreiben | `app.py:3936` `import_wiso_v1_references` |
| `GET` | `/api/v1/parity/v1/references` | List v1 reference metrics | read-only | `app.py:3912` `list_v1_reference_metrics` |
| `POST` | `/api/v1/parity/v1/references` | Add v1 reference metric | kann Daten oder Artefakte schreiben | `app.py:3906` `add_v1_reference_metric` |
| `DELETE` | `/api/v1/parity/v1/references/{reference_id}` | Delete v1 reference metric | loescht | `app.py:3916` `delete_v1_reference_metric` |

## Weitere Endpunkte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/activity/assets` | Activity assets | read-only | `app.py:1767` `activity_assets` |
| `GET` | `/api/v1/activity/events/{event_id}` | Activity detail | read-only | `app.py:1773` `activity_detail` |
| `POST` | `/api/v1/activity/export.csv` | Activity export | kann Daten oder Artefakte schreiben | `app.py:1780` `activity_export` |
| `POST` | `/api/v1/activity/query` | Activity query | kann Daten oder Artefakte schreiben | `app.py:1759` `activity_query` |
| `POST` | `/api/v1/demo/seed` | Seed demo | kann Daten oder Artefakte schreiben | `app.py:6752` `seed_demo` |
| `GET` | `/api/v1/derivatives/lines` | List derivative lines | read-only | `app.py:6733` `list_derivative_lines` |
| `POST` | `/api/v1/derivatives/rebuild` | Rebuild derivatives | kann Daten oder Artefakte schreiben | `app.py:6729` `rebuild_derivatives` |
| `GET` | `/api/v1/derivatives/summary` | Derivative summary | read-only | `app.py:6737` `derivative_summary` |
| `POST` | `/api/v1/pipeline/rebuild` | Rebuild pipeline | kann Daten oder Artefakte schreiben | `app.py:6741` `rebuild_pipeline` |
| `GET` | `/api/v1/updates` | Status | read-only | `updates.py:50` `status` |
| `POST` | `/api/v1/updates/check` | Check | kann Daten oder Artefakte schreiben | `updates.py:58` `check` |
| `POST` | `/api/v1/updates/handoff` | Handoff | kann Daten oder Artefakte schreiben | `updates.py:62` `handoff` |
| `PUT` | `/api/v1/updates/settings` | Settings | schreibt | `updates.py:54` `settings` |
| `GET` | `/api/v1/workspace/environment` | Workspace environment | read-only | `app.py:1723` `workspace_environment` |
| `POST` | `/api/v1/workspace/review/query` | Workspace review | kann Daten oder Artefakte schreiben | `app.py:1755` `workspace_review` |
| `GET` | `/api/v1/workspace/sources` | Workspace sources | read-only | `app.py:1728` `workspace_sources` |
| `GET` | `/api/v1/workspace/sources/{ref}` | Workspace source | read-only | `app.py:1744` `workspace_source` |
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
| `POST` | `/api/v1/workspace/sources/{ref}/sync` | Workspace source sync | kann Daten oder Artefakte schreiben | `app.py:1805` `workspace_source_sync` |
| `GET` | `/api/v1/workspace/status` | Workspace status | read-only | `app.py:1751` `workspace_status` |
| `POST` | `/api/v1/workspace/wallets` | Save public wallet address | kann Daten oder Artefakte schreiben | `app.py:1732` `save_public_wallet_address` |
