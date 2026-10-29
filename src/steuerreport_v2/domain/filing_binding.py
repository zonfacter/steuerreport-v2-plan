"""Konfliktbindung vorhandener Auswertungen; keine Methoden- oder Jahresfreigabe."""
from __future__ import annotations

from steuerreport_v2.db.duckdb_store import DuckDbStore


BINDING_VERSION = "filing_state_binding_v1"
EXPORT_BINDING_PREFIX = "export.package.binding."
ARCHIVE_TABLES = (
    "export_packages", "tax_filing_snapshots", "tax_filing_snapshot_files",
    "tax_filing_snapshot_events", "tax_year_report_pdf_artifacts",
)


def current_filing_binding(store: DuckDbStore) -> tuple[str, str | None]:
    # Archiv-/Downloadmetadaten aendern keine Berechnung. Fachliche Inputs,
    # Entscheidungen, Ergebnisse und Software-/Konfigurationsdateien bleiben gebunden.
    from steuerreport_v2.domain.ai_changes import _fingerprint

    with store.connect() as con:
        digest = _fingerprint(con, excluded_tables=ARCHIVE_TABLES,
                              excluded_admin_prefixes=(EXPORT_BINDING_PREFIX, "history.job."))
        row = con.execute("select run_id from tax_run_summaries order by created_at desc limit 1").fetchone()
    return digest, str(row[0]) if row else None


def snapshot_binding_status(store: DuckDbStore, report: object | None) -> str:
    if report is None:
        return "missing"
    digest = getattr(report, "input_binding_sha256", None)
    if not digest or getattr(report, "binding_version", None) != BINDING_VERSION:
        return "unbound"
    current, run_id = current_filing_binding(store)
    if current != digest or run_id != getattr(report, "latest_tax_run_id", None):
        return "stale"
    return "current"
