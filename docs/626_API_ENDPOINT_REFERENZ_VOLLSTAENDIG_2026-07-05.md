# Vollstaendige API Endpoint Referenz

Stand: 2026-10-28

Diese Referenz wird mit `scripts/generate_api_endpoint_reference_v2.py` direkt aus `src/steuerreport_v2/api/app.py` und seinen statisch eingebundenen Routermodulen erzeugt. Sie inventarisiert deren statisch deklarierte FastAPI-Routen. Fachliche Request-/Response- und Sicherheitsdetails stehen in `docs/API_CONTRACTS_V2.md` und zur Laufzeit in `/docs` bzw. `/openapi.json`.

## Nutzung

- `GET` ist read-only, sofern der Fachcontract nicht ausdruecklich einen externen   Live-Abruf beschreibt.
- Schreibende Methoden koennen Decisions, Imports, Preise, Jobs oder lokale   Belegartefakte erzeugen. Vor produktiver Nutzung den Fachcontract pruefen.
- Echte Steuerdaten und Secrets gehoeren nicht in Git, Dokumentation oder   Beispielrequests.

## Statistik

- Endpunkte gesamt: `463`
- GET: `329`
- POST: `115`
- PUT: `9`
- PATCH: `1`
- DELETE: `9`

## Health und API Meta

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/health` | HEALTH health | read-only | `app.py:854` `health` |
| `GET` | `/api/v1/meta/capabilities` | Api capabilities | read-only | `app.py:858` `api_capabilities` |
| `GET` | `/health` | HEALTH health | read-only | `app.py:854` `health` |

## Administration und Secrets

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/admin/cex-credentials` | Speichert cex credentials | schreibt/erzeugt Artefakte | `app.py:1167` `save_cex_credentials` |
| `GET` | `/api/v1/admin/cex-credentials/v1-takeover` | V1 cex credentials takeover report | read-only | `app.py:1339` `v1_cex_credentials_takeover_report` |
| `POST` | `/api/v1/admin/cex-credentials/v1-takeover` | Importiert v1 cex credentials | schreibt/erzeugt Artefakte | `app.py:1345` `import_v1_cex_credentials` |
| `GET` | `/api/v1/admin/connections` | Connections | read-only | `connections.py:52` `connections` |
| `POST` | `/api/v1/admin/connections` | Create | kann Daten oder Artefakte schreiben | `connections.py:56` `create` |
| `GET` | `/api/v1/admin/connections/jobs` | Jobs | read-only | `connections.py:60` `jobs` |
| `POST` | `/api/v1/admin/connections/jobs/{job_id}/cancel` | Cancel | kann Daten oder Artefakte schreiben | `connections.py:64` `cancel` |
| `PUT` | `/api/v1/admin/connections/{connection_id}` | Update | schreibt | `connections.py:68` `update` |
| `DELETE` | `/api/v1/admin/connections/{connection_id}/credentials` | Delete credentials | loescht | `connections.py:72` `delete_credentials` |
| `GET` | `/api/v1/admin/connections/{connection_id}/snapshots` | Snapshots | read-only | `connections.py:76` `snapshots` |
| `POST` | `/api/v1/admin/connections/{connection_id}/sync` | Sync | kann Daten oder Artefakte schreiben | `connections.py:84` `sync` |
| `POST` | `/api/v1/admin/connections/{connection_id}/test` | Test | kann Daten oder Artefakte schreiben | `connections.py:80` `test` |
| `GET` | `/api/v1/admin/database` | DATABASE status | read-only | `app.py:868` `database_status` |
| `GET` | `/api/v1/admin/installation` | Read installation | read-only | `app.py:745` `read_installation` |
| `PUT` | `/api/v1/admin/installation` | Write installation | schreibt | `app.py:752` `write_installation` |
| `GET` | `/api/v1/admin/installation/configs/{filename}` | Read installation config | read-only | `app.py:775` `read_installation_config` |
| `PUT` | `/api/v1/admin/installation/configs/{filename}` | Write installation config | schreibt | `app.py:782` `write_installation_config` |
| `DELETE` | `/api/v1/admin/installation/providers/{provider}` | Delete installation provider | loescht | `app.py:767` `delete_installation_provider` |
| `PUT` | `/api/v1/admin/installation/providers/{provider}` | Write installation provider | schreibt | `app.py:759` `write_installation_provider` |
| `POST` | `/api/v1/admin/jupiter/api-key` | Speichert jupiter api key | schreibt/erzeugt Artefakte | `app.py:1198` `save_jupiter_api_key` |
| `GET` | `/api/v1/admin/provider-references` | References | read-only | `request_limits.py:133` `references` |
| `GET` | `/api/v1/admin/request-limits` | Read limits | read-only | `request_limits.py:69` `read_limits` |
| `PUT` | `/api/v1/admin/request-limits` | Write limits | schreibt | `request_limits.py:73` `write_limits` |
| `GET` | `/api/v1/admin/request-limits/endpoints` | Endpoints | read-only | `request_limits.py:88` `endpoints` |
| `GET` | `/api/v1/admin/request-limits/presets` | Presets | read-only | `request_limits.py:95` `presets` |
| `POST` | `/api/v1/admin/request-limits/presets/solana_public_free` | Apply preset | kann Daten oder Artefakte schreiben | `request_limits.py:123` `apply_preset` |
| `GET` | `/api/v1/admin/request-limits/status` | Status | read-only | `request_limits.py:82` `status` |
| `GET` | `/api/v1/admin/settings` | Liste admin settings | read-only | `app.py:1129` `list_admin_settings` |
| `PATCH` | `/api/v1/admin/settings` | Aktualisiert admin setting | schreibt | `app.py:1133` `update_admin_setting` |
| `DELETE` | `/api/v1/admin/settings/{key}` | Loescht admin setting | loescht | `app.py:1149` `delete_admin_setting` |
| `GET` | `/api/v1/admin/status` | ADMIN status | read-only | `app.py:872` `admin_status` |

## Cockpit und Product Readiness

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/cockpit/summary` | COCKPIT summary | read-only | `app.py:876` `cockpit_summary` |
| `GET` | `/api/v1/product/readiness` | Produkt-Readiness fuer vorhandene Quellen, Review-Gate, Steuerjahre und Belegpakete | read-only | `app.py:884` `product_readiness` |

## Contracts

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/contracts/event-types` | EVENT types | read-only | `app.py:1378` `event_types` |

## Import und Preflight

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/import/assistant/execute` | Fuehrt aus import assistant | schreibt/erzeugt Artefakte | `app.py:1849` `execute_import_assistant` |
| `POST` | `/api/v1/import/assistant/preview` | Preview import assistant | read-only | `app.py:1824` `preview_import_assistant` |
| `GET` | `/api/v1/import/batches` | Liste import batches | read-only | `app.py:1575` `list_import_batches` |
| `POST` | `/api/v1/import/batches` | Erzeugt import batch | schreibt/erzeugt Artefakte | `app.py:1571` `create_import_batch` |
| `DELETE` | `/api/v1/import/batches/{batch_id}` | Loescht import batch | loescht | `app.py:1595` `delete_import_batch` |
| `GET` | `/api/v1/import/batches/{batch_id}` | Detailansicht import batch | read-only | `app.py:1579` `get_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/normalize` | NORMALIZE import batch | schreibt/erzeugt Artefakte | `app.py:1867` `normalize_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/run` | Fuehrt aus import pipeline | schreibt/erzeugt Artefakte | `app.py:1893` `run_import_pipeline` |
| `GET` | `/api/v1/import/batches/{batch_id}/trace.json` | Download/Export import batch trace | read-only | `app.py:1725` `download_import_batch_trace` |
| `GET` | `/api/v1/import/blockpit-solana/preflight` | BLOCKPIT solana preflight | read-only | `app.py:1432` `blockpit_solana_preflight` |
| `POST` | `/api/v1/import/blockpit-solana/price-probe` | BLOCKPIT solana price probe | optional schreibt Preise bei dry_run=false | `app.py:1450` `blockpit_solana_price_probe` |
| `GET` | `/api/v1/import/coverage` | Importiert coverage | read-only | `app.py:1400` `import_coverage` |
| `POST` | `/api/v1/import/csv/preview` | Preview csv import | read-only | `app.py:1770` `preview_csv_import` |
| `POST` | `/api/v1/import/csv/raw` | Importiert csv raw | schreibt/erzeugt Artefakte | `app.py:1747` `import_csv_raw` |
| `POST` | `/api/v1/import/file/preview` | Preview file import | read-only | `app.py:1784` `preview_file_import` |
| `POST` | `/api/v1/import/file/raw` | Importiert file raw | schreibt/erzeugt Artefakte | `app.py:1799` `import_file_raw` |
| `GET` | `/api/v1/import/jup-perps/preview` | JUP perps preview | read-only | `app.py:1557` `jup_perps_preview` |
| `GET` | `/api/v1/import/parser-preflight` | PARSER preflight | read-only | `app.py:1420` `parser_preflight` |
| `GET` | `/api/v1/import/policy/audit` | Importiert policy audit | read-only | `app.py:1414` `import_policy_audit` |
| `GET` | `/api/v1/import/profiles` | Importiert profiles | read-only | `app.py:1396` `import_profiles` |
| `GET` | `/api/v1/import/solscan/evidence-trace` | SOLSCAN evidence trace | read-only | `app.py:1507` `solscan_evidence_trace` |
| `GET` | `/api/v1/import/solscan/helium-reward-evidence` | SOLSCAN helium reward evidence | read-only | `app.py:1527` `solscan_helium_reward_evidence` |
| `POST` | `/api/v1/import/solscan/rpc-probe` | SOLSCAN rpc probe | schreibt/erzeugt Artefakte | `app.py:1491` `solscan_rpc_probe` |
| `GET` | `/api/v1/import/solscan/token-preflight` | SOLSCAN token preflight | read-only | `app.py:1471` `solscan_token_preflight` |
| `GET` | `/api/v1/import/wallet-monthly/preflight` | WALLET monthly preflight | read-only | `app.py:1539` `wallet_monthly_preflight` |

## Raw und Canonical Events

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/events/canonical` | Liste canonical events | read-only | `app.py:1620` `list_canonical_events` |
| `GET` | `/api/v1/raw/objects` | Liste raw objects | read-only | `app.py:1613` `list_raw_objects` |

## Ledger

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ledger/balances` | Liste balance positions | read-only | `app.py:1918` `list_balance_positions` |
| `POST` | `/api/v1/ledger/balances/rebuild` | Rebuild balance ledger | schreibt/erzeugt Artefakte | `app.py:1914` `rebuild_balance_ledger` |

## Quellen und Connectoren

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/connectors/catalog` | Connector catalog | read-only | `app.py:892` `connector_catalog` |
| `GET` | `/api/v1/connectors/connections` | Connector connections | read-only | `app.py:896` `connector_connections` |
| `GET` | `/api/v1/connectors/mobile/documents` | Mobile connector documents | read-only | `app.py:1023` `mobile_connector_documents` |
| `POST` | `/api/v1/connectors/mobile/documents` | Upload mobile connector document | kann Daten oder Artefakte schreiben | `app.py:964` `upload_mobile_connector_document` |
| `GET` | `/api/v1/connectors/mobile/documents/{document_id}/content` | Mobile connector document content | read-only | `app.py:1034` `mobile_connector_document_content` |
| `POST` | `/api/v1/connectors/mobile/pairings` | Create mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:900` `create_mobile_connector_pairing` |
| `GET` | `/api/v1/connectors/mobile/session` | Current mobile connector session | read-only | `app.py:945` `current_mobile_connector_session` |
| `GET` | `/api/v1/connectors/mobile/sessions` | Mobile connector sessions | read-only | `app.py:938` `mobile_connector_sessions` |
| `POST` | `/api/v1/connectors/mobile/sessions` | Exchange mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:920` `exchange_mobile_connector_pairing` |
| `DELETE` | `/api/v1/connectors/mobile/sessions/{session_id}` | Revoke mobile connector session | loescht | `app.py:1062` `revoke_mobile_connector_session` |
| `POST` | `/api/v1/connectors/wallet/challenges` | Create wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1084` `create_wallet_ownership_challenge` |
| `POST` | `/api/v1/connectors/wallet/verifications` | Verify wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1105` `verify_wallet_ownership_challenge` |
| `GET` | `/api/v1/sources/binance/asset-dividend-api-preview` | Binance asset dividend api preview | read-only | `app.py:3414` `binance_asset_dividend_api_preview` |
| `POST` | `/api/v1/sources/binance/asset-dividend-api/import` | Binance asset dividend api import | kann Daten oder Artefakte schreiben | `app.py:3542` `binance_asset_dividend_api_import` |
| `GET` | `/api/v1/sources/binance/earn-history-api-preview` | BINANCE earn history api preview | read-only | `app.py:3350` `binance_earn_history_api_preview` |
| `POST` | `/api/v1/sources/binance/earn-history-api/import` | BINANCE earn history api import | schreibt/erzeugt Artefakte | `app.py:3487` `binance_earn_history_api_import` |
| `POST` | `/api/v1/sources/binance/earn-history-harvest/import` | BINANCE earn history harvest import | schreibt/erzeugt Artefakte | `app.py:3476` `binance_earn_history_harvest_import` |
| `GET` | `/api/v1/sources/binance/earn-history-preflight` | BINANCE earn history preflight | read-only | `app.py:3344` `binance_earn_history_preflight` |
| `GET` | `/api/v1/sources/binance/reconciliation/evidence` | BINANCE reconciliation evidence | read-only | `app.py:3312` `binance_reconciliation_evidence` |
| `GET` | `/api/v1/sources/binance/withdraw-history-api-preview` | BINANCE withdraw history api preview | read-only | `app.py:3383` `binance_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/binance/withdraw-history-api/import` | BINANCE withdraw history api import | schreibt/erzeugt Artefakte | `app.py:3515` `binance_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/bitget/withdraw-history-api-preview` | BITGET withdraw history api preview | read-only | `app.py:3445` `bitget_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/bitget/withdraw-history-api/import` | BITGET withdraw history api import | schreibt/erzeugt Artefakte | `app.py:3569` `bitget_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/connector-diagnostics` | SOURCES connector diagnostics | read-only | `app.py:3233` `sources_connector_diagnostics` |
| `GET` | `/api/v1/sources/jupiter/tokens/metadata-cache` | JUPITER token metadata cache | read-only | `app.py:1255` `jupiter_token_metadata_cache` |
| `POST` | `/api/v1/sources/jupiter/tokens/metadata-cache/refresh` | Aktualisiert jupiter token metadata cache | schreibt/erzeugt Artefakte | `app.py:1273` `refresh_jupiter_token_metadata_cache` |
| `GET` | `/api/v1/sources/jupiter/tokens/risk-review` | JUPITER token risk review | read-only | `app.py:1307` `jupiter_token_risk_review` |
| `GET` | `/api/v1/sources/jupiter/tokens/search` | JUPITER token search | read-only | `app.py:1215` `jupiter_token_search` |
| `GET` | `/api/v1/sources/overview` | SOURCES overview | read-only | `app.py:3229` `sources_overview` |
| `GET` | `/api/v1/sources/registry/config` | Sources registry config | read-only | `app.py:3239` `sources_registry_config` |
| `POST` | `/api/v1/sources/registry/runs` | Sources registry run | kann Daten oder Artefakte schreiben | `app.py:3249` `sources_registry_run` |
| `GET` | `/api/v1/sources/registry/runs/latest` | Sources registry run latest | read-only | `app.py:3260` `sources_registry_run_latest` |
| `GET` | `/api/v1/sources/{source_id}` | SOURCE detail | read-only | `app.py:3278` `source_detail` |
| `GET` | `/api/v1/sources/{source_id}/reconciliation` | SOURCE reconciliation | read-only | `app.py:3294` `source_reconciliation` |

## Portfolio

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/portfolio/as-of` | PORTFOLIO as of | read-only | `app.py:2375` `portfolio_as_of` |
| `GET` | `/api/v1/portfolio/fiat-deposits/binance` | PORTFOLIO binance fiat deposits | read-only | `app.py:2485` `portfolio_binance_fiat_deposits` |
| `POST` | `/api/v1/portfolio/jup-wallet/import-history` | PORTFOLIO jup wallet import history | schreibt/erzeugt Artefakte | `app.py:2467` `portfolio_jup_wallet_import_history` |
| `GET` | `/api/v1/portfolio/reconciliation` | PORTFOLIO reconciliation | read-only | `app.py:2427` `portfolio_reconciliation` |
| `POST` | `/api/v1/portfolio/reconciliation/refresh` | PORTFOLIO reconciliation refresh | schreibt/erzeugt Artefakte | `app.py:2431` `portfolio_reconciliation_refresh` |
| `GET` | `/api/v1/portfolio/separation-report` | PORTFOLIO separation report | read-only | `app.py:2481` `portfolio_separation_report` |
| `GET` | `/api/v1/portfolio/snapshot` | PORTFOLIO snapshot | read-only | `app.py:2363` `portfolio_snapshot` |
| `GET` | `/api/v1/portfolio/sources` | PORTFOLIO sources | read-only | `app.py:2400` `portfolio_sources` |
| `GET` | `/api/v1/portfolio/token-risk` | PORTFOLIO token risk | read-only | `app.py:2404` `portfolio_token_risk` |
| `GET` | `/api/v1/portfolio/valuation-audit` | PORTFOLIO valuation audit | read-only | `app.py:2371` `portfolio_valuation_audit` |
| `GET` | `/api/v1/portfolio/value-history` | Portfolio value history | read-only | `app.py:2379` `portfolio_value_history` |

## Preise

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/prices` | Liste price points | read-only | `app.py:1937` `list_price_points` |
| `POST` | `/api/v1/prices` | Fuegt hinzu price point | schreibt/erzeugt Artefakte | `app.py:1931` `add_price_point` |
| `GET` | `/api/v1/prices/as-of-gate` | Prices as of gate | read-only | `app.py:2065` `prices_as_of_gate` |
| `POST` | `/api/v1/prices/as-of-gate/backfill` | Prices as of gate backfill | kann Daten oder Artefakte schreiben | `app.py:2081` `prices_as_of_gate_backfill` |
| `POST` | `/api/v1/prices/as-of-gate/token-review-decisions` | Akzeptiert eine mint- und stichtagsgebundene Risikotoken-Bewertung | kann Daten oder Artefakte schreiben | `app.py:2094` `accept_as_of_token_valuation` |
| `GET` | `/api/v1/prices/as-of-gate/token-review-decisions.csv` | Liefert die Stichtags-Risikotoken-Entscheidungen als Beleg-CSV | read-only | `app.py:2105` `as_of_token_valuation_decisions_csv` |
| `POST` | `/api/v1/prices/backfill/current-portfolio` | BACKFILL current portfolio prices | pruefen | `app.py:2045` `backfill_current_portfolio_prices` |
| `POST` | `/api/v1/prices/backfill/external` | BACKFILL external prices | pruefen | `app.py:2024` `backfill_external_prices` |
| `GET` | `/api/v1/prices/coverage` | PRICE coverage | read-only | `app.py:2124` `price_coverage` |
| `POST` | `/api/v1/prices/coverage/decisions` | Fuegt hinzu price gap decision | schreibt/erzeugt Artefakte | `app.py:2319` `add_price_gap_decision` |
| `GET` | `/api/v1/prices/historical/mappings` | Mappings | read-only | `historical_prices.py:44` `mappings` |
| `PUT` | `/api/v1/prices/historical/mappings` | Save mapping | schreibt | `historical_prices.py:48` `save_mapping` |
| `POST` | `/api/v1/prices/historical/plan` | Plant historische Tagespreise lokal mit Jahresuebersicht und reiner Listenpagination | read-only; keine Anbieterabfrage | `historical_prices.py:40` `plan` |
| `GET` | `/api/v1/prices/historical/previews` | Recent | read-only | `historical_prices.py:52` `recent` |
| `POST` | `/api/v1/prices/historical/previews` | Sammelt bestaetigte Preisbelege und berechnet eine isolierte Vorschau | externer Abruf und private Vorschauartefakte; keine produktive Preisuebernahme | `historical_prices.py:102` `fetch` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}` | Get | read-only | `historical_prices.py:56` `get` |
| `POST` | `/api/v1/prices/historical/previews/{request_id}/apply` | Uebernimmt bestaetigte Preise und Neuberechnung bei unveraenderten Quellen | bestaetigte Preis-/Ledger-Neuberechnung und Auditspur; keine Ereignisumklassifikation | `historical_prices.py:106` `apply` |
| `POST` | `/api/v1/prices/historical/previews/{request_id}/continue` | Ergaenzt eine kumulative Preisvorschau nach erneuter externer Bestaetigung | externer Abruf und private Vorschauartefakte; keine produktive Preisuebernahme | `historical_prices.py:64` `continue_preview` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/evidence/{sha}` | Evidence | read-only | `historical_prices.py:97` `evidence` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/report.json` | Exportiert die vollstaendige Preisvorschau und Belegbindung als JSON | read-only | `historical_prices.py:68` `json_report` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/report.md` | Exportiert die vollstaendige Jahresauswertung als Markdown | read-only | `historical_prices.py:75` `markdown_report` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/report.zip` | Exportiert saemtliche Jahreszeilen und gepruefte Originalbelege als ZIP | read-only | `historical_prices.py:81` `zip_report` |
| `GET` | `/api/v1/prices/historical/previews/{request_id}/status` | Liest laufenden oder gespeicherten Preisabrufstatus ohne Anbieterabfrage | read-only | `historical_prices.py:60` `status` |
| `POST` | `/api/v1/prices/import/csv` | Importiert price csv | schreibt/erzeugt Artefakte | `app.py:1954` `import_price_csv` |
| `POST` | `/api/v1/prices/import/csv/preview` | Preview price csv | read-only | `app.py:1945` `preview_price_csv` |
| `POST` | `/api/v1/prices/import/v1-fx-cache` | Importiert v1 fx cache | schreibt/erzeugt Artefakte | `app.py:1994` `import_v1_fx_cache` |
| `POST` | `/api/v1/prices/import/v1-fx-cache/preview` | Preview v1 fx cache import | read-only | `app.py:1984` `preview_v1_fx_cache_import` |
| `GET` | `/api/v1/prices/latest` | Liste latest price points | read-only | `app.py:1941` `list_latest_price_points` |
| `GET` | `/api/v1/prices/quality` | PRICE quality | read-only | `app.py:2128` `price_quality` |
| `GET` | `/api/v1/prices/quality/binance-normalizer-review` | PRICE quality binance normalizer review | read-only | `app.py:2258` `price_quality_binance_normalizer_review` |
| `GET` | `/api/v1/prices/quality/closure-candidates` | PRICE quality closure candidates | read-only | `app.py:2274` `price_quality_closure_candidates` |
| `POST` | `/api/v1/prices/quality/decisions` | Fuegt hinzu price quality decision | schreibt/erzeugt Artefakte | `app.py:2280` `add_price_quality_decision` |
| `GET` | `/api/v1/prices/quality/event-quote-evidence-review` | PRICE quality event quote evidence review | read-only | `app.py:2266` `price_quality_event_quote_evidence_review` |
| `GET` | `/api/v1/prices/quality/group` | PRICE quality group | read-only | `app.py:2132` `price_quality_group` |
| `GET` | `/api/v1/prices/quality/manual-review` | PRICE quality manual review | read-only | `app.py:2148` `price_quality_manual_review` |
| `GET` | `/api/v1/prices/quality/solscan-signature-review` | PRICE quality solscan signature review | read-only | `app.py:2250` `price_quality_solscan_signature_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-apply` | APPLY price quality stablecoin fx anchor prices | schreibt/erzeugt Artefakte | `app.py:2240` `apply_price_quality_stablecoin_fx_anchor_prices` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions` | Fuegt hinzu price quality stablecoin fx anchor preview decision | schreibt/erzeugt Artefakte | `app.py:2228` `add_price_quality_stablecoin_fx_anchor_preview_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest` | PRICE quality stablecoin fx anchor preview latest | read-only | `app.py:2218` `price_quality_stablecoin_fx_anchor_preview_latest` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-impact` | PRICE quality stablecoin fx replacement impact | read-only | `app.py:2176` `price_quality_stablecoin_fx_replacement_impact` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-preview` | PRICE quality stablecoin fx replacement preview | read-only | `app.py:2164` `price_quality_stablecoin_fx_replacement_preview` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-review` | PRICE quality stablecoin fx review | read-only | `app.py:2156` `price_quality_stablecoin_fx_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions` | Fuegt hinzu price quality stablecoin fx tax impact decision | schreibt/erzeugt Artefakte | `app.py:2206` `add_price_quality_stablecoin_fx_tax_impact_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-latest` | PRICE quality stablecoin fx tax impact latest | read-only | `app.py:2192` `price_quality_stablecoin_fx_tax_impact_latest` |
| `GET` | `/api/v1/prices/requirements` | PRICE requirements | read-only | `app.py:2315` `price_requirements` |
| `DELETE` | `/api/v1/prices/{price_id}` | Loescht price point | loescht | `app.py:2344` `delete_price_point` |

## Flows und Transfers

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/flows/net` | NET flows | read-only | `app.py:6396` `net_flows` |
| `POST` | `/api/v1/flows/rebuild` | Rebuild flows | schreibt/erzeugt Artefakte | `app.py:6392` `rebuild_flows` |
| `GET` | `/api/v1/transfers/candidates` | TRANSFER candidates | read-only | `app.py:1922` `transfer_candidates` |

## Review

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/review/decision-suggestions` | REVIEW decision suggestions | read-only | `app.py:3626` `review_decision_suggestions` |
| `POST` | `/api/v1/review/decision-suggestions/{suggestion_id}/accept` | ACCEPT review decision suggestion | schreibt/erzeugt Artefakte | `app.py:3644` `accept_review_decision_suggestion` |
| `GET` | `/api/v1/review/decisions` | Liste review decisions | read-only | `app.py:3622` `list_review_decisions` |
| `POST` | `/api/v1/review/decisions` | Fuegt hinzu review decision | schreibt/erzeugt Artefakte | `app.py:3614` `add_review_decision` |
| `GET` | `/api/v1/review/evidence-traces` | REVIEW evidence traces | read-only | `app.py:3630` `review_evidence_traces` |
| `POST` | `/api/v1/review/evidence-traces/canonicalize` | Kanonisiert review evidence traces | schreibt/erzeugt Artefakte | `app.py:3634` `canonicalize_review_evidence_traces` |
| `GET` | `/api/v1/review/gates` | REVIEW gates | read-only | `app.py:3596` `review_gates` |
| `GET` | `/api/v1/review/tasks` | REVIEW tasks | read-only | `app.py:3602` `review_tasks` |

## Steuer, BMF und Steuerjahre

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/tax-filing-snapshots` | Liefert das append-only Register hashgebundener Abgabe- und Referenzpakete | read-only | `app.py:9306` `tax_filing_snapshots` |
| `GET` | `/api/v1/tax-filing-snapshots/{snapshot_id}/package.zip` | Liefert ein erneut SHA-256-geprueftes unveraenderliches Abgabepaket | read-only | `app.py:9610` `download_tax_filing_snapshot_package` |
| `POST` | `/api/v1/tax-filing-snapshots/{snapshot_id}/usage-confirmation` | Confirm tax filing snapshot usage | kann Daten oder Artefakte schreiben | `app.py:9354` `confirm_tax_filing_snapshot_usage` |
| `GET` | `/api/v1/tax-methodology/bmf-action-plan` | TAX methodology bmf action plan | read-only | `app.py:4729` `tax_methodology_bmf_action_plan` |
| `GET` | `/api/v1/tax-methodology/bmf-amendment-worklist` | TAX methodology bmf amendment worklist | read-only | `app.py:4817` `tax_methodology_bmf_amendment_worklist` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog` | TAX methodology bmf closure backlog | read-only | `app.py:4746` `tax_methodology_bmf_closure_backlog` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog-snapshot` | TAX methodology bmf closure backlog snapshot | read-only | `app.py:4754` `tax_methodology_bmf_closure_backlog_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-compliance-matrix` | Tax methodology bmf compliance matrix | read-only | `app.py:4707` `tax_methodology_bmf_compliance_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness` | TAX methodology bmf filing readiness | read-only | `app.py:4762` `tax_methodology_bmf_filing_readiness` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness-snapshot` | TAX methodology bmf filing readiness snapshot | read-only | `app.py:4773` `tax_methodology_bmf_filing_readiness_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-finalization-matrix` | TAX methodology bmf finalization matrix | read-only | `app.py:4781` `tax_methodology_bmf_finalization_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-comparison` | TAX methodology bmf prior filing comparison | read-only | `app.py:4805` `tax_methodology_bmf_prior_filing_comparison` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | TAX methodology bmf prior filing declared amounts | read-only | `app.py:4909` `tax_methodology_bmf_prior_filing_declared_amounts` |
| `PUT` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | TAX methodology write bmf prior filing declared amounts | schreibt | `app.py:4917` `tax_methodology_write_bmf_prior_filing_declared_amounts` |
| `GET` | `/api/v1/tax-methodology/bmf-submission-guide` | TAX methodology bmf submission guide | read-only | `app.py:4795` `tax_methodology_bmf_submission_guide` |
| `GET` | `/api/v1/tax-methodology/legal-research/freshness` | Legal research freshness | read-only | `app.py:3274` `legal_research_freshness` |
| `GET` | `/api/v1/tax-methodology/legal-research/sources` | Legal research sources | read-only | `app.py:3264` `legal_research_sources` |
| `GET` | `/api/v1/tax-methodology/summary` | TAX methodology summary | read-only | `app.py:4695` `tax_methodology_summary` |
| `GET` | `/api/v1/tax-methodology/time-precision-audit` | Tax methodology time precision audit | read-only | `app.py:4717` `tax_methodology_time_precision_audit` |
| `GET` | `/api/v1/tax-years/business-reward-inventory-review` | Tax years business reward inventory review | read-only | `app.py:4464` `tax_years_business_reward_inventory_review` |
| `GET` | `/api/v1/tax-years/correction-map` | TAX years correction map | read-only | `app.py:4619` `tax_years_correction_map` |
| `GET` | `/api/v1/tax-years/filing-closure-overview` | TAX years filing closure overview | read-only | `app.py:4440` `tax_years_filing_closure_overview` |
| `GET` | `/api/v1/tax-years/filing-matrix` | TAX years filing matrix | read-only | `app.py:4430` `tax_years_filing_matrix` |
| `GET` | `/api/v1/tax-years/helium-swap-alchemy-audit` | TAX years helium swap alchemy audit | read-only | `app.py:7571` `tax_years_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/helium-swap-context` | TAX years helium swap context | read-only | `app.py:4649` `tax_years_helium_swap_context` |
| `GET` | `/api/v1/tax-years/helium-swap-evidence-review` | TAX years helium swap evidence review | read-only | `app.py:4657` `tax_years_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/payment-overview` | TAX years payment overview | read-only | `app.py:4420` `tax_years_payment_overview` |
| `GET` | `/api/v1/tax-years/reward-bmf-recheck` | TAX years reward bmf recheck | read-only | `app.py:4927` `tax_years_reward_bmf_recheck` |
| `GET` | `/api/v1/tax-years/reward-trading-separation` | TAX years reward trading separation | read-only | `app.py:4452` `tax_years_reward_trading_separation` |
| `GET` | `/api/v1/tax-years/solana-program-income-review` | TAX years solana program income review | read-only | `app.py:4641` `tax_years_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-fx-review` | TAX years solana stablecoin fx review | read-only | `app.py:4687` `tax_years_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-swap-context` | TAX years solana stablecoin swap context | read-only | `app.py:4679` `tax_years_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/stablecoin-fifo-review` | TAX years stablecoin fifo review | read-only | `app.py:4665` `tax_years_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/stablecoin-quote-leg-review` | TAX years stablecoin quote leg review | read-only | `app.py:4671` `tax_years_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/summary` | TAX years summary | read-only | `app.py:4410` `tax_years_summary` |
| `GET` | `/api/v1/tax-years/turnover-audit-summary` | TAX years turnover audit summary | read-only | `app.py:4629` `tax_years_turnover_audit_summary` |
| `GET` | `/api/v1/tax-years/{year}` | TAX year detail | read-only | `app.py:4931` `tax_year_detail` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-correction-review` | TAX year asset fifo correction review | read-only | `app.py:6289` `tax_year_asset_fifo_correction_review` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-drilldown` | TAX year asset fifo drilldown | read-only | `app.py:6265` `tax_year_asset_fifo_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-plausibility` | TAX year asset fifo plausibility | read-only | `app.py:6275` `tax_year_asset_fifo_plausibility` |
| `GET` | `/api/v1/tax-years/{year}/bmf-closure-appendix` | TAX year bmf closure appendix | read-only | `app.py:6347` `tax_year_bmf_closure_appendix` |
| `GET` | `/api/v1/tax-years/{year}/cex-deposit-transfer-evidence` | TAX year cex deposit transfer evidence | read-only | `app.py:5485` `tax_year_cex_deposit_transfer_evidence` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility` | TAX year cex exchange outflow anchor feasibility | read-only | `app.py:5683` `tax_year_cex_exchange_outflow_anchor_feasibility` |
| `POST` | `/api/v1/tax-years/{year}/cex-exchange-outflow-decisions` | Fuegt hinzu tax year cex exchange outflow decision | schreibt/erzeugt Artefakte | `app.py:5703` `add_tax_year_cex_exchange_outflow_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-evidence` | TAX year cex exchange outflow evidence | read-only | `app.py:5663` `tax_year_cex_exchange_outflow_evidence` |
| `POST` | `/api/v1/tax-years/{year}/cex-sender-ownership-decisions` | Fuegt hinzu tax year cex sender ownership decision | schreibt/erzeugt Artefakte | `app.py:5517` `add_tax_year_cex_sender_ownership_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-sender-ownership-latest` | TAX year cex sender ownership latest | read-only | `app.py:5501` `tax_year_cex_sender_ownership_latest` |
| `GET` | `/api/v1/tax-years/{year}/compliance-status` | TAX year compliance status | read-only | `app.py:5447` `tax_year_compliance_status` |
| `GET` | `/api/v1/tax-years/{year}/correction-map` | TAX year correction map | read-only | `app.py:5098` `tax_year_correction_map` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide` | TAX year declaration guide | read-only | `app.py:4947` `tax_year_declaration_guide` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide.html` | Tax year declaration guide html | read-only | `app.py:4969` `tax_year_declaration_guide_html` |
| `GET` | `/api/v1/tax-years/{year}/drivers` | TAX year drivers | read-only | `app.py:6199` `tax_year_drivers` |
| `GET` | `/api/v1/tax-years/{year}/evidence` | TAX year evidence | read-only | `app.py:6315` `tax_year_evidence` |
| `GET` | `/api/v1/tax-years/{year}/evidence.html` | Tax year evidence html | read-only | `app.py:6335` `tax_year_evidence_html` |
| `GET` | `/api/v1/tax-years/{year}/external-inflows` | TAX year external inflows | read-only | `app.py:6353` `tax_year_external_inflows` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report` | Erzeugt bzw. liefert den read-only Einzelpositions-, Ursachen- und Summenabgleich | read-only | `app.py:9387` `tax_filing_audit_report` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.json` | Liefert das unveraenderliche JSON-Auditartefakt | read-only | `app.py:9395` `tax_filing_audit_report_json` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.md` | Liefert das unveraenderliche Markdown-Auditartefakt | read-only | `app.py:9413` `tax_filing_audit_report_markdown` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison` | Vergleicht den eingereichten bzw. archivierten Stand je Einkunftsart mit der aktuellen Berechnung | read-only | `app.py:9371` `tax_filing_snapshot_comparison` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison.html` | Liefert die druckbare Korrekturpruefungsakte statt einer rohen JSON-Ansicht | read-only | `app.py:9537` `tax_filing_snapshot_comparison_html` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshots` | Liefert das hashgebundene Snapshot-Register fuer ein konkretes Steuerjahr | read-only | `app.py:9312` `tax_year_filing_snapshots` |
| `POST` | `/api/v1/tax-years/{year}/filing-snapshots` | Archiviert den aktuellen Paketstand oder bestaetigt eine konkrete Revision als tatsaechlich eingereicht | kann Daten oder Artefakte schreiben | `app.py:9316` `capture_tax_filing_snapshot` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary` | TAX year filing summary | read-only | `app.py:4981` `tax_year_filing_summary` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary.html` | Tax year filing summary html | read-only | `app.py:4991` `tax_year_filing_summary_html` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-acquisition-event-deltas` | TAX year gain evidence acquisition event deltas | read-only | `app.py:6254` `tax_year_gain_evidence_acquisition_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-event-deltas` | TAX year gain evidence event deltas | read-only | `app.py:6245` `tax_year_gain_evidence_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-price-deltas` | TAX year gain evidence price deltas | read-only | `app.py:6231` `tax_year_gain_evidence_price_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-review` | TAX year gain evidence review | read-only | `app.py:6223` `tax_year_gain_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/gain-loss-reality-check` | TAX year gain loss reality check | read-only | `app.py:6211` `tax_year_gain_loss_reality_check` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-alchemy-audit` | TAX year helium swap alchemy audit | read-only | `app.py:7577` `tax_year_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-context` | TAX year helium swap context | read-only | `app.py:6149` `tax_year_helium_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-evidence-review` | TAX year helium swap evidence review | read-only | `app.py:6157` `tax_year_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/income-guide` | TAX year income guide | read-only | `app.py:6131` `tax_year_income_guide` |
| `GET` | `/api/v1/tax-years/{year}/methodology` | TAX year methodology | read-only | `app.py:5437` `tax_year_methodology` |
| `GET` | `/api/v1/tax-years/{year}/solana-program-income-review` | TAX year solana program income review | read-only | `app.py:6141` `tax_year_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-fx-review` | TAX year solana stablecoin fx review | read-only | `app.py:6191` `tax_year_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-swap-context` | TAX year solana stablecoin swap context | read-only | `app.py:6181` `tax_year_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-fifo-review` | TAX year stablecoin fifo review | read-only | `app.py:6165` `tax_year_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-quote-leg-review` | TAX year stablecoin quote leg review | read-only | `app.py:6173` `tax_year_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/{year}/turnover-audit` | TAX year turnover audit | read-only | `app.py:6303` `tax_year_turnover_audit` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-delta` | TAX year wallet fifo delta | read-only | `app.py:5451` `tax_year_wallet_fifo_delta` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-exchange-evidence-gaps` | TAX year wallet fifo exchange evidence gaps | read-only | `app.py:5937` `tax_year_wallet_fifo_exchange_evidence_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-gaps` | TAX year wallet fifo gaps | read-only | `app.py:5461` `tax_year_wallet_fifo_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-opening-balance-evidence` | TAX year wallet fifo opening balance evidence | read-only | `app.py:5921` `tax_year_wallet_fifo_opening_balance_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-origin-trace` | TAX year wallet fifo origin trace | read-only | `app.py:5469` `tax_year_wallet_fifo_origin_trace` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-closure` | TAX year wallet fifo provenance closure | read-only | `app.py:5872` `tax_year_wallet_fifo_provenance_closure` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-events` | TAX year wallet fifo provenance events | read-only | `app.py:5887` `tax_year_wallet_fifo_provenance_events` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-priorities` | TAX year wallet fifo provenance priorities | read-only | `app.py:5861` `tax_year_wallet_fifo_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-raw-provenance-breakdown` | TAX year wallet fifo raw provenance breakdown | read-only | `app.py:5905` `tax_year_wallet_fifo_raw_provenance_breakdown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-origin` | TAX year wallet fifo solana origin | read-only | `app.py:6104` `tax_year_wallet_fifo_solana_origin` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence` | Tax year wallet fifo solana program settlement evidence | read-only | `app.py:5986` `tax_year_wallet_fifo_solana_program_settlement_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-batch-latest` | TAX year wallet fifo solana provenance batch latest | read-only | `app.py:5975` `tax_year_wallet_fifo_solana_provenance_batch_latest` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-classification` | TAX year wallet fifo solana provenance classification | read-only | `app.py:5953` `tax_year_wallet_fifo_solana_provenance_classification` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-drilldown` | TAX year wallet fifo solana raw bmf evidence drilldown | read-only | `app.py:6052` `tax_year_wallet_fifo_solana_raw_bmf_evidence_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-summary` | TAX year wallet fifo solana raw bmf evidence summary | read-only | `app.py:6036` `tax_year_wallet_fifo_solana_raw_bmf_evidence_summary` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-priorities` | TAX year wallet fifo solana raw provenance priorities | read-only | `app.py:6004` `tax_year_wallet_fifo_solana_raw_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-senders` | TAX year wallet fifo solana raw provenance senders | read-only | `app.py:6020` `tax_year_wallet_fifo_solana_raw_provenance_senders` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-cluster-outflows` | TAX year wallet fifo solana sender cluster outflows | read-only | `app.py:6084` `tax_year_wallet_fifo_solana_sender_cluster_outflows` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-clusters` | TAX year wallet fifo solana sender clusters | read-only | `app.py:6072` `tax_year_wallet_fifo_solana_sender_clusters` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-service-swap-evidence` | Tax year wallet fifo solana service swap evidence | read-only | `app.py:5996` `tax_year_wallet_fifo_solana_service_swap_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps` | TAX year wallet fifo withdrawal gaps | read-only | `app.py:6120` `tax_year_wallet_fifo_withdrawal_gaps` |
| `GET` | `/api/v1/tax/bmf-combined-fifo-staging/latest` | Tax bmf combined fifo staging latest | read-only | `app.py:4514` `tax_bmf_combined_fifo_staging_latest` |
| `POST` | `/api/v1/tax/bmf-combined-fifo-staging/run` | Tax bmf combined fifo staging run | kann Daten oder Artefakte schreiben | `app.py:4526` `tax_bmf_combined_fifo_staging_run` |
| `GET` | `/api/v1/tax/bmf-event-price-remediation/latest` | Tax bmf event price remediation latest | read-only | `app.py:4594` `tax_bmf_event_price_remediation_latest` |
| `POST` | `/api/v1/tax/bmf-event-price-remediation/run` | Tax bmf event price remediation run | kann Daten oder Artefakte schreiben | `app.py:4606` `tax_bmf_event_price_remediation_run` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz` | Tax bmf fifo event evidence events artifact | read-only | `app.py:4546` `tax_bmf_fifo_event_evidence_events_artifact` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/latest` | Tax bmf fifo event evidence latest | read-only | `app.py:4536` `tax_bmf_fifo_event_evidence_latest` |
| `POST` | `/api/v1/tax/bmf-fifo-event-evidence/run` | Tax bmf fifo event evidence run | kann Daten oder Artefakte schreiben | `app.py:4584` `tax_bmf_fifo_event_evidence_run` |
| `GET` | `/api/v1/tax/cross-cex-transfer-evidence` | Tax cross cex transfer evidence | read-only | `app.py:3888` `tax_cross_cex_transfer_evidence` |
| `GET` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/latest` | Tax crypto swap fifo parallel preview latest | read-only | `app.py:4492` `tax_crypto_swap_fifo_parallel_preview_latest` |
| `POST` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/run` | Tax crypto swap fifo parallel preview run | kann Daten oder Artefakte schreiben | `app.py:4504` `tax_crypto_swap_fifo_parallel_preview_run` |
| `GET` | `/api/v1/tax/crypto-swap-valuation-review` | Tax crypto swap valuation review | read-only | `app.py:4476` `tax_crypto_swap_valuation_review` |
| `GET` | `/api/v1/tax/fairspot-staking-reconciliation` | Tax fairspot staking reconciliation | read-only | `app.py:3894` `tax_fairspot_staking_reconciliation` |
| `POST` | `/api/v1/tax/fifo/rebuild` | Rebuild fifo tax | schreibt/erzeugt Artefakte | `app.py:3828` `rebuild_fifo_tax` |
| `GET` | `/api/v1/tax/holding-periods` | TAX holding periods | read-only | `app.py:3844` `tax_holding_periods` |
| `GET` | `/api/v1/tax/legacy-helium-overview` | TAX legacy helium overview | read-only | `app.py:4396` `tax_legacy_helium_overview` |
| `GET` | `/api/v1/tax/lines` | Liste tax lines | read-only | `app.py:3832` `list_tax_lines` |
| `GET` | `/api/v1/tax/loss-realization-planner` | TAX loss realization planner | read-only | `app.py:3858` `tax_loss_realization_planner` |
| `GET` | `/api/v1/tax/lots` | Liste tax lots | read-only | `app.py:3836` `list_tax_lots` |
| `GET` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipts | read-only | `app.py:3900` `tax_moonpay_receipts` |
| `POST` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipt upsert | kann Daten oder Artefakte schreiben | `app.py:3952` `tax_moonpay_receipt_upsert` |
| `GET` | `/api/v1/tax/moonpay-receipts/trade-history.csv` | Tax moonpay trade history document | read-only | `app.py:3906` `tax_moonpay_trade_history_document` |
| `GET` | `/api/v1/tax/moonpay-receipts/{tx_id}/document` | Tax moonpay receipt document | read-only | `app.py:3932` `tax_moonpay_receipt_document` |
| `GET` | `/api/v1/tax/pionex-hnt-reconciliation` | Tax pionex hnt reconciliation | read-only | `app.py:3884` `tax_pionex_hnt_reconciliation` |
| `GET` | `/api/v1/tax/service-swap-mappings` | Tax service swap mappings | read-only | `app.py:3880` `tax_service_swap_mappings` |
| `GET` | `/api/v1/tax/solana-staking-position-reconciliation` | Tax solana staking position reconciliation | read-only | `app.py:3963` `tax_solana_staking_position_reconciliation` |
| `GET` | `/api/v1/tax/summary` | TAX summary | read-only | `app.py:3876` `tax_summary` |
| `GET` | `/api/v1/tax/unmatched-disposals` | Liste tax unmatched disposals | read-only | `app.py:3840` `list_tax_unmatched_disposals` |
| `GET` | `/api/v1/tax/wallet-fifo-internal-transfer-carry` | Tax wallet fifo internal transfer carry | read-only | `app.py:3978` `tax_wallet_fifo_internal_transfer_carry` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/applies/latest` | Tax wallet fifo migration apply latest | read-only | `app.py:4352` `tax_wallet_fifo_migration_apply_latest` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/apply` | Tax wallet fifo migration apply | kann Daten oder Artefakte schreiben | `app.py:4341` `tax_wallet_fifo_migration_apply` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/apply-readiness` | Tax wallet fifo migration apply readiness | read-only | `app.py:4329` `tax_wallet_fifo_migration_apply_readiness` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/rehearsals` | Tax wallet fifo migration rehearsal | kann Daten oder Artefakte schreiben | `app.py:4300` `tax_wallet_fifo_migration_rehearsal` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/latest` | Tax wallet fifo migration rehearsal latest | read-only | `app.py:4311` `tax_wallet_fifo_migration_rehearsal_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/{rehearsal_id}` | Tax wallet fifo migration rehearsal by id | read-only | `app.py:4317` `tax_wallet_fifo_migration_rehearsal_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-preview` | TAX wallet fifo preview | read-only | `app.py:3969` `tax_wallet_fifo_preview` |
| `POST` | `/api/v1/tax/wallet-fifo-runs` | Tax wallet fifo parallel run | kann Daten oder Artefakte schreiben | `app.py:3990` `tax_wallet_fifo_parallel_run` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest` | Tax wallet fifo parallel run latest | read-only | `app.py:4001` `tax_wallet_fifo_parallel_run_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-acceptance` | Tax wallet fifo latest method acceptance | read-only | `app.py:4237` `tax_wallet_fifo_latest_method_acceptance` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation` | Tax wallet fifo latest method delta explanation | read-only | `app.py:4249` `tax_wallet_fifo_latest_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}` | Tax wallet fifo parallel run by id | read-only | `app.py:4265` `tax_wallet_fifo_parallel_run_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/evidence/{filename}` | Tax wallet fifo parallel run evidence | read-only | `app.py:4381` `tax_wallet_fifo_parallel_run_evidence` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance | read-only | `app.py:4276` `tax_wallet_fifo_method_acceptance` |
| `POST` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance create | kann Daten oder Artefakte schreiben | `app.py:4288` `tax_wallet_fifo_method_acceptance_create` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-delta-explanation` | Tax wallet fifo method delta explanation | read-only | `app.py:4358` `tax_wallet_fifo_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision` | Tax wallet fifo bitget strategy basis decision | read-only | `app.py:4055` `tax_wallet_fifo_bitget_strategy_basis_decision` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run_id}` | Tax wallet fifo bitget strategy basis decision create | kann Daten oder Artefakte schreiben | `app.py:4069` `tax_wallet_fifo_bitget_strategy_basis_decision_create` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps` | Tax wallet fifo bitget strategy gaps | read-only | `app.py:4007` `tax_wallet_fifo_bitget_strategy_gaps` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv` | Tax wallet fifo bitget strategy gaps csv | read-only | `app.py:4019` `tax_wallet_fifo_bitget_strategy_gaps_csv` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction` | Tax wallet fifo bitget strategy reconstruction | read-only | `app.py:4040` `tax_wallet_fifo_bitget_strategy_reconstruction` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv` | Tax wallet fifo bitget strategy reconstruction csv | read-only | `app.py:4084` `tax_wallet_fifo_bitget_strategy_reconstruction_csv` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill` | Tax wallet fifo bitget strategy reference price backfill | kann Daten oder Artefakte schreiben | `app.py:4122` `tax_wallet_fifo_bitget_strategy_reference_price_backfill` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill/latest` | Tax wallet fifo bitget strategy reference price backfill latest | read-only | `app.py:4111` `tax_wallet_fifo_bitget_strategy_reference_price_backfill_latest` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip` | Tax wallet fifo bitget strategy review package | read-only | `app.py:4194` `tax_wallet_fifo_bitget_strategy_review_package` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review.html` | Tax wallet fifo bitget strategy review html | read-only | `app.py:4164` `tax_wallet_fifo_bitget_strategy_review_html` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-support-package.zip` | Tax wallet fifo bitget support package | read-only | `app.py:4136` `tax_wallet_fifo_bitget_support_package` |

## Reports und Exporte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/export/all-transaction-decision-candidates.json` | Download/Export all transaction decision candidates json | read-only | `app.py:7510` `download_all_transaction_decision_candidates_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-closure.json` | Download/Export all transaction evidence closure json | read-only | `app.py:7484` `download_all_transaction_evidence_closure_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-matrix.json` | Download/Export all transaction evidence matrix json | read-only | `app.py:7472` `download_all_transaction_evidence_matrix_json` |
| `GET` | `/api/v1/export/all-transaction-open-detail-review.json` | Download/Export all transaction open detail review json | read-only | `app.py:7496` `download_all_transaction_open_detail_review_json` |
| `POST` | `/api/v1/export/audit` | EXPORT audit | pruefen | `app.py:6502` `export_audit` |
| `GET` | `/api/v1/export/audit.json` | Download/Export audit json | read-only | `app.py:6510` `download_audit_json` |
| `GET` | `/api/v1/export/binance-fiat-deposits.csv` | Download/Export binance fiat deposits csv | read-only | `app.py:6907` `download_binance_fiat_deposits_csv` |
| `GET` | `/api/v1/export/derivative-lines.csv` | Download/Export derivative lines csv | read-only | `app.py:7043` `download_derivative_lines_csv` |
| `POST` | `/api/v1/export/elster-prep` | EXPORT elster prep | pruefen | `app.py:6506` `export_elster_prep` |
| `GET` | `/api/v1/export/evidence-manifest.json` | Download/Export evidence manifest | read-only | `app.py:6424` `download_evidence_manifest` |
| `GET` | `/api/v1/export/evidence-package-index.json` | Download/Export evidence package index | read-only | `app.py:6435` `download_evidence_package_index` |
| `GET` | `/api/v1/export/evidence-package.zip` | Download/Export evidence package zip | read-only | `app.py:7996` `download_evidence_package_zip` |
| `GET` | `/api/v1/export/hnt-provenance-events.csv` | Download/Export hnt provenance events csv | read-only | `app.py:6843` `download_hnt_provenance_events_csv` |
| `GET` | `/api/v1/export/hnt-provenance-timeline.csv` | Download/Export hnt provenance timeline csv | read-only | `app.py:6783` `download_hnt_provenance_timeline_csv` |
| `GET` | `/api/v1/export/packages` | Liste export packages | read-only | `app.py:6404` `list_export_packages` |
| `DELETE` | `/api/v1/export/packages/{package_id}` | Loescht export package | loescht | `app.py:6482` `delete_export_package` |
| `GET` | `/api/v1/export/packages/{package_id}/download.pdf` | Download/Export export package pdf | read-only | `app.py:6448` `download_export_package_pdf` |
| `GET` | `/api/v1/export/parity-diagnostics.csv` | Download/Export parity diagnostics csv | read-only | `app.py:6735` `download_parity_diagnostics_csv` |
| `POST` | `/api/v1/export/pdf` | Erzeugt pdf export | schreibt/erzeugt Artefakte | `app.py:6400` `create_pdf_export` |
| `GET` | `/api/v1/export/price-gaps.csv` | Download/Export price gaps csv | read-only | `app.py:6639` `download_price_gaps_csv` |
| `GET` | `/api/v1/export/price-requirements.csv` | Download/Export price requirements csv | read-only | `app.py:6689` `download_price_requirements_csv` |
| `GET` | `/api/v1/export/readiness` | EXPORT readiness | read-only | `app.py:6408` `export_readiness` |
| `GET` | `/api/v1/export/review-decisions.csv` | Download/Export review decisions csv | read-only | `app.py:6530` `download_review_decisions_csv` |
| `GET` | `/api/v1/export/solana-failed-tx-tax-impact.json` | Download/Export solana failed tx tax impact json | read-only | `app.py:7460` `download_solana_failed_tx_tax_impact_json` |
| `GET` | `/api/v1/export/solana-tx-alchemy-audit.json` | Download/Export solana tx alchemy audit json | read-only | `app.py:7448` `download_solana_tx_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-external-inflows.csv` | Download/Export tax external inflows csv | read-only | `app.py:7189` `download_tax_external_inflows_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-alchemy-audit.json` | Download/Export tax helium swap alchemy audit json | read-only | `app.py:7585` `download_tax_helium_swap_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-helium-swap-context.csv` | Download/Export tax helium swap context csv | read-only | `app.py:7898` `download_tax_helium_swap_context_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-evidence-review.csv` | Download/Export tax helium swap evidence review csv | read-only | `app.py:7979` `download_tax_helium_swap_evidence_review_csv` |
| `GET` | `/api/v1/export/tax-income-guide.csv` | Download/Export tax income guide csv | read-only | `app.py:7107` `download_tax_income_guide_csv` |
| `GET` | `/api/v1/export/tax-lines.csv` | Download/Export tax lines csv | read-only | `app.py:7000` `download_tax_lines_csv` |
| `GET` | `/api/v1/export/tax-methodology/bmf-amendment-worklist.csv` | Download/Export bmf amendment worklist csv | read-only | `app.py:4899` `download_bmf_amendment_worklist_csv` |
| `GET` | `/api/v1/export/tax-payment-overview.json` | Download/Export tax payment overview json | read-only | `app.py:6519` `download_tax_payment_overview_json` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-evidence.csv` | Download/Export tax solana stablecoin swap evidence csv | read-only | `app.py:7702` `download_tax_solana_stablecoin_swap_evidence_csv` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv` | Download/Export tax solana stablecoin swap fifo lines csv | read-only | `app.py:7821` `download_tax_solana_stablecoin_swap_fifo_lines_csv` |
| `GET` | `/api/v1/export/tax-years/correction-map.csv` | Download/Export tax years correction map csv | read-only | `app.py:5367` `download_tax_years_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/correction-map.csv` | Download/Export tax year correction map csv | read-only | `app.py:5377` `download_tax_year_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/evidence-package.zip` | Download/Export tax year evidence package zip | read-only | `app.py:8275` `download_tax_year_evidence_package_zip` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-checklist.csv` | Download/Export tax year filing checklist csv | read-only | `app.py:5427` `download_tax_year_filing_checklist_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-snapshot-comparison.csv` | Liefert den Abgabestand-Delta je Einkunftsart als CSV | read-only | `app.py:9558` `tax_filing_snapshot_comparison_csv` |
| `GET` | `/api/v1/export/token-risk-documentation.csv` | Download/Export token risk documentation csv | read-only | `app.py:6578` `download_token_risk_documentation_csv` |
| `GET` | `/api/v1/reports/center` | REPORT center | read-only | `app.py:6416` `report_center` |

## Stichtag und Zugewinn

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/divorce/coinbase/connector` | Berechnet Coinbase-Historienabdeckung und Stichtagsbestand | read-only | `app.py:2805` `divorce_coinbase_connector` |
| `GET` | `/api/v1/divorce/coinbase/connector.csv` | Liefert den Coinbase-Historien- und Stichtagsnachweis als CSV | read-only | `app.py:2815` `divorce_coinbase_connector_csv` |
| `POST` | `/api/v1/divorce/coinbase/valuation-decisions` | Bindet den serverseitigen Coinbase-Stichtagswert an das Historienmanifest | kann Daten oder Artefakte schreiben | `app.py:2830` `divorce_coinbase_valuation_decision` |
| `GET` | `/api/v1/divorce/equalization-summary` | DIVORCE equalization summary | read-only | `app.py:3024` `divorce_equalization_summary` |
| `GET` | `/api/v1/divorce/equalization-summary/accounts.csv` | DIVORCE equalization accounts csv | read-only | `app.py:3074` `divorce_equalization_accounts_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/capital-flows.csv` | Divorce equalization capital flows csv | read-only | `app.py:3130` `divorce_equalization_capital_flows_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/evidence-package.zip` | DIVORCE equalization evidence package zip | read-only | `app.py:3158` `divorce_equalization_evidence_package_zip` |
| `GET` | `/api/v1/divorce/equalization-summary/live-reconciliation.csv` | DIVORCE equalization live reconciliation csv | read-only | `app.py:3102` `divorce_equalization_live_reconciliation_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/valuation-tokens.csv` | DIVORCE equalization valuation tokens csv | read-only | `app.py:3046` `divorce_equalization_valuation_tokens_csv` |
| `GET` | `/api/v1/divorce/inheritance-credit-candidates` | Liefert datensparsame CAMT-Gutschriften fuer die Erbmittelpruefung | read-only | `app.py:2524` `divorce_inheritance_credit_candidates` |
| `POST` | `/api/v1/divorce/inheritance-credit-decisions` | Klassifiziert eine konkrete CAMT-Gutschrift hashgebunden als Erbmittel | kann Daten oder Artefakte schreiben | `app.py:2553` `divorce_inheritance_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-credits.csv` | Liefert alle freigegebenen Erbmittelzufluesse als Beleg-CSV | read-only | `app.py:2536` `divorce_inheritance_credits_csv` |
| `POST` | `/api/v1/divorce/inheritance-document-credit-decisions` | Bindet einen dokumentierten Netto-Erbmittelzufluss an Beleg und Betrag | kann Daten oder Artefakte schreiben | `app.py:2593` `divorce_inheritance_document_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-documents` | Liefert den datensparsamen Erbnachweis- und Reviewstatus | read-only | `app.py:2683` `divorce_inheritance_documents` |
| `POST` | `/api/v1/divorce/inheritance-documents` | Speichert einen validierten formalen Erbnachweis als Kandidat | kann Daten oder Artefakte schreiben | `app.py:2702` `divorce_inheritance_document_upload` |
| `GET` | `/api/v1/divorce/inheritance-documents.csv` | Liefert den Erbnachweis-Hashindex als CSV | read-only | `app.py:2691` `divorce_inheritance_documents_csv` |
| `POST` | `/api/v1/divorce/inheritance-documents/review-decisions` | Bindet einen gesichteten formalen Erbnachweis an SHA-256 | kann Daten oder Artefakte schreiben | `app.py:2742` `divorce_inheritance_document_review_decision` |
| `GET` | `/api/v1/divorce/inheritance-origin` | Divorce inheritance origin | read-only | `app.py:2491` `divorce_inheritance_origin` |
| `GET` | `/api/v1/divorce/inheritance-origin.csv` | Divorce inheritance origin csv | read-only | `app.py:2778` `divorce_inheritance_origin_csv` |
| `POST` | `/api/v1/divorce/service-route-evidence/decisions` | Bindet eine vollstaendig liquidierte Serviceposition an den Vermoegensfluss | kann Daten oder Artefakte schreiben | `app.py:2988` `divorce_service_route_decision` |
| `POST` | `/api/v1/divorce/service-route-evidence/refresh` | Erzeugt einen SHA-gebundenen Solana-RPC-Lebenszyklusbeleg fuer eine Serviceposition | kann Daten oder Artefakte schreiben | `app.py:2961` `divorce_service_route_evidence_refresh` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}` | Liefert den letzten validen Servicepositions-Lebenszyklusbeleg | read-only | `app.py:2974` `divorce_service_route_evidence` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}/artifacts/{filename}` | Liefert einen SHA-geprueften komprimierten Solana-RPC-Beleg | read-only | `app.py:3002` `divorce_service_route_evidence_artifact` |
| `POST` | `/api/v1/divorce/sparkasse-camt` | Importiert validierte CAMT.052-XML- oder ZIP-Belege | kann Daten oder Artefakte schreiben | `app.py:2635` `divorce_sparkasse_camt_upload` |
| `GET` | `/api/v1/divorce/sparkasse-statements` | Gleicht Sparkassen-PDF-Auszugbelege read-only gegen CAMT.052 ab | read-only | `app.py:2503` `divorce_sparkasse_statements` |
| `GET` | `/api/v1/divorce/sparkasse-statements.csv` | Liefert den datensparsamen PDF-zu-CAMT-Belegabgleich als CSV | read-only | `app.py:2511` `divorce_sparkasse_statements_csv` |
| `GET` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic documents | read-only | `app.py:2795` `divorce_trade_republic_documents` |
| `POST` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic document upload | kann Daten oder Artefakte schreiben | `app.py:2881` `divorce_trade_republic_document_upload` |
| `GET` | `/api/v1/divorce/trade-republic/documents.csv` | Divorce trade republic documents csv | read-only | `app.py:2866` `divorce_trade_republic_documents_csv` |
| `POST` | `/api/v1/divorce/trade-republic/valuation-decisions` | Divorce trade republic valuation decision | kann Daten oder Artefakte schreiben | `app.py:2925` `divorce_trade_republic_valuation_decision` |
| `POST` | `/api/v1/divorce/valuation-runs` | Divorce valuation run | kann Daten oder Artefakte schreiben | `app.py:3186` `divorce_valuation_run` |
| `GET` | `/api/v1/divorce/valuation-runs/latest` | Divorce valuation run latest | read-only | `app.py:3196` `divorce_valuation_run_latest` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}` | Divorce valuation run by id | read-only | `app.py:3200` `divorce_valuation_run_by_id` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}/evidence/{filename}` | Divorce valuation run evidence | read-only | `app.py:3209` `divorce_valuation_run_evidence` |

## KI-Aufgaben

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ai/agents` | Ai agents | read-only | `app.py:9671` `ai_agents` |
| `PUT` | `/api/v1/ai/agents` | Save ai agents | schreibt | `app.py:9675` `save_ai_agents` |
| `GET` | `/api/v1/ai/changes` | Ai change sets | read-only | `app.py:9683` `ai_change_sets` |
| `POST` | `/api/v1/ai/changes` | Create ai change set | kann Daten oder Artefakte schreiben | `app.py:9687` `create_ai_change_set` |
| `POST` | `/api/v1/ai/changes/generate` | Generate ai change set | kann Daten oder Artefakte schreiben | `app.py:9691` `generate_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}` | Ai change set | read-only | `app.py:9695` `ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/apply` | Apply ai change set | kann Daten oder Artefakte schreiben | `app.py:9707` `apply_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}/audit.json` | Ai change audit | read-only | `app.py:9721` `ai_change_audit` |
| `POST` | `/api/v1/ai/changes/{identifier}/preview` | Preview ai change set | kann Daten oder Artefakte schreiben | `app.py:9703` `preview_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/reject` | Reject ai change set | kann Daten oder Artefakte schreiben | `app.py:9713` `reject_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revert` | Revert ai change set | kann Daten oder Artefakte schreiben | `app.py:9717` `revert_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revise` | Revise ai change set | kann Daten oder Artefakte schreiben | `app.py:9699` `revise_ai_change_set` |
| `POST` | `/api/v1/ai/data-context` | Ai data context | kann Daten oder Artefakte schreiben | `app.py:9679` `ai_data_context` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review` | LOCAL ai asset fifo correction review | read-only | `app.py:9782` `local_ai_asset_fifo_correction_review` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review/artifacts/{artifact}` | Download/Export local ai asset fifo correction artifact | read-only | `app.py:9788` `download_local_ai_asset_fifo_correction_artifact` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review` | LOCAL ai wallet fifo provenance review | read-only | `app.py:9815` `local_ai_wallet_fifo_provenance_review` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/{artifact}` | Download/Export local ai wallet fifo provenance artifact | read-only | `app.py:9821` `download_local_ai_wallet_fifo_provenance_artifact` |
| `GET` | `/api/v1/ai/local-year-package-qa` | LOCAL ai year package qa | read-only | `app.py:9751` `local_ai_year_package_qa` |
| `GET` | `/api/v1/ai/local-year-package-qa/artifacts/{artifact}` | Download/Export local ai year package qa artifact | read-only | `app.py:9755` `download_local_ai_year_package_qa_artifact` |
| `GET` | `/api/v1/ai/provider` | Ai provider status | read-only | `app.py:9650` `ai_provider_status` |
| `PUT` | `/api/v1/ai/provider` | Save ai provider | schreibt | `app.py:9727` `save_ai_provider` |
| `POST` | `/api/v1/ai/provider/models` | Ai provider models | kann Daten oder Artefakte schreiben | `app.py:9731` `ai_provider_models` |
| `POST` | `/api/v1/ai/provider/test` | Test ai provider | kann Daten oder Artefakte schreiben | `app.py:9735` `test_ai_provider` |
| `GET` | `/api/v1/ai/tasks` | Liste ai tasks | read-only | `app.py:9747` `list_ai_tasks` |
| `POST` | `/api/v1/ai/tasks` | Erzeugt ai task | schreibt/erzeugt Artefakte | `app.py:9743` `create_ai_task` |
| `DELETE` | `/api/v1/ai/tasks/{task_id}` | Loescht ai task | loescht | `app.py:9848` `delete_ai_task` |
| `POST` | `/api/v1/ai/tasks/{task_id}/execute` | Execute ai task | kann Daten oder Artefakte schreiben | `app.py:9739` `execute_ai_task` |

## V1-Paritaet

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/parity/compare` | Vergleicht v1 v2 parity | read-only | `app.py:3763` `compare_v1_v2_parity` |
| `POST` | `/api/v1/parity/decisions` | Fuegt hinzu parity decision | schreibt/erzeugt Artefakte | `app.py:3803` `add_parity_decision` |
| `GET` | `/api/v1/parity/diagnostics` | PARITY diagnostics | read-only | `app.py:3767` `parity_diagnostics` |
| `GET` | `/api/v1/parity/group-detail` | PARITY group detail | read-only | `app.py:3775` `parity_group_detail` |
| `GET` | `/api/v1/parity/hnt-fifo-provenance` | PARITY hnt fifo provenance | read-only | `app.py:3785` `parity_hnt_fifo_provenance` |
| `GET` | `/api/v1/parity/hnt-wallet-bridge` | PARITY hnt wallet bridge | read-only | `app.py:3779` `parity_hnt_wallet_bridge` |
| `GET` | `/api/v1/parity/release-readiness` | PARITY release readiness | read-only | `app.py:3771` `parity_release_readiness` |
| `POST` | `/api/v1/parity/v1/import/wiso` | Importiert wiso v1 references | schreibt/erzeugt Artefakte | `app.py:3729` `import_wiso_v1_references` |
| `GET` | `/api/v1/parity/v1/references` | Liste v1 reference metrics | read-only | `app.py:3705` `list_v1_reference_metrics` |
| `POST` | `/api/v1/parity/v1/references` | Fuegt hinzu v1 reference metric | schreibt/erzeugt Artefakte | `app.py:3699` `add_v1_reference_metric` |
| `DELETE` | `/api/v1/parity/v1/references/{reference_id}` | Loescht v1 reference metric | loescht | `app.py:3709` `delete_v1_reference_metric` |

## Weitere Endpunkte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/activity/assets` | Activity assets | read-only | `app.py:1670` `activity_assets` |
| `GET` | `/api/v1/activity/events/{event_id}` | Activity detail | read-only | `app.py:1676` `activity_detail` |
| `POST` | `/api/v1/activity/export.csv` | Activity export | kann Daten oder Artefakte schreiben | `app.py:1683` `activity_export` |
| `POST` | `/api/v1/activity/query` | Activity query | kann Daten oder Artefakte schreiben | `app.py:1662` `activity_query` |
| `POST` | `/api/v1/demo/seed` | SEED demo | schreibt/erzeugt Artefakte | `app.py:6388` `seed_demo` |
| `GET` | `/api/v1/derivatives/lines` | Liste derivative lines | read-only | `app.py:6369` `list_derivative_lines` |
| `POST` | `/api/v1/derivatives/rebuild` | Rebuild derivatives | schreibt/erzeugt Artefakte | `app.py:6365` `rebuild_derivatives` |
| `GET` | `/api/v1/derivatives/summary` | DERIVATIVE summary | read-only | `app.py:6373` `derivative_summary` |
| `POST` | `/api/v1/pipeline/rebuild` | Rebuild pipeline | schreibt/erzeugt Artefakte | `app.py:6377` `rebuild_pipeline` |
| `GET` | `/api/v1/workspace/environment` | Workspace environment | read-only | `app.py:1626` `workspace_environment` |
| `POST` | `/api/v1/workspace/review/query` | Workspace review | kann Daten oder Artefakte schreiben | `app.py:1658` `workspace_review` |
| `GET` | `/api/v1/workspace/sources` | Workspace sources | read-only | `app.py:1631` `workspace_sources` |
| `GET` | `/api/v1/workspace/sources/{ref}` | Workspace source | read-only | `app.py:1647` `workspace_source` |
| `GET` | `/api/v1/workspace/sources/{ref}/history` | Liest Abruffaehigkeit und gespeicherte Historienauftraege der konkreten Quelle | read-only | `history.py:47` `history` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs` | Startet bestaetigten externen Abruf und isolierte Vorschau ohne produktiven Finanzimport | kann Daten oder Artefakte schreiben | `history.py:51` `start` |
| `GET` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}` | Liest den gespeicherten quellengebundenen Auftragsstatus | read-only | `history.py:55` `job` |
| `GET` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/audit.json` | Liest Quellenbindung, Originalhashes, Vorschau und Importfreigabe | read-only | `history.py:81` `audit` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/cancel` | Bricht Folgeabrufe und Importfreigabe ab; Originalbelege bleiben erhalten | kann Daten oder Artefakte schreiben | `history.py:63` `cancel` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/import` | Uebernimmt unveraenderte Vorschau nach Import- und Berechnungsfreigabe atomar | kann Daten oder Artefakte schreiben | `history.py:71` `apply` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/pause` | Speichert eine Pause fuer den laufenden Abruf | kann Daten oder Artefakte schreiben | `history.py:59` `pause` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/repreview` | Repreview | kann Daten oder Artefakte schreiben | `history.py:77` `repreview` |
| `POST` | `/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/resume` | Setzt den Abruf nach ausdruecklicher Anbieterbestaetigung am gespeicherten Cursor fort | kann Daten oder Artefakte schreiben | `history.py:67` `resume` |
| `POST` | `/api/v1/workspace/sources/{ref}/sync` | Workspace source sync | kann Daten oder Artefakte schreiben | `app.py:1708` `workspace_source_sync` |
| `GET` | `/api/v1/workspace/status` | Workspace status | read-only | `app.py:1654` `workspace_status` |
| `POST` | `/api/v1/workspace/wallets` | Save public wallet address | kann Daten oder Artefakte schreiben | `app.py:1635` `save_public_wallet_address` |
