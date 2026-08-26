"""
title: Steuerreport V2 Read-only
author: Steuerreport V2
version: 1.0.0
description: Kontrollierter Lesezugriff auf Status-, Steuerjahr-, FIFO-, Quellen- und Stichtagsdaten.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, time as datetime_time, timezone
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


class _RejectRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirects are disabled", headers, fp)


class Tools:
    class Valves(BaseModel):
        API_BASE_URL: str = Field(
            default="http://192.168.2.122:8010/api/v1",
            description="Trusted Steuerreport V2 API base URL ending in /api/v1.",
        )
        TIMEOUT_SECONDS: int = Field(default=90, ge=5, le=180)
        MAX_RESPONSE_BYTES: int = Field(default=131072, ge=16384, le=524288)

    def __init__(self) -> None:
        self.valves = self.Valves()

    def _base_url(self) -> str:
        value = self.valves.API_BASE_URL.rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("API_BASE_URL must use http or https")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("API_BASE_URL must contain a host and no credentials")
        if parsed.query or parsed.fragment or not parsed.path.endswith("/api/v1"):
            raise ValueError("API_BASE_URL must end in /api/v1 without query or fragment")
        return value

    @staticmethod
    def _error(kind: str, message: str, **details) -> dict:
        return {
            "ok": False,
            "error": {"kind": kind, "message": message, **details},
        }

    def _get(
        self,
        path: str,
        query: dict | None = None,
        *,
        read_limit: int | None = None,
        transform=None,
    ) -> dict:
        if not path.startswith("/") or ".." in path:
            return self._error("invalid_path", "The requested API path is not allowed")

        try:
            url = f"{self._base_url()}{path}"
        except ValueError as exc:
            return self._error("invalid_configuration", str(exc))

        if query:
            url = f"{url}?{urlencode(query)}"

        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "OpenWebUI-Steuerreport-Readonly/1.0",
            },
            method="GET",
        )
        started = time.monotonic()
        opener = build_opener(_RejectRedirectHandler())
        output_limit = int(self.valves.MAX_RESPONSE_BYTES)
        limit = int(read_limit or output_limit)

        try:
            with opener.open(request, timeout=int(self.valves.TIMEOUT_SECONDS)) as response:
                content_type = response.headers.get_content_type()
                payload_bytes = response.read(limit + 1)
                if len(payload_bytes) > limit:
                    return self._error(
                        "response_too_large",
                        "The response exceeded the configured safety limit",
                        endpoint=path,
                        max_response_bytes=limit,
                    )
                if content_type != "application/json":
                    return self._error(
                        "unexpected_content_type",
                        "The endpoint did not return JSON",
                        endpoint=path,
                        content_type=content_type,
                    )
                payload = json.loads(payload_bytes.decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(min(limit, 8192)).decode("utf-8", errors="replace")
            return self._error(
                "http_error",
                f"Steuerreport API returned HTTP {exc.code}",
                endpoint=path,
                status=exc.code,
                detail=detail[:2000],
            )
        except URLError as exc:
            return self._error(
                "connection_error",
                "Steuerreport API is not reachable",
                endpoint=path,
                detail=str(exc.reason)[:500],
            )
        except TimeoutError:
            return self._error(
                "timeout",
                "Steuerreport API did not answer before the read timeout",
                endpoint=path,
                timeout_seconds=int(self.valves.TIMEOUT_SECONDS),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._error(
                "invalid_json",
                "Steuerreport API returned malformed JSON",
                endpoint=path,
                detail=str(exc)[:500],
            )

        if transform is not None:
            payload = transform(payload)
            projected_size = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if projected_size > output_limit:
                return self._error(
                    "projected_response_too_large",
                    "The compacted response still exceeded the configured safety limit",
                    endpoint=path,
                    projected_response_bytes=projected_size,
                    max_response_bytes=output_limit,
                )

        return {
            "ok": True,
            "endpoint": path,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "data": payload,
        }

    @staticmethod
    def _decimal_magnitude(value) -> float:
        try:
            return abs(float(value))
        except (TypeError, ValueError, OverflowError):
            return 0.0

    @classmethod
    def _compact_asset_rows(cls, rows, value_key: str, limit: int = 10) -> dict:
        items = rows if isinstance(rows, list) else []
        ordered = sorted(
            (item for item in items if isinstance(item, dict)),
            key=lambda item: cls._decimal_magnitude(item.get(value_key)),
            reverse=True,
        )
        return {
            "items": ordered[:limit],
            "total_count": len(ordered),
            "omitted_count": max(0, len(ordered) - limit),
        }

    @classmethod
    def _compact_equalization_payload(cls, payload: dict) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return payload

        source = payload["data"]
        original_bytes = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        large_sections = {
            "accounts",
            "live_reconciliation",
            "marital_pre_cutoff",
            "post_cutoff_direct_eur_invest",
            "post_cutoff_all_lots",
        }
        compact = {key: value for key, value in source.items() if key not in large_sections}

        accounts = []
        for account in source.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            item = {
                key: value
                for key, value in account.items()
                if key not in {"cutoff_assets", "valuation_assets"}
            }
            item["asset_detail_projection"] = {
                "cutoff_rows_omitted": len(account.get("cutoff_assets") or []),
                "valuation_rows_omitted": len(account.get("valuation_assets") or []),
                "detail_endpoint": "/portfolio/as-of",
            }
            accounts.append(item)
        compact["accounts"] = accounts

        inheritance_gate = source.get("inheritance_origin_gate")
        if isinstance(inheritance_gate, dict):
            projected_inheritance = {
                key: value
                for key, value in inheritance_gate.items()
                if key != "investment_flows"
            }
            projected_inheritance["investment_flows_top"] = cls._compact_asset_rows(
                inheritance_gate.get("investment_flows"), "amount_eur", limit=10
            )
            compact["inheritance_origin_gate"] = projected_inheritance

        capital_gate = source.get("capital_flow_gate")
        if isinstance(capital_gate, dict):
            projected_capital = {
                key: value
                for key, value in capital_gate.items()
                if key != "outflows"
            }
            projected_capital["outflows_top"] = cls._compact_asset_rows(
                capital_gate.get("outflows"), "value_eur", limit=10
            )
            compact["capital_flow_gate"] = projected_capital

        for key in (
            "marital_pre_cutoff",
            "post_cutoff_direct_eur_invest",
            "post_cutoff_all_lots",
        ):
            bucket = source.get(key)
            if not isinstance(bucket, dict):
                compact[key] = bucket
                continue
            projected_bucket = {field: value for field, value in bucket.items() if field != "assets"}
            projected_bucket["assets_top"] = cls._compact_asset_rows(
                bucket.get("assets"), "total_value_or_proceeds_eur", limit=10
            )
            compact[key] = projected_bucket

        reconciliation = [
            item
            for item in (source.get("live_reconciliation") or [])
            if isinstance(item, dict)
        ]
        status_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        material_items = []
        for item in reconciliation:
            status = str(item.get("status") or "unknown")
            severity = str(item.get("severity") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            if severity != "info" or cls._decimal_magnitude(item.get("delta_value_eur")) >= 1:
                material_items.append(item)
        compact["live_reconciliation"] = {
            "total_count": len(reconciliation),
            "status_counts": status_counts,
            "severity_counts": severity_counts,
            "material_items": material_items[:20],
            "omitted_non_material_count": max(0, len(reconciliation) - len(material_items[:20])),
        }
        compact["agent_projection"] = {
            "kind": "equalization_summary_compact_v1",
            "original_response_bytes": original_bytes,
            "account_asset_rows": "omitted_use_portfolio_as_of",
            "inheritance_investment_flow_limit": 10,
            "capital_outflow_limit": 10,
            "fifo_bucket_asset_limit": 10,
            "live_reconciliation_filter": "severity_not_info_or_abs_delta_value_eur_gte_1",
            "detail_note": (
                "Aggregate values and evidence gates are complete. Large per-asset and non-material "
                "live lists are bounded for the model context."
            ),
        }

        return {**payload, "data": compact}

    @classmethod
    def _compact_portfolio_as_of_payload(cls, payload: dict) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return payload

        source = payload["data"]
        original_bytes = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        compact = {
            key: value
            for key, value in source.items()
            if key not in {"positions", "asset_summary"}
        }
        compact["asset_summary_top"] = cls._compact_asset_rows(
            source.get("asset_summary"), "value_eur", limit=15
        )
        compact["positions_top"] = cls._compact_asset_rows(
            source.get("positions"), "value_eur", limit=15
        )
        excluded_accounts = source.get("excluded_account_summary") or []
        compact["excluded_balance_notice"] = {
            "account_count": len(excluded_accounts) if isinstance(excluded_accounts, list) else 0,
            "included_in_portfolio_total": False,
            "may_be_added_to_portfolio_total": False,
            "semantics": source.get("excluded_value_semantics")
            or (
                "Audit-only technical event-account valuation. It is not an account balance, "
                "not portfolio wealth and must not be added to total_value_eur."
            ),
        }
        compact["agent_projection"] = {
            "kind": "portfolio_as_of_compact_v2",
            "original_response_bytes": original_bytes,
            "asset_summary_limit": 15,
            "position_limit": 15,
            "detail_note": (
                "Portfolio total, account summary, exclusions with reasons and price gaps are complete. "
                "Excluded values are diagnostic event-account valuations and must never be added. "
                "Per-asset and per-account position rows are ordered by absolute EUR value and bounded."
            ),
        }
        return {**payload, "data": compact}

    @staticmethod
    def _validated_year(year: int) -> int | None:
        upper = datetime.now(timezone.utc).year + 1
        return year if 2021 <= year <= upper else None

    @staticmethod
    def _validated_date(value: str) -> str | None:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        return parsed.isoformat() if 2021 <= parsed.year <= 2100 else None

    def get_operational_status(
        self,
        view: Literal[
            "health",
            "review_gate",
            "cockpit",
            "portfolio",
            "portfolio_reconciliation",
            "portfolio_sources",
            "source_overview",
            "connector_diagnostics",
        ] = "cockpit",
    ) -> dict:
        """Liefert genau einen aktuellen Betriebs-, Portfolio- oder Quellenstatus.

        :param view: Gewuenschte Statussicht. Fuer steuerliche Aussagen immer den
            Datenstand aus der Antwort nennen.
        """

        paths = {
            "health": "/health",
            "review_gate": "/review/gates",
            "cockpit": "/cockpit/summary",
            "portfolio": "/portfolio/snapshot",
            "portfolio_reconciliation": "/portfolio/reconciliation",
            "portfolio_sources": "/portfolio/sources",
            "source_overview": "/sources/overview",
            "connector_diagnostics": "/sources/connector-diagnostics",
        }
        path = paths.get(view)
        if not path:
            return self._error("invalid_view", "Unknown operational status view")
        return self._get(path)

    def get_tax_year(
        self,
        year: int,
        view: Literal[
            "summary",
            "filing_summary",
            "declaration_guide",
            "compliance_status",
            "gain_loss_reality_check",
        ] = "summary",
    ) -> dict:
        """Liefert eine belegorientierte Sicht fuer ein Steuerjahr.

        :param year: Steuerjahr ab 2021 bis hoechstens zum Folgejahr.
        :param view: Zusammenfassung, Abgabesicht, Eingabehilfe, Compliance oder
            Plausibilitaetskontrolle.
        """

        valid_year = self._validated_year(year)
        if valid_year is None:
            return self._error("invalid_year", "Tax year is outside the supported range")
        suffixes = {
            "summary": "",
            "filing_summary": "/filing-summary",
            "declaration_guide": "/declaration-guide",
            "compliance_status": "/compliance-status",
            "gain_loss_reality_check": "/gain-loss-reality-check",
        }
        suffix = suffixes.get(view)
        if suffix is None:
            return self._error("invalid_view", "Unknown tax-year view")
        return self._get(f"/tax-years/{valid_year}{suffix}")

    def get_tax_year_overview(self) -> dict:
        """Liefert die kompakte Jahresuebersicht ueber alle vorhandenen Steuerjahre."""

        return self._get("/tax-years/summary")

    def get_fifo_status(
        self,
        year: int,
        view: Literal[
            "gaps",
            "origin_trace",
            "provenance_closure",
            "withdrawal_gaps",
            "asset_plausibility",
        ] = "provenance_closure",
    ) -> dict:
        """Liefert die Wallet-/Depot-FIFO-Pruefsicht fuer ein Steuerjahr.

        :param year: Steuerjahr ab 2021 bis hoechstens zum Folgejahr.
        :param view: Gewuenschte FIFO-Kontrolle. Eine leere Worklist ist nur mit
            dem zugehoerigen Methoden- und Reviewstatus als geschlossen zu werten.
        """

        valid_year = self._validated_year(year)
        if valid_year is None:
            return self._error("invalid_year", "Tax year is outside the supported range")
        suffixes = {
            "gaps": "wallet-fifo-gaps",
            "origin_trace": "wallet-fifo-origin-trace",
            "provenance_closure": "wallet-fifo-provenance-closure",
            "withdrawal_gaps": "wallet-fifo-withdrawal-gaps",
            "asset_plausibility": "asset-fifo-plausibility",
        }
        suffix = suffixes.get(view)
        if not suffix:
            return self._error("invalid_view", "Unknown FIFO status view")
        return self._get(f"/tax-years/{valid_year}/{suffix}")

    def get_asset_fifo(self, year: int, asset: str, limit: int = 50) -> dict:
        """Liefert den FIFO-Drilldown fuer genau ein Asset und Steuerjahr.

        :param year: Steuerjahr ab 2021 bis hoechstens zum Folgejahr.
        :param asset: Kurzes Asset-Symbol wie HNT, SOL, JUP oder TRUMP.
        :param limit: Maximale Anzahl Detailzeilen zwischen 1 und 100.
        """

        valid_year = self._validated_year(year)
        clean_asset = asset.strip().upper() if isinstance(asset, str) else ""
        if valid_year is None:
            return self._error("invalid_year", "Tax year is outside the supported range")
        if not re.fullmatch(r"[A-Z0-9._-]{1,32}", clean_asset):
            return self._error("invalid_asset", "Asset must be a short symbol")
        if not 1 <= limit <= 100:
            return self._error("invalid_limit", "Limit must be between 1 and 100")
        return self._get(
            f"/tax-years/{valid_year}/asset-fifo-drilldown",
            {"asset": clean_asset, "limit": limit},
        )

    def get_bmf_status(
        self,
        year: int,
        view: Literal[
            "compliance_matrix",
            "filing_readiness",
            "finalization_matrix",
            "closure_backlog",
        ] = "filing_readiness",
    ) -> dict:
        """Liefert BMF-Matrix, Abgabereife oder offenen Abschluss-Backlog.

        :param year: Steuerjahr ab 2021 bis hoechstens zum Folgejahr.
        :param view: Gewuenschte BMF-Kontrollsicht.
        """

        valid_year = self._validated_year(year)
        if valid_year is None:
            return self._error("invalid_year", "Tax year is outside the supported range")
        paths = {
            "compliance_matrix": "/tax-methodology/bmf-compliance-matrix",
            "filing_readiness": "/tax-methodology/bmf-filing-readiness",
            "finalization_matrix": "/tax-methodology/bmf-finalization-matrix",
            "closure_backlog": "/tax-methodology/bmf-closure-backlog",
        }
        path = paths.get(view)
        if not path:
            return self._error("invalid_view", "Unknown BMF status view")
        query = {"year": valid_year} if view in {"filing_readiness", "closure_backlog"} else None
        return self._get(path, query)

    def get_legal_research_status(
        self,
        view: Literal["freshness", "sources"] = "freshness",
    ) -> dict:
        """Liefert den Stand der offiziellen Rechtsquellen-Aktualitaetspruefung.

        :param view: Freshness-Gate des letzten Monitorlaufs oder die versionierte
            Registry der ueberwachten offiziellen Quellen.
        """

        paths = {
            "freshness": "/tax-methodology/legal-research/freshness",
            "sources": "/tax-methodology/legal-research/sources",
        }
        path = paths.get(view)
        if not path:
            return self._error("invalid_view", "Unknown legal research status view")
        return self._get(path)

    def get_source_status(
        self,
        source_id: str,
        view: Literal["source", "reconciliation"] = "source",
    ) -> dict:
        """Liefert Status oder Reconciliation einer konfigurierten Quelle.

        :param source_id: Technische Quellen-ID aus der Quellenuebersicht.
        :param view: Quellenstatus oder Ledger-/Live-Reconciliation.
        """

        value = source_id.strip() if isinstance(source_id, str) else ""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", value):
            return self._error("invalid_source_id", "Source ID contains unsupported characters")
        suffix = "" if view == "source" else "/reconciliation" if view == "reconciliation" else None
        if suffix is None:
            return self._error("invalid_view", "Unknown source status view")
        return self._get(f"/sources/{quote(value, safe='._:-')}{suffix}")

    def get_portfolio_as_of(
        self,
        as_of_date: str,
        timezone_mode: Literal["Europe/Berlin", "UTC"] = "Europe/Berlin",
    ) -> dict:
        """Liefert den historischen Portfolio-Snapshot fuer einen ISO-Stichtag.

        :param as_of_date: Stichtag im Format YYYY-MM-DD. Live-Bestaende duerfen
            nicht als historische Werte zurueckgerechnet werden.
        :param timezone_mode: Tagesende in der deutschen Berichtszeitzone oder
            ausdruecklich in UTC. Fuer Steuer- und Zugewinnstichtage ist
            Europe/Berlin der Standard.
        """

        value = self._validated_date(as_of_date)
        if value is None:
            return self._error("invalid_date", "Date must use YYYY-MM-DD and be in the supported range")
        if timezone_mode not in {"Europe/Berlin", "UTC"}:
            return self._error("invalid_timezone", "Timezone mode must be Europe/Berlin or UTC")
        zone = ZoneInfo(timezone_mode) if timezone_mode == "Europe/Berlin" else timezone.utc
        resolved_utc = datetime.combine(
            date.fromisoformat(value),
            datetime_time.max,
            tzinfo=zone,
        ).astimezone(timezone.utc)
        resolved_iso = resolved_utc.isoformat().replace("+00:00", "Z")
        result = self._get(
            "/portfolio/as-of",
            {"as_of": resolved_iso},
            transform=self._compact_portfolio_as_of_payload,
        )
        if result.get("ok"):
            result["request_context"] = {
                "requested_local_date": value,
                "timezone_mode": timezone_mode,
                "resolved_as_of_utc": resolved_iso,
            }
        return result

    def get_equalization_summary(
        self,
        separation_date: str = "2025-06-13",
        end_asset_date: str = "2026-07-24",
        materiality_threshold_eur: float = 1.0,
    ) -> dict:
        """Liefert die Stichtags-/Zugewinnsicht fuer die expliziten Falldaten.

        :param separation_date: Trennungsdatum im Format YYYY-MM-DD.
        :param end_asset_date: Endvermoegensstichtag im Format YYYY-MM-DD.
        :param materiality_threshold_eur: Untergrenze fuer materielle Positionen
            zwischen 0 und 1000 EUR.
        """

        start = self._validated_date(separation_date)
        end = self._validated_date(end_asset_date)
        if start is None or end is None or start > end:
            return self._error("invalid_date_range", "The date range is invalid")
        if not 0 <= materiality_threshold_eur <= 1000:
            return self._error("invalid_threshold", "Materiality threshold must be between 0 and 1000 EUR")
        return self._get(
            "/divorce/equalization-summary",
            {
                "separation_date": start,
                "end_asset_date": end,
                "materiality_threshold_eur": f"{materiality_threshold_eur:.2f}",
            },
            read_limit=max(int(self.valves.MAX_RESPONSE_BYTES), 524288),
            transform=self._compact_equalization_payload,
        )
