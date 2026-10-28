from datetime import datetime
from decimal import Decimal

import pytest

from steuerreport_v2.contracts.tax import TaxLine
from steuerreport_v2.domain.swap_valuation_parallel import _Totals
from steuerreport_v2.domain.tax_time import PRIVATE_HOLDING_POLICY_VERSION


def test_private_holding_policy_version_is_available_for_artifact_binding():
    assert PRIVATE_HOLDING_POLICY_VERSION == "de_private_calendar_holding_berlin_v1"


@pytest.mark.parametrize("disposed,holding_days,within", [
    ("2024-03-01T22:59:59Z", 366, True),
    ("2024-03-01T23:00:00Z", 365, False),
])
def test_current_swap_totals_use_berlin_calendar_not_holding_days(disposed, holding_days, within):
    line = TaxLine(
        tax_line_id="fixture-line", lot_id="fixture-lot", source_event_id="fixture-sale",
        asset="HNT", quantity=Decimal("1"),
        acquired_at=datetime.fromisoformat("2023-03-01T12:00:00Z"),
        disposed_at=datetime.fromisoformat(disposed), holding_days=holding_days,
        acquisition_cost_eur=Decimal("100"), disposal_proceeds_eur=Decimal("150"),
        gain_loss_eur=Decimal("50"),
    )
    totals = _Totals()
    totals.add(line)
    assert totals.gain_loss_eur == Decimal("50")
    assert totals.short_holding_gain_loss_eur == (Decimal("50") if within else Decimal("0"))
    assert totals.long_holding_gain_loss_eur == (Decimal("0") if within else Decimal("50"))
    assert totals.acquisition_cost_eur == Decimal("100")
    assert totals.proceeds_eur == Decimal("150")
    assert totals.tax_lines_count == 1
