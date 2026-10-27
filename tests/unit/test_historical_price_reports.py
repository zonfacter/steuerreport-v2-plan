import copy
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import socket
import zipfile

import pytest

from steuerreport_v2.domain import historical_price_reports as reports
from steuerreport_v2.domain.historical_price_reports import report_json, report_markdown, report_zip


@pytest.fixture
def preview():
    return {
        "id": "test-preview", "preview_sha256": "a" * 64, "plan_sha256": "b" * 64,
        "created_at": "2026-10-27T10:00:00+00:00", "software_version": "test-version",
        "methodology": "historical-eur-daily-v2", "applied": False,
        "query": {"scope": "all_observed", "year": None, "provider": "defillama", "max_requests": 10},
        "rows": [{
            "asset": "SOL", "price_date": "2024-06-02", "first_event_at": "2024-06-02T12:00:00+00:00",
            "status": "fetched", "price_eur": "138.123456789123456789", "priced_at": "2024-06-02T11:59:59+00:00",
            "fx_date": "2024-05-31", "provider_id": "coingecko:solana", "evidence_sha256": [],
            "event_count": 2, "event_types": ["reward", "transfer"], "years": [2024],
            "event_year_counts": {"2024": 2}, "reason": None,
        }],
        "year_summary": [{"year": 2024, "events_count": 2, "tokens_count": 1, "inventory_count": 1,
                          "covered_count": 1, "open_count": 0}],
        "before_summary": {"tax": {"2024": {"gain_loss_eur": "-12.5"}}},
        "after_summary": {"tax": {"2024": {"gain_loss_eur": "-10.5"}}},
        "before_valuation_summary": {"unvalued_flow_count": 2},
        "after_valuation_summary": {"unvalued_flow_count": 0},
        "tax_line_deltas": [{"key": "line", "before": None, "after": {"gain_loss_eur": "-10.5"}}],
        "source_event_types": {"reward": 1, "transfer": 1}, "canonical_events_unchanged": True,
        "evidence": [],
    }


def unpack(preview, loader=lambda sha: pytest.fail("Unerwarteter Belegabruf")):
    with zipfile.ZipFile(io.BytesIO(report_zip(preview, loader))) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def csv_rows(files, year):
    return list(csv.DictReader(io.StringIO(files[f"{year}/preise.csv"].decode("utf-8"), newline="")))


def test_json_binds_full_preview_and_preserves_missing_values(preview):
    preview["rows"].append({"asset": "MISSING", "status": "open", "price_eur": None})
    document = report_json(preview)
    assert document["report_version"] == 1
    for key in ("preview_sha256", "plan_sha256", "created_at", "software_version", "methodology"):
        assert document[key] == preview[key]
    assert document["preview"] == preview
    assert document["preview"]["rows"][1]["price_eur"] is None
    assert "priced_at" not in document["preview"]["rows"][1]
    document["preview"]["rows"][0]["asset"] = "CHANGED"
    assert preview["rows"][0]["asset"] == "SOL"
    assert json.loads(json.dumps(document))["preview"]["rows"][1]["price_eur"] is None


def test_decimal_and_date_values_do_not_lose_precision(preview):
    row = preview["rows"][0]
    row.update(price_eur=Decimal("-138.123456789123456789"), price_date=date(2024, 6, 2),
               priced_at=datetime(2024, 6, 2, tzinfo=timezone.utc))
    result = report_json(preview)["preview"]["rows"][0]
    assert result["price_eur"] == "-138.123456789123456789"
    assert result["price_date"] == "2024-06-02"
    assert result["priced_at"] == "2024-06-02T00:00:00+00:00"
    assert csv_rows(unpack(preview), 2024)[0]["price_eur"] == result["price_eur"]


def test_markdown_contains_complete_tables_summaries_and_escaped_cells(preview):
    sha = hashlib.sha256(b"original").hexdigest()
    preview["evidence"] = [{"sha256": sha}]
    preview["rows"][0].update(asset="RAW|SYMBOL\r\n<script>", status="blocked", reason="mint|missing\nreview")
    markdown = report_markdown(preview)
    assert "RAW\\|SYMBOL<br>&lt;script&gt;" in markdown
    assert "mint\\|missing<br>review" in markdown
    for field in reports._ROW_FIELDS:
        assert field in markdown
    for text in ("Jahresuebersicht", "Offene Gruende", "Quellenhashes", sha, "Vorher und Nachher",
                 "before_summary", "after_summary", "before_valuation_summary", "after_valuation_summary",
                 "source_event_types", "canonical_events_unchanged", "-10.5", "Tagesreferenzen"):
        assert text in markdown
    assert "keine Einnahmen" in markdown
    assert "Keine Quellen-, Token-, Review- oder Jahresfreigabe." in markdown
    assert "Finanzdatenbank unveraendert" in markdown


def test_applied_report_does_not_claim_database_is_unchanged(preview):
    preview.update(applied=True, applied_at="2026-10-27T12:00:00+00:00")
    for text in (report_markdown(preview), json.dumps(report_json(preview))):
        assert "Tatsaechlich angewendet" in text
        assert "Finanzdatenbank unveraendert" not in text
        assert "keine Preise uebernommen" not in text
    assert report_json(preview)["applied_at"] == preview["applied_at"]


def test_more_than_200_rows_exported_in_all_formats(preview):
    base = preview["rows"][0]
    preview["rows"] = [{**base, "asset": f"TOKEN{index:04d}", "status": status,
                        "price_eur": base["price_eur"] if status in {"fetched", "covered"} else None}
                       for index in range(257)
                       for status in (["fetched", "covered", "pending", "open", "blocked"][index % 5],)]
    files = unpack(preview)
    assert len(json.loads(files["report.json"])["preview"]["rows"]) == 257
    exported = csv_rows(files, 2024)
    assert len(exported) == 257
    assert {row["status"] for row in exported} == {"fetched", "covered", "pending", "open", "blocked"}
    assert "TOKEN0256" in files["report.md"].decode()
    for row in exported:
        if row["status"] in {"pending", "open", "blocked"}:
            assert row["price_eur"] == ""


def test_zip_is_deterministic_sorted_epoch_and_manifest_verifies_every_file(preview):
    bodies = [b'{ "original": 1.000 }\n', b'provider error, not JSON\r\n']
    originals = {hashlib.sha256(body).hexdigest(): body for body in bodies}
    preview["evidence"] = [{"sha256": sha, "url": "https://never-called.invalid"} for sha in reversed(originals)]
    preview["rows"][0]["evidence_sha256"] = list(originals) * 2
    calls = []

    def load(sha):
        calls.append(sha)
        return originals[sha]

    first = report_zip(preview, load)
    second = report_zip(copy.deepcopy(preview), originals.__getitem__)
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert calls == sorted(originals)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert not any(name.lower().endswith(".pdf") for name in names)
        for entry in archive.infolist():
            assert entry.date_time == (1980, 1, 1, 0, 0, 0)
        manifest = json.loads(archive.read("manifest.json"))
        assert [item["filename"] for item in manifest["files"]] == sorted(set(names) - {"manifest.json"})
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read(item["filename"])).hexdigest() == item["sha256"]
        for sha, body in originals.items():
            assert archive.read(f"evidence/{sha}.json") == body
        assert json.loads(archive.read("tax_line_deltas.json")) == preview["tax_line_deltas"]
        assert archive.read("report.md").decode() == report_markdown(preview)
        assert json.loads(archive.read("report.json")) == report_json(preview)


def test_explicit_year_membership_wins_over_utc_day_and_multi_year_rows_repeat(preview):
    base = preview["rows"][0]
    preview["rows"] = [
        {**base, "asset": "BOUNDARY", "first_event_at": "2023-12-31T23:30:00Z",
         "price_date": "2023-12-31", "years": [2024], "event_year_counts": {"2024": 2}},
        {**base, "asset": "MULTI", "years": [2023, 2024, 2024], "event_year_counts": {"2023": 1, "2024": 1}},
    ]
    preview["year_summary"].append({"year": 2025, "events_count": 0})
    files = unpack(preview)
    assert [row["asset"] for row in csv_rows(files, 2023)] == ["MULTI"]
    assert [row["asset"] for row in csv_rows(files, 2024)] == ["BOUNDARY", "MULTI"]
    assert json.loads(csv_rows(files, 2024)[1]["event_year_counts"]) == {"2023": 1, "2024": 1}
    assert csv_rows(files, 2025) == []
    assert files["2025/preise.csv"].count(b"\n") == 1


@pytest.mark.parametrize(("instant", "expected_year"), [
    ("2024-01-01T00:30:00+01:00", 2023),
    ("2023-12-31T23:30:00-01:00", 2024),
    ("2024-01-01T00:00:00", 2024),
])
def test_legacy_timestamp_year_is_parsed_in_utc(preview, instant, expected_year):
    row = preview["rows"][0]
    del row["years"]
    row.update(first_event_at=instant, price_date="2022-12-31")
    assert len(csv_rows(unpack(preview), expected_year)) == 1


def test_legacy_date_only_and_unassigned_rows_and_empty_query_year(preview):
    preview["rows"] = [{"asset": "DATE", "price_date": "2020-01-01"},
                       {"asset": "UNKNOWN", "first_event_at": "invalid"}]
    files = unpack(preview)
    assert csv_rows(files, 2020)[0]["asset"] == "DATE"
    assert csv_rows(files, "nichtzugeordnet")[0]["asset"] == "UNKNOWN"
    preview.update(rows=[], year_summary=[], query={"year": 2030})
    assert csv_rows(unpack(preview), 2030) == []


@pytest.mark.parametrize("invalid_year", ["../../escape", "2024/evil", "0000", 2008, 2101, True, 2024.0, None])
def test_invalid_years_and_hostile_asset_never_become_paths(preview, invalid_year):
    preview["year_summary"] = [{"year": invalid_year}]
    preview["query"]["year"] = invalid_year
    preview["rows"][0].update(years=[invalid_year], asset="../../hostile/asset\n.csv")
    files = unpack(preview)
    assert set(files) == {"report.json", "report.md", "manifest.json", "tax_line_deltas.json",
                          "nichtzugeordnet/preise.csv"}
    assert csv_rows(files, "nichtzugeordnet")[0]["asset"] == "../../hostile/asset\n.csv"


@pytest.mark.parametrize("symbol", ["=1+2", "+SUM(1,2)", "-cmd", "@SUM(A1)", " \t=1+2", "\r\n@evil"])
def test_csv_formula_strings_are_guarded_without_changing_raw_json(preview, symbol):
    preview["rows"][0].update(asset=symbol, provider_id=symbol, reason=symbol, price_eur="-0.125")
    files = unpack(preview)
    row = csv_rows(files, 2024)[0]
    for key in ("asset", "provider_id", "reason"):
        assert row[key] == "'" + symbol
        assert json.loads(files["report.json"])["preview"]["rows"][0][key] == symbol
    assert row["price_eur"] == "-0.125"


@pytest.mark.parametrize("price", ["=1+2", "-1+2", "+HYPERLINK(1)", "@evil"])
def test_non_numeric_price_strings_are_also_guarded(preview, price):
    preview["rows"][0]["price_eur"] = price
    assert csv_rows(unpack(preview), 2024)[0]["price_eur"] == "'" + price


def test_csv_quotes_commas_quotes_pipes_and_newlines_roundtrip(preview):
    symbol = 'raw,"quoted"|symbol\r\nsecond line'
    preview["rows"][0]["asset"] = symbol
    assert csv_rows(unpack(preview), 2024)[0]["asset"] == symbol


def test_additional_csv_headers_are_also_formula_safe(preview):
    preview["rows"][0]["=UNTRUSTED"] = "@value"
    row = csv_rows(unpack(preview), 2024)[0]
    assert row["'=UNTRUSTED"] == "'@value"
    assert report_json(preview)["preview"]["rows"][0]["=UNTRUSTED"] == "@value"


@pytest.mark.parametrize("sha", ["a" * 63, "a" * 65, "g" * 64, "https://example.invalid/" + "a" * 64,
                                 "../" + "a" * 61, "a" * 64 + "\n", None])
@pytest.mark.parametrize("location", ["evidence", "rows"])
def test_invalid_evidence_ids_rejected_before_any_loader_call(preview, sha, location):
    preview["evidence"] = [{"sha256": "a" * 64}]
    if location == "evidence":
        preview["evidence"].append({"sha256": sha})
    else:
        preview["rows"][0]["evidence_sha256"] = [sha]
    with pytest.raises(ValueError, match="historical_price_report_evidence_invalid"):
        unpack(preview)


def test_valid_hash_with_changed_original_is_rejected(preview):
    preview["evidence"] = [{"sha256": hashlib.sha256(b"original").hexdigest()}]
    with pytest.raises(ValueError, match="historical_price_report_evidence_mismatch"):
        report_zip(preview, lambda sha: b"changed")


@pytest.mark.parametrize("refs", ["", "https://example.invalid", 123, {"a" * 64: True}])
def test_invalid_reference_shapes_rejected_in_every_format(preview, refs):
    preview["rows"][0]["evidence_sha256"] = refs
    for export in (report_json, report_markdown, unpack):
        with pytest.raises(ValueError, match="historical_price_report_evidence_invalid"):
            export(preview)


def test_row_only_evidence_and_uppercase_hashes_are_validated(preview):
    body = b"original bytes"
    sha = hashlib.sha256(body).hexdigest()
    preview["rows"][0]["evidence_sha256"] = [sha.upper()]
    assert unpack(preview, {sha: body}.__getitem__)[f"evidence/{sha}.json"] == body


@pytest.mark.parametrize("body", ["text", {"json": "object"}, bytearray(b"bytes"), None])
def test_evidence_loader_must_provide_original_bytes(preview, body):
    preview["evidence"] = [{"sha256": "a" * 64}]
    with pytest.raises(ValueError, match="historical_price_report_evidence_body_invalid"):
        report_zip(preview, lambda sha: body)


def test_missing_deltas_are_not_fabricated_and_empty_deltas_are_exported(preview):
    preview.pop("tax_line_deltas")
    assert "tax_line_deltas.json" not in unpack(preview)
    preview["tax_line_deltas"] = []
    assert json.loads(unpack(preview)["tax_line_deltas.json"]) == []


def test_no_mutation_filesystem_writes_or_network_calls(preview, tmp_path, monkeypatch):
    before = copy.deepcopy(preview)

    def forbidden(*args, **kwargs):
        pytest.fail("Export darf keine Live-Verbindung oeffnen")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.chdir(tmp_path)
    report_json(preview)
    report_markdown(preview)
    unpack(preview)
    assert preview == before
    assert list(tmp_path.iterdir()) == []


def test_production_limit_is_64_mib():
    assert reports.MAX_UNCOMPRESSED_BYTES == 64 * 1024 * 1024


def test_total_size_limit_is_inclusive(preview, monkeypatch):
    normal = unpack(preview)
    monkeypatch.setattr(reports, "MAX_UNCOMPRESSED_BYTES", sum(map(len, normal.values())))
    assert unpack(preview) == normal


def test_dictionary_insertion_order_does_not_change_zip(preview):
    reordered = dict(reversed(list(preview.items())))
    reordered["rows"] = [dict(reversed(list(row.items()))) for row in preview["rows"]]
    assert report_zip(preview, lambda sha: b"") == report_zip(reordered, lambda sha: b"")


def test_year_range_endpoints_are_supported(preview):
    preview["year_summary"] = [{"year": 2009}, {"year": 2100}]
    preview["rows"][0]["years"] = [2009, "2100"]
    files = unpack(preview)
    assert len(csv_rows(files, 2009)) == len(csv_rows(files, 2100)) == 1


@pytest.mark.parametrize("kind", ["json", "markdown", "csv", "evidence", "manifest", "total"])
def test_size_limit_includes_all_uncompressed_files_before_zip_creation(preview, monkeypatch, kind):
    normal = unpack(preview)
    json_size = len(normal["report.json"])
    md_size = len(normal["report.md"])
    csv_size = len(normal["2024/preise.csv"])
    delta_size = len(normal["tax_line_deltas.json"])
    data_size = json_size + md_size + csv_size + delta_size
    limits = {"json": 1, "markdown": json_size + 1, "csv": json_size + md_size + 1,
              "manifest": data_size, "total": sum(map(len, normal.values())) - 1}
    body = b"x" * 100_000
    if kind == "evidence":
        preview["evidence"] = [{"sha256": hashlib.sha256(body).hexdigest()}]
        limit = data_size + 10_000
    else:
        limit = limits[kind]
    monkeypatch.setattr(reports, "MAX_UNCOMPRESSED_BYTES", limit)

    def no_zip(*args, **kwargs):
        pytest.fail("Groessenpruefung muss vor ZIP-Erzeugung fehlschlagen")

    monkeypatch.setattr(reports.zipfile, "ZipFile", no_zip)
    with pytest.raises(ValueError, match="^historical_price_report_too_large$"):
        report_zip(preview, lambda sha: body)
