from datetime import date, datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import portfolio as portfolio_module
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


class FrozenDatetimeMeta(type):
    def __instancecheck__(cls, instance):
        return isinstance(instance, datetime)


class FrozenDatetime(datetime, metaclass=FrozenDatetimeMeta):
    @classmethod
    def now(cls, tz=None):
        instant = cls(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        return instant if tz is None else instant.astimezone(tz)


def test_default_history_ends_today_even_when_latest_ledger_entry_is_older(tmp_path, monkeypatch):
    service = PortfolioService(DuckDbStore(tmp_path / "synthetic.duckdb"))
    monkeypatch.setattr(portfolio_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(service, "_ledger_date_bounds", lambda: (date(2026, 10, 1), date(2026, 10, 16)))

    result = service.value_history(interval="day", max_points=60)

    assert result.from_date == "2026-10-01"
    assert result.to_date == "2026-10-30"
    assert result.points[-1].date == "2026-10-30"
    assert "selben UTC-Kalendertag" in result.methodology
    assert "Teilwert" in result.methodology


def test_future_only_ledger_does_not_push_default_history_into_future(tmp_path, monkeypatch):
    service = PortfolioService(DuckDbStore(tmp_path / "synthetic.duckdb"))
    monkeypatch.setattr(portfolio_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(service, "_ledger_date_bounds", lambda: (date(2027, 1, 1), date(2027, 1, 1)))

    result = service.value_history(interval="day")

    assert result.from_date == result.to_date == "2026-10-30"
    assert [point.date for point in result.points] == ["2026-10-30"]


def test_explicit_historical_end_date_remains_unchanged(tmp_path, monkeypatch):
    service = PortfolioService(DuckDbStore(tmp_path / "synthetic.duckdb"))
    monkeypatch.setattr(portfolio_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(service, "_ledger_date_bounds", lambda: (date(2024, 1, 1), date(2026, 10, 16)))

    result = service.value_history(from_date="2025-01-01", to_date="2025-01-31", interval="day")

    assert result.from_date == "2025-01-01"
    assert result.to_date == "2025-01-31"
    assert result.points[-1].date == "2025-01-31"


def test_default_today_excludes_later_same_day_events_and_prices(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="synthetic.csv",
        content=(
            "time,coin,change,type,account\n"
            "2026-10-30T09:00:00Z,EUR,10,deposit,test-account\n"
            "2026-10-30T09:00:00Z,BTC,1,deposit,test-account\n"
            "2026-10-30T18:00:00Z,EUR,20,deposit,test-account\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    for hour, price in [(11, "100"), (15, "1000")]:
        store.add_price_point(PricePointCreate(
            asset="BTC", price_eur=Decimal(price),
            priced_at=datetime(2026, 10, 30, hour, tzinfo=timezone.utc),
            source="manual-test",
        ))
    monkeypatch.setattr(portfolio_module, "datetime", FrozenDatetime)

    result = PortfolioService(store).value_history(interval="day")

    assert result.points[-1].as_of == datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    assert result.points[-1].total_value_eur == Decimal("110")
    assert result.points[-1].missing_price_assets == []
