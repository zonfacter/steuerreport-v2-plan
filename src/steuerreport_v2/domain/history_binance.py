"""Kontogebundene Binance-Historie mit dem vorhandenen Earn-Record-Mapper."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService
from steuerreport_v2.domain.history_cex import CexHistoryCollector
from steuerreport_v2.domain.history_types import (
    HistoryFetchError, HistoryOptions, HistoryPage, HistoryRecord, HistoryTarget,
)
from steuerreport_v2.importers.source_history_importer import canonical_json

MAX_PRODUCTS = 1000
MAX_POSITION_IDS = 5000


class BinanceEarnHistoryCollector:
    """Fetches one provider page at a time through the existing Earn adapter."""

    def __init__(self, store, target: HistoryTarget, options: HistoryOptions):
        if (target.provider.lower() != "binance" or not target.connection_id
                or options.include_binance_earn is not True):
            raise HistoryFetchError("history_binance_earn_connection_required", resumable=False)
        self.target, self.options = target, options
        self.spot = CexHistoryCollector(store, target, options)
        self.earn = BinanceEarnHistoryService(store, connection_id=target.connection_id)
        self.start, self.end = options.start, options.end
        self.max_records = options.max_records
        self.products = self._group_products(self.earn.history_products_for_connection())
        if len(self.products) > MAX_PRODUCTS:
            raise HistoryFetchError("history_binance_earn_product_limit", resumable=False)
        self.windows = self.earn._time_windows(self.start, self.end)
        self.binding = hashlib.sha256(canonical_json([
            1, target.source_ref, target.account, target.connection_id,
            options.start.isoformat(), options.end.isoformat(), self.products,
        ]).encode()).hexdigest()
        self.coverage_notes = (
            "Simple Earn wird nur fuer Produktanker aus dem zuletzt gespeicherten Snapshot dieser Verbindung und bereits kontogebundenen Earn-Belegen abgefragt.",
            "Die Anbieter-API weist hier keine vollstaendige Produkt- oder Aufbewahrungsabdeckung nach. Fehlende Anker, Retention-Luecken und CSV-/Earn-Ueberlappungen bleiben pruefpflichtig.",
        )

    @staticmethod
    def _group_products(rows: list[dict[str, str | None]]) -> list[dict[str, object]]:
        grouped: dict[tuple[str, str, str | None], set[str]] = {}
        for row in rows:
            asset = str(row.get("asset") or "").strip().upper()
            account_type = str(row.get("account_type") or "")
            product_id = row.get("product_id") or None
            position_id = str(row.get("position_id") or "").strip()
            if (not re.fullmatch(r"[A-Z0-9]{2,40}", asset)
                    or account_type not in {"simple_earn_flexible", "simple_earn_locked"}
                    or (product_id is not None and len(product_id) > 200)
                    or len(position_id) > 200):
                raise HistoryFetchError("history_binance_earn_product_anchor_invalid", resumable=False)
            grouped.setdefault((asset, account_type, product_id), set())
            if position_id:
                grouped[(asset, account_type, product_id)].add(position_id)
        return [
            {"asset": asset, "account_type": account_type, "product_id": product_id,
             "position_ids": sorted(positions)}
            for (asset, account_type, product_id), positions in sorted(
                grouped.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or ""),
            )
        ]

    def _initial(self) -> dict[str, object]:
        return {
            "v": 1, "binding": self.binding, "products": self.products,
            "product_index": 0, "spec_index": 0, "window_index": 0,
            "page": 1, "discovered_positions": {}, "query_positions": [],
            "positions_for_spec": -1, "position_index": 0,
        }

    def _state(self, cursor: dict[str, object]) -> dict[str, object]:
        if not cursor:
            return self._initial()
        if (not isinstance(cursor, dict) or type(cursor.get("v")) is not int
                or cursor.get("v") != 1 or cursor.get("binding") != self.binding
                or cursor.get("products") != self.products):
            raise HistoryFetchError("history_cursor_binding_mismatch", resumable=False)
        state = deepcopy(cursor)
        indexes = ("product_index", "spec_index", "window_index", "page", "position_index")
        if any(type(state.get(key)) is not int or state[key] < 0 for key in indexes):
            raise HistoryFetchError("history_cursor_invalid", resumable=False)
        if (state["product_index"] > len(self.products) or state["page"] < 1
                or state["page"] > 10000):
            raise HistoryFetchError("history_cursor_invalid", resumable=False)
        if not isinstance(state.get("discovered_positions"), dict):
            raise HistoryFetchError("history_cursor_invalid", resumable=False)
        return state

    def _position_ids(self, state: dict[str, object], spec: dict[str, str], product: dict[str, object]) -> list[str]:
        spec_index = int(state["spec_index"])
        if state.get("positions_for_spec") != spec_index:
            ids = set(str(value) for value in product["position_ids"])
            discovered = state["discovered_positions"].get(str(state["product_index"]), [])
            if not isinstance(discovered, list) or len(discovered) > MAX_POSITION_IDS:
                raise HistoryFetchError("history_cursor_invalid", resumable=False)
            ids.update(str(value) for value in discovered)
            values = sorted(ids) if spec.get("use_position_id") == "true" else [""]
            if spec.get("use_position_id") == "true" and not values:
                values = [""]
            state.update(query_positions=values, positions_for_spec=spec_index, position_index=0)
        values = state.get("query_positions")
        if not isinstance(values, list) or not values or state["position_index"] >= len(values):
            raise HistoryFetchError("history_cursor_invalid", resumable=False)
        return values

    def _advance(self, state: dict[str, object], spec: dict[str, str], positions: list[str]) -> None:
        state["page"] = 1
        if state["window_index"] + 1 < len(self.windows):
            state["window_index"] += 1
            return
        state["window_index"] = 0
        if state["position_index"] + 1 < len(positions):
            state["position_index"] += 1
            return
        state["position_index"] = 0
        state["spec_index"] += 1
        state["positions_for_spec"] = -1
        state["query_positions"] = []
        if state["spec_index"] >= len(self.earn._endpoint_specs(str(self.products[state["product_index"]]["account_type"]))):
            state["product_index"] += 1
            state["spec_index"] = 0

    @staticmethod
    def _identity(record_type: str, payload: dict[str, object]) -> str:
        provider_id = next((str(payload[key]).strip() for key in ("id", "tranId", "purchaseId", "redeemId")
                            if payload.get(key) not in (None, "")), "")
        if provider_id:
            external = f"{record_type}:{provider_id}"
            if len(external) <= 480:
                return "binance-earn:" + external
        digest = hashlib.sha256(canonical_json([record_type, payload]).encode()).hexdigest()
        return "binance-earn-fingerprint:" + digest

    def fetch_page(self, cursor: dict, check) -> HistoryPage:
        state = self._state(cursor)
        if not self.products:
            return HistoryPage([], state, True, (
                *self.coverage_notes,
                "Keine Earn-Produktanker fuer diese Verbindung vorhanden; es wurden keine Earn-Endpunkte abgefragt.",
            ), phase="Earn-Abdeckung ohne Produktanker")
        if state["product_index"] >= len(self.products):
            return HistoryPage([], state, True, self.coverage_notes, phase="Simple-Earn-Anker abgefragt")
        if not self.windows:
            raise HistoryFetchError("history_date_range_invalid", resumable=False)

        product = self.products[state["product_index"]]
        specs = self.earn._endpoint_specs(str(product["account_type"]))
        if state["spec_index"] >= len(specs) or state["window_index"] >= len(self.windows):
            raise HistoryFetchError("history_cursor_invalid", resumable=False)
        spec = specs[state["spec_index"]]
        positions = self._position_ids(state, spec, product)
        position_id = str(positions[state["position_index"]])
        window_start, window_end = self.windows[state["window_index"]]
        page_number = int(state["page"])
        page_size = min(self.earn.SIZE, max(1, self.max_records))
        params: dict[str, object] = {
            "asset": product["asset"],
            "startTime": self.earn._millis(window_start),
            "endTime": self.earn._millis(window_end),
            "size": page_size,
            "current": page_number,
        }
        if spec["scope"] == "flexible" and product["product_id"]:
            params["productId"] = product["product_id"]
        if spec.get("use_position_id") == "true" and position_id:
            params["positionId"] = position_id
        if spec.get("reward_type"):
            params["type"] = spec["reward_type"]

        check()
        api_key, secret_key = self.earn._credentials()
        response = self.earn._signed_get_with_retries(api_key, secret_key, spec["endpoint"], params)
        check()
        rows = response.get("rows") if isinstance(response, dict) else None
        total_raw = response.get("total") if isinstance(response, dict) else None
        if not isinstance(rows, list) or len(rows) > page_size or any(not isinstance(row, dict) for row in rows):
            raise HistoryFetchError("history_binance_earn_response_invalid", resumable=False)
        total = None
        if total_raw is not None:
            try:
                total = int(total_raw)
            except (TypeError, ValueError, OverflowError):
                raise HistoryFetchError("history_binance_earn_total_invalid", resumable=False) from None
            if total < 0:
                raise HistoryFetchError("history_binance_earn_total_invalid", resumable=False)

        records: list[HistoryRecord] = []
        discovered = state["discovered_positions"].setdefault(str(state["product_index"]), [])
        for payload in rows:
            raw_payload = deepcopy(payload)
            discovered_id = str(raw_payload.get("positionId") or "").strip()
            if discovered_id and discovered_id not in discovered:
                if len(discovered) >= MAX_POSITION_IDS:
                    raise HistoryFetchError("history_binance_earn_position_limit", resumable=False)
                discovered.append(discovered_id)
            record_model = {
                "endpoint": spec["endpoint"], "asset": product["asset"],
                "product_id": product["product_id"],
                "position_id": position_id or None,
                "record_type": spec["record_type"], "payload": raw_payload,
            }
            mapped = self.earn._rows_from_earn_record(record_model)
            identity = self._identity(spec["record_type"], raw_payload)
            for row in mapped:
                row["account"] = self.target.account
                row["provider_record_id"] = identity
                row["provider_endpoint"] = spec["endpoint"]
            records.append(HistoryRecord(
                identity=identity,
                source="binance_simple_earn_api",
                rows=mapped,
                raw={
                    "payload": raw_payload,
                    "provider": "binance",
                    "endpoint": spec["endpoint"],
                    "record_type": spec["record_type"],
                    "asset": product["asset"],
                    "product_id": product["product_id"],
                    "position_id": position_id or None,
                    "request": {
                        "window_start": window_start.isoformat(),
                        "window_end": window_end.isoformat(),
                        "current": page_number, "size": page_size,
                    },
                },
            ))

        more = total > page_number * page_size if total is not None else len(rows) == page_size
        notes = list(self.coverage_notes if not cursor else ())
        if more and total is None:
            notes.append("Mindestens eine Earn-Seite war voll, aber Binance lieferte keine Gesamtzahl; die Folgeseite wird angefragt, Vollstaendigkeit bleibt unbewiesen.")
        if total is not None and not rows and total > (page_number - 1) * page_size:
            notes.append("Earn-Antwort ist leer, obwohl die gemeldete Gesamtzahl weitere Records erwarten laesst; Abdeckung bleibt widerspruechlich.")
            more = False
        if more:
            state["page"] = page_number + 1
        else:
            self._advance(state, spec, positions)
        check()
        done = state["product_index"] >= len(self.products)
        return HistoryPage(
            records, state, done, tuple(dict.fromkeys(notes)), requests=1,
            phase=f"Simple Earn: {spec['record_type']} / {product['asset']} / Seite {page_number}",
            complete_history_proven=False,
            extra={"endpoint": spec["endpoint"], "record_type": spec["record_type"],
                   "asset": product["asset"], "page": page_number, "total": total},
        )


class BinanceHistoryCollector:
    """Combines the existing Spot collector and bounded Simple-Earn adapter."""

    def __init__(self, store, target: HistoryTarget, options: HistoryOptions):
        self.spot = CexHistoryCollector(store, target, options)
        self.earn = BinanceEarnHistoryCollector(store, target, options)
        self.binding = hashlib.sha256(canonical_json([
            1, target.source_ref, target.account, target.connection_id,
            options.start.isoformat(), options.end.isoformat(), self.earn.binding,
        ]).encode()).hexdigest()

    def fetch_page(self, cursor: dict, check) -> HistoryPage:
        if not cursor:
            state: dict[str, object] = {
                "v": 1, "binding": self.binding, "stage": "spot", "spot_cursor": {}, "earn_cursor": {},
            }
        elif (not isinstance(cursor, dict) or cursor.get("v") != 1
              or cursor.get("binding") != self.binding or cursor.get("stage") not in {"spot", "earn"}
              or not isinstance(cursor.get("spot_cursor"), dict)
              or not isinstance(cursor.get("earn_cursor"), dict)):
            raise HistoryFetchError("history_cursor_binding_mismatch", resumable=False)
        else:
            state = deepcopy(cursor)
        if state["stage"] == "spot":
            page = self.spot.fetch_page(state["spot_cursor"], check)
            state["spot_cursor"] = page.cursor
            if page.done:
                state["stage"] = "earn"
            return HistoryPage(
                page.records, state, False, page.notes, requests=page.requests,
                phase=page.phase, complete_history_proven=False, extra=page.extra,
            )
        page = self.earn.fetch_page(state["earn_cursor"], check)
        state["earn_cursor"] = page.cursor
        return HistoryPage(
            page.records, state, page.done, page.notes, requests=page.requests,
            phase=page.phase, complete_history_proven=False, extra=page.extra,
        )
