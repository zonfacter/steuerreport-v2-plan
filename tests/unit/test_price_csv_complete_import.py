from steuerreport_v2.domain.price_csv_importer import PriceCsvImporter


def test_preview_limit_does_not_truncate_a_confirmed_price_import():
    content = "asset,price_eur,priced_at,source\n" + "\n".join(
        f"SYNTHETIC_{index},1.123456789123456789,2025-01-01T00:00:00Z,synthetic-csv"
        for index in range(201)
    )
    preview, prices = PriceCsvImporter().to_price_points(content)
    assert preview.can_import and preview.row_count == preview.valid_rows == 201
    assert len(preview.rows) == 50
    assert len(prices) == 201
    assert prices[-1].asset == "SYNTHETIC_200"
    assert str(prices[-1].price_eur) == "1.123456789123456789"


def test_invalid_row_after_preview_limit_rejects_the_entire_import():
    content = "asset,price_eur,priced_at\n" + "SOL,1,2025-01-01T00:00:00Z\n" * 50 + "SOL,-1,2025-01-02T00:00:00Z"
    preview, prices = PriceCsvImporter().to_price_points(content)
    assert not preview.can_import and preview.invalid_rows == 1
    assert prices == []
