from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
import os

import pytest
from steuerreport_v2.contracts.connections import ConnectionCreate
from steuerreport_v2.contracts.imports import ImportAssistantRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.import_assistant import ImportAssistantService
from steuerreport_v2.domain.import_context import bitget_import_context, timezone_from_name
from steuerreport_v2.domain.workspace import WorkspaceService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


def _bitget_connection(store: DuckDbStore, tmp_path, monkeypatch) -> str:
    key = tmp_path / "vault.key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(key))
    return str(ConnectionService(store).create(ConnectionCreate(
        provider="bitget", label="Synthetic Bitget", account="fixture",
    )).id)


def test_export_timezone_supports_utc_fixed_offsets_and_iana_dst(tmp_path):
    parser = RawNormalizer(DuckDbStore(tmp_path / "timezone-parser.duckdb"))

    assert parser._parse_datetime("2025-01-02 12:00:00", timezone_from_name("UTC+01:00")) == datetime(2025, 1, 2, 11, tzinfo=timezone.utc)
    assert parser._parse_datetime("2025-01-02 12:00:00", timezone_from_name("Europe/Berlin")) == datetime(2025, 1, 2, 11, tzinfo=timezone.utc)
    assert parser._parse_datetime("2025-07-02 12:00:00", timezone_from_name("Europe/Berlin")) == datetime(2025, 7, 2, 10, tzinfo=timezone.utc)
    assert parser._parse_datetime("2025-07-02T12:00:00+05:30", timezone_from_name("UTC")) == datetime(2025, 7, 2, 6, 30, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="ambiguous"):
        parser._parse_datetime("2025-10-26 02:30:00", timezone_from_name("Europe/Berlin"))
    with pytest.raises(ValueError, match="does_not_exist"):
        parser._parse_datetime("2025-03-30 02:30:00", timezone_from_name("Europe/Berlin"))


@pytest.mark.parametrize("value", ["", "UTC+15:00", "UTC+01:75", "Not/A_Zone"])
def test_invalid_export_timezone_is_rejected(value):
    with pytest.raises(ValueError, match="import_timezone_invalid"):
        timezone_from_name(value)


def test_bitget_context_requires_pair_only_for_isolated_margin():
    context = bitget_import_context(
        export_timezone="Europe/Berlin", product_scope="isolated_margin",
        margin_pair="btc/usdt",
    )
    assert context["export_timezone"] == "Europe/Berlin"
    assert context["timezone_basis"] == "operator_selected"
    assert context["product_scope"] == "isolated_margin"
    assert context["margin_pair"] == "BTC_USDT"
    with pytest.raises(ValueError, match="bitget_margin_pair_required"):
        bitget_import_context(
            export_timezone="UTC", product_scope="isolated_margin", margin_pair=None,
        )


def test_bitget_assistant_persists_context_and_scopes_normalized_event(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "bitget-context.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    content = "Date,Coin,Type,Amount\n2025-01-02 12:00:00,DEMOCOIN,deposit,4\n"
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv",
        content=content,
        connection_id=connection_id, export_timezone="Europe/Berlin",
        bitget_product_scope="spot",
    )

    preview = ImportAssistantService(store).preview(request)
    assert preview.can_execute is True
    assert preview.preview is not None
    assert preview.preview.file_sha256 == "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    result = ImportAssistantService(store).execute(request)

    assert str(result.batch.connection_id) == connection_id
    assert result.batch.import_context == {
        "context_version": "1",
        "export_timezone": "Europe/Berlin",
        "product_scope": "spot",
        "timezone_basis": "operator_selected",
    }
    event = store.list_canonical_events()[0]
    assert event.account == f"connection:{connection_id}"
    assert event.event_time == datetime(2025, 1, 2, 11)
    source = next(row for row in WorkspaceService(store).sources().sources if row.connection_id == connection_id)
    assert source.events_count == 1
    reopened = DuckDbStore(store.path).get_import_batch(result.batch.batch_id)
    assert reopened is not None
    assert reopened.import_context == result.batch.import_context


def test_bitget_whitespace_timezone_is_missing_not_legacy_fallback(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "whitespace-timezone.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv",
        content="Date,Coin,Type,Amount\n2025-01-02 12:00:00,DEMOCOIN,deposit,4\n",
        connection_id=connection_id, export_timezone="   ", bitget_product_scope="spot",
    )

    preview = ImportAssistantService(store).preview(request)

    assert preview.can_execute is False
    assert preview.import_context == {}
    assert any("Exportzeitzone" in warning for warning in preview.warnings)
    assert store.list_import_batches() == []


def test_bitget_invalid_timezone_preview_does_not_claim_legacy_or_selected_timezone(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "invalid-timezone-preview.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv",
        content="Date,Coin,Type,Amount\n2025-01-02 12:00:00,DEMOCOIN,deposit,4\n",
        connection_id=connection_id, export_timezone="Not/A_Zone", bitget_product_scope="spot",
    )

    preview = ImportAssistantService(store).preview(request)

    assert preview.can_execute is False
    assert preview.import_context == {}
    assert preview.preview is not None
    assert preview.preview.import_context == {}
    assert preview.tax_impact.estimated_normalizable_rows is None
    assert "UTC+08:00" not in str(preview.preview.import_context)
    assert not any("ausgewaehlte Exportzeitzone gilt" in warning for warning in preview.warnings)
    assert any("Lokale Zeitwerte werden in dieser Vorschau nicht interpretiert" in warning for warning in preview.warnings)
    assert store.list_import_batches() == []


def test_bitget_source_is_canonicalized_before_context_and_normalization(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "canonical-source.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    request = ImportAssistantRequest(
        source=" BITGET ", filename="synthetic.csv",
        content="Date,Coin,Type,Amount\n2025-01-02 12:00:00,DEMOCOIN,deposit,4\n",
        connection_id=connection_id, export_timezone="UTC+01:00", bitget_product_scope="spot",
    )

    assert request.source == "bitget"
    result = ImportAssistantService(store).execute(request)

    assert result.batch.source == "bitget"
    assert store.list_canonical_events()[0].account == f"connection:{connection_id}"
    assert store.list_canonical_events()[0].event_time == datetime(2025, 1, 2, 11)


def test_bitget_same_provider_connections_remain_separate(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "separate-connections.duckdb")
    first_connection = _bitget_connection(store, tmp_path, monkeypatch)
    second_connection = _bitget_connection(store, tmp_path, monkeypatch)
    content = "Date,Coin,Type,Amount\n2025-01-02 12:00:00,DEMOCOIN,deposit,4\n"
    service = ImportAssistantService(store)

    first = service.execute(ImportAssistantRequest(
        source="bitget", filename="same-export.csv", content=content,
        connection_id=first_connection, export_timezone="UTC+01:00",
        bitget_product_scope="spot",
    ))
    second = service.execute(ImportAssistantRequest(
        source="bitget", filename="same-export.csv", content=content,
        connection_id=second_connection, export_timezone="UTC+01:00",
        bitget_product_scope="spot",
    ))

    assert first.batch.batch_id != second.batch.batch_id
    accounts = {event.account for event in store.list_canonical_events()}
    assert accounts == {
        f"connection:{first_connection}",
        f"connection:{second_connection}",
    }


def test_bitget_assistant_blocks_missing_scope_timezone_or_connection(tmp_path):
    store = DuckDbStore(tmp_path / "blocked-context.duckdb")
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv",
        content="Date,Coin,Type,Amount\n2025-01-02 12:00:00,DEMOCOIN,deposit,4\n",
    )

    preview = ImportAssistantService(store).preview(request)

    assert preview.can_execute is False
    assert preview.blocked_reason == "Bitget-Import benoetigt eine bestehende Verbindung, Exportzeitzone und Produktscope."
    assert any("Exportzeitzone" in warning for warning in preview.warnings)
    assert store.list_import_batches() == []


def test_bitget_preview_blocks_ambiguous_dst_time_before_any_batch_is_created(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "dst-preview.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv",
        content="Date,Coin,Type,Amount\n2025-10-26 02:30:00,DEMOCOIN,deposit,4\n",
        connection_id=connection_id, export_timezone="Europe/Berlin",
        bitget_product_scope="spot",
    )

    preview = ImportAssistantService(store).preview(request)

    assert preview.can_execute is False
    assert preview.preview is not None
    assert preview.preview.blocking_reasons == [
        "Zeile 1: lokale Uhrzeit ist in der ausgewaehlten Zeitzone mehrdeutig; Export mit Offset waehlen."
    ]
    assert store.list_import_batches() == []


@pytest.mark.parametrize(("timestamp", "header_offset", "selected_zone", "expected", "reason"), [
    ("2025-01-02 12:00:00", "+8", "Asia/Shanghai", True, None),
    ("2025-07-02 12:00:00", "+8", "Europe/Berlin", False, "ausgewaehlten Exportzeitzone"),
    ("2025-07-02 12:00:00", "+8", "UTC+08:00", True, None),
    ("2025-01-02 12:00:00", "+8", "UTC+01:00", False, "ausgewaehlten Exportzeitzone"),
    ("2025-01-02T12:00:00+01:00", "+8", "UTC+01:00", False, "Zeitwert widerspricht"),
    ("2025-01-02T12:00:00+08:00", "+8", "UTC+01:00", True, None),
])
def test_bitget_timezone_conflicts_are_explicit_in_preview(
    tmp_path, monkeypatch, timestamp, header_offset, selected_zone, expected, reason,
):
    store = DuckDbStore(tmp_path / "timezone-conflict.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv",
        content=f"Timestamp UTC{header_offset} (Completion),Coin,Type,Amount\n{timestamp},DEMOCOIN,deposit,4\n",
        connection_id=connection_id, export_timezone=selected_zone, bitget_product_scope="spot",
    )

    preview = ImportAssistantService(store).preview(request)

    assert preview.can_execute is expected
    if reason:
        assert preview.preview is not None
        assert any(reason in message for message in preview.preview.blocking_reasons)
        with pytest.raises(ValueError):
            ImportAssistantService(store).execute(request)
    assert store.list_import_batches() == []


@pytest.mark.parametrize("encoded", [False, True])
@pytest.mark.parametrize(("fee", "fee_asset", "allowed"), [
    ("-0.25", "", False), ("invalid", "", False),
    ("0", "", True), ("-0.25", "BGB", True),
])
def test_guided_bitget_margin_fee_requires_evidenced_currency(
    tmp_path, monkeypatch, encoded, fee, fee_asset, allowed,
):
    store = DuckDbStore(tmp_path / "margin-fee.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    content = ("Time,Pair,Coin,Type,Amount,fee,fee_asset,Balance\n"
               f"2025-01-02 12:00:00,DEMOCOINUSDT,DEMOCOIN,buy,5,{fee},{fee_asset},25\n")
    source = {"content_base64": base64.b64encode(content.encode()).decode()} if encoded else {"content": content}
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv", connection_id=connection_id,
        export_timezone="UTC", bitget_product_scope="isolated_margin", bitget_margin_pair="DEMOCOIN_USDT",
        **source,
    )

    preview = ImportAssistantService(store).preview(request)

    assert preview.can_execute is allowed
    assert any("falsche Auswahl" in warning for warning in preview.warnings)
    if not allowed:
        assert preview.preview is not None
        assert any("Margin-Gebuehr" in message for message in preview.preview.blocking_reasons)
        with pytest.raises(ValueError):
            ImportAssistantService(store).execute(request)
    assert store.list_import_batches() == []


@pytest.mark.parametrize("timestamp", ["not-a-date", ""])
def test_bitget_preview_blocks_invalid_or_missing_row_timestamp_before_batch(tmp_path, monkeypatch, timestamp):
    store = DuckDbStore(tmp_path / f"invalid-time-{hashlib.sha256(timestamp.encode()).hexdigest()[:8]}.duckdb")
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv",
        content=f"Date,Coin,Type,Amount\n{timestamp},DEMOCOIN,deposit,4\n",
        connection_id=connection_id, export_timezone="Europe/Berlin", bitget_product_scope="spot",
    )

    preview = ImportAssistantService(store).preview(request)

    assert preview.can_execute is False
    assert preview.preview is not None
    assert preview.preview.blocking_reasons
    assert "Zeile 1" in preview.preview.blocking_reasons[0]
    with pytest.raises(ValueError):
        ImportAssistantService(store).execute(request)
    assert store.list_import_batches() == []


def test_bitget_same_bytes_with_different_context_are_not_reused(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "context-dedupe.duckdb")
    importer = ImportAssistantService(store)
    connection_id = _bitget_connection(store, tmp_path, monkeypatch)
    content = "Date,Coin,Type,Amount\n2025-01-02 12:00:00,DEMOCOIN,deposit,4\n"
    request = ImportAssistantRequest(
        source="bitget", filename="synthetic.csv", content=content,
        connection_id=connection_id, export_timezone="UTC+01:00",
        bitget_product_scope="spot",
    )
    first = importer.execute(request)
    changed = ImportAssistantRequest(
        **{**request.model_dump(), "export_timezone": "Europe/Berlin"},
    )

    preview = importer.preview(changed)
    assert preview.can_execute is False
    assert preview.preview is not None
    assert preview.preview.duplicate_batch_id == first.batch.batch_id
    assert preview.preview.duplicate_batch_import_context == first.batch.import_context
    assert any("anderem oder unbekanntem Importkontext" in warning for warning in preview.warnings)
    with pytest.raises(ValueError):
        importer.execute(changed)
    with pytest.raises(ValueError, match="duplicate_import_scope_mismatch"):
        CsvRawImporter(store).import_text(
            "bitget", "synthetic.csv", content, connection_id=connection_id,
            import_context={
                "context_version": "1", "export_timezone": "Europe/Berlin",
                "timezone_basis": "operator_selected", "product_scope": "spot",
            },
        )
    assert len(store.list_import_batches()) == 1
