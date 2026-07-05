# Vollstaendige API Endpoint Referenz

Stand: 2026-07-05

Diese Referenz wurde aus `src/steuerreport_v2/api/app.py` erzeugt und listet alle FastAPI-Routen des aktuellen Release-Stands. Sie ergaenzt `docs/API_CONTRACTS_V2.md`, das die wichtigsten Contracts fachlich beschreibt, aber nicht jeden einzelnen Endpunkt vollstaendig inventarisiert.

## Nutzung

- Alle API-Antworten verwenden grundsaetzlich das Standardformat `trace_id`, `status`, `data`, `errors`, `warnings`, sofern ein Endpoint nicht bewusst Datei-/CSV-/ZIP-/PDF-Content ausliefert.
- `GET`-Endpunkte sind grundsaetzlich read-only.
- Die Spalte `Schreibwirkung` ist eine Sicherheitsorientierung: `read-only` schreibt keine Steuerdaten; `schreibt/erzeugt Artefakte` kann Daten, Decisions, Jobs, Preise, Exporte oder lokale Artefakte erzeugen; `optional` haengt von Parametern wie `dry_run` ab.
- Detaillierte Request-/Response-Schemas stehen zur Laufzeit ueber `GET /openapi.json` bzw. Swagger UI bereit, wenn der FastAPI-Service laeuft.
- Echte Steuerdaten liegen lokal in `data/`, `var/` und `artifacts/`; diese Pfade sind nicht Teil des Git-Repositories.

## Statistik

- Endpunkte gesamt: `270`
- GET: `211`
- POST: `51`
- PUT: `1`
- PATCH: `1`
- DELETE: `6`

## Health

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | HEALTH health | read-only | `app.py:461` `health` |

## Administration und Secrets

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/admin/cex-credentials` | Speichert cex credentials | schreibt/erzeugt Artefakte | `app.py:517` `save_cex_credentials` |
| `GET` | `/api/v1/admin/cex-credentials/v1-takeover` | V1 cex credentials takeover report | read-only | `app.py:681` `v1_cex_credentials_takeover_report` |
| `POST` | `/api/v1/admin/cex-credentials/v1-takeover` | Importiert v1 cex credentials | schreibt/erzeugt Artefakte | `app.py:685` `import_v1_cex_credentials` |
| `GET` | `/api/v1/admin/database` | DATABASE status | read-only | `app.py:465` `database_status` |
| `POST` | `/api/v1/admin/jupiter/api-key` | Speichert jupiter api key | schreibt/erzeugt Artefakte | `app.py:546` `save_jupiter_api_key` |
| `GET` | `/api/v1/admin/settings` | Liste admin settings | read-only | `app.py:479` `list_admin_settings` |
| `PATCH` | `/api/v1/admin/settings` | Aktualisiert admin setting | schreibt | `app.py:483` `update_admin_setting` |
| `DELETE` | `/api/v1/admin/settings/{key}` | Loescht admin setting | loescht | `app.py:499` `delete_admin_setting` |
| `GET` | `/api/v1/admin/status` | ADMIN status | read-only | `app.py:469` `admin_status` |

## Cockpit

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/cockpit/summary` | COCKPIT summary | read-only | `app.py:473` `cockpit_summary` |

## Contracts

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/contracts/event-types` | EVENT types | read-only | `app.py:718` `event_types` |

## Import und Preflight

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/import/assistant/execute` | Fuehrt aus import assistant | schreibt/erzeugt Artefakte | `app.py:1064` `execute_import_assistant` |
| `POST` | `/api/v1/import/assistant/preview` | Preview import assistant | read-only | `app.py:1052` `preview_import_assistant` |
| `GET` | `/api/v1/import/batches` | Liste import batches | read-only | `app.py:903` `list_import_batches` |
| `POST` | `/api/v1/import/batches` | Erzeugt import batch | schreibt/erzeugt Artefakte | `app.py:899` `create_import_batch` |
| `DELETE` | `/api/v1/import/batches/{batch_id}` | Loescht import batch | loescht | `app.py:923` `delete_import_batch` |
| `GET` | `/api/v1/import/batches/{batch_id}` | Detailansicht import batch | read-only | `app.py:907` `get_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/normalize` | NORMALIZE import batch | schreibt/erzeugt Artefakte | `app.py:1080` `normalize_import_batch` |
| `POST` | `/api/v1/import/batches/{batch_id}/run` | Fuehrt aus import pipeline | schreibt/erzeugt Artefakte | `app.py:1106` `run_import_pipeline` |
| `GET` | `/api/v1/import/batches/{batch_id}/trace.json` | Download/Export import batch trace | read-only | `app.py:954` `download_import_batch_trace` |
| `GET` | `/api/v1/import/blockpit-solana/preflight` | BLOCKPIT solana preflight | read-only | `app.py:772` `blockpit_solana_preflight` |
| `POST` | `/api/v1/import/blockpit-solana/price-probe` | BLOCKPIT solana price probe | optional schreibt Preise bei dry_run=false | `app.py:790` `blockpit_solana_price_probe` |
| `GET` | `/api/v1/import/coverage` | Importiert coverage | read-only | `app.py:740` `import_coverage` |
| `POST` | `/api/v1/import/csv/preview` | Preview csv import | read-only | `app.py:998` `preview_csv_import` |
| `POST` | `/api/v1/import/csv/raw` | Importiert csv raw | schreibt/erzeugt Artefakte | `app.py:975` `import_csv_raw` |
| `POST` | `/api/v1/import/file/preview` | Preview file import | read-only | `app.py:1012` `preview_file_import` |
| `POST` | `/api/v1/import/file/raw` | Importiert file raw | schreibt/erzeugt Artefakte | `app.py:1027` `import_file_raw` |
| `GET` | `/api/v1/import/jup-perps/preview` | JUP perps preview | read-only | `app.py:885` `jup_perps_preview` |
| `GET` | `/api/v1/import/parser-preflight` | PARSER preflight | read-only | `app.py:760` `parser_preflight` |
| `GET` | `/api/v1/import/policy/audit` | Importiert policy audit | read-only | `app.py:754` `import_policy_audit` |
| `GET` | `/api/v1/import/profiles` | Importiert profiles | read-only | `app.py:736` `import_profiles` |
| `GET` | `/api/v1/import/solscan/evidence-trace` | SOLSCAN evidence trace | read-only | `app.py:839` `solscan_evidence_trace` |
| `GET` | `/api/v1/import/solscan/helium-reward-evidence` | SOLSCAN helium reward evidence | read-only | `app.py:859` `solscan_helium_reward_evidence` |
| `POST` | `/api/v1/import/solscan/rpc-probe` | SOLSCAN rpc probe | schreibt/erzeugt Artefakte | `app.py:831` `solscan_rpc_probe` |
| `GET` | `/api/v1/import/solscan/token-preflight` | SOLSCAN token preflight | read-only | `app.py:811` `solscan_token_preflight` |
| `GET` | `/api/v1/import/wallet-monthly/preflight` | WALLET monthly preflight | read-only | `app.py:867` `wallet_monthly_preflight` |

## Raw und Canonical Events

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/events/canonical` | Liste canonical events | read-only | `app.py:948` `list_canonical_events` |
| `GET` | `/api/v1/raw/objects` | Liste raw objects | read-only | `app.py:941` `list_raw_objects` |

## Ledger

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ledger/balances` | Liste balance positions | read-only | `app.py:1131` `list_balance_positions` |
| `POST` | `/api/v1/ledger/balances/rebuild` | Rebuild balance ledger | schreibt/erzeugt Artefakte | `app.py:1127` `rebuild_balance_ledger` |

## Transfers

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/transfers/candidates` | TRANSFER candidates | read-only | `app.py:1135` `transfer_candidates` |

## Preise und Price Quality

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/prices` | Liste price points | read-only | `app.py:1148` `list_price_points` |
| `POST` | `/api/v1/prices` | Fuegt hinzu price point | schreibt/erzeugt Artefakte | `app.py:1142` `add_price_point` |
| `POST` | `/api/v1/prices/backfill/current-portfolio` | BACKFILL current portfolio prices | pruefen | `app.py:1248` `backfill_current_portfolio_prices` |
| `POST` | `/api/v1/prices/backfill/external` | BACKFILL external prices | pruefen | `app.py:1229` `backfill_external_prices` |
| `GET` | `/api/v1/prices/coverage` | PRICE coverage | read-only | `app.py:1266` `price_coverage` |
| `POST` | `/api/v1/prices/coverage/decisions` | Fuegt hinzu price gap decision | schreibt/erzeugt Artefakte | `app.py:1435` `add_price_gap_decision` |
| `POST` | `/api/v1/prices/import/csv` | Importiert price csv | schreibt/erzeugt Artefakte | `app.py:1161` `import_price_csv` |
| `POST` | `/api/v1/prices/import/csv/preview` | Preview price csv | read-only | `app.py:1156` `preview_price_csv` |
| `POST` | `/api/v1/prices/import/v1-fx-cache` | Importiert v1 fx cache | schreibt/erzeugt Artefakte | `app.py:1199` `import_v1_fx_cache` |
| `POST` | `/api/v1/prices/import/v1-fx-cache/preview` | Preview v1 fx cache import | read-only | `app.py:1189` `preview_v1_fx_cache_import` |
| `GET` | `/api/v1/prices/latest` | Liste latest price points | read-only | `app.py:1152` `list_latest_price_points` |
| `GET` | `/api/v1/prices/quality` | PRICE quality | read-only | `app.py:1270` `price_quality` |
| `GET` | `/api/v1/prices/quality/binance-normalizer-review` | PRICE quality binance normalizer review | read-only | `app.py:1384` `price_quality_binance_normalizer_review` |
| `GET` | `/api/v1/prices/quality/closure-candidates` | PRICE quality closure candidates | read-only | `app.py:1392` `price_quality_closure_candidates` |
| `POST` | `/api/v1/prices/quality/decisions` | Fuegt hinzu price quality decision | schreibt/erzeugt Artefakte | `app.py:1396` `add_price_quality_decision` |
| `GET` | `/api/v1/prices/quality/event-quote-evidence-review` | PRICE quality event quote evidence review | read-only | `app.py:1388` `price_quality_event_quote_evidence_review` |
| `GET` | `/api/v1/prices/quality/group` | PRICE quality group | read-only | `app.py:1274` `price_quality_group` |
| `GET` | `/api/v1/prices/quality/manual-review` | PRICE quality manual review | read-only | `app.py:1290` `price_quality_manual_review` |
| `GET` | `/api/v1/prices/quality/solscan-signature-review` | PRICE quality solscan signature review | read-only | `app.py:1380` `price_quality_solscan_signature_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-apply` | APPLY price quality stablecoin fx anchor prices | schreibt/erzeugt Artefakte | `app.py:1370` `apply_price_quality_stablecoin_fx_anchor_prices` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions` | Fuegt hinzu price quality stablecoin fx anchor preview decision | schreibt/erzeugt Artefakte | `app.py:1360` `add_price_quality_stablecoin_fx_anchor_preview_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest` | PRICE quality stablecoin fx anchor preview latest | read-only | `app.py:1350` `price_quality_stablecoin_fx_anchor_preview_latest` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-impact` | PRICE quality stablecoin fx replacement impact | read-only | `app.py:1310` `price_quality_stablecoin_fx_replacement_impact` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-replacement-preview` | PRICE quality stablecoin fx replacement preview | read-only | `app.py:1298` `price_quality_stablecoin_fx_replacement_preview` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-review` | PRICE quality stablecoin fx review | read-only | `app.py:1294` `price_quality_stablecoin_fx_review` |
| `POST` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions` | Fuegt hinzu price quality stablecoin fx tax impact decision | schreibt/erzeugt Artefakte | `app.py:1340` `add_price_quality_stablecoin_fx_tax_impact_decision` |
| `GET` | `/api/v1/prices/quality/stablecoin-fx-tax-impact-latest` | PRICE quality stablecoin fx tax impact latest | read-only | `app.py:1326` `price_quality_stablecoin_fx_tax_impact_latest` |
| `GET` | `/api/v1/prices/requirements` | PRICE requirements | read-only | `app.py:1431` `price_requirements` |
| `DELETE` | `/api/v1/prices/{price_id}` | Loescht price point | loescht | `app.py:1458` `delete_price_point` |

## Portfolio

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/portfolio/as-of` | PORTFOLIO as of | read-only | `app.py:1487` `portfolio_as_of` |
| `GET` | `/api/v1/portfolio/fiat-deposits/binance` | PORTFOLIO binance fiat deposits | read-only | `app.py:1558` `portfolio_binance_fiat_deposits` |
| `POST` | `/api/v1/portfolio/jup-wallet/import-history` | PORTFOLIO jup wallet import history | schreibt/erzeugt Artefakte | `app.py:1548` `portfolio_jup_wallet_import_history` |
| `GET` | `/api/v1/portfolio/reconciliation` | PORTFOLIO reconciliation | read-only | `app.py:1518` `portfolio_reconciliation` |
| `POST` | `/api/v1/portfolio/reconciliation/refresh` | PORTFOLIO reconciliation refresh | schreibt/erzeugt Artefakte | `app.py:1522` `portfolio_reconciliation_refresh` |
| `GET` | `/api/v1/portfolio/separation-report` | PORTFOLIO separation report | read-only | `app.py:1554` `portfolio_separation_report` |
| `GET` | `/api/v1/portfolio/snapshot` | PORTFOLIO snapshot | read-only | `app.py:1477` `portfolio_snapshot` |
| `GET` | `/api/v1/portfolio/sources` | PORTFOLIO sources | read-only | `app.py:1491` `portfolio_sources` |
| `GET` | `/api/v1/portfolio/token-risk` | PORTFOLIO token risk | read-only | `app.py:1495` `portfolio_token_risk` |
| `GET` | `/api/v1/portfolio/valuation-audit` | PORTFOLIO valuation audit | read-only | `app.py:1483` `portfolio_valuation_audit` |

## Zugewinnausgleich

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/divorce/equalization-summary` | DIVORCE equalization summary | read-only | `app.py:1562` `divorce_equalization_summary` |
| `GET` | `/api/v1/divorce/equalization-summary/accounts.csv` | DIVORCE equalization accounts csv | read-only | `app.py:1576` `divorce_equalization_accounts_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/evidence-package.zip` | DIVORCE equalization evidence package zip | read-only | `app.py:1596` `divorce_equalization_evidence_package_zip` |
| `GET` | `/api/v1/divorce/equalization-summary/live-reconciliation.csv` | DIVORCE equalization live reconciliation csv | read-only | `app.py:1586` `divorce_equalization_live_reconciliation_csv` |
| `GET` | `/api/v1/divorce/equalization-summary/valuation-tokens.csv` | DIVORCE equalization valuation tokens csv | read-only | `app.py:1566` `divorce_equalization_valuation_tokens_csv` |

## Quellen und Connectoren

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/sources/binance/earn-history-api-preview` | BINANCE earn history api preview | read-only | `app.py:1678` `binance_earn_history_api_preview` |
| `POST` | `/api/v1/sources/binance/earn-history-api/import` | BINANCE earn history api import | schreibt/erzeugt Artefakte | `app.py:1772` `binance_earn_history_api_import` |
| `POST` | `/api/v1/sources/binance/earn-history-harvest/import` | BINANCE earn history harvest import | schreibt/erzeugt Artefakte | `app.py:1761` `binance_earn_history_harvest_import` |
| `GET` | `/api/v1/sources/binance/earn-history-preflight` | BINANCE earn history preflight | read-only | `app.py:1674` `binance_earn_history_preflight` |
| `GET` | `/api/v1/sources/binance/reconciliation/evidence` | BINANCE reconciliation evidence | read-only | `app.py:1646` `binance_reconciliation_evidence` |
| `GET` | `/api/v1/sources/binance/withdraw-history-api-preview` | BINANCE withdraw history api preview | read-only | `app.py:1707` `binance_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/binance/withdraw-history-api/import` | BINANCE withdraw history api import | schreibt/erzeugt Artefakte | `app.py:1798` `binance_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/bitget/withdraw-history-api-preview` | BITGET withdraw history api preview | read-only | `app.py:1734` `bitget_withdraw_history_api_preview` |
| `POST` | `/api/v1/sources/bitget/withdraw-history-api/import` | BITGET withdraw history api import | schreibt/erzeugt Artefakte | `app.py:1823` `bitget_withdraw_history_api_import` |
| `GET` | `/api/v1/sources/connector-diagnostics` | SOURCES connector diagnostics | read-only | `app.py:1610` `sources_connector_diagnostics` |
| `GET` | `/api/v1/sources/jupiter/tokens/metadata-cache` | JUPITER token metadata cache | read-only | `app.py:603` `jupiter_token_metadata_cache` |
| `POST` | `/api/v1/sources/jupiter/tokens/metadata-cache/refresh` | Aktualisiert jupiter token metadata cache | schreibt/erzeugt Artefakte | `app.py:619` `refresh_jupiter_token_metadata_cache` |
| `GET` | `/api/v1/sources/jupiter/tokens/risk-review` | JUPITER token risk review | read-only | `app.py:651` `jupiter_token_risk_review` |
| `GET` | `/api/v1/sources/jupiter/tokens/search` | JUPITER token search | read-only | `app.py:563` `jupiter_token_search` |
| `GET` | `/api/v1/sources/overview` | SOURCES overview | read-only | `app.py:1606` `sources_overview` |
| `GET` | `/api/v1/sources/{source_id}` | SOURCE detail | read-only | `app.py:1614` `source_detail` |
| `GET` | `/api/v1/sources/{source_id}/reconciliation` | SOURCE reconciliation | read-only | `app.py:1630` `source_reconciliation` |

## Review und Gates

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/review/decision-suggestions` | REVIEW decision suggestions | read-only | `app.py:1876` `review_decision_suggestions` |
| `POST` | `/api/v1/review/decision-suggestions/{suggestion_id}/accept` | ACCEPT review decision suggestion | schreibt/erzeugt Artefakte | `app.py:1894` `accept_review_decision_suggestion` |
| `GET` | `/api/v1/review/decisions` | Liste review decisions | read-only | `app.py:1872` `list_review_decisions` |
| `POST` | `/api/v1/review/decisions` | Fuegt hinzu review decision | schreibt/erzeugt Artefakte | `app.py:1866` `add_review_decision` |
| `GET` | `/api/v1/review/evidence-traces` | REVIEW evidence traces | read-only | `app.py:1880` `review_evidence_traces` |
| `POST` | `/api/v1/review/evidence-traces/canonicalize` | Kanonisiert review evidence traces | schreibt/erzeugt Artefakte | `app.py:1884` `canonicalize_review_evidence_traces` |
| `GET` | `/api/v1/review/gates` | REVIEW gates | read-only | `app.py:1848` `review_gates` |
| `GET` | `/api/v1/review/tasks` | REVIEW tasks | read-only | `app.py:1854` `review_tasks` |

## V1 Paritaet

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/parity/compare` | Vergleicht v1 v2 parity | read-only | `app.py:2011` `compare_v1_v2_parity` |
| `POST` | `/api/v1/parity/decisions` | Fuegt hinzu parity decision | schreibt/erzeugt Artefakte | `app.py:2049` `add_parity_decision` |
| `GET` | `/api/v1/parity/diagnostics` | PARITY diagnostics | read-only | `app.py:2015` `parity_diagnostics` |
| `GET` | `/api/v1/parity/group-detail` | PARITY group detail | read-only | `app.py:2023` `parity_group_detail` |
| `GET` | `/api/v1/parity/hnt-fifo-provenance` | PARITY hnt fifo provenance | read-only | `app.py:2031` `parity_hnt_fifo_provenance` |
| `GET` | `/api/v1/parity/hnt-wallet-bridge` | PARITY hnt wallet bridge | read-only | `app.py:2027` `parity_hnt_wallet_bridge` |
| `GET` | `/api/v1/parity/release-readiness` | PARITY release readiness | read-only | `app.py:2019` `parity_release_readiness` |
| `POST` | `/api/v1/parity/v1/import/wiso` | Importiert wiso v1 references | schreibt/erzeugt Artefakte | `app.py:1977` `import_wiso_v1_references` |
| `GET` | `/api/v1/parity/v1/references` | Liste v1 reference metrics | read-only | `app.py:1955` `list_v1_reference_metrics` |
| `POST` | `/api/v1/parity/v1/references` | Fuegt hinzu v1 reference metric | schreibt/erzeugt Artefakte | `app.py:1949` `add_v1_reference_metric` |
| `DELETE` | `/api/v1/parity/v1/references/{reference_id}` | Loescht v1 reference metric | loescht | `app.py:1959` `delete_v1_reference_metric` |

## Tax FIFO

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/tax/fifo/rebuild` | Rebuild fifo tax | schreibt/erzeugt Artefakte | `app.py:2072` `rebuild_fifo_tax` |
| `GET` | `/api/v1/tax/holding-periods` | TAX holding periods | read-only | `app.py:2088` `tax_holding_periods` |
| `GET` | `/api/v1/tax/legacy-helium-overview` | TAX legacy helium overview | read-only | `app.py:2114` `tax_legacy_helium_overview` |
| `GET` | `/api/v1/tax/lines` | Liste tax lines | read-only | `app.py:2076` `list_tax_lines` |
| `GET` | `/api/v1/tax/loss-realization-planner` | TAX loss realization planner | read-only | `app.py:2092` `tax_loss_realization_planner` |
| `GET` | `/api/v1/tax/lots` | Liste tax lots | read-only | `app.py:2080` `list_tax_lots` |
| `GET` | `/api/v1/tax/summary` | TAX summary | read-only | `app.py:2106` `tax_summary` |
| `GET` | `/api/v1/tax/unmatched-disposals` | Liste tax unmatched disposals | read-only | `app.py:2084` `list_tax_unmatched_disposals` |
| `GET` | `/api/v1/tax/wallet-fifo-preview` | TAX wallet fifo preview | read-only | `app.py:2110` `tax_wallet_fifo_preview` |

## Steuerjahre und BMF

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/tax-years/correction-map` | TAX years correction map | read-only | `app.py:2156` `tax_years_correction_map` |
| `GET` | `/api/v1/tax-years/filing-closure-overview` | TAX years filing closure overview | read-only | `app.py:2136` `tax_years_filing_closure_overview` |
| `GET` | `/api/v1/tax-years/filing-matrix` | TAX years filing matrix | read-only | `app.py:2126` `tax_years_filing_matrix` |
| `GET` | `/api/v1/tax-years/helium-swap-alchemy-audit` | TAX years helium swap alchemy audit | read-only | `app.py:4286` `tax_years_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/helium-swap-context` | TAX years helium swap context | read-only | `app.py:2168` `tax_years_helium_swap_context` |
| `GET` | `/api/v1/tax-years/helium-swap-evidence-review` | TAX years helium swap evidence review | read-only | `app.py:2172` `tax_years_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/payment-overview` | TAX years payment overview | read-only | `app.py:2122` `tax_years_payment_overview` |
| `GET` | `/api/v1/tax-years/reward-bmf-recheck` | TAX years reward bmf recheck | read-only | `app.py:2316` `tax_years_reward_bmf_recheck` |
| `GET` | `/api/v1/tax-years/reward-trading-separation` | TAX years reward trading separation | read-only | `app.py:2146` `tax_years_reward_trading_separation` |
| `GET` | `/api/v1/tax-years/solana-program-income-review` | TAX years solana program income review | read-only | `app.py:2164` `tax_years_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-fx-review` | TAX years solana stablecoin fx review | read-only | `app.py:2188` `tax_years_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/solana-stablecoin-swap-context` | TAX years solana stablecoin swap context | read-only | `app.py:2184` `tax_years_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/stablecoin-fifo-review` | TAX years stablecoin fifo review | read-only | `app.py:2176` `tax_years_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/stablecoin-quote-leg-review` | TAX years stablecoin quote leg review | read-only | `app.py:2180` `tax_years_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/summary` | TAX years summary | read-only | `app.py:2118` `tax_years_summary` |
| `GET` | `/api/v1/tax-years/turnover-audit-summary` | TAX years turnover audit summary | read-only | `app.py:2160` `tax_years_turnover_audit_summary` |
| `GET` | `/api/v1/tax-years/{year}` | TAX year detail | read-only | `app.py:2320` `tax_year_detail` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-correction-review` | TAX year asset fifo correction review | read-only | `app.py:3175` `tax_year_asset_fifo_correction_review` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-drilldown` | TAX year asset fifo drilldown | read-only | `app.py:3153` `tax_year_asset_fifo_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/asset-fifo-plausibility` | TAX year asset fifo plausibility | read-only | `app.py:3161` `tax_year_asset_fifo_plausibility` |
| `GET` | `/api/v1/tax-years/{year}/bmf-closure-appendix` | TAX year bmf closure appendix | read-only | `app.py:3197` `tax_year_bmf_closure_appendix` |
| `GET` | `/api/v1/tax-years/{year}/cex-deposit-transfer-evidence` | TAX year cex deposit transfer evidence | read-only | `app.py:2498` `tax_year_cex_deposit_transfer_evidence` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility` | TAX year cex exchange outflow anchor feasibility | read-only | `app.py:2694` `tax_year_cex_exchange_outflow_anchor_feasibility` |
| `POST` | `/api/v1/tax-years/{year}/cex-exchange-outflow-decisions` | Fuegt hinzu tax year cex exchange outflow decision | schreibt/erzeugt Artefakte | `app.py:2714` `add_tax_year_cex_exchange_outflow_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-exchange-outflow-evidence` | TAX year cex exchange outflow evidence | read-only | `app.py:2674` `tax_year_cex_exchange_outflow_evidence` |
| `POST` | `/api/v1/tax-years/{year}/cex-sender-ownership-decisions` | Fuegt hinzu tax year cex sender ownership decision | schreibt/erzeugt Artefakte | `app.py:2530` `add_tax_year_cex_sender_ownership_decision` |
| `GET` | `/api/v1/tax-years/{year}/cex-sender-ownership-latest` | TAX year cex sender ownership latest | read-only | `app.py:2514` `tax_year_cex_sender_ownership_latest` |
| `GET` | `/api/v1/tax-years/{year}/compliance-status` | TAX year compliance status | read-only | `app.py:2470` `tax_year_compliance_status` |
| `GET` | `/api/v1/tax-years/{year}/correction-map` | TAX year correction map | read-only | `app.py:2332` `tax_year_correction_map` |
| `GET` | `/api/v1/tax-years/{year}/declaration-guide` | TAX year declaration guide | read-only | `app.py:2324` `tax_year_declaration_guide` |
| `GET` | `/api/v1/tax-years/{year}/drivers` | TAX year drivers | read-only | `app.py:3113` `tax_year_drivers` |
| `GET` | `/api/v1/tax-years/{year}/evidence` | TAX year evidence | read-only | `app.py:3193` `tax_year_evidence` |
| `GET` | `/api/v1/tax-years/{year}/external-inflows` | TAX year external inflows | read-only | `app.py:3201` `tax_year_external_inflows` |
| `GET` | `/api/v1/tax-years/{year}/filing-summary` | TAX year filing summary | read-only | `app.py:2328` `tax_year_filing_summary` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-acquisition-event-deltas` | TAX year gain evidence acquisition event deltas | read-only | `app.py:3146` `tax_year_gain_evidence_acquisition_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-event-deltas` | TAX year gain evidence event deltas | read-only | `app.py:3139` `tax_year_gain_evidence_event_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-price-deltas` | TAX year gain evidence price deltas | read-only | `app.py:3125` `tax_year_gain_evidence_price_deltas` |
| `GET` | `/api/v1/tax-years/{year}/gain-evidence-review` | TAX year gain evidence review | read-only | `app.py:3121` `tax_year_gain_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/gain-loss-reality-check` | TAX year gain loss reality check | read-only | `app.py:3117` `tax_year_gain_loss_reality_check` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-alchemy-audit` | TAX year helium swap alchemy audit | read-only | `app.py:4290` `tax_year_helium_swap_alchemy_audit` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-context` | TAX year helium swap context | read-only | `app.py:3089` `tax_year_helium_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/helium-swap-evidence-review` | TAX year helium swap evidence review | read-only | `app.py:3093` `tax_year_helium_swap_evidence_review` |
| `GET` | `/api/v1/tax-years/{year}/income-guide` | TAX year income guide | read-only | `app.py:3081` `tax_year_income_guide` |
| `GET` | `/api/v1/tax-years/{year}/methodology` | TAX year methodology | read-only | `app.py:2466` `tax_year_methodology` |
| `GET` | `/api/v1/tax-years/{year}/solana-program-income-review` | TAX year solana program income review | read-only | `app.py:3085` `tax_year_solana_program_income_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-fx-review` | TAX year solana stablecoin fx review | read-only | `app.py:3109` `tax_year_solana_stablecoin_fx_review` |
| `GET` | `/api/v1/tax-years/{year}/solana-stablecoin-swap-context` | TAX year solana stablecoin swap context | read-only | `app.py:3105` `tax_year_solana_stablecoin_swap_context` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-fifo-review` | TAX year stablecoin fifo review | read-only | `app.py:3097` `tax_year_stablecoin_fifo_review` |
| `GET` | `/api/v1/tax-years/{year}/stablecoin-quote-leg-review` | TAX year stablecoin quote leg review | read-only | `app.py:3101` `tax_year_stablecoin_quote_leg_review` |
| `GET` | `/api/v1/tax-years/{year}/turnover-audit` | TAX year turnover audit | read-only | `app.py:3189` `tax_year_turnover_audit` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-delta` | TAX year wallet fifo delta | read-only | `app.py:2474` `tax_year_wallet_fifo_delta` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-exchange-evidence-gaps` | TAX year wallet fifo exchange evidence gaps | read-only | `app.py:2917` `tax_year_wallet_fifo_exchange_evidence_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-gaps` | TAX year wallet fifo gaps | read-only | `app.py:2478` `tax_year_wallet_fifo_gaps` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-opening-balance-evidence` | TAX year wallet fifo opening balance evidence | read-only | `app.py:2901` `tax_year_wallet_fifo_opening_balance_evidence` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-origin-trace` | TAX year wallet fifo origin trace | read-only | `app.py:2482` `tax_year_wallet_fifo_origin_trace` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-closure` | TAX year wallet fifo provenance closure | read-only | `app.py:2860` `tax_year_wallet_fifo_provenance_closure` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-events` | TAX year wallet fifo provenance events | read-only | `app.py:2867` `tax_year_wallet_fifo_provenance_events` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-provenance-priorities` | TAX year wallet fifo provenance priorities | read-only | `app.py:2853` `tax_year_wallet_fifo_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-raw-provenance-breakdown` | TAX year wallet fifo raw provenance breakdown | read-only | `app.py:2885` `tax_year_wallet_fifo_raw_provenance_breakdown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-origin` | TAX year wallet fifo solana origin | read-only | `app.py:3058` `tax_year_wallet_fifo_solana_origin` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-batch-latest` | TAX year wallet fifo solana provenance batch latest | read-only | `app.py:2955` `tax_year_wallet_fifo_solana_provenance_batch_latest` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-classification` | TAX year wallet fifo solana provenance classification | read-only | `app.py:2933` `tax_year_wallet_fifo_solana_provenance_classification` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-drilldown` | TAX year wallet fifo solana raw bmf evidence drilldown | read-only | `app.py:3010` `tax_year_wallet_fifo_solana_raw_bmf_evidence_drilldown` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-summary` | TAX year wallet fifo solana raw bmf evidence summary | read-only | `app.py:2994` `tax_year_wallet_fifo_solana_raw_bmf_evidence_summary` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-priorities` | TAX year wallet fifo solana raw provenance priorities | read-only | `app.py:2962` `tax_year_wallet_fifo_solana_raw_provenance_priorities` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-senders` | TAX year wallet fifo solana raw provenance senders | read-only | `app.py:2978` `tax_year_wallet_fifo_solana_raw_provenance_senders` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-cluster-outflows` | TAX year wallet fifo solana sender cluster outflows | read-only | `app.py:3038` `tax_year_wallet_fifo_solana_sender_cluster_outflows` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-solana-sender-clusters` | TAX year wallet fifo solana sender clusters | read-only | `app.py:3030` `tax_year_wallet_fifo_solana_sender_clusters` |
| `GET` | `/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps` | TAX year wallet fifo withdrawal gaps | read-only | `app.py:3074` `tax_year_wallet_fifo_withdrawal_gaps` |

## BMF Methodik

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/tax-methodology/bmf-action-plan` | TAX methodology bmf action plan | read-only | `app.py:2196` `tax_methodology_bmf_action_plan` |
| `GET` | `/api/v1/tax-methodology/bmf-amendment-worklist` | TAX methodology bmf amendment worklist | read-only | `app.py:2248` `tax_methodology_bmf_amendment_worklist` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog` | TAX methodology bmf closure backlog | read-only | `app.py:2209` `tax_methodology_bmf_closure_backlog` |
| `GET` | `/api/v1/tax-methodology/bmf-closure-backlog-snapshot` | TAX methodology bmf closure backlog snapshot | read-only | `app.py:2213` `tax_methodology_bmf_closure_backlog_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness` | TAX methodology bmf filing readiness | read-only | `app.py:2217` `tax_methodology_bmf_filing_readiness` |
| `GET` | `/api/v1/tax-methodology/bmf-filing-readiness-snapshot` | TAX methodology bmf filing readiness snapshot | read-only | `app.py:2226` `tax_methodology_bmf_filing_readiness_snapshot` |
| `GET` | `/api/v1/tax-methodology/bmf-finalization-matrix` | TAX methodology bmf finalization matrix | read-only | `app.py:2230` `tax_methodology_bmf_finalization_matrix` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-comparison` | TAX methodology bmf prior filing comparison | read-only | `app.py:2244` `tax_methodology_bmf_prior_filing_comparison` |
| `GET` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | TAX methodology bmf prior filing declared amounts | read-only | `app.py:2306` `tax_methodology_bmf_prior_filing_declared_amounts` |
| `PUT` | `/api/v1/tax-methodology/bmf-prior-filing-declared-amounts` | TAX methodology write bmf prior filing declared amounts | schreibt | `app.py:2310` `tax_methodology_write_bmf_prior_filing_declared_amounts` |
| `GET` | `/api/v1/tax-methodology/bmf-submission-guide` | TAX methodology bmf submission guide | read-only | `app.py:2240` `tax_methodology_bmf_submission_guide` |
| `GET` | `/api/v1/tax-methodology/summary` | TAX methodology summary | read-only | `app.py:2192` `tax_methodology_summary` |

## Derivate

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/derivatives/lines` | Liste derivative lines | read-only | `app.py:3209` `list_derivative_lines` |
| `POST` | `/api/v1/derivatives/rebuild` | Rebuild derivatives | schreibt/erzeugt Artefakte | `app.py:3205` `rebuild_derivatives` |
| `GET` | `/api/v1/derivatives/summary` | DERIVATIVE summary | read-only | `app.py:3213` `derivative_summary` |

## Flows

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/flows/net` | NET flows | read-only | `app.py:3229` `net_flows` |
| `POST` | `/api/v1/flows/rebuild` | Rebuild flows | schreibt/erzeugt Artefakte | `app.py:3225` `rebuild_flows` |

## Export und Evidence

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/export/all-transaction-decision-candidates.json` | Download/Export all transaction decision candidates json | read-only | `app.py:4244` `download_all_transaction_decision_candidates_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-closure.json` | Download/Export all transaction evidence closure json | read-only | `app.py:4228` `download_all_transaction_evidence_closure_json` |
| `GET` | `/api/v1/export/all-transaction-evidence-matrix.json` | Download/Export all transaction evidence matrix json | read-only | `app.py:4220` `download_all_transaction_evidence_matrix_json` |
| `GET` | `/api/v1/export/all-transaction-open-detail-review.json` | Download/Export all transaction open detail review json | read-only | `app.py:4236` `download_all_transaction_open_detail_review_json` |
| `POST` | `/api/v1/export/audit` | EXPORT audit | pruefen | `app.py:3318` `export_audit` |
| `GET` | `/api/v1/export/audit.json` | Download/Export audit json | read-only | `app.py:3326` `download_audit_json` |
| `GET` | `/api/v1/export/binance-fiat-deposits.csv` | Download/Export binance fiat deposits csv | read-only | `app.py:3698` `download_binance_fiat_deposits_csv` |
| `GET` | `/api/v1/export/derivative-lines.csv` | Download/Export derivative lines csv | read-only | `app.py:3821` `download_derivative_lines_csv` |
| `POST` | `/api/v1/export/elster-prep` | EXPORT elster prep | pruefen | `app.py:3322` `export_elster_prep` |
| `GET` | `/api/v1/export/evidence-manifest.json` | Download/Export evidence manifest | read-only | `app.py:3251` `download_evidence_manifest` |
| `GET` | `/api/v1/export/evidence-package-index.json` | Download/Export evidence package index | read-only | `app.py:3260` `download_evidence_package_index` |
| `GET` | `/api/v1/export/evidence-package.zip` | Download/Export evidence package zip | read-only | `app.py:4659` `download_evidence_package_zip` |
| `GET` | `/api/v1/export/hnt-provenance-events.csv` | Download/Export hnt provenance events csv | read-only | `app.py:3636` `download_hnt_provenance_events_csv` |
| `GET` | `/api/v1/export/hnt-provenance-timeline.csv` | Download/Export hnt provenance timeline csv | read-only | `app.py:3582` `download_hnt_provenance_timeline_csv` |
| `GET` | `/api/v1/export/packages` | Liste export packages | read-only | `app.py:3237` `list_export_packages` |
| `DELETE` | `/api/v1/export/packages/{package_id}` | Loescht export package | loescht | `app.py:3300` `delete_export_package` |
| `GET` | `/api/v1/export/packages/{package_id}/download.pdf` | Download/Export export package pdf | read-only | `app.py:3269` `download_export_package_pdf` |
| `GET` | `/api/v1/export/parity-diagnostics.csv` | Download/Export parity diagnostics csv | read-only | `app.py:3536` `download_parity_diagnostics_csv` |
| `POST` | `/api/v1/export/pdf` | Erzeugt pdf export | schreibt/erzeugt Artefakte | `app.py:3233` `create_pdf_export` |
| `GET` | `/api/v1/export/price-gaps.csv` | Download/Export price gaps csv | read-only | `app.py:3446` `download_price_gaps_csv` |
| `GET` | `/api/v1/export/price-requirements.csv` | Download/Export price requirements csv | read-only | `app.py:3494` `download_price_requirements_csv` |
| `GET` | `/api/v1/export/readiness` | EXPORT readiness | read-only | `app.py:3241` `export_readiness` |
| `GET` | `/api/v1/export/review-decisions.csv` | Download/Export review decisions csv | read-only | `app.py:3344` `download_review_decisions_csv` |
| `GET` | `/api/v1/export/solana-failed-tx-tax-impact.json` | Download/Export solana failed tx tax impact json | read-only | `app.py:4212` `download_solana_failed_tx_tax_impact_json` |
| `GET` | `/api/v1/export/solana-tx-alchemy-audit.json` | Download/Export solana tx alchemy audit json | read-only | `app.py:4204` `download_solana_tx_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-external-inflows.csv` | Download/Export tax external inflows csv | read-only | `app.py:3961` `download_tax_external_inflows_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-alchemy-audit.json` | Download/Export tax helium swap alchemy audit json | read-only | `app.py:4294` `download_tax_helium_swap_alchemy_audit_json` |
| `GET` | `/api/v1/export/tax-helium-swap-context.csv` | Download/Export tax helium swap context csv | read-only | `app.py:4573` `download_tax_helium_swap_context_csv` |
| `GET` | `/api/v1/export/tax-helium-swap-evidence-review.csv` | Download/Export tax helium swap evidence review csv | read-only | `app.py:4646` `download_tax_helium_swap_evidence_review_csv` |
| `GET` | `/api/v1/export/tax-income-guide.csv` | Download/Export tax income guide csv | read-only | `app.py:3883` `download_tax_income_guide_csv` |
| `GET` | `/api/v1/export/tax-lines.csv` | Download/Export tax lines csv | read-only | `app.py:3778` `download_tax_lines_csv` |
| `GET` | `/api/v1/export/tax-methodology/bmf-amendment-worklist.csv` | Download/Export bmf amendment worklist csv | read-only | `app.py:2298` `download_bmf_amendment_worklist_csv` |
| `GET` | `/api/v1/export/tax-payment-overview.json` | Download/Export tax payment overview json | read-only | `app.py:3335` `download_tax_payment_overview_json` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-evidence.csv` | Download/Export tax solana stablecoin swap evidence csv | read-only | `app.py:4397` `download_tax_solana_stablecoin_swap_evidence_csv` |
| `GET` | `/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv` | Download/Export tax solana stablecoin swap fifo lines csv | read-only | `app.py:4502` `download_tax_solana_stablecoin_swap_fifo_lines_csv` |
| `GET` | `/api/v1/export/tax-years/correction-map.csv` | Download/Export tax years correction map csv | read-only | `app.py:2404` `download_tax_years_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/correction-map.csv` | Download/Export tax year correction map csv | read-only | `app.py:2412` `download_tax_year_correction_map_csv` |
| `GET` | `/api/v1/export/tax-years/{year}/evidence-package.zip` | Download/Export tax year evidence package zip | read-only | `app.py:4871` `download_tax_year_evidence_package_zip` |
| `GET` | `/api/v1/export/tax-years/{year}/filing-checklist.csv` | Download/Export tax year filing checklist csv | read-only | `app.py:2456` `download_tax_year_filing_checklist_csv` |
| `GET` | `/api/v1/export/token-risk-documentation.csv` | Download/Export token risk documentation csv | read-only | `app.py:3388` `download_token_risk_documentation_csv` |

## Report Center

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/reports/center` | REPORT center | read-only | `app.py:3245` `report_center` |

## Lokale KI und AI Tasks

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review` | LOCAL ai asset fifo correction review | read-only | `app.py:5492` `local_ai_asset_fifo_correction_review` |
| `GET` | `/api/v1/ai/local-asset-fifo-correction-review/artifacts/{artifact}` | Download/Export local ai asset fifo correction artifact | read-only | `app.py:5496` `download_local_ai_asset_fifo_correction_artifact` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review` | LOCAL ai wallet fifo provenance review | read-only | `app.py:5523` `local_ai_wallet_fifo_provenance_review` |
| `GET` | `/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/{artifact}` | Download/Export local ai wallet fifo provenance artifact | read-only | `app.py:5527` `download_local_ai_wallet_fifo_provenance_artifact` |
| `GET` | `/api/v1/ai/local-year-package-qa` | LOCAL ai year package qa | read-only | `app.py:5461` `local_ai_year_package_qa` |
| `GET` | `/api/v1/ai/local-year-package-qa/artifacts/{artifact}` | Download/Export local ai year package qa artifact | read-only | `app.py:5465` `download_local_ai_year_package_qa_artifact` |
| `GET` | `/api/v1/ai/tasks` | Liste ai tasks | read-only | `app.py:5457` `list_ai_tasks` |
| `POST` | `/api/v1/ai/tasks` | Erzeugt ai task | schreibt/erzeugt Artefakte | `app.py:5453` `create_ai_task` |
| `DELETE` | `/api/v1/ai/tasks/{task_id}` | Loescht ai task | loescht | `app.py:5554` `delete_ai_task` |

## Demo und Seeds

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/demo/seed` | SEED demo | schreibt/erzeugt Artefakte | `app.py:3221` `seed_demo` |

## health

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/health` | HEALTH health | read-only | `app.py:461` `health` |

## pipeline

| Methode | Endpoint | Zweck | Schreibwirkung | Code |
| --- | --- | --- | --- | --- |
| `POST` | `/api/v1/pipeline/rebuild` | Rebuild pipeline | schreibt/erzeugt Artefakte | `app.py:3217` `rebuild_pipeline` |

