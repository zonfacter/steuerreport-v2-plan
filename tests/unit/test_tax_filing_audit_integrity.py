from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditError, TaxFilingAuditService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


TIME = datetime(2026, 11, 15, tzinfo=timezone.utc)
FIELDS = (
    "taxable_private_disposals_eur", "tax_free_private_disposals_eur",
    "rewards_mining_staking_income_eur", "derivative_pnl_eur",
    "taxable_disposal_proceeds_eur", "acquisition_cost_eur",
)


def test_cold_audit_does_not_create_a_database_or_archive(tmp_path):
    path = tmp_path / "synthetic.duckdb"
    service = TaxFilingAuditService(DuckDbStore(path))
    with pytest.raises(TaxFilingAuditError, match="nicht initialisiert"):
        service.build(2025)
    assert not path.exists()
    assert not service.archive_root.exists()


def test_current_reads_do_not_reopen_a_writable_store(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    before = store.path.read_bytes()

    def forbidden_connect():
        raise AssertionError("Audit reopened its original writable store")

    monkeypatch.setattr(store, "connect", forbidden_connect)
    report = TaxFilingAuditService(store).build(2025, query_time=TIME, materialize=False)
    assert report.current_read_binding == "initialized_read_only_transaction"
    assert report.detail_comparison_status == "not_available"
    assert report.reproducibility.status == "not_verifiable"
    assert report.reproducibility.sums_identical is False
    assert all(row.status == "not_available" for row in report.reconciliation)
    assert all(row.reference_value_eur is None for row in report.reconciliation)
    assert all(row.aggregate_delta_eur is None and row.residual_eur is None for row in report.reconciliation)
    assert store.path.read_bytes() == before


def test_equal_table_counts_do_not_hide_changed_runtime_inputs(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.upsert_admin_setting(AdminSettingWrite(key="synthetic.audit.input", value_json="1"))
    service = TaxFilingAuditService(store)
    first = service.build(2025, query_time=TIME, materialize=False)
    store.upsert_admin_setting(AdminSettingWrite(key="synthetic.audit.input", value_json="2"))
    second = service.build(2025, query_time=TIME, materialize=False)
    assert first.report_id != second.report_id
    assert first.current.runtime_fingerprint_sha256 != second.current.runtime_fingerprint_sha256
    assert first.reproducibility.current_input_fingerprint != second.reproducibility.current_input_fingerprint


def test_exact_reconciliation_preserves_decimal_38_18_difference(tmp_path):
    service = TaxFilingAuditService(DuckDbStore(tmp_path / "unused.duckdb"))
    old_value = Decimal("99999999999999999999.123456789012345678")
    new_value = Decimal("99999999999999999999.123456789012345679")
    old = {"asset": "SYNTH", "quantity": Decimal("1"), "gain": old_value, "taxable": True}
    new = {**old, "gain": new_value}
    delta = service._delta_from_position(old, new, "changed", "tax_line")
    assert delta.value_delta_eur == Decimal("0.000000000000000001")
    baseline = SimpleNamespace(**dict.fromkeys(FIELDS, Decimal("0")))
    current = SimpleNamespace(**dict.fromkeys(FIELDS, Decimal("0")))
    baseline.taxable_private_disposals_eur = old_value
    current.taxable_private_disposals_eur = new_value
    rows = service._reconciliation(baseline_values=baseline, current_values=current, deltas=[delta])
    assert all(row.status == "reconciled" and row.residual_eur == 0 for row in rows)
    assert rows[0].aggregate_delta_eur == Decimal("0.000000000000000001")


@pytest.mark.parametrize("change", ["added", "changed"])
def test_missing_provenance_does_not_invent_a_change_cause(tmp_path, change):
    service = TaxFilingAuditService(DuckDbStore(tmp_path / "unused.duckdb"))
    old = {"gain": Decimal("1"), "lot_id": None}
    new = {"gain": Decimal("2"), "lot_id": "current-lot", "filename": "synthetic.csv", "file_hash": "a" * 64}
    cause, explanation = service._classify_cause(old if change == "changed" else None, new, change, "tax_line")
    assert cause == "unknown"
    assert explanation


def test_ambiguous_repeated_event_is_not_paired_by_occurrence(tmp_path):
    service = TaxFilingAuditService(DuckDbStore(tmp_path / "unused.duckdb"))
    row = {"event_id": "synthetic-event", "asset": "SYNTH", "quantity": Decimal("1")}
    pairs, removed, added = service._pair_positions(service._add_occurrences([row, row]), service._add_occurrences([row, row]))
    assert pairs == []
    assert len(removed) == len(added) == 2


def test_ambiguous_reference_export_is_rejected():
    with pytest.raises(ValueError, match="Mehrdeutiger Referenzexport"):
        TaxFilingAuditService._member({"one/tax-lines.csv": b"", "two/tax-lines.csv": b""}, "tax-lines.csv")


def test_audit_does_not_read_or_write_shared_wallet_preview_cache(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()

    def forbidden(*args, **kwargs):
        raise AssertionError("Audit accessed a shared wallet preview cache")

    monkeypatch.setattr(WalletFifoPreviewService, "_read_preview_disk_cache", forbidden)
    monkeypatch.setattr(WalletFifoPreviewService, "_write_preview_disk_cache", forbidden)
    monkeypatch.setattr(WalletFifoPreviewService, "_preview_cache_key", forbidden)
    first = TaxFilingAuditService(store).build(2025, query_time=TIME, materialize=False)
    second = TaxFilingAuditService(store).build(2025, query_time=TIME, materialize=False)
    assert first.report_id == second.report_id
    assert not (tmp_path / ".steuerreport_v2_cache/wallet_fifo_preview").exists()


def test_read_bound_preview_uses_its_own_provenance_and_origin_caches(tmp_path, monkeypatch):
    class PoisonedCache(dict):
        def get(self, *args, **kwargs):
            raise AssertionError("Read-bound service consulted a shared cache")

        def __setitem__(self, *args, **kwargs):
            raise AssertionError("Read-bound service modified a shared cache")

    names = ("_PREVIEW_CACHE", "_PROVENANCE_CLOSURE_CACHE", "_SOLANA_ORIGIN_TRACE_CACHE")
    caches = {name: PoisonedCache({"sentinel": object()}) for name in names}
    for name, cache in caches.items():
        monkeypatch.setattr(WalletFifoPreviewService, name, cache)
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    with store.read_initialized_snapshot() as snapshot:
        service = WalletFifoPreviewService(snapshot, shared_preview_cache=False)
        for name in names:
            assert getattr(service, name) is not caches[name]
            assert getattr(service, name) == {}
        closure = service.provenance_closure_report(2025)
        assert closure.year == 2025
        assert service._PROVENANCE_CLOSURE_CACHE
    assert all(list(cache) == ["sentinel"] for cache in caches.values())


def test_oversized_new_report_is_not_partially_published(tmp_path, monkeypatch):
    from steuerreport_v2.domain import tax_filing_audit

    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    service = TaxFilingAuditService(store)
    report = service.build(2025, query_time=TIME, materialize=False)
    monkeypatch.setattr(tax_filing_audit, "MAX_AUDIT_ARTIFACT_BYTES", 1)
    with pytest.raises(TaxFilingAuditError, match="maximale Groesse"):
        service._materialize(report)
    assert not list(service.archive_root.rglob("*.json"))
    assert not list(service.archive_root.rglob("*.md"))
