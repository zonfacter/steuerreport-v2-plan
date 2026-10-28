"""Unabhaengige, rein synthetische XLSX-Abnahme fuer GitHub Issue #4.

Sollwerte sind vor Backend-Implementierung festgelegt. Kein Skip/Xfail fuer
fehlende MEXC-Unterstuetzung; keine privaten Exporte, Preise oder Konten.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import socket
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import duckdb
from openpyxl import Workbook
from pydantic import ValidationError
import pytest

from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


D = Decimal
REPO = Path(__file__).resolve().parents[2]
UID = "SYNTHETIC-ACCOUNT"
ACCOUNT = "synthetic-spot"
LEDGER_ACCOUNT = "mexc:" + UID + ":" + ACCOUNT
WHEN = datetime(2031, 7, 9, 11, tzinfo=timezone.utc)
REASON = "Synthetische Originalbelege einzeln geprueft."
SPOT_HEADERS = (
    "UID", "Creation Time(UTC+01:00)", "Crypto", "Transaction Type",
    "Direction", "Quantity",
)
HEADERS = {
    "spot_statement": SPOT_HEADERS,
    "funding_other": ("UID", "Time", "Crypto", "Type", "Quantity", "Status", "Remark"),
    "asset_snapshot": ("UID", "Date(UTC+8)", "Account", "Crypto", "Total", "USDT Valuation"),
    "futures_capital_flow": (
        "UID", "Time(UTC+01:00)", "Futures Trading Pair", "Crypto", "Fund Type",
        "Fund Flow Type", "Amount",
    ),
    **{kind: SPOT_HEADERS for kind in (
        "futures_statement", "earn_fixed", "earn_flexible", "send_history",
    )},
}


@pytest.fixture
def case(tmp_path, monkeypatch):
    assert not tmp_path.resolve().is_relative_to(REPO)
    profile = tmp_path / "profile.json"
    profile.write_text("{}\n", encoding="ascii")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(tmp_path / "synthetic.duckdb"))
    original_init = DuckDbStore.__init__
    original_connect = duckdb.connect
    original_socket_connect = socket.socket.connect
    original_socket_connect_ex = socket.socket.connect_ex

    def check_path(path):
        assert Path(path).resolve().is_relative_to(tmp_path.resolve()), "Fremde DB gesperrt"

    def guarded_init(self, path=None):
        if path is not None:
            check_path(path)
        original_init(self, path)
        check_path(self.path)

    def guarded_connect(database=":memory:", *args, **kwargs):
        if str(database) != ":memory:":
            check_path(database)
        return original_connect(database, *args, **kwargs)

    def blocked(*args, **kwargs):
        raise OSError("MEXC-Referenz: kein Netzwerk/DNS")

    def connect(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            return blocked()
        return original_socket_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            return blocked()
        return original_socket_connect_ex(sock, address)

    monkeypatch.setattr(DuckDbStore, "__init__", guarded_init)
    monkeypatch.setattr(duckdb, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    return store, FileRawImporter(CsvRawImporter(store))


def _options(kind="spot_statement", **changes):
    result = {"export_kind": kind, "account": ACCOUNT}
    if kind == "funding_other":
        result["timezone"] = "UTC+01:00"
    result.update(changes)
    return result


def _spot(**changes):
    result = dict(zip(SPOT_HEADERS, (
        UID, "2031-07-09 12:00:00", "DEMOCOIN", "Airdrop", "Inflow", "2.5",
    )))
    result.update(changes)
    return result


def _funding(**changes):
    result = dict(zip(HEADERS["funding_other"], (
        UID, "2031-07-09 12:00:00", "DEMOCOIN", "Airdrop", "2.5", None, None,
    )))
    result.update(changes)
    return result


def _snapshot_row():
    return dict(zip(HEADERS["asset_snapshot"], (UID, "20310709", "Spot", "DEMOCOIN", "2.5", "123")))


def _bonus_rows():
    return [dict(zip(HEADERS["futures_capital_flow"], values)) for values in (
        (UID, "2031-07-09 12:00:00", None, "USDT", "BONUS", "Inflow", "7"),
        (UID, "2031-07-10 12:00:00", None, "USDT", "BONUS", "Outflow", "-7"),
    )]


def _xlsx(rows, kind="spot_statement", *, sheets=("Sheet1",), revision="original", extra_headers=()):
    book = Workbook()
    book.properties.creator = "SYNTHETIC TEST ONLY"
    book.properties.title = revision
    book.properties.created = datetime(2031, 7, 9)
    book.properties.modified = datetime(2031, 7, 9)
    for index, name in enumerate(sheets):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = name
        headers = HEADERS[kind] + tuple(extra_headers)
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(header) for header in headers])
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def _numeric_xlsx(uid, quantity):
    source = _xlsx([_spot()])
    output = BytesIO()
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with ZipFile(BytesIO(source)) as original, ZipFile(output, "w") as changed:
        for member in original.infolist():
            content = original.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(content)
                for coordinate, literal in (("A2", uid), ("F2", quantity)):
                    cell = root.find(f".//{{{namespace}}}c[@r='{coordinate}']")
                    assert cell is not None
                    cell.clear()
                    cell.attrib.update(r=coordinate, t="n")
                    ET.SubElement(cell, "{" + namespace + "}v").text = literal
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            changed.writestr(member, content)
    return output.getvalue()


def _csv(rows, kind="funding_other"):
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=HEADERS[kind], lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _request(content, options, *, filename="synthetic.xlsx", sheet="Sheet1"):
    return {
        "source": "mexc", "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "sheet_name": sheet, "mexc": options,
    }


def _preview(case, content, options, **kwargs):
    return case[1].preview_base64(**_request(content, options, **kwargs))


def _native(preview):
    native = preview.model_dump(mode="json")["mexc"]
    assert isinstance(native, dict)
    assert {"raw_rows", "bookable_rows", "linked_rows", "review_rows", "snapshot_rows", "bonus_rows", "rows"} <= native.keys()
    return native


def _counts(native, **expected):
    for name, value in expected.items():
        assert native[name] == value, (name, native)


def _import(case, content, options, **kwargs):
    store, importer = case
    batch = importer.import_base64(**_request(content, options, **kwargs))
    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    return batch, events


def _raw(case, batch):
    return case[0].list_raw_objects(batch.batch_id, limit=None)


def _metadata(raw):
    payload = json.loads(raw.payload_json)
    assert isinstance(payload["_mexc"], str), "_mexc muss serialisiertes JSON sein"
    metadata = json.loads(payload["_mexc"])
    assert metadata["version"] == 1
    assert metadata["row_number"] == raw.row_number
    return payload, metadata


def _positions(case):
    return {(p.account, p.asset): p.quantity for p in BalanceLedgerBuilder(case[0]).positions()}


def _state(case):
    with case[0].connect() as con:
        return {table: con.execute(f"select * from {table} order by all").fetchall() for table in (
            "raw_import_batches", "raw_objects", "canonical_events", "balance_ledger",
            "review_decisions", "tax_lots", "tax_lines", "derivative_lines",
        )}


def _reject_before_batch(case, monkeypatch, content, options, **kwargs):
    before = _state(case)

    def forbidden(*args, **kwargs):
        pytest.fail("Ungueltiger Import darf nicht einmal einen Batch anlegen")

    with monkeypatch.context() as patch:
        patch.setattr(case[0], "create_import_batch", forbidden)
        with pytest.raises(ValueError):
            case[1].import_base64(**_request(content, options, **kwargs))
    assert _state(case) == before


def _decision(action, target=None, reason=REASON):
    result = {"action": action, "reason": reason}
    if target is not None:
        result["target_raw_object_id"] = target
    return result


def _seed(case, *, row=None, options=None):
    batch, events = _import(case, _xlsx([row or _spot()]), options or _options())
    assert len(events) == 1
    return batch, _raw(case, batch)[0]


def test_harness_blocks_foreign_database_and_all_ip_network(case, tmp_path):
    with pytest.raises(AssertionError, match="Fremde DB"):
        DuckDbStore(tmp_path.parent / "forbidden.duckdb")
    with pytest.raises(AssertionError, match="Fremde DB"):
        duckdb.connect(str(tmp_path.parent / "forbidden.duckdb"))
    with pytest.raises(OSError, match="kein Netzwerk"):
        socket.getaddrinfo("synthetic.invalid", 443)
    with socket.socket() as sock:
        with pytest.raises(OSError, match="kein Netzwerk"):
            sock.connect(("127.0.0.1", 9))
        with pytest.raises(OSError, match="kein Netzwerk"):
            sock.connect_ex(("127.0.0.1", 9))


@pytest.mark.parametrize("kind", HEADERS)
def test_header_only_native_xlsx_is_empty_not_corrupt(case, kind):
    before = _state(case)
    preview = _preview(case, _xlsx([], kind), _options(kind))
    assert preview.file_format == "xlsx"
    assert preview.sheet_name == "Sheet1"
    assert preview.columns == list(HEADERS[kind])
    assert preview.row_count == 0
    assert preview.can_import is False
    native = _native(preview)
    _counts(native, raw_rows=0, bookable_rows=0, linked_rows=0, review_rows=0, snapshot_rows=0, bonus_rows=0)
    assert native["rows"] == []
    assert _state(case) == before


def test_missing_options_cannot_guess_product_from_header_or_filename(case, monkeypatch):
    content = _xlsx([_spot()])
    before = _state(case)
    preview = _preview(case, content, None, filename="MEXC Spot Statement.xlsx")
    assert preview.can_import is False
    assert _state(case) == before
    _reject_before_batch(case, monkeypatch, content, None)


@pytest.mark.parametrize("options", [{}, {"export_kind": "spot_statement"}, {"account": ACCOUNT}])
def test_incomplete_options_are_preview_blockers_not_silent_defaults(case, monkeypatch, options):
    content = _xlsx([_spot()])
    preview = _preview(case, content, options)
    assert preview.can_import is False
    assert _native(preview)["blocking_reasons"]
    _reject_before_batch(case, monkeypatch, content, options)


@pytest.mark.parametrize("changes", [
    {"export_kind": "unverified_product"},
    {"account": "synthetic\naccount"},
    {"timezone": "SYNTHETIC/NO_SUCH_ZONE"},
    {"decisions": {"2": {"action": "auto_merge", "reason": REASON}}},
    {"decisions": {"2": _decision("separate", reason="123456789")}},
])
def test_malformed_dict_options_raise_pydantic_validation_error(case, changes):
    before = _state(case)
    with pytest.raises(ValidationError):
        _preview(case, _xlsx([_spot()]), _options(**changes))
    assert _state(case) == before


def test_contract_model_and_dict_have_same_preview_and_assistant_preserves_options(case):
    from steuerreport_v2.contracts.imports import ImportAssistantRequest
    from steuerreport_v2.contracts.mexc_import import MexcImportOptions

    content = _xlsx([_spot()])
    options = _options()
    typed = MexcImportOptions.model_validate(options)
    request = ImportAssistantRequest(import_mode="file", **_request(content, options))
    assert isinstance(request.mexc, MexcImportOptions)
    assert request.mexc == typed
    assert _preview(case, content, typed) == _preview(case, content, options)
    batch, events = _import(case, content, typed)
    assert len(events) == 1
    assert _metadata(_raw(case, batch)[0])[1]["export_kind"] == "spot_statement"


def test_airdrop_ready_and_review_overlap_raw_provenance_and_fixed_summer_offset(case):
    row = _spot()
    content = _xlsx([row])
    before = _state(case)
    preview = _preview(case, content, _options())
    native = _native(preview)
    assert preview.can_import is True
    _counts(native, raw_rows=1, bookable_rows=1, linked_rows=0, review_rows=1, snapshot_rows=0, bonus_rows=0)
    assert native["rows"][0]["row_number"] == 2
    assert native["rows"][0]["status"] == "ready"
    assert _state(case) == before, "Vorschau muss rein lesend sein"
    batch, events = _import(case, content, _options())
    assert len(events) == 1
    event = events[0]
    assert (event.source, event.account, event.asset, event.event_type, event.quantity) == (
        "mexc", LEDGER_ACCOUNT, "DEMOCOIN", "unknown", D("2.5"),
    )
    assert event.event_time.astimezone(timezone.utc) == WHEN
    assert event.quote_asset is None and event.quote_quantity is None
    assert event.fee_quantity in (None, D("0"))
    raw, = _raw(case, batch)
    assert raw.row_number == 2
    assert event.raw_object_id == raw.raw_object_id
    payload, meta = _metadata(raw)
    assert {key: payload[key] for key in row} == row
    assert meta["export_kind"] == "spot_statement"
    assert meta["account"] == ACCOUNT
    assert meta["uid"] == UID
    assert meta["sheet_name"] == "Sheet1"
    assert meta["file_sha256"] == "sha256:" + hashlib.sha256(content).hexdigest()
    assert meta["file_sha256"] == preview.file_sha256
    assert meta["role"] == "book"
    assert datetime.fromisoformat(meta["event_time"].replace("Z", "+00:00")).astimezone(timezone.utc) == WHEN
    assert (meta["asset"], D(meta["quantity"]), meta["label"]) == ("DEMOCOIN", D("2.5"), "Airdrop")
    assert meta["signature"]
    assert not meta.get("link_target_raw_object_id")
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("2.5")}
    archived = case[0].path.parent / "mexc_originals" / (hashlib.sha256(content).hexdigest() + ".original")
    assert archived.read_bytes() == content


@pytest.mark.parametrize("quantity,direction,expected", [
    ("2.5", "Inflow", "2.5"), ("+2.5", "Inflow", "2.5"),
    ("2.5", "Outflow", "-2.5"), ("-2.5", "Outflow", "-2.5"),
    ("2.500000000001", "Inflow", "2.500000000001"),
])
def test_direction_sign_and_decimal_values_are_not_double_negated_or_rounded(case, quantity, direction, expected):
    row = _spot(Quantity=quantity, Direction=direction)
    batch, events = _import(case, _xlsx([row]), _options())
    assert len(events) == 1
    assert events[0].quantity == D(expected)
    assert events[0].event_type == "unknown"
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D(expected)}
    assert _metadata(_raw(case, batch)[0])[0]["Quantity"] == quantity


@pytest.mark.parametrize("quantity,direction,expected", [
    ("12345678901234567890.123456789012345678", "Inflow", "12345678901234567890.123456789012345678"),
    ("12345678901234567890.123456789012345678", "Outflow", "-12345678901234567890.123456789012345678"),
    ("99999999999999999999.999999999999999999", "Inflow", "99999999999999999999.999999999999999999"),
])
def test_full_decimal_38_18_precision_survives_native_canonical_and_ledger(case, quantity, direction, expected):
    content = _xlsx([_spot(Quantity=quantity, Direction=direction)])
    batch, events = _import(case, content, _options())
    assert len(events) == 1
    assert events[0].quantity == D(expected), "Canonical darf nicht auf Decimal-Defaultpraezision runden"
    assert D(_metadata(_raw(case, batch)[0])[1]["quantity"]) == D(expected)
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D(expected)}
    with case[0].connect() as con:
        stored = con.execute("select delta_quantity,balance_quantity from balance_ledger").fetchall()
    assert stored == [(D(expected), D(expected))], "Auch die laufende Ledger-Balance muss exakt bleiben"


def test_numeric_excel_xml_literals_preserve_large_uid_and_eighteen_decimal_places(case):
    uid, quantity = "9007199254740993", "0.123456789012345678"
    content = _numeric_xlsx(uid, quantity)
    batch, events = _import(case, content, _options())
    payload, meta = _metadata(_raw(case, batch)[0])
    assert (payload["UID"], payload["Quantity"]) == (uid, quantity)
    assert meta["uid"] == uid
    assert events[0].quantity == D(quantity)
    assert _positions(case) == {("mexc:" + uid + ":" + ACCOUNT, "DEMOCOIN"): D(quantity)}


@pytest.mark.parametrize("quantity", ["100000000000000000000", "0.1234567890123456789"])
def test_unrepresentable_decimal_values_block_before_batch_instead_of_rounding(case, monkeypatch, quantity):
    content = _xlsx([_spot(Quantity=quantity)])
    preview = _preview(case, content, _options())
    assert preview.can_import is False
    assert _native(preview)["rows"][0]["status"] == "invalid"
    _reject_before_batch(case, monkeypatch, content, _options())


@pytest.mark.parametrize("limit", ["rows", "file_bytes", "expanded_zip"])
def test_native_size_limits_reject_without_partial_import(case, monkeypatch, limit):
    if limit == "rows":
        content = _xlsx([_spot()] * 10001)
    elif limit == "file_bytes":
        content = b"x" * (25 * 1024 * 1024 + 1)
    else:
        output = BytesIO()
        with ZipFile(BytesIO(_xlsx([_spot()]))) as original, ZipFile(output, "w", compression=ZIP_DEFLATED) as changed:
            for member in original.infolist():
                changed.writestr(member.filename, original.read(member.filename))
            # Nur 1 MiB gleichzeitig im RAM; hoch komprimierter synthetischer Ballast.
            with changed.open("synthetic-padding.bin", "w") as padding:
                chunk = b"0" * (1024 * 1024)
                for _ in range(101):
                    padding.write(chunk)
        content = output.getvalue()
        assert len(content) < 25 * 1024 * 1024
    _reject_before_batch(case, monkeypatch, content, _options())


@pytest.mark.parametrize("changes", [{"Quantity": "-2.5"}, {"Direction": "SIDEWAYS"}, {"Quantity": "not-a-number"}])
def test_contradictory_or_unknown_direction_and_bad_amount_are_not_bookable(case, monkeypatch, changes):
    content = _xlsx([_spot(**changes)])
    preview = _preview(case, content, _options())
    assert preview.can_import is False
    native = _native(preview)
    _counts(native, raw_rows=1, bookable_rows=0)
    row, = native["rows"]
    assert row["row_number"] == 2
    assert row["status"] in {"invalid", "review"}
    assert row["reason"]
    assert case[0].list_canonical_events() == []
    _reject_before_batch(case, monkeypatch, content, _options())


@pytest.mark.parametrize("missing", ["timezone", "time"])
def test_funding_without_time_basis_or_value_blocks_even_raw_import(case, monkeypatch, missing):
    options = _options("funding_other")
    row = _funding()
    if missing == "timezone":
        options.pop("timezone")
        _seed(case)
    else:
        row["Time"] = ""
    content = _xlsx([row], "funding_other")
    preview = _preview(case, content, options)
    assert preview.can_import is False
    native = _native(preview)
    _counts(native, raw_rows=1, bookable_rows=0)
    assert native["rows"][0]["reason"]
    _reject_before_batch(case, monkeypatch, content, options)


def test_funding_explicit_fixed_offset_books_unknown_not_income(case):
    batch, events = _import(case, _xlsx([_funding()], "funding_other"), _options("funding_other"))
    assert len(events) == 1
    assert events[0].event_time.astimezone(timezone.utc) == WHEN
    assert (events[0].event_type, events[0].quantity) == ("unknown", D("2.5"))
    payload, meta = _metadata(_raw(case, batch)[0])
    assert payload["Time"] == "2031-07-09 12:00:00"
    assert meta["timezone"] == "UTC+01:00"


def test_physical_row_numbers_survive_blank_excel_row(case):
    content = _xlsx([{}, _spot()])
    native = _native(_preview(case, content, _options()))
    _counts(native, raw_rows=1, bookable_rows=1)
    assert native["rows"][0]["row_number"] == 3
    batch, events = _import(case, content, _options())
    assert len(events) == 1
    raw, = _raw(case, batch)
    assert raw.row_number == 3
    assert _metadata(raw)[1]["row_number"] == 3


@pytest.mark.parametrize("local_time,expected_status", [("11:00:00", "duplicate_candidate"), ("12:00:00", "ready")])
def test_candidate_comparison_uses_utc_instant_not_local_time_text(case, local_time, expected_status):
    _seed(case)
    content = _xlsx([_funding(Time="2031-07-09 " + local_time)], "funding_other")
    native = _native(_preview(case, content, _options("funding_other", timezone="UTC")))
    assert native["rows"][0]["status"] == expected_status


def test_same_bytes_from_other_source_do_not_hide_mexc_file(case):
    content = _xlsx([_spot()])
    foreign = case[1].import_base64(source="binance", filename="synthetic.xlsx", content_base64=base64.b64encode(content).decode("ascii"))
    preview = _preview(case, content, _options())
    assert preview.duplicate_batch_id is None
    assert preview.can_import is True
    assert _native(preview)["rows"][0]["status"] == "ready"
    own, events = _import(case, content, _options())
    assert own.batch_id != foreign.batch_id
    assert len(events) == 1


def test_separate_decision_ten_character_boundary_is_accepted(case):
    _seed(case)
    options = _options("funding_other", decisions={"2": _decision("separate", reason="1234567890")})
    batch, events = _import(case, _xlsx([_funding()], "funding_other"), options)
    assert len(events) == 1
    assert _metadata(_raw(case, batch)[0])[1]["decision_reason"] == "1234567890"
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("5.0")}


@pytest.mark.parametrize("path", ["base64", "csv_importer"])
def test_csv_native_path_preserves_physical_row_and_exact_original_bytes(case, path):
    out = StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=SPOT_HEADERS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerow(_spot())
    text = out.getvalue()
    content = text.encode("utf-8")
    if path == "base64":
        batch, events = _import(case, content, _options(), filename="synthetic.csv", sheet=None)
    else:
        importer = CsvRawImporter(case[0])
        preview = importer.preview_text(source="mexc", filename="synthetic.csv", content=text, mexc=_options())
        assert preview.can_import is True
        batch = importer.import_text(source="mexc", filename="synthetic.csv", content=text, mexc=_options())
        events = RawNormalizer(case[0]).normalize_batch(batch.batch_id)
        BalanceLedgerBuilder(case[0]).rebuild()
    assert len(events) == 1
    assert events[0].quantity == D("2.5")
    raw, = _raw(case, batch)
    assert raw.row_number == 2
    assert _metadata(raw)[1]["sheet_name"] is None
    archived = case[0].path.parent / "mexc_originals" / (hashlib.sha256(content).hexdigest() + ".original")
    assert archived.read_bytes() == content


def test_snapshot_and_linked_raws_are_not_unmapped_but_bonus_is(case):
    from steuerreport_v2.domain.review import ReviewService

    snapshot, _ = _import(case, _xlsx([_snapshot_row()], "asset_snapshot"), _options("asset_snapshot"))
    _, root = _seed(case)
    linked_options = _options("funding_other", decisions={"2": _decision("link_existing", root.raw_object_id)})
    linked, _ = _import(case, _xlsx([_funding()], "funding_other"), linked_options)
    bonus, _ = _import(case, _xlsx(_bonus_rows(), "futures_capital_flow"), _options("futures_capital_flow"))
    unmapped = case[0].unmapped_raw_object_counts()
    assert snapshot.batch_id not in unmapped
    assert linked.batch_id not in unmapped
    assert unmapped[bonus.batch_id] == 2
    gate = ReviewService(case[0]).gate()
    assert gate.allow_export is False
    assert any(i.blocks_export and bonus.batch_id in i.scope for i in gate.issues)


@pytest.mark.parametrize("foreign_marker", ["bitget_withdrawal_evidence", "history_evidence_only"])
def test_mexc_bonus_cannot_escape_review_using_other_sources_evidence_markers(case, foreign_marker):
    from steuerreport_v2.domain.review import ReviewService

    rows = _bonus_rows()
    for row in rows:
        row["Futures Trading Pair"] = "SYNTHETIC_PAIR"
    extra = ()
    if foreign_marker == "bitget_withdrawal_evidence":
        for row in rows:
            row["Futures Trading Pair"] = foreign_marker
    else:
        extra = (foreign_marker,)
        for row in rows:
            row[foreign_marker] = "1"
    batch, events = _import(case, _xlsx(rows, "futures_capital_flow", extra_headers=extra), _options("futures_capital_flow"))
    assert events == []
    gate = ReviewService(case[0]).gate()
    observed = (case[0].unmapped_raw_object_counts().get(batch.batch_id), gate.allow_export)
    assert observed == (2, False), ("Fremde Belegmarker duerfen MEXC-BONUS nicht freigeben", observed, [i.code for i in gate.issues])
    assert any(i.blocks_export and batch.batch_id in i.scope for i in gate.issues)


def test_deleted_link_root_is_a_specific_blocker_and_never_recreated_as_booking(case):
    from steuerreport_v2.domain.review import ReviewService

    root_batch, root = _seed(case)
    linked_options = _options("funding_other", decisions={"2": _decision("link_existing", root.raw_object_id)})
    linked, _ = _import(case, _xlsx([_funding()], "funding_other"), linked_options)
    case[0].delete_import_batch(root_batch.batch_id)
    assert RawNormalizer(case[0]).normalize_batch(linked.batch_id) == []
    BalanceLedgerBuilder(case[0]).rebuild()
    assert _positions(case) == {}
    gate = ReviewService(case[0]).gate()
    assert gate.allow_export is False
    assert any(i.blocks_export and i.code == "mexc_link_target_missing" for i in gate.issues)


def test_cross_export_candidate_blocks_until_linked_then_keeps_two_raws_one_event(case, monkeypatch):
    root_batch, root = _seed(case)
    original = root.payload_json
    content = _xlsx([_funding()], "funding_other")
    options = _options("funding_other")
    preview = _preview(case, content, options)
    assert preview.can_import is False
    native = _native(preview)
    row, = native["rows"]
    assert row["status"] == "duplicate_candidate"
    assert row["row_number"] == 2
    assert row["candidates"]
    assert root.raw_object_id in set(_string_leaves(row["candidates"]))
    _reject_before_batch(case, monkeypatch, content, options)
    options["decisions"] = {"2": _decision("link_existing", root.raw_object_id)}
    linked_preview = _preview(case, content, options)
    assert linked_preview.can_import is True
    _counts(_native(linked_preview), raw_rows=1, bookable_rows=0, linked_rows=1)
    assert _native(linked_preview)["rows"][0]["status"] == "linked"
    linked_batch, events = _import(case, content, options)
    assert events == []
    assert len(case[0].list_canonical_events()) == 1
    linked_raw, = _raw(case, linked_batch)
    _, metadata = _metadata(linked_raw)
    assert metadata["role"] == "linked"
    assert metadata["link_target_raw_object_id"] == root.raw_object_id
    assert metadata["decision_reason"] == REASON
    assert metadata["signature"] == _metadata(root)[1]["signature"]
    assert _raw(case, root_batch)[0].payload_json == original
    assert sum(len(_raw(case, b)) for b in case[0].list_import_batches()) == 2
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("2.5")}
    RawNormalizer(case[0]).normalize_batch(linked_batch.batch_id)
    RawNormalizer(case[0]).normalize_batch(root_batch.batch_id)
    BalanceLedgerBuilder(case[0]).rebuild()
    assert len(case[0].list_canonical_events()) == 1
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("2.5")}


@pytest.mark.parametrize("action,expected_count,expected_quantity", [("link_existing", 1, "2.5"), ("separate", 2, "5.0")])
def test_csv_cross_file_decisions_are_checked_independently_of_xlsx_empty_cells(case, monkeypatch, action, expected_count, expected_quantity):
    root_batch, root = _seed(case)
    before_root = root.payload_json
    content = _csv([_funding()])
    options = _options("funding_other")
    kwargs = {"filename": "synthetic.csv", "sheet": None}
    preview = _preview(case, content, options, **kwargs)
    assert preview.can_import is False
    assert _native(preview)["rows"][0]["status"] == "duplicate_candidate"
    _reject_before_batch(case, monkeypatch, content, options, **kwargs)
    options["decisions"] = {"2": _decision(action, root.raw_object_id if action == "link_existing" else None)}
    batch, _ = _import(case, content, options, **kwargs)
    _, meta = _metadata(_raw(case, batch)[0])
    assert meta["role"] == ("linked" if action == "link_existing" else "book")
    assert meta["decision_reason"] == REASON
    if action == "link_existing":
        assert meta["link_target_raw_object_id"] == root.raw_object_id
    assert _raw(case, root_batch)[0].payload_json == before_root
    assert len(case[0].list_canonical_events()) == expected_count
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D(expected_quantity)}


def test_separate_decision_preserves_second_legitimate_equal_booking(case):
    _seed(case)
    options = _options("funding_other", decisions={"2": _decision("separate")})
    batch, events = _import(case, _xlsx([_funding()], "funding_other"), options)
    assert len(events) == 1
    assert len(case[0].list_canonical_events()) == 2
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("5.0")}
    meta = _metadata(_raw(case, batch)[0])[1]
    assert meta["role"] == "book"
    assert meta["decision_reason"] == REASON


def test_two_identical_physical_rows_are_not_automatically_collapsed(case):
    content = _xlsx([_spot(), _spot()])
    batch, events = _import(case, content, _options())
    assert len(events) == 2
    assert len({e.raw_object_id for e in events}) == 2
    assert [r.row_number for r in _raw(case, batch)] == [2, 3]
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("5.0")}


@pytest.mark.parametrize("action,expected_events,expected_balance", [("link_existing", 1, "2.5"), ("separate", 2, "5.0")])
def test_regenerated_file_different_hash_needs_explicit_overlap_decision(case, monkeypatch, action, expected_events, expected_balance):
    original = _xlsx([_spot()], revision="first")
    changed = _xlsx([_spot()], revision="regenerated")
    assert hashlib.sha256(original).digest() != hashlib.sha256(changed).digest()
    batch, _ = _import(case, original, _options())
    root, = _raw(case, batch)
    options = _options()
    preview = _preview(case, changed, options)
    assert preview.file_sha256 != _metadata(root)[1]["file_sha256"]
    assert preview.can_import is False
    assert _native(preview)["rows"][0]["status"] == "duplicate_candidate"
    _reject_before_batch(case, monkeypatch, changed, options)
    options["decisions"] = {"2": _decision(action, root.raw_object_id if action == "link_existing" else None)}
    _import(case, changed, options)
    assert len(case[0].list_canonical_events()) == expected_events
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D(expected_balance)}


def test_reimport_is_context_bound_idempotent_and_decisions_do_not_change_identity(case):
    content = _xlsx([_spot()])
    options = _options()
    fingerprint = _preview(case, content, options).import_fingerprint
    batch, _ = _import(case, content, options)
    before = _state(case)
    changed_decision = _options(decisions={"2": _decision("separate", reason="Anderer synthetischer Pruefvermerk.")})
    preview = _preview(case, content, changed_decision, filename="renamed.xlsx")
    assert preview.import_fingerprint == fingerprint
    assert preview.duplicate_batch_id == batch.batch_id
    repeated = case[1].import_base64(**_request(content, changed_decision, filename="renamed.xlsx"))
    assert repeated.batch_id == batch.batch_id
    assert _state(case) == before


def test_concurrent_identical_file_import_does_not_create_partial_or_double_batch(case):
    request = _request(_xlsx([_spot()]), _options())
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(lambda _: case[1].import_base64(**request), range(2)))
    assert batches[0].batch_id == batches[1].batch_id
    assert len(case[0].list_import_batches()) == 1
    assert len(_raw(case, batches[0])) == 1
    events = RawNormalizer(case[0]).normalize_batch(batches[0].batch_id)
    BalanceLedgerBuilder(case[0]).rebuild()
    assert len(events) == 1
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("2.5")}


def test_stale_ready_preview_is_rechecked_before_import(case, monkeypatch):
    later = _xlsx([_spot()], revision="later")
    assert _preview(case, later, _options()).can_import is True
    _seed(case)
    _reject_before_batch(case, monkeypatch, later, _options())


@pytest.mark.parametrize("dimension", ["account", "export_kind", "timezone", "sheet"])
def test_import_fingerprint_binds_each_mapping_dimension(case, dimension):
    kind = "funding_other" if dimension == "timezone" else "spot_statement"
    content = _xlsx([_funding() if kind == "funding_other" else _spot()], kind, sheets=("Sheet1", "Sheet2"))
    original_options = _options(kind)
    changed_options = dict(original_options)
    changed_sheet = "Sheet1"
    if dimension == "sheet":
        changed_sheet = "Sheet2"
    elif dimension == "account":
        changed_options["account"] = "synthetic-second-account"
    elif dimension == "export_kind":
        changed_options["export_kind"] = "futures_statement"
    else:
        changed_options["timezone"] = "UTC"
    original = _preview(case, content, original_options)
    changed = _preview(case, content, changed_options, sheet=changed_sheet)
    assert original.file_sha256 == changed.file_sha256
    assert original.import_fingerprint != changed.import_fingerprint


def test_same_bytes_in_different_account_are_not_deduplicated_or_candidate_linked(case):
    content = _xlsx([_spot()])
    first, _ = _import(case, content, _options())
    options = _options(account="synthetic-second-account")
    preview = _preview(case, content, options)
    assert preview.duplicate_batch_id is None
    assert preview.can_import is True
    assert _native(preview)["rows"][0]["status"] == "ready"
    second, events = _import(case, content, options)
    assert first.batch_id != second.batch_id
    assert len(events) == 1
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("2.5"), ("mexc:" + UID + ":synthetic-second-account", "DEMOCOIN"): D("2.5")}


def test_uid_and_account_boundaries_cannot_collide_in_ledger_namespace(case):
    first_account = "synthetic:spot"
    second_uid, second_account = UID + ":synthetic", "spot"
    _, first_events = _import(case, _xlsx([_spot()]), _options(account=first_account))
    _, second_events = _import(case, _xlsx([_spot(UID=second_uid)]), _options(account=second_account))
    assert len(first_events) == len(second_events) == 1
    assert first_events[0].account != second_events[0].account, "Unterschiedliche UID/Konto-Tupel duerfen nicht durch ':' kollidieren"
    positions = BalanceLedgerBuilder(case[0]).positions()
    assert len(positions) == 2
    assert [p.quantity for p in positions] == [D("2.5"), D("2.5")]


@pytest.mark.parametrize("mismatch", ["missing", "account", "uid", "time", "asset", "quantity", "label", "foreign_source"])
def test_invalid_link_target_is_rejected_before_batch_creation(case, monkeypatch, mismatch):
    changes = {
        "uid": {"UID": "SYNTHETIC-OTHER-UID"},
        "time": {"Creation Time(UTC+01:00)": "2031-07-09 12:00:01"},
        "asset": {"Crypto": "OTHERCOIN"},
        "quantity": {"Quantity": "3.5"},
        "label": {"Transaction Type": "Unknown/Airdrop"},
    }
    options = _options(account="synthetic-other-account") if mismatch == "account" else _options()
    batch, _ = _import(case, _xlsx([_spot(**changes.get(mismatch, {}))]), options)
    root, = _raw(case, batch)
    target = root.raw_object_id
    if mismatch == "missing":
        target = "synthetic-nonexistent-raw-id"
    if mismatch == "foreign_source":
        foreign = case[0].create_import_batch(ImportBatchCreate(source="manual-csv", filename="synthetic.csv", file_hash="synthetic-foreign"))
        case[0].add_raw_objects(foreign.batch_id, [RawObjectCreate(row_number=2, payload_json=root.payload_json)])
        target = case[0].list_raw_objects(foreign.batch_id)[0].raw_object_id
    incoming = _options("funding_other", decisions={"2": _decision("link_existing", target)})
    _reject_before_batch(case, monkeypatch, _csv([_funding()]), incoming, filename="synthetic.csv", sheet=None)


def test_link_to_link_is_rejected_instead_of_chaining_or_cycling(case, monkeypatch):
    _, root = _seed(case)
    first_options = _options("funding_other", decisions={"2": _decision("link_existing", root.raw_object_id)})
    linked_batch, _ = _import(case, _xlsx([_funding()], "funding_other"), first_options)
    linked_raw, = _raw(case, linked_batch)
    options = _options(decisions={"2": _decision("link_existing", linked_raw.raw_object_id)})
    _reject_before_batch(case, monkeypatch, _xlsx([_spot()], revision="third"), options)


@pytest.mark.parametrize("kind", ["asset_snapshot", "futures_capital_flow"])
def test_snapshot_or_bonus_cannot_be_link_root(case, monkeypatch, kind):
    rows = [_snapshot_row()] if kind == "asset_snapshot" else _bonus_rows()
    batch, events = _import(case, _xlsx(rows, kind), _options(kind))
    assert events == []
    target = _raw(case, batch)[0].raw_object_id
    options = _options(decisions={"2": _decision("link_existing", target)})
    _reject_before_batch(case, monkeypatch, _xlsx([_spot()]), options)


def test_invalid_second_row_decision_leaves_no_partial_first_row_or_batch(case, monkeypatch):
    _, root = _seed(case)
    options = _options("funding_other", decisions={
        "2": _decision("link_existing", root.raw_object_id),
        "3": _decision("link_existing", "synthetic-missing-target"),
    })
    _reject_before_batch(case, monkeypatch, _csv([_funding(), _funding()]), options, filename="synthetic.csv", sheet=None)


@pytest.mark.parametrize("action", ["separate", "link_existing"])
def test_short_decision_reason_blocks_direct_import_before_batch(case, monkeypatch, action):
    _, root = _seed(case)
    options = _options("funding_other", decisions={"2": _decision(action, root.raw_object_id if action == "link_existing" else None, reason="123456789")})
    _reject_before_batch(case, monkeypatch, _xlsx([_funding()], "funding_other"), options)


def test_snapshot_is_only_raw_evidence_and_never_acquisition_or_valuation_cash(case):
    content = _xlsx([_snapshot_row()], "asset_snapshot")
    options = _options("asset_snapshot")
    preview = _preview(case, content, options)
    assert preview.can_import is True
    _counts(_native(preview), raw_rows=1, bookable_rows=0, linked_rows=0, snapshot_rows=1, bonus_rows=0)
    batch, events = _import(case, content, options)
    assert events == []
    payload, meta = _metadata(_raw(case, batch)[0])
    assert meta["role"] == "snapshot"
    assert payload["Date(UTC+8)"] == "20310709"
    assert (payload["Total"], payload["USDT Valuation"]) == ("2.5", "123")
    assert _positions(case) == {}
    assert _state(case)["tax_lots"] == []
    assert _state(case)["tax_lines"] == []
    assert _state(case)["derivative_lines"] == []


def test_bonus_allocation_and_negative_reversal_remain_two_raws_no_events(case):
    rows = _bonus_rows()
    content = _xlsx(rows, "futures_capital_flow")
    options = _options("futures_capital_flow")
    preview = _preview(case, content, options)
    assert preview.can_import is True
    _counts(_native(preview), raw_rows=2, bookable_rows=0, linked_rows=0, snapshot_rows=0, bonus_rows=2)
    batch, events = _import(case, content, options)
    assert events == []
    raws = _raw(case, batch)
    assert [raw.row_number for raw in raws] == [2, 3]
    amounts = []
    for raw, original in zip(raws, rows):
        payload, meta = _metadata(raw)
        assert {key: payload[key] for key in original} == original
        assert meta["role"] == "bonus"
        amounts.append(D(payload["Amount"]))
    assert amounts == [D("7"), D("-7")]
    assert sum(amounts) == D("0")
    assert _positions(case) == {}
    assert _state(case)["tax_lots"] == []
    assert _state(case)["derivative_lines"] == []


@pytest.mark.parametrize("kind", ["futures_statement", "earn_fixed", "earn_flexible", "send_history"])
def test_same_headers_other_products_are_review_evidence_not_spot_bookings(case, kind):
    content = _xlsx([_spot()], kind)
    options = _options(kind)
    preview = _preview(case, content, options)
    assert preview.can_import is True
    native = _native(preview)
    _counts(native, raw_rows=1, bookable_rows=0, review_rows=1)
    assert native["rows"][0]["status"] in {"evidence_only", "review"}
    assert native["rows"][0]["reason"]
    batch, events = _import(case, content, options)
    assert events == []
    assert _metadata(_raw(case, batch)[0])[1]["role"] == "review"
    assert _positions(case) == {}


def test_unknown_other_label_is_raw_review_not_generic_unknown_balance_event(case):
    row = _spot(**{"Transaction Type": "SYNTHETIC_UNDOCUMENTED_OPERATION"})
    content = _xlsx([row])
    preview = _preview(case, content, _options())
    native = _native(preview)
    _counts(native, raw_rows=1, bookable_rows=0, review_rows=1)
    assert native["rows"][0]["status"] == "review"
    assert native["rows"][0]["reason"]
    batch, events = _import(case, content, _options())
    assert events == []
    assert _metadata(_raw(case, batch)[0])[1]["role"] == "review"
    assert _positions(case) == {}


def test_airdrop_has_own_mexc_classification_export_blocker(case):
    from steuerreport_v2.domain.review import ReviewService

    _seed(case)
    gate = ReviewService(case[0]).gate()
    assert gate.allow_export is False
    assert any(issue.blocks_export and issue.code == "mexc_classification_required" for issue in gate.issues), [i.code for i in gate.issues]
    assert [(e.event_type, e.quantity) for e in case[0].list_canonical_events()] == [("unknown", D("2.5"))]


def _string_leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _string_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_leaves(item)
    elif isinstance(value, str):
        yield value


def test_assistant_preview_passes_native_options_and_trace_exposes_both_evidence_directions(case):
    from fastapi.testclient import TestClient
    from steuerreport_v2.api.app import create_app

    content = _xlsx([_spot()])
    request = {"import_mode": "file", **_request(content, _options())}
    before = _state(case)
    with TestClient(create_app(case[0])) as client:
        response = client.post("/api/v1/import/assistant/preview", json=request)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["can_execute"] is True
        assert data["preview"]["mexc"]["raw_rows"] == 1
        assert data["preview"]["mexc"]["bookable_rows"] == 1
        assert _state(case) == before
        root_response = client.post("/api/v1/import/assistant/execute", json=request)
        assert root_response.status_code == 200
        root_result = root_response.json()
        assert root_result["status"] == "ok", root_result
        root_batch_id = root_result["data"]["batch"]["batch_id"]
        root, = case[0].list_raw_objects(root_batch_id, limit=None)
        funding = _xlsx([_funding()], "funding_other")
        linked_options = _options("funding_other", decisions={"2": _decision("link_existing", root.raw_object_id)})
        linked_request = {"import_mode": "file", **_request(funding, linked_options)}
        linked_response = client.post("/api/v1/import/assistant/execute", json=linked_request)
        assert linked_response.status_code == 200
        linked_result = linked_response.json()
        assert linked_result["status"] == "ok", linked_result
        linked_batch_id = linked_result["data"]["batch"]["batch_id"]
        linked_raw, = case[0].list_raw_objects(linked_batch_id, limit=None)
        for batch_id in (root_batch_id, linked_batch_id):
            trace_response = client.get(f"/api/v1/import/batches/{batch_id}/trace.json")
            assert trace_response.status_code == 200
            trace = trace_response.json()
            assert trace["batch"]["batch_id"] == batch_id
            assert trace["raw_objects"]
            assert "canonical_events" in trace
            assert trace["mexc_evidence"], "Belegtrace braucht Vorwaerts- und Rueckverweise"
            ids = set(_string_leaves(trace["mexc_evidence"]))
            assert {root.raw_object_id, linked_raw.raw_object_id} <= ids
        assert len(case[0].list_canonical_events()) == 1
        assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): D("2.5")}
