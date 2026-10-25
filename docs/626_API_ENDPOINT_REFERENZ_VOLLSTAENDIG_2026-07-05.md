# Vollstaendige API Endpoint Referenz

Stand: 2026-10-25

Diese Referenz wird mit `scripts/generate_api_endpoint_reference_v2.py` direkt aus `src/steuerreport_v2/api/app.py` erzeugt. Sie inventarisiert jede statisch deklarierte FastAPI-Route. Fachliche Request-/Response- und Sicherheitsdetails stehen in `docs/API_CONTRACTS_V2.md` und zur Laufzeit in `/docs` bzw. `/openapi.json`.

## Nutzung

- `GET` ist read-only, sofern der Fachcontract nicht ausdruecklich einen externen   Live-Abruf beschreibt.
- Schreibende Methoden koennen Decisions, Imports, Preise, Jobs oder lokale   Belegartefakte erzeugen. Vor produktiver Nutzung den Fachcontract pruefen.
- Echte Steuerdaten und Secrets gehoeren nicht in Git, Dokumentation oder   Beispielrequests.

## Statistik

- Endpunkte gesamt: `412`
- GET: `303`
- POST: `95`
- PUT: `5`
- PATCH: `1`
- DELETE: `8`

## Health und API Meta

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/health` | HEALTH health | read-only | `app.py:836` `health` |
| `GET` | `/api/v1/meta/capabilities` | Api capabilities | read-only | `app.py:840` `api_capabilities` |
| `GET` | `/health` | HEALTH health | read-only | `app.py:836` `health` |

## Administration und Secrets

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/admin/cex-credentials` | Speichert cex credentials | schreibt/erzeugt Artefakte | `app.py:1149` `save_cex_credentials` |
| `GET` | `/api/v1/admin/cex-credentials/v1-takeover` | V1 cex credentials takeover report | read-only | `app.py:1321` `v1_cex_credentials_takeover_report` |
| `POST` | `/api/v1/admin/cex-credentials/v1-takeover` | Importiert v1 cex credentials | schreibt/erzeugt Artefakte | `app.py:1327` `import_v1_cex_credentials` |
| `GET` | `/api/v1/admin/database` | DATABASE status | read-only | `app.py:850` `database_status` |
| `GET` | `/api/v1/admin/installation` | Read installation | read-only | `app.py:727` `read_installation` |
| `PUT` | `/api/v1/admin/installation` | Write installation | schreibt | `app.py:734` `write_installation` |
| `GET` | `/api/v1/admin/installation/configs/{filename}` | Read installation config | read-only | `app.py:757` `read_installation_config` |
| `PUT` | `/api/v1/admin/installation/configs/{filename}` | Write installation config | schreibt | `app.py:764` `write_installation_config` |
| `DELETE` | `/api/v1/admin/installation/providers/{provider}` | Delete installation provider | loescht | `app.py:749` `delete_installation_provider` |
| `PUT` | `/api/v1/admin/installation/providers/{provider}` | Write installation provider | schreibt | `app.py:741` `write_installation_provider` |
| `POST` | `/api/v1/admin/jupiter/api-key` | Speichert jupiter api key | schreibt/erzeugt Artefakte | `app.py:1180` `save_jupiter_api_key` |
| `GET` | `/api/v1/admin/settings` | Liste admin settings | read-only | `app.py:1111` `list_admin_settings` |
| `PATCH` | `/api/v1/admin/settings` | Aktualisiert admin setting | schreibt | `app.py:1115` `update_admin_setting` |
| `DELETE` | `/api/v1/admin/settings/{key}` | Loescht admin setting | loescht | `app.py:1131` `delete_admin_setting` |
| `GET` | `/api/v1/admin/status` | ADMIN status | read-only | `app.py:854` `admin_status` |

## Cockpit und Product Readiness

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/cockpit/summary` | COCKPIT summary | read-only | `app.py:858` `cockpit_summary` |
| `GET` | `/api/v1/product/readiness` | Produkt-Readiness fuer vorhandene Quellen, Review-Gate, Steuerjahre und Belegpakete | read-only | `app.py:866` `product_readiness` |

## Contracts

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/contracts/event-types` | EVENT types | read-only | `app.py:1360` `event_types` |

## Import und Preflight

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/import/assistant/execute` | Fuehrt aus import assistant | schreibt/erzeugt Artefakte | `app.py:1732` `execute_import_assistant` |
| `POST` | `/api/v1/import/assistant/preview` | Preview import assistant | read-only | `app.py:1707` `preview_import_assistant` |
| `GET` | `/api/v1/import/batches` | Liste import batches | read-only | `app.py:1557` `list_import_batches` |
| `POST` | `/api/v1/import/batches` | Erzeugt import batch | schreibt/erzeugt Artefakte | `app.py:1553` `create_import_batch` |
| `DELETE` | `/api/v1/import/batches/{batch_id}` | Loescht import batch | loescht | `app.py:1577` `delete_import_batch` |
| `GET` | `/api/v1/import/batches/{batch_id}` | Detailansicht import batch | read-only | `app.py:1561` `get_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/normalize` | NORMALIZE import batch | schreibt/erzeugt Artefakte | `app.py:1750` `normalize_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/run` | Fuehrt aus import pipeline | schreibt/erzeugt Artefakte | `app.py:1776` `run_import_pipeline` |
| `GET` | `/api/v1/import/batches/{batch_id}/trace.json` | Download/Export import batch trace | read-only | `app.py:1608` `download_import_batch_trace` |
| `GET` | `/api/v1/import/blockpit-solana/preflight` | BLOCKPIT solana preflight | read-only | `app.py:1414` `blockpit_solana_preflight` |
| `POST` | `/api/v1/import/blockpit-solana/price-probe` | BLOCKPIT solana price probe | optional schreibt Preise bei dry_run=false | `app.py:1432` `blockpit_solana_price_probe` |
| `GET` | `/api/v1/import/coverage` | Importiert coverage | read-only | `app.py:1382` `import_coverage` |
| `POST` | `/api/v1/import/csv/preview` | Preview csv import | read-only | `app.py:1653` `preview_csv_import` |
| `POST` | `/api/v1/import/csv/raw` | Importiert csv raw | schreibt/erzeugt Artefakte | `app.py:1630` `import_csv_raw` |
| `POST` | `/api/v1/import/file/preview` | Preview file import | read-only | `app.py:1667` `preview_file_import` |
| `POST` | `/api/v1/import/file/raw` | Importiert file raw | schreibt/erzeugt Artefakte | `app.py:1682` `import_file_raw` |
| `GET` | `/api/v1/import/jup-perps/preview` | JUP perps preview | read-only | `app.py:1539` `jup_perps_preview` |
| `GET` | `/api/v1/import/parser-preflight` | PARSER preflight | read-only | `app.py:1402` `parser_preflight` |
| `GET` | `/api/v1/import/policy/audit` | Importiert policy audit | read-only | `app.py:1396` `import_policy_audit` |
| `GET` | `/api/v1/import/profiles` | Importiert profiles | read-only | `app.py:1378` `import_profiles` |
| `GET` | `/api/v1/import/solscan/evidence-trace` | SOLSCAN evidence trace | read-only | `app.py:1489` `solscan_evidence_trace` |
| `GET` | `/api/v1/import/solscan/helium-reward-evidence` | SOLSCAN helium reward evidence | read-only | `app.py:1509` `solscan_helium_reward_evidence` |
| `POST` | `/api/v1/import/solscan/rpc-probe` | SOLSCAN rpc probe | schreibt/erzeugt Artefakte | `app.py:1473` `solscan_rpc_probe` |
| `GET` | `/api/v1/import/solscan/token-preflight` | SOLSCAN token preflight | read-only | `app.py:1453` `solscan_token_preflight` |
| `GET` | `/api/v1/import/wallet-monthly/preflight` | WALLET monthly preflight | read-only | `app.py:1521` `wallet_monthly_preflight` |

## Raw und Canonical Events

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/events/canonical` | Liste canonical events | read-only | `app.py:1602` `list_canonical_events` |
| `GET` | `/api/v1/raw/objects` | Liste raw objects | read-only | `app.py:1595` `list_raw_objects` |

## Ledger

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ledger/balances` | Liste balance positions | read-only | `app.py:1801` `list_balance_positions` |
| `POST` | `/api/v1/ledger/balances/rebuild` | Rebuild balance ledger | schreibt/erzeugt Artefakte | `app.py:1797` `rebuild_balance_ledger` |

## Quellen und Connectoren

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/connectors/catalog` | Connector catalog | read-only | `app.py:874` `connector_catalog` |
| `GET` | `/api/v1/connectors/connections` | Connector connections | read-only | `app.py:878` `connector_connections` |
| `GET` | `/api/v1/connectors/mobile/documents` | Mobile connector documents | read-only | `app.py:1005` `mobile_connector_documents` |
| `POST` | `/api/v1/connectors/mobile/documents` | Upload mobile connector document | kann Daten oder Artefakte schreiben | `app.py:946` `upload_mobile_connector_document` |
| `GET` | `/api/v1/connectors/mobile/documents/{document_id}/content` | Mobile connector document content | read-only | `app.py:1016` `mobile_connector_document_content` |
| `POST` | `/api/v1/connectors/mobile/pairings` | Create mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:882` `create_mobile_connector_pairing` |
| `GET` | `/api/v1/connectors/mobile/session` | Current mobile connector session | read-only | `app.py:927` `current_mobile_connector_session` |
| `GET` | `/api/v1/connectors/mobile/sessions` | Mobile connector sessions | read-only | `app.py:920` `mobile_connector_sessions` |
| `POST` | `/api/v1/connectors/mobile/sessions` | Exchange mobile connector pairing | kann Daten oder Artefakte schreiben | `app.py:902` `exchange_mobile_connector_pairing` |
| `DELETE` | `/api/v1/connectors/mobile/sessions/{session_id}` | Revoke mobile connector session | loescht | `app.py:1044` `revoke_mobile_connector_session` |
| `POST` | `/api/v1/connectors/wallet/challenges` | Create wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1066` `create_wallet_ownership_challenge` |
| `POST` | `/api/v1/connectors/wallet/verifications` | Verify wallet ownership challenge | kann Daten oder Artefakte schreiben | `app.py:1087` `verify_wallet_ownership_challenge` |
| `GET` | `/api/v1/sources/binance/asset-dividend-api-preview` | Binance asset dividend api preview | read-only | `app.py:3284` `binance_asset_dividend_api_preview` |
| `POST` | `/api/v1/sources/binance/asset-dividend-api/import` | Binance asset dividend api import | kann Daten oder Artefakte schreiben | `app.py:3412` `binance_asset_dividend_api_import` |
| `GET` | `/api/v1/sources/binance/earn-history-api-preview` | BINANCE earn history api preview | read-only | `app.py:3220` `binance_earn_history_api_preview` |
| `POST` | `/api/v1/sources/binance/earn-history-api/import` | BINANCE earn history api import | schreibt/erzeugt Artefakte | `app.py:3357` `binance_earn_history_api_import` |
| `POST` | `/api/v1/sources/binance/earn-history-harvest/import` | BINANCE earn history harvest import | schreibt/erzeugt Artefakte | `app.py:3346` `binance_earn_history_harvest_import` |
| `GET` | `/api/v1/sources/binance/earn-history-preflight` | BINANCE earn history preflight | read-only | `app.py:3214` `binance_earn_history_preflight` |
| `GET` | `/api/v1/sources/binance/reconciliation/evidence` | BINANCE reconciliation evidence | read-only | `app.py:3182` `binance_reconciliation_evidence` |
| `GET` | `/api/v1/sources/binance/withdraw-history-api-preview` | BINANCE withdraw history api preview | read-only | `app.py:3253` `binance_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/binance/withdraw-history-api/import` | BINANCE withdraw history api import | schreibt/erzeugt Artefakte | `app.py:3385` `binance_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/bitget/withdraw-history-api-preview` | BITGET withdraw history api preview | read-only | `app.py:3315` `bitget_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/bitget/withdraw-history-api/import` | BITGET withdraw history api import | schreibt/erzeugt Artefakte | `app.py:3439` `bitget_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/connector-diagnostics` | SOURCES connector diagnostics | read-only | `app.py:3103` `sources_connector_diagnostics` |
| `GET` | `/api/v1/sources/jupiter/tokens/metadata-cache` | JUPITER token metadata cache | read-only | `app.py:1237` `jupiter_token_metadata_cache` |
| `POST` | `/api/v1/sources/jupiter/tokens/metadata-cache/refresh` | Aktualisiert jupiter token metadata cache | schreibt/erzeugt Artefakte | `app.py:1255` `refresh_jupiter_token_metadata_cache` |
| `GET` | `/api/v1/sources/jupiter/tokens/risk-review` | JUPITER token risk review | read-only | `app.py:1289` `jupiter_token_risk_review` |
| `GET` | `/api/v1/sources/jupiter/tokens/search` | JUPITER token search | read-only | `app.py:1197` `jupiter_token_search` |
| `GET` | `/api/v1/sources/overview` | SOURCES overview | read-only | `app.py:3099` `sources_overview` |
| `GET` | `/api/v1/sources/registry/config` | Sources registry config | read-only | `app.py:3109` `sources_registry_config` |
| `POST` | `/api/v1/sources/registry/runs` | Sources registry run | kann Daten oder Artefakte schreiben | `app.py:3119` `sources_registry_run` |
| `GET` | `/api/v1/sources/registry/runs/latest` | Sources registry run latest | read-only | `app.py:3130` `sources_registry_run_latest` |
| `GET` | `/api/v1/sources/{source_id}` | SOURCE detail | read-only | `app.py:3148` `source_detail` |
| `GET` | `/api/v1/sources/{source_id}/reconciliation` | SOURCE reconciliation | read-only | `app.py:3164` `source_reconciliation` |

## Portfolio

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/portfolio/as-of` | PORTFOLIO as of | read-only | `app.py:2258` `portfolio_as_of` |
| `GET` | `/api/v1/portfolio/fiat-deposits/binance` | PORTFOLIO binance fiat deposits | read-only | `app.py:2355` `portfolio_binance_fiat_deposits` |
| `POST` | `/api/v1/portfolio/jup-wallet/import-history` | PORTFOLIO jup wallet import history | schreibt/erzeugt Artefakte | `app.py:2345` `portfolio_jup_wallet_import_history` |
| `GET` | `/api/v1/portfolio/reconciliation` | PORTFOLIO reconciliation | read-only | `app.py:2310` `portfolio_reconciliation` |
| `POST` | `/api/v1/portfolio/reconciliation/refresh` | PORTFOLIO reconciliation refresh | schreibt/erzeugt Artefakte | `app.py:2314` `portfolio_reconciliation_refresh` |
| `GET` | `/api/v1/portfolio/separation-report` | PORTFOLIO separation report | read-only | `app.py:2351` `portfolio_separation_report` |
| `GET` | `/api/v1/portfolio/snapshot` | PORTFOLIO snapshot | read-only | `app.py:2246` `portfolio_snapshot` |
| `GET` | `/api/v1/portfolio/sources` | PORTFOLIO sources | read-only | `app.py:2283` `portfolio_sources` |
| `GET` | `/api/v1/portfolio/token-risk` | PORTFOLIO token risk | read-only | `app.py:2287` `portfolio_token_risk` |
| `GET` | `/api/v1/portfolio/valuation-audit` | PORTFOLIO valuation audit | read-only | `app.py:2254` `portfolio_valuation_audit` |
| `GET` | `/api/v1/portfolio/value-history` | Portfolio value history | read-only | `app.py:2262` `portfolio_value_history` |

## Preise

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/prices` | Liste price points | read-only | `app.py:1820` `list_price_points` |
| `POST` | `/api/v1/prices` | Fuegt hinzu price point | schreibt/erzeugt Artefakte | `app.py:1814` `add_price_point` |
| `GET` | `/api/v1/prices/as-of-gate` | Prices as of gate | read-only | `app.py:1948` `prices_as_of_gate` |
| `POST` | `/api/v1/prices/as-of-gate/backfill` | Prices as of gate backfill | kann Daten oder Artefakte schreiben | `app.py:1964` `prices_as_of_gate_backfill` |
| `POST` | `/api/v1/prices/as-of-gate/token-review-decisions` | Akzeptiert eine mint- und stichtagsgebundene Risikotoken-Bewertung | kann Daten oder Artefakte schreiben | `app.py:1977` `accept_as_of_token_valuation` |
| `GET` | `/api/v1/prices/as-of-gate/token-review-decisions.csv` | Liefert die Stichtags-Risikotoken-Entscheidungen als Beleg-CSV | read-only | `app.py:1988` `as_of_token_valuation_decisions_csv` |
| `POST` | `/api/v1/prices/backfill/current-portfolio` | BACKFILL current portfolio prices | pruefen | `app.py:1928` `backfill_current_portfolio_prices` |
| `POST` | `/api/v1/prices/backfill/external` | BACKFILL external prices | pruefen | `app.py:1907` `backfill_external_prices` |
| `GET` | `/api/v1/prices/coverage` | PRICE coverage | read-only | `app.py:2007` `price_coverage` |
| `POST` | `/api/v1/prices/coverage/decisions` | Fuegt hinzu price gap decision | schreibt/erzeugt Artefakte | `app.py:2202` `add_price_gap_decision` |
| `POST` | `/api/v1/prices/import/csv` | Importiert price csv | schreibt/erzeugt Artefakte | `app.py:1837` `import_price_csv` |
| `POST` | `/api/v1/prices/import/csv/preview` | Preview price csv | read-only | `app.py:1828` `preview_price_csv` |
| `POST` | `/api/v1/prices/import/v1-fx-cache` | Importiert v1 fx cache | schreibt/erzeugt Artefakte | `app.py:1877` `import_v1_fx_cache` |
| `POST` | `/api/v1/prices/import/v1-fx-cache/preview` | Preview v1 fx cache import | read-only | `app.py:1867` `preview_v1_fx_cache_import` |
| `GET` | `/api/v1/prices/latest` | Liste latest price points | read-only | `app.py:1824` `list_latest_price_points` |
| `GET` | `/api/v1/prices/quality` | PRICE quality | read-only | `app.py:2011` `price_quality` |
| `GET` | `/api/v1/prices/quality/binance-normalizer-review` | PRICE quality binance normalizer review | read-only | `app.py:2141` `price_quality_binance_normalizer_review` |
| `GET` | `/api/v1/prices/quality/closure-candidates` | PRICE quality closure candidates | read-only | `app.py:2157` `price_quality_closure_candidates` |
| `POST` | `/api/v1/prices/quality/decisions` | Fuegt hinzu price quality decision | schreibt/erzeugt Artefakte | `app.py:2163` `add_price_quality_decision` |
| `GET` | `/api/v1/prices/quality/event-quote-evidence-review` | PRICE quality event quote evidence review | read-only | `app.py:2149` `price_quality_event_quote_evidence_review` |
| `GET` | `/api/v1/prices/quality/group` | PRICE quality group | read-only | `app.py:2015` `price_quality_group` |
| `GET` | `/api/v1/prices/quality/manual-review` | PRICE quality manual review | read-only | `app.py:2031` `price_quality_manual_review` |
| `GET` | `/api/v1/prices/quality/solscan-signature-review` | PRICE quality solscan signature review | read-only | `app.py:2133` `price_quality_solscan_signature_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-apply` | APPLY price quality stablecoin fx anchor prices | schreibt/erzeugt Artefakte | `app.py:2123` `apply_price_quality_stablecoin_fx_anchor_prices` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions` | Fuegt hinzu price quality stablecoin fx anchor preview decision | schreibt/erzeugt Artefakte | `app.py:2111` `add_price_quality_stablecoin_fx_anchor_preview_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest` | PRICE quality stablecoin fx anchor preview latest | read-only | `app.py:2101` `price_quality_stablecoin_fx_anchor_preview_latest` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-impact` | PRICE quality stablecoin fx replacement impact | read-only | `app.py:2059` `price_quality_stablecoin_fx_replacement_impact` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-preview` | PRICE quality stablecoin fx replacement preview | read-only | `app.py:2047` `price_quality_stablecoin_fx_replacement_preview` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-review` | PRICE quality stablecoin fx review | read-only | `app.py:2039` `price_quality_stablecoin_fx_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions` | Fuegt hinzu price quality stablecoin fx tax impact decision | schreibt/erzeugt Artefakte | `app.py:2089` `add_price_quality_stablecoin_fx_tax_impact_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-latest` | PRICE quality stablecoin fx tax impact latest | read-only | `app.py:2075` `price_quality_stablecoin_fx_tax_impact_latest` |
| `GET` | `/api/v1/prices/requirements` | PRICE requirements | read-only | `app.py:2198` `price_requirements` |
| `DELETE` | `/api/v1/prices/{price_id}` | Loescht price point | loescht | `app.py:2227` `delete_price_point` |

## Flows und Transfers

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/flows/net` | NET flows | read-only | `app.py:6259` `net_flows` |
| `POST` | `/api/v1/flows/rebuild` | Rebuild flows | schreibt/erzeugt Artefakte | `app.py:6255` `rebuild_flows` |
| `GET` | `/api/v1/transfers/candidates` | TRANSFER candidates | read-only | `app.py:1805` `transfer_candidates` |

## Review

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/review/decision-suggestions` | REVIEW decision suggestions | read-only | `app.py:3496` `review_decision_suggestions` |
| `POST` | `/api/v1/review/decision-suggestions/{suggestion_id}/accept` | ACCEPT review decision suggestion | schreibt/erzeugt Artefakte | `app.py:3514` `accept_review_decision_suggestion` |
| `GET` | `/api/v1/review/decisions` | Liste review decisions | read-only | `app.py:3492` `list_review_decisions` |
| `POST` | `/api/v1/review/decisions` | Fuegt hinzu review decision | schreibt/erzeugt Artefakte | `app.py:3484` `add_review_decision` |
| `GET` | `/api/v1/review/evidence-traces` | REVIEW evidence traces | read-only | `app.py:3500` `review_evidence_traces` |
| `POST` | `/api/v1/review/evidence-traces/canonicalize` | Kanonisiert review evidence traces | schreibt/erzeugt Artefakte | `app.py:3504` `canonicalize_review_evidence_traces` |
| `GET` | `/api/v1/review/gates` | REVIEW gates | read-only | `app.py:3466` `review_gates` |
| `GET` | `/api/v1/review/tasks` | REVIEW tasks | read-only | `app.py:3472` `review_tasks` |

## Steuer, BMF und Steuerjahre

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/tax-filing-snapshots` | Liefert das append-only Register hashgebundener Abgabe- und Referenzpakete | read-only | `app.py:9169` `tax_filing_snapshots` |
| `GET` | `/api/v1/tax-filing-snapshots/{snapshot_id}/package.zip` | Liefert ein erneut SHA-256-geprueftes unveraenderliches Abgabepaket | read-only | `app.py:9473` `download_tax_filing_snapshot_package` |
| `POST` | `/api/v1/tax-filing-snapshots/{snapshot_id}/usage-confirmation` | Confirm tax filing snapshot usage | kann Daten oder Artefakte schreiben | `app.py:9217` `confirm_tax_filing_snapshot_usage` |
| `GET` | `/api/v1/tax-methodology/bmf-action-plan` | TAX methodology bmf action plan | read-only | `app.py:4599` `tax_methodology_bmf_action_plan` |
| `GET` | `/api/v1/tax-methodology/bmf-amendment-worklist` | TAX methodology bmf amendment worklist | read-only | `app.py:4687` `tax_methodology_bmf_amendment_worklist` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog` | TAX methodology bmf closure backlog | read-only | `app.py:4616` `tax_methodology_bmf_closure_backlog` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog-snapshot` | TAX methodology bmf closure backlog snapshot | read-only | `app.py:4624` `tax_methodology_bmf_closure_backlog_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-compliance-matrix` | Tax methodology bmf compliance matrix | read-only | `app.py:4577` `tax_methodology_bmf_compliance_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness` | TAX methodology bmf filing readiness | read-only | `app.py:4632` `tax_methodology_bmf_filing_readiness` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness-snapshot` | TAX methodology bmf filing readiness snapshot | read-only | `app.py:4643` `tax_methodology_bmf_filing_readiness_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-finalization-matrix` | TAX methodology bmf finalization matrix | read-only | `app.py:4651` `tax_methodology_bmf_finalization_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-comparison` | TAX methodology bmf prior filing comparison | read-only | `app.py:4675` `tax_methodology_bmf_prior_filing_comparison` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | TAX methodology bmf prior filing declared amounts | read-only | `app.py:4779` `tax_methodology_bmf_prior_filing_declared_amounts` |
| `PUT` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | TAX methodology write bmf prior filing declared amounts | schreibt | `app.py:4787` `tax_methodology_write_bmf_prior_filing_declared_amounts` |
| `GET` | `/api/v1/tax-methodology/bmf-submission-guide` | TAX methodology bmf submission guide | read-only | `app.py:4665` `tax_methodology_bmf_submission_guide` |
| `GET` | `/api/v1/tax-methodology/legal-research/freshness` | Legal research freshness | read-only | `app.py:3144` `legal_research_freshness` |
| `GET` | `/api/v1/tax-methodology/legal-research/sources` | Legal research sources | read-only | `app.py:3134` `legal_research_sources` |
| `GET` | `/api/v1/tax-methodology/summary` | TAX methodology summary | read-only | `app.py:4565` `tax_methodology_summary` |
| `GET` | `/api/v1/tax-methodology/time-precision-audit` | Tax methodology time precision audit | read-only | `app.py:4587` `tax_methodology_time_precision_audit` |
| `GET` | `/api/v1/tax-years/business-reward-inventory-review` | Tax years business reward inventory review | read-only | `app.py:4334` `tax_years_business_reward_inventory_review` |
| `GET` | `/api/v1/tax-years/correction-map` | TAX years correction map | read-only | `app.py:4489` `tax_years_correction_map` |
| `GET` | `/api/v1/tax-years/filing-closure-overview` | TAX years filing closure overview | read-only | `app.py:4310` `tax_years_filing_closure_overview` |
| `GET` | `/api/v1/tax-years/filing-matrix` | TAX years filing matrix | read-only | `app.py:4300` `tax_years_filing_matrix` |
| `GET` | `/api/v1/tax-years/helium-swap-alchemy-audit` | TAX years helium swap alchemy audit | read-only | `app.py:7434` `tax_years_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/helium-swap-context` | TAX years helium swap context | read-only | `app.py:4519` `tax_years_helium_swap_context` |
| `GET` | `/api/v1/tax-years/helium-swap-evidence-review` | TAX years helium swap evidence review | read-only | `app.py:4527` `tax_years_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/payment-overview` | TAX years payment overview | read-only | `app.py:4290` `tax_years_payment_overview` |
| `GET` | `/api/v1/tax-years/reward-bmf-recheck` | TAX years reward bmf recheck | read-only | `app.py:4797` `tax_years_reward_bmf_recheck` |
| `GET` | `/api/v1/tax-years/reward-trading-separation` | TAX years reward trading separation | read-only | `app.py:4322` `tax_years_reward_trading_separation` |
| `GET` | `/api/v1/tax-years/solana-program-income-review` | TAX years solana program income review | read-only | `app.py:4511` `tax_years_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-fx-review` | TAX years solana stablecoin fx review | read-only | `app.py:4557` `tax_years_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-swap-context` | TAX years solana stablecoin swap context | read-only | `app.py:4549` `tax_years_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/stablecoin-fifo-review` | TAX years stablecoin fifo review | read-only | `app.py:4535` `tax_years_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/stablecoin-quote-leg-review` | TAX years stablecoin quote leg review | read-only | `app.py:4541` `tax_years_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/summary` | TAX years summary | read-only | `app.py:4280` `tax_years_summary` |
| `GET` | `/api/v1/tax-years/turnover-audit-summary` | TAX years turnover audit summary | read-only | `app.py:4499` `tax_years_turnover_audit_summary` |
| `GET` | `/api/v1/tax-years/{year}` | TAX year detail | read-only | `app.py:4801` `tax_year_detail` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-correction-review` | TAX year asset fifo correction review | read-only | `app.py:6159` `tax_year_asset_fifo_correction_review` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-drilldown` | TAX year asset fifo drilldown | read-only | `app.py:6135` `tax_year_asset_fifo_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-plausibility` | TAX year asset fifo plausibility | read-only | `app.py:6145` `tax_year_asset_fifo_plausibility` |
| `GET` | `/api/v1/tax-years/{year}/bmf-closure-appendix` | TAX year bmf closure appendix | read-only | `app.py:6217` `tax_year_bmf_closure_appendix` |
| `GET` | `/api/v1/tax-years/{year}/cex-deposit-transfer-evidence` | TAX year cex deposit transfer evidence | read-only | `app.py:5355` `tax_year_cex_deposit_transfer_evidence` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility` | TAX year cex exchange outflow anchor feasibility | read-only | `app.py:5553` `tax_year_cex_exchange_outflow_anchor_feasibility` |
| `POST` | `/api/v1/tax-years/{year}/cex-exchange-outflow-decisions` | Fuegt hinzu tax year cex exchange outflow decision | schreibt/erzeugt Artefakte | `app.py:5573` `add_tax_year_cex_exchange_outflow_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-evidence` | TAX year cex exchange outflow evidence | read-only | `app.py:5533` `tax_year_cex_exchange_outflow_evidence` |
| `POST` | `/api/v1/tax-years/{year}/cex-sender-ownership-decisions` | Fuegt hinzu tax year cex sender ownership decision | schreibt/erzeugt Artefakte | `app.py:5387` `add_tax_year_cex_sender_ownership_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-sender-ownership-latest` | TAX year cex sender ownership latest | read-only | `app.py:5371` `tax_year_cex_sender_ownership_latest` |
| `GET` | `/api/v1/tax-years/{year}/compliance-status` | TAX year compliance status | read-only | `app.py:5317` `tax_year_compliance_status` |
| `GET` | `/api/v1/tax-years/{year}/correction-map` | TAX year correction map | read-only | `app.py:4968` `tax_year_correction_map` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide` | TAX year declaration guide | read-only | `app.py:4817` `tax_year_declaration_guide` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide.html` | Tax year declaration guide html | read-only | `app.py:4839` `tax_year_declaration_guide_html` |
| `GET` | `/api/v1/tax-years/{year}/drivers` | TAX year drivers | read-only | `app.py:6069` `tax_year_drivers` |
| `GET` | `/api/v1/tax-years/{year}/evidence` | TAX year evidence | read-only | `app.py:6185` `tax_year_evidence` |
| `GET` | `/api/v1/tax-years/{year}/evidence.html` | Tax year evidence html | read-only | `app.py:6205` `tax_year_evidence_html` |
| `GET` | `/api/v1/tax-years/{year}/external-inflows` | TAX year external inflows | read-only | `app.py:6223` `tax_year_external_inflows` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report` | Erzeugt bzw. liefert den read-only Einzelpositions-, Ursachen- und Summenabgleich | read-only | `app.py:9250` `tax_filing_audit_report` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.json` | Liefert das unveraenderliche JSON-Auditartefakt | read-only | `app.py:9258` `tax_filing_audit_report_json` |
| `GET` | `/api/v1/tax-years/{year}/filing-audit-report.md` | Liefert das unveraenderliche Markdown-Auditartefakt | read-only | `app.py:9276` `tax_filing_audit_report_markdown` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison` | Vergleicht den eingereichten bzw. archivierten Stand je Einkunftsart mit der aktuellen Berechnung | read-only | `app.py:9234` `tax_filing_snapshot_comparison` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshot-comparison.html` | Liefert die druckbare Korrekturpruefungsakte statt einer rohen JSON-Ansicht | read-only | `app.py:9400` `tax_filing_snapshot_comparison_html` |
| `GET` | `/api/v1/tax-years/{year}/filing-snapshots` | Liefert das hashgebundene Snapshot-Register fuer ein konkretes Steuerjahr | read-only | `app.py:9175` `tax_year_filing_snapshots` |
| `POST` | `/api/v1/tax-years/{year}/filing-snapshots` | Archiviert den aktuellen Paketstand oder bestaetigt eine konkrete Revision als tatsaechlich eingereicht | kann Daten oder Artefakte schreiben | `app.py:9179` `capture_tax_filing_snapshot` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary` | TAX year filing summary | read-only | `app.py:4851` `tax_year_filing_summary` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary.html` | Tax year filing summary html | read-only | `app.py:4861` `tax_year_filing_summary_html` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-acquisition-event-deltas` | TAX year gain evidence acquisition event deltas | read-only | `app.py:6124` `tax_year_gain_evidence_acquisition_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-event-deltas` | TAX year gain evidence event deltas | read-only | `app.py:6115` `tax_year_gain_evidence_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-price-deltas` | TAX year gain evidence price deltas | read-only | `app.py:6101` `tax_year_gain_evidence_price_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-review` | TAX year gain evidence review | read-only | `app.py:6093` `tax_year_gain_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/gain-loss-reality-check` | TAX year gain loss reality check | read-only | `app.py:6081` `tax_year_gain_loss_reality_check` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-alchemy-audit` | TAX year helium swap alchemy audit | read-only | `app.py:7440` `tax_year_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-context` | TAX year helium swap context | read-only | `app.py:6019` `tax_year_helium_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-evidence-review` | TAX year helium swap evidence review | read-only | `app.py:6027` `tax_year_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/income-guide` | TAX year income guide | read-only | `app.py:6001` `tax_year_income_guide` |
| `GET` | `/api/v1/tax-years/{year}/methodology` | TAX year methodology | read-only | `app.py:5307` `tax_year_methodology` |
| `GET` | `/api/v1/tax-years/{year}/solana-program-income-review` | TAX year solana program income review | read-only | `app.py:6011` `tax_year_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-fx-review` | TAX year solana stablecoin fx review | read-only | `app.py:6061` `tax_year_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-swap-context` | TAX year solana stablecoin swap context | read-only | `app.py:6051` `tax_year_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-fifo-review` | TAX year stablecoin fifo review | read-only | `app.py:6035` `tax_year_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-quote-leg-review` | TAX year stablecoin quote leg review | read-only | `app.py:6043` `tax_year_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/{year}/turnover-audit` | TAX year turnover audit | read-only | `app.py:6173` `tax_year_turnover_audit` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-delta` | TAX year wallet fifo delta | read-only | `app.py:5321` `tax_year_wallet_fifo_delta` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-exchange-evidence-gaps` | TAX year wallet fifo exchange evidence gaps | read-only | `app.py:5807` `tax_year_wallet_fifo_exchange_evidence_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-gaps` | TAX year wallet fifo gaps | read-only | `app.py:5331` `tax_year_wallet_fifo_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-opening-balance-evidence` | TAX year wallet fifo opening balance evidence | read-only | `app.py:5791` `tax_year_wallet_fifo_opening_balance_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-origin-trace` | TAX year wallet fifo origin trace | read-only | `app.py:5339` `tax_year_wallet_fifo_origin_trace` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-closure` | TAX year wallet fifo provenance closure | read-only | `app.py:5742` `tax_year_wallet_fifo_provenance_closure` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-events` | TAX year wallet fifo provenance events | read-only | `app.py:5757` `tax_year_wallet_fifo_provenance_events` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-priorities` | TAX year wallet fifo provenance priorities | read-only | `app.py:5731` `tax_year_wallet_fifo_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-raw-provenance-breakdown` | TAX year wallet fifo raw provenance breakdown | read-only | `app.py:5775` `tax_year_wallet_fifo_raw_provenance_breakdown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-origin` | TAX year wallet fifo solana origin | read-only | `app.py:5974` `tax_year_wallet_fifo_solana_origin` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence` | Tax year wallet fifo solana program settlement evidence | read-only | `app.py:5856` `tax_year_wallet_fifo_solana_program_settlement_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-batch-latest` | TAX year wallet fifo solana provenance batch latest | read-only | `app.py:5845` `tax_year_wallet_fifo_solana_provenance_batch_latest` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-classification` | TAX year wallet fifo solana provenance classification | read-only | `app.py:5823` `tax_year_wallet_fifo_solana_provenance_classification` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-drilldown` | TAX year wallet fifo solana raw bmf evidence drilldown | read-only | `app.py:5922` `tax_year_wallet_fifo_solana_raw_bmf_evidence_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-summary` | TAX year wallet fifo solana raw bmf evidence summary | read-only | `app.py:5906` `tax_year_wallet_fifo_solana_raw_bmf_evidence_summary` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-priorities` | TAX year wallet fifo solana raw provenance priorities | read-only | `app.py:5874` `tax_year_wallet_fifo_solana_raw_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-senders` | TAX year wallet fifo solana raw provenance senders | read-only | `app.py:5890` `tax_year_wallet_fifo_solana_raw_provenance_senders` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-cluster-outflows` | TAX year wallet fifo solana sender cluster outflows | read-only | `app.py:5954` `tax_year_wallet_fifo_solana_sender_cluster_outflows` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-clusters` | TAX year wallet fifo solana sender clusters | read-only | `app.py:5942` `tax_year_wallet_fifo_solana_sender_clusters` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-service-swap-evidence` | Tax year wallet fifo solana service swap evidence | read-only | `app.py:5866` `tax_year_wallet_fifo_solana_service_swap_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps` | TAX year wallet fifo withdrawal gaps | read-only | `app.py:5990` `tax_year_wallet_fifo_withdrawal_gaps` |
| `GET` | `/api/v1/tax/bmf-combined-fifo-staging/latest` | Tax bmf combined fifo staging latest | read-only | `app.py:4384` `tax_bmf_combined_fifo_staging_latest` |
| `POST` | `/api/v1/tax/bmf-combined-fifo-staging/run` | Tax bmf combined fifo staging run | kann Daten oder Artefakte schreiben | `app.py:4396` `tax_bmf_combined_fifo_staging_run` |
| `GET` | `/api/v1/tax/bmf-event-price-remediation/latest` | Tax bmf event price remediation latest | read-only | `app.py:4464` `tax_bmf_event_price_remediation_latest` |
| `POST` | `/api/v1/tax/bmf-event-price-remediation/run` | Tax bmf event price remediation run | kann Daten oder Artefakte schreiben | `app.py:4476` `tax_bmf_event_price_remediation_run` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz` | Tax bmf fifo event evidence events artifact | read-only | `app.py:4416` `tax_bmf_fifo_event_evidence_events_artifact` |
| `GET` | `/api/v1/tax/bmf-fifo-event-evidence/latest` | Tax bmf fifo event evidence latest | read-only | `app.py:4406` `tax_bmf_fifo_event_evidence_latest` |
| `POST` | `/api/v1/tax/bmf-fifo-event-evidence/run` | Tax bmf fifo event evidence run | kann Daten oder Artefakte schreiben | `app.py:4454` `tax_bmf_fifo_event_evidence_run` |
| `GET` | `/api/v1/tax/cross-cex-transfer-evidence` | Tax cross cex transfer evidence | read-only | `app.py:3758` `tax_cross_cex_transfer_evidence` |
| `GET` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/latest` | Tax crypto swap fifo parallel preview latest | read-only | `app.py:4362` `tax_crypto_swap_fifo_parallel_preview_latest` |
| `POST` | `/api/v1/tax/crypto-swap-fifo-parallel-preview/run` | Tax crypto swap fifo parallel preview run | kann Daten oder Artefakte schreiben | `app.py:4374` `tax_crypto_swap_fifo_parallel_preview_run` |
| `GET` | `/api/v1/tax/crypto-swap-valuation-review` | Tax crypto swap valuation review | read-only | `app.py:4346` `tax_crypto_swap_valuation_review` |
| `GET` | `/api/v1/tax/fairspot-staking-reconciliation` | Tax fairspot staking reconciliation | read-only | `app.py:3764` `tax_fairspot_staking_reconciliation` |
| `POST` | `/api/v1/tax/fifo/rebuild` | Rebuild fifo tax | schreibt/erzeugt Artefakte | `app.py:3698` `rebuild_fifo_tax` |
| `GET` | `/api/v1/tax/holding-periods` | TAX holding periods | read-only | `app.py:3714` `tax_holding_periods` |
| `GET` | `/api/v1/tax/legacy-helium-overview` | TAX legacy helium overview | read-only | `app.py:4266` `tax_legacy_helium_overview` |
| `GET` | `/api/v1/tax/lines` | Liste tax lines | read-only | `app.py:3702` `list_tax_lines` |
| `GET` | `/api/v1/tax/loss-realization-planner` | TAX loss realization planner | read-only | `app.py:3728` `tax_loss_realization_planner` |
| `GET` | `/api/v1/tax/lots` | Liste tax lots | read-only | `app.py:3706` `list_tax_lots` |
| `GET` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipts | read-only | `app.py:3770` `tax_moonpay_receipts` |
| `POST` | `/api/v1/tax/moonpay-receipts` | Tax moonpay receipt upsert | kann Daten oder Artefakte schreiben | `app.py:3822` `tax_moonpay_receipt_upsert` |
| `GET` | `/api/v1/tax/moonpay-receipts/trade-history.csv` | Tax moonpay trade history document | read-only | `app.py:3776` `tax_moonpay_trade_history_document` |
| `GET` | `/api/v1/tax/moonpay-receipts/{tx_id}/document` | Tax moonpay receipt document | read-only | `app.py:3802` `tax_moonpay_receipt_document` |
| `GET` | `/api/v1/tax/pionex-hnt-reconciliation` | Tax pionex hnt reconciliation | read-only | `app.py:3754` `tax_pionex_hnt_reconciliation` |
| `GET` | `/api/v1/tax/service-swap-mappings` | Tax service swap mappings | read-only | `app.py:3750` `tax_service_swap_mappings` |
| `GET` | `/api/v1/tax/solana-staking-position-reconciliation` | Tax solana staking position reconciliation | read-only | `app.py:3833` `tax_solana_staking_position_reconciliation` |
| `GET` | `/api/v1/tax/summary` | TAX summary | read-only | `app.py:3746` `tax_summary` |
| `GET` | `/api/v1/tax/unmatched-disposals` | Liste tax unmatched disposals | read-only | `app.py:3710` `list_tax_unmatched_disposals` |
| `GET` | `/api/v1/tax/wallet-fifo-internal-transfer-carry` | Tax wallet fifo internal transfer carry | read-only | `app.py:3848` `tax_wallet_fifo_internal_transfer_carry` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/applies/latest` | Tax wallet fifo migration apply latest | read-only | `app.py:4222` `tax_wallet_fifo_migration_apply_latest` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/apply` | Tax wallet fifo migration apply | kann Daten oder Artefakte schreiben | `app.py:4211` `tax_wallet_fifo_migration_apply` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/apply-readiness` | Tax wallet fifo migration apply readiness | read-only | `app.py:4199` `tax_wallet_fifo_migration_apply_readiness` |
| `POST` | `/api/v1/tax/wallet-fifo-migrations/rehearsals` | Tax wallet fifo migration rehearsal | kann Daten oder Artefakte schreiben | `app.py:4170` `tax_wallet_fifo_migration_rehearsal` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/latest` | Tax wallet fifo migration rehearsal latest | read-only | `app.py:4181` `tax_wallet_fifo_migration_rehearsal_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-migrations/rehearsals/{rehearsal_id}` | Tax wallet fifo migration rehearsal by id | read-only | `app.py:4187` `tax_wallet_fifo_migration_rehearsal_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-preview` | TAX wallet fifo preview | read-only | `app.py:3839` `tax_wallet_fifo_preview` |
| `POST` | `/api/v1/tax/wallet-fifo-runs` | Tax wallet fifo parallel run | kann Daten oder Artefakte schreiben | `app.py:3860` `tax_wallet_fifo_parallel_run` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest` | Tax wallet fifo parallel run latest | read-only | `app.py:3871` `tax_wallet_fifo_parallel_run_latest` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-acceptance` | Tax wallet fifo latest method acceptance | read-only | `app.py:4107` `tax_wallet_fifo_latest_method_acceptance` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation` | Tax wallet fifo latest method delta explanation | read-only | `app.py:4119` `tax_wallet_fifo_latest_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}` | Tax wallet fifo parallel run by id | read-only | `app.py:4135` `tax_wallet_fifo_parallel_run_by_id` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/evidence/{filename}` | Tax wallet fifo parallel run evidence | read-only | `app.py:4251` `tax_wallet_fifo_parallel_run_evidence` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance | read-only | `app.py:4146` `tax_wallet_fifo_method_acceptance` |
| `POST` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance` | Tax wallet fifo method acceptance create | kann Daten oder Artefakte schreiben | `app.py:4158` `tax_wallet_fifo_method_acceptance_create` |
| `GET` | `/api/v1/tax/wallet-fifo-runs/{run_id}/method-delta-explanation` | Tax wallet fifo method delta explanation | read-only | `app.py:4228` `tax_wallet_fifo_method_delta_explanation` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision` | Tax wallet fifo bitget strategy basis decision | read-only | `app.py:3925` `tax_wallet_fifo_bitget_strategy_basis_decision` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run_id}` | Tax wallet fifo bitget strategy basis decision create | kann Daten oder Artefakte schreiben | `app.py:3939` `tax_wallet_fifo_bitget_strategy_basis_decision_create` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps` | Tax wallet fifo bitget strategy gaps | read-only | `app.py:3877` `tax_wallet_fifo_bitget_strategy_gaps` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv` | Tax wallet fifo bitget strategy gaps csv | read-only | `app.py:3889` `tax_wallet_fifo_bitget_strategy_gaps_csv` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction` | Tax wallet fifo bitget strategy reconstruction | read-only | `app.py:3910` `tax_wallet_fifo_bitget_strategy_reconstruction` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv` | Tax wallet fifo bitget strategy reconstruction csv | read-only | `app.py:3954` `tax_wallet_fifo_bitget_strategy_reconstruction_csv` |
| `POST` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill` | Tax wallet fifo bitget strategy reference price backfill | kann Daten oder Artefakte schreiben | `app.py:3992` `tax_wallet_fifo_bitget_strategy_reference_price_backfill` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill/latest` | Tax wallet fifo bitget strategy reference price backfill latest | read-only | `app.py:3981` `tax_wallet_fifo_bitget_strategy_reference_price_backfill_latest` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip` | Tax wallet fifo bitget strategy review package | read-only | `app.py:4064` `tax_wallet_fifo_bitget_strategy_review_package` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-strategy-review.html` | Tax wallet fifo bitget strategy review html | read-only | `app.py:4034` `tax_wallet_fifo_bitget_strategy_review_html` |
| `GET` | `/api/v1/tax/wallet-fifo/bitget-support-package.zip` | Tax wallet fifo bitget support package | read-only | `app.py:4006` `tax_wallet_fifo_bitget_support_package` |

## Reports und Exporte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/export/all-transaction-decision-candidates.json` | Download/Export all transaction decision candidates json | read-only | `app.py:7373` `download_all_transaction_decision_candidates_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-closure.json` | Download/Export all transaction evidence closure json | read-only | `app.py:7347` `download_all_transaction_evidence_closure_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-matrix.json` | Download/Export all transaction evidence matrix json | read-only | `app.py:7335` `download_all_transaction_evidence_matrix_json` |
| `GET` | `/api/v1/export/all-transaction-open-detail-review.json` | Download/Export all transaction open detail review json | read-only | `app.py:7359` `download_all_transaction_open_detail_review_json` |
| `POST` | `/api/v1/export/audit` | EXPORT audit | pruefen | `app.py:6365` `export_audit` |
| `GET` | `/api/v1/export/audit.json` | Download/Export audit json | read-only | `app.py:6373` `download_audit_json` |
| `GET` | `/api/v1/export/binance-fiat-deposits.csv` | Download/Export binance fiat deposits csv | read-only | `app.py:6770` `download_binance_fiat_deposits_csv` |
| `GET` | `/api/v1/export/derivative-lines.csv` | Download/Export derivative lines csv | read-only | `app.py:6906` `download_derivative_lines_csv` |
| `POST` | `/api/v1/export/elster-prep` | EXPORT elster prep | pruefen | `app.py:6369` `export_elster_prep` |
| `GET` | `/api/v1/export/evidence-manifest.json` | Download/Export evidence manifest | read-only | `app.py:6287` `download_evidence_manifest` |
| `GET` | `/api/v1/export/evidence-package-index.json` | Download/Export evidence package index | read-only | `app.py:6298` `download_evidence_package_index` |
| `GET` | `/api/v1/export/evidence-package.zip` | Download/Export evidence package zip | read-only | `app.py:7859` `download_evidence_package_zip` |
| `GET` | `/api/v1/export/hnt-provenance-events.csv` | Download/Export hnt provenance events csv | read-only | `app.py:6706` `download_hnt_provenance_events_csv` |
| `GET` | `/api/v1/export/hnt-provenance-timeline.csv` | Download/Export hnt provenance timeline csv | read-only | `app.py:6646` `download_hnt_provenance_timeline_csv` |
| `GET` | `/api/v1/export/packages` | Liste export packages | read-only | `app.py:6267` `list_export_packages` |
| `DELETE` | `/api/v1/export/packages/{package_id}` | Loescht export package | loescht | `app.py:6345` `delete_export_package` |
| `GET` | `/api/v1/export/packages/{package_id}/download.pdf` | Download/Export export package pdf | read-only | `app.py:6311` `download_export_package_pdf` |
| `GET` | `/api/v1/export/parity-diagnostics.csv` | Download/Export parity diagnostics csv | read-only | `app.py:6598` `download_parity_diagnostics_csv` |
| `POST` | `/api/v1/export/pdf` | Erzeugt pdf export | schreibt/erzeugt Artefakte | `app.py:6263` `create_pdf_export` |
| `GET` | `/api/v1/export/price-gaps.csv` | Download/Export price gaps csv | read-only | `app.py:6502` `download_price_gaps_csv` |
| `GET` | `/api/v1/export/price-requirements.csv` | Download/Export price requirements csv | read-only | `app.py:6552` `download_price_requirements_csv` |
| `GET` | `/api/v1/export/readiness` | EXPORT readiness | read-only | `app.py:6271` `export_readiness` |
| `GET` | `/api/v1/export/review-decisions.csv` | Download/Export review decisions csv | read-only | `app.py:6393` `download_review_decisions_csv` |
| `GET` | `/api/v1/export/solana-failed-tx-tax-impact.json` | Download/Export solana failed tx tax impact json | read-only | `app.py:7323` `download_solana_failed_tx_tax_impact_json` |
| `GET` | `/api/v1/export/solana-tx-alchemy-audit.json` | Download/Export solana tx alchemy audit json | read-only | `app.py:7311` `download_solana_tx_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-external-inflows.csv` | Download/Export tax external inflows csv | read-only | `app.py:7052` `download_tax_external_inflows_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-alchemy-audit.json` | Download/Export tax helium swap alchemy audit json | read-only | `app.py:7448` `download_tax_helium_swap_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-helium-swap-context.csv` | Download/Export tax helium swap context csv | read-only | `app.py:7761` `download_tax_helium_swap_context_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-evidence-review.csv` | Download/Export tax helium swap evidence review csv | read-only | `app.py:7842` `download_tax_helium_swap_evidence_review_csv` |
| `GET` | `/api/v1/export/tax-income-guide.csv` | Download/Export tax income guide csv | read-only | `app.py:6970` `download_tax_income_guide_csv` |
| `GET` | `/api/v1/export/tax-lines.csv` | Download/Export tax lines csv | read-only | `app.py:6863` `download_tax_lines_csv` |
| `GET` | `/api/v1/export/tax-methodology/bmf-amendment-worklist.csv` | Download/Export bmf amendment worklist csv | read-only | `app.py:4769` `download_bmf_amendment_worklist_csv` |
| `GET` | `/api/v1/export/tax-payment-overview.json` | Download/Export tax payment overview json | read-only | `app.py:6382` `download_tax_payment_overview_json` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-evidence.csv` | Download/Export tax solana stablecoin swap evidence csv | read-only | `app.py:7565` `download_tax_solana_stablecoin_swap_evidence_csv` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv` | Download/Export tax solana stablecoin swap fifo lines csv | read-only | `app.py:7684` `download_tax_solana_stablecoin_swap_fifo_lines_csv` |
| `GET` | `/api/v1/export/tax-years/correction-map.csv` | Download/Export tax years correction map csv | read-only | `app.py:5237` `download_tax_years_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/correction-map.csv` | Download/Export tax year correction map csv | read-only | `app.py:5247` `download_tax_year_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/evidence-package.zip` | Download/Export tax year evidence package zip | read-only | `app.py:8138` `download_tax_year_evidence_package_zip` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-checklist.csv` | Download/Export tax year filing checklist csv | read-only | `app.py:5297` `download_tax_year_filing_checklist_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-snapshot-comparison.csv` | Liefert den Abgabestand-Delta je Einkunftsart als CSV | read-only | `app.py:9421` `tax_filing_snapshot_comparison_csv` |
| `GET` | `/api/v1/export/token-risk-documentation.csv` | Download/Export token risk documentation csv | read-only | `app.py:6441` `download_token_risk_documentation_csv` |
| `GET` | `/api/v1/reports/center` | REPORT center | read-only | `app.py:6279` `report_center` |

## Stichtag und Zugewinn

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/divorce/coinbase/connector` | Berechnet Coinbase-Historienabdeckung und Stichtagsbestand | read-only | `app.py:2675` `divorce_coinbase_connector` |
| `GET` | `/api/v1/divorce/coinbase/connector.csv` | Liefert den Coinbase-Historien- und Stichtagsnachweis als CSV | read-only | `app.py:2685` `divorce_coinbase_connector_csv` |
| `POST` | `/api/v1/divorce/coinbase/valuation-decisions` | Bindet den serverseitigen Coinbase-Stichtagswert an das Historienmanifest | kann Daten oder Artefakte schreiben | `app.py:2700` `divorce_coinbase_valuation_decision` |
| `GET` | `/api/v1/divorce/equalization-summary` | DIVORCE equalization summary | read-only | `app.py:2894` `divorce_equalization_summary` |
| `GET` | `/api/v1/divorce/equalization-summary/accounts.csv` | DIVORCE equalization accounts csv | read-only | `app.py:2944` `divorce_equalization_accounts_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/capital-flows.csv` | Divorce equalization capital flows csv | read-only | `app.py:3000` `divorce_equalization_capital_flows_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/evidence-package.zip` | DIVORCE equalization evidence package zip | read-only | `app.py:3028` `divorce_equalization_evidence_package_zip` |
| `GET` | `/api/v1/divorce/equalization-summary/live-reconciliation.csv` | DIVORCE equalization live reconciliation csv | read-only | `app.py:2972` `divorce_equalization_live_reconciliation_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/valuation-tokens.csv` | DIVORCE equalization valuation tokens csv | read-only | `app.py:2916` `divorce_equalization_valuation_tokens_csv` |
| `GET` | `/api/v1/divorce/inheritance-credit-candidates` | Liefert datensparsame CAMT-Gutschriften fuer die Erbmittelpruefung | read-only | `app.py:2394` `divorce_inheritance_credit_candidates` |
| `POST` | `/api/v1/divorce/inheritance-credit-decisions` | Klassifiziert eine konkrete CAMT-Gutschrift hashgebunden als Erbmittel | kann Daten oder Artefakte schreiben | `app.py:2423` `divorce_inheritance_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-credits.csv` | Liefert alle freigegebenen Erbmittelzufluesse als Beleg-CSV | read-only | `app.py:2406` `divorce_inheritance_credits_csv` |
| `POST` | `/api/v1/divorce/inheritance-document-credit-decisions` | Bindet einen dokumentierten Netto-Erbmittelzufluss an Beleg und Betrag | kann Daten oder Artefakte schreiben | `app.py:2463` `divorce_inheritance_document_credit_decision` |
| `GET` | `/api/v1/divorce/inheritance-documents` | Liefert den datensparsamen Erbnachweis- und Reviewstatus | read-only | `app.py:2553` `divorce_inheritance_documents` |
| `POST` | `/api/v1/divorce/inheritance-documents` | Speichert einen validierten formalen Erbnachweis als Kandidat | kann Daten oder Artefakte schreiben | `app.py:2572` `divorce_inheritance_document_upload` |
| `GET` | `/api/v1/divorce/inheritance-documents.csv` | Liefert den Erbnachweis-Hashindex als CSV | read-only | `app.py:2561` `divorce_inheritance_documents_csv` |
| `POST` | `/api/v1/divorce/inheritance-documents/review-decisions` | Bindet einen gesichteten formalen Erbnachweis an SHA-256 | kann Daten oder Artefakte schreiben | `app.py:2612` `divorce_inheritance_document_review_decision` |
| `GET` | `/api/v1/divorce/inheritance-origin` | Divorce inheritance origin | read-only | `app.py:2361` `divorce_inheritance_origin` |
| `GET` | `/api/v1/divorce/inheritance-origin.csv` | Divorce inheritance origin csv | read-only | `app.py:2648` `divorce_inheritance_origin_csv` |
| `POST` | `/api/v1/divorce/service-route-evidence/decisions` | Bindet eine vollstaendig liquidierte Serviceposition an den Vermoegensfluss | kann Daten oder Artefakte schreiben | `app.py:2858` `divorce_service_route_decision` |
| `POST` | `/api/v1/divorce/service-route-evidence/refresh` | Erzeugt einen SHA-gebundenen Solana-RPC-Lebenszyklusbeleg fuer eine Serviceposition | kann Daten oder Artefakte schreiben | `app.py:2831` `divorce_service_route_evidence_refresh` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}` | Liefert den letzten validen Servicepositions-Lebenszyklusbeleg | read-only | `app.py:2844` `divorce_service_route_evidence` |
| `GET` | `/api/v1/divorce/service-route-evidence/{tx_id}/artifacts/{filename}` | Liefert einen SHA-geprueften komprimierten Solana-RPC-Beleg | read-only | `app.py:2872` `divorce_service_route_evidence_artifact` |
| `POST` | `/api/v1/divorce/sparkasse-camt` | Importiert validierte CAMT.052-XML- oder ZIP-Belege | kann Daten oder Artefakte schreiben | `app.py:2505` `divorce_sparkasse_camt_upload` |
| `GET` | `/api/v1/divorce/sparkasse-statements` | Gleicht Sparkassen-PDF-Auszugbelege read-only gegen CAMT.052 ab | read-only | `app.py:2373` `divorce_sparkasse_statements` |
| `GET` | `/api/v1/divorce/sparkasse-statements.csv` | Liefert den datensparsamen PDF-zu-CAMT-Belegabgleich als CSV | read-only | `app.py:2381` `divorce_sparkasse_statements_csv` |
| `GET` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic documents | read-only | `app.py:2665` `divorce_trade_republic_documents` |
| `POST` | `/api/v1/divorce/trade-republic/documents` | Divorce trade republic document upload | kann Daten oder Artefakte schreiben | `app.py:2751` `divorce_trade_republic_document_upload` |
| `GET` | `/api/v1/divorce/trade-republic/documents.csv` | Divorce trade republic documents csv | read-only | `app.py:2736` `divorce_trade_republic_documents_csv` |
| `POST` | `/api/v1/divorce/trade-republic/valuation-decisions` | Divorce trade republic valuation decision | kann Daten oder Artefakte schreiben | `app.py:2795` `divorce_trade_republic_valuation_decision` |
| `POST` | `/api/v1/divorce/valuation-runs` | Divorce valuation run | kann Daten oder Artefakte schreiben | `app.py:3056` `divorce_valuation_run` |
| `GET` | `/api/v1/divorce/valuation-runs/latest` | Divorce valuation run latest | read-only | `app.py:3066` `divorce_valuation_run_latest` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}` | Divorce valuation run by id | read-only | `app.py:3070` `divorce_valuation_run_by_id` |
| `GET` | `/api/v1/divorce/valuation-runs/{run_id}/evidence/{filename}` | Divorce valuation run evidence | read-only | `app.py:3079` `divorce_valuation_run_evidence` |

## KI-Aufgaben

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ai/changes` | Ai change sets | read-only | `app.py:9530` `ai_change_sets` |
| `POST` | `/api/v1/ai/changes` | Create ai change set | kann Daten oder Artefakte schreiben | `app.py:9534` `create_ai_change_set` |
| `POST` | `/api/v1/ai/changes/generate` | Generate ai change set | kann Daten oder Artefakte schreiben | `app.py:9538` `generate_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}` | Ai change set | read-only | `app.py:9542` `ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/apply` | Apply ai change set | kann Daten oder Artefakte schreiben | `app.py:9554` `apply_ai_change_set` |
| `GET` | `/api/v1/ai/changes/{identifier}/audit.json` | Ai change audit | read-only | `app.py:9568` `ai_change_audit` |
| `POST` | `/api/v1/ai/changes/{identifier}/preview` | Preview ai change set | kann Daten oder Artefakte schreiben | `app.py:9550` `preview_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/reject` | Reject ai change set | kann Daten oder Artefakte schreiben | `app.py:9560` `reject_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revert` | Revert ai change set | kann Daten oder Artefakte schreiben | `app.py:9564` `revert_ai_change_set` |
| `POST` | `/api/v1/ai/changes/{identifier}/revise` | Revise ai change set | kann Daten oder Artefakte schreiben | `app.py:9546` `revise_ai_change_set` |
| `POST` | `/api/v1/ai/data-context` | Ai data context | kann Daten oder Artefakte schreiben | `app.py:9526` `ai_data_context` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review` | LOCAL ai asset fifo correction review | read-only | `app.py:9629` `local_ai_asset_fifo_correction_review` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review/artifacts/{artifact}` | Download/Export local ai asset fifo correction artifact | read-only | `app.py:9635` `download_local_ai_asset_fifo_correction_artifact` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review` | LOCAL ai wallet fifo provenance review | read-only | `app.py:9662` `local_ai_wallet_fifo_provenance_review` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/{artifact}` | Download/Export local ai wallet fifo provenance artifact | read-only | `app.py:9668` `download_local_ai_wallet_fifo_provenance_artifact` |
| `GET` | `/api/v1/ai/local-year-package-qa` | LOCAL ai year package qa | read-only | `app.py:9598` `local_ai_year_package_qa` |
| `GET` | `/api/v1/ai/local-year-package-qa/artifacts/{artifact}` | Download/Export local ai year package qa artifact | read-only | `app.py:9602` `download_local_ai_year_package_qa_artifact` |
| `GET` | `/api/v1/ai/provider` | Ai provider status | read-only | `app.py:9509` `ai_provider_status` |
| `PUT` | `/api/v1/ai/provider` | Save ai provider | schreibt | `app.py:9574` `save_ai_provider` |
| `POST` | `/api/v1/ai/provider/models` | Ai provider models | kann Daten oder Artefakte schreiben | `app.py:9578` `ai_provider_models` |
| `POST` | `/api/v1/ai/provider/test` | Test ai provider | kann Daten oder Artefakte schreiben | `app.py:9582` `test_ai_provider` |
| `GET` | `/api/v1/ai/tasks` | Liste ai tasks | read-only | `app.py:9594` `list_ai_tasks` |
| `POST` | `/api/v1/ai/tasks` | Erzeugt ai task | schreibt/erzeugt Artefakte | `app.py:9590` `create_ai_task` |
| `DELETE` | `/api/v1/ai/tasks/{task_id}` | Loescht ai task | loescht | `app.py:9695` `delete_ai_task` |
| `POST` | `/api/v1/ai/tasks/{task_id}/execute` | Execute ai task | kann Daten oder Artefakte schreiben | `app.py:9586` `execute_ai_task` |

## V1-Paritaet

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/parity/compare` | Vergleicht v1 v2 parity | read-only | `app.py:3633` `compare_v1_v2_parity` |
| `POST` | `/api/v1/parity/decisions` | Fuegt hinzu parity decision | schreibt/erzeugt Artefakte | `app.py:3673` `add_parity_decision` |
| `GET` | `/api/v1/parity/diagnostics` | PARITY diagnostics | read-only | `app.py:3637` `parity_diagnostics` |
| `GET` | `/api/v1/parity/group-detail` | PARITY group detail | read-only | `app.py:3645` `parity_group_detail` |
| `GET` | `/api/v1/parity/hnt-fifo-provenance` | PARITY hnt fifo provenance | read-only | `app.py:3655` `parity_hnt_fifo_provenance` |
| `GET` | `/api/v1/parity/hnt-wallet-bridge` | PARITY hnt wallet bridge | read-only | `app.py:3649` `parity_hnt_wallet_bridge` |
| `GET` | `/api/v1/parity/release-readiness` | PARITY release readiness | read-only | `app.py:3641` `parity_release_readiness` |
| `POST` | `/api/v1/parity/v1/import/wiso` | Importiert wiso v1 references | schreibt/erzeugt Artefakte | `app.py:3599` `import_wiso_v1_references` |
| `GET` | `/api/v1/parity/v1/references` | Liste v1 reference metrics | read-only | `app.py:3575` `list_v1_reference_metrics` |
| `POST` | `/api/v1/parity/v1/references` | Fuegt hinzu v1 reference metric | schreibt/erzeugt Artefakte | `app.py:3569` `add_v1_reference_metric` |
| `DELETE` | `/api/v1/parity/v1/references/{reference_id}` | Loescht v1 reference metric | loescht | `app.py:3579` `delete_v1_reference_metric` |

## Weitere Endpunkte

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/demo/seed` | SEED demo | schreibt/erzeugt Artefakte | `app.py:6251` `seed_demo` |
| `GET` | `/api/v1/derivatives/lines` | Liste derivative lines | read-only | `app.py:6239` `list_derivative_lines` |
| `POST` | `/api/v1/derivatives/rebuild` | Rebuild derivatives | schreibt/erzeugt Artefakte | `app.py:6235` `rebuild_derivatives` |
| `GET` | `/api/v1/derivatives/summary` | DERIVATIVE summary | read-only | `app.py:6243` `derivative_summary` |
| `POST` | `/api/v1/pipeline/rebuild` | Rebuild pipeline | schreibt/erzeugt Artefakte | `app.py:6247` `rebuild_pipeline` |
