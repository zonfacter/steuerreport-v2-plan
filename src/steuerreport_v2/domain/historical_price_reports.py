"""Reine, lesende Exporte gespeicherter historischer Tagespreisvorschauen.

Der Aufrufer liefert die vollstaendige Vorschau und einen lokalen Belegleser
``evidence_loader(sha256) -> bytes``. Kein Datenbankzugriff, Abruf oder Schreiben.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import html
import io
import json
import re
import zipfile


MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_SHA256 = re.compile(r"[a-fA-F0-9]{64}")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_ROW_FIELDS = (
    "asset", "price_date", "first_event_at", "status", "reason", "price_eur",
    "priced_at", "fx_date", "provider_id", "evidence_sha256", "event_count",
    "event_types", "years", "event_year_counts", "source",
)
_WARNING = "Keine Quellen-, Token-, Review- oder Jahresfreigabe."


class _Budget:
    def __init__(self):
        self.remaining = MAX_UNCOMPRESSED_BYTES

    def check(self, size):
        if size > self.remaining:
            raise ValueError("historical_price_report_too_large")

    def consume(self, size):
        self.check(size)
        self.remaining -= size


class _TextBuffer:
    """Begrenzt auch JSON-, CSV- und Markdown-Aufbau vor dem ZIP-Schreiben."""

    def __init__(self, budget):
        self.budget = budget
        self.buffer = io.BytesIO()

    def write(self, value):
        data = value.encode("utf-8")
        self.budget.consume(len(data))
        self.buffer.write(data)
        return len(value)

    def content(self):
        return self.buffer.getvalue()


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Nicht JSON-faehiger Berichtswert: {type(value).__name__}")


def _json_bytes(value, budget):
    output = _TextBuffer(budget)
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, indent=2,
                               allow_nan=False, default=_json_default)
    for chunk in encoder.iterencode(value):
        output.write(chunk)
    output.write("\n")
    return output.content()


def _database_status(preview):
    if preview.get("applied") is True:
        return "Tatsaechlich angewendet: Preise uebernommen und abgeleitete Finanzdaten neu berechnet."
    return "Nur Vorschau: Finanzdatenbank unveraendert; keine Preise uebernommen."


def report_json(preview: dict) -> dict:
    """Versionierter JSON-Bericht samt Bindungen und vollstaendiger Vorschau.

    Fehlende Werte bleiben null; Decimal-Werte bleiben verlustfreie Strings.
    Das Ergebnis teilt keine veraenderlichen Objekte mit der Eingabe.
    """
    _evidence_ids(preview)
    document = {
        "report_version": 1,
        "report_type": "historical_price_report",
        **{key: preview.get(key) for key in (
            "preview_sha256", "plan_sha256", "created_at", "updated_at",
            "applied_at", "software_version", "methodology",
        )},
        "price_meaning": "EUR-Tagesreferenz, kein Ausfuehrungskurs und keine Einnahmen.",
        "warning": _WARNING,
        "financial_database_status": _database_status(preview),
        "applied": preview.get("applied") is True,
        "preview": preview,
    }
    return json.loads(_json_bytes(document, _Budget()))


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default, allow_nan=False)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _cell(value):
    text = html.escape(_text(value), quote=False).replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _fields(rows, defaults):
    return [*defaults, *sorted({key for row in rows for key in row} - set(defaults))]


def _table(output, rows, fields):
    output.write("| " + " | ".join(_cell(field) for field in fields) + " |\n")
    output.write("| " + " | ".join("---" for _ in fields) + " |\n")
    for row in rows:
        output.write("| " + " | ".join(_cell(row.get(field)) for field in fields) + " |\n")
    output.write("\n")


def _evidence_ids(preview):
    candidates = [item.get("sha256") if isinstance(item, Mapping) else None
                  for item in preview.get("evidence", [])]
    for row in preview.get("rows", []):
        refs = row.get("evidence_sha256")
        if refs is None:
            continue
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, (list, tuple)):
            raise ValueError("historical_price_report_evidence_invalid")
        candidates.extend(refs)
    result = set()
    for sha in candidates:
        if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
            raise ValueError("historical_price_report_evidence_invalid")
        result.add(sha.lower())
    return sorted(result)


def _markdown_bytes(preview, budget):
    output = _TextBuffer(budget)
    output.write("# Historische EUR-Tagesreferenzen\n\n")
    output.write("Preise sind Tagesreferenzen, keine Einnahmen und keine Ausfuehrungskurse.\n\n")
    output.write(_WARNING + "\n\n" + _database_status(preview) + "\n\n")
    output.write("## Bindungen und Abfrage\n\n")
    metadata = {key: preview.get(key) for key in (
        "id", "preview_sha256", "plan_sha256", "created_at", "updated_at", "applied_at",
        "software_version", "methodology", "time_basis", "query", "source_event_types",
        "canonical_events_unchanged",
    )}
    _table(output, ({"Feld": key, "Wert": value} for key, value in metadata.items()), ("Feld", "Wert"))
    output.write("## Jahresuebersicht\n\n")
    years = preview.get("year_summary", [])
    _table(output, years, _fields(years, ("year", "events_count", "tokens_count", "inventory_count",
                                        "requirements_count", "covered_count", "fetchable_count",
                                        "blocked_count", "open_count")))
    output.write("## Vollstaendige Tagesreferenztabelle\n\n")
    rows = preview.get("rows", [])
    _table(output, rows, _fields(rows, _ROW_FIELDS))
    output.write("## Offene Gruende\n\n")
    reasons = Counter((row.get("status") or "unbekannt", row.get("reason") or "Grund nicht angegeben")
                      for row in rows if row.get("status") not in {"fetched", "covered"})
    _table(output, ({"Status": status, "Grund": reason, "Tagesreferenzen": count}
                    for (status, reason), count in sorted(reasons.items())),
           ("Status", "Grund", "Tagesreferenzen"))
    output.write("## Vorher und Nachher\n\n")
    _table(output, ({"Feld": key, "Wert": preview.get(key)} for key in (
        "before_summary", "after_summary", "before_valuation_summary", "after_valuation_summary",
    )), ("Feld", "Wert"))
    output.write("## Steuerzeilendifferenzen\n\n")
    deltas = preview.get("tax_line_deltas") or []
    _table(output, deltas, _fields(deltas, ("key", "before", "after")))
    manual = preview.get("manual_submission")
    if isinstance(manual, Mapping):
        output.write("## Manuelle Preis- und FX-Belege\n\n")
        observations = []
        price = manual.get("price")
        if isinstance(price, Mapping):
            observations.append({"Art": "Tokenpreis", **price})
        fx = manual.get("fx")
        if isinstance(fx, Mapping):
            observations.append({"Art": "FX", **fx})
        _table(output, observations, _fields(observations, ("Art", "raw_value", "raw_currency", "unit", "priced_at_original", "priced_at_utc", "source_name", "source_reference", "source_observed_at", "date", "base", "quote", "raw_rate", "rate_eur_per_usd", "policy_id", "evidence_filename", "evidence_sha256")))
        if manual.get("fx_block_reason"):
            output.write(f"FX-Status: {_cell(manual['fx_block_reason'])}; die Vorschau bleibt blockiert.\n\n")
    output.write("## Quellenhashes (SHA-256)\n\n")
    _table(output, ({"SHA-256": sha} for sha in _evidence_ids(preview)), ("SHA-256",))
    return output.content()


def report_markdown(preview: dict) -> str:
    """Vollstaendige, tabellarische Vorschau ohne Anzeige-/Seitenlimit."""
    return _markdown_bytes(preview, _Budget()).decode("utf-8")


def _valid_year(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) or (isinstance(value, str) and re.fullmatch(r"[0-9]{4}", value)):
        year = int(value)
        if 2009 <= year <= 2100:
            return year
    return None


def _row_years(row):
    # Explizite Berichtsjahre koennen vom UTC-Preisdatum abweichen.
    if "years" in row:
        values = row["years"] if isinstance(row["years"], (list, tuple)) else []
        return {year for value in values if (year := _valid_year(value)) is not None} or {None}
    for field in ("first_event_at", "price_date"):
        try:
            instant = datetime.fromisoformat(_text(row.get(field)))
            instant = instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant.astimezone(timezone.utc)
            return {_valid_year(instant.year)}
        except (ValueError, OverflowError):
            continue
    return {None}


def _csv_cell(field, value):
    text = _text(value)
    # Nur numerische Preise sind von der String-Formelsperre ausgenommen.
    numeric_price = field == "price_eur" and _NUMBER.fullmatch(text) is not None
    numeric_value = isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if not numeric_price and not numeric_value and text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _csv_bytes(rows, fields, budget):
    output = _TextBuffer(budget)
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writerow({field: _csv_cell(field, field) for field in fields})
    for row in rows:
        writer.writerow({field: _csv_cell(field, row.get(field)) for field in fields})
    return output.content()


def report_zip(preview: dict, evidence_loader: Callable[[str], bytes]) -> bytes:
    """Deterministisches ZIP; Originalbelege ausschliesslich nach SHA-Pruefung.

    Die 64-MiB-Grenze gilt fuer alle unkomprimierten Dateien samt Manifest.
    Erst nach vollstaendiger Pruefung wird das ZIP im Speicher aufgebaut.
    """
    evidence_ids = _evidence_ids(preview)
    budget = _Budget()
    files = {"report.json": _json_bytes(report_json(preview), budget),
             "report.md": _markdown_bytes(preview, budget)}
    rows = preview.get("rows", [])
    fields = _fields(rows, _ROW_FIELDS)
    groups = {}
    for summary in preview.get("year_summary", []):
        if (year := _valid_year(summary.get("year"))) is not None:
            groups.setdefault(year, [])
    query_year = _valid_year(preview.get("query", {}).get("year"))
    if query_year is not None:
        groups.setdefault(query_year, [])
    for row in rows:
        for year in _row_years(row):
            groups.setdefault(year, []).append(row)
    if not groups:
        groups[None] = []
    for year, items in groups.items():
        directory = str(year) if year is not None else "nichtzugeordnet"
        files[directory + "/preise.csv"] = _csv_bytes(items, fields, budget)
    if "tax_line_deltas" in preview:
        files["tax_line_deltas.json"] = _json_bytes(preview["tax_line_deltas"], budget)
    evidence_metadata = {
        item["sha256"]: item
        for item in preview.get("evidence", [])
        if isinstance(item, Mapping) and isinstance(item.get("sha256"), str)
    }
    for sha in evidence_ids:
        body = evidence_loader(sha)
        if not isinstance(body, bytes):
            raise ValueError("historical_price_report_evidence_body_invalid")
        budget.check(len(body))
        if hashlib.sha256(body).hexdigest() != sha:
            raise ValueError("historical_price_report_evidence_mismatch")
        budget.consume(len(body))
        item = evidence_metadata.get(sha, {})
        suffix = ".original" if str(item.get("kind", "")).startswith("manual_") else ".json"
        files[f"evidence/{sha}{suffix}"] = body
    files["manifest.json"] = _json_bytes({"report_version": 1, "files": [
        {"filename": name, "sha256": hashlib.sha256(body).hexdigest()}
        for name, body in sorted(files.items())
    ]}, budget)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, body in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()
