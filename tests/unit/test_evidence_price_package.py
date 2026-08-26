import importlib.util
import json
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/import_evidence_price_package_v2.py"
SPEC = importlib.util.spec_from_file_location("import_evidence_price_package_v2", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _package(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "confidence": "0.95",
                "source_prefix": "provider:fx",
                "points": [["SOL", "2025-01-01", "100.25"]],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_price_package_loads_exact_decimal_and_source(tmp_path):
    points = module.load_package(_package(tmp_path))

    assert len(points) == 1
    assert str(points[0].price_eur) == "100.25"
    assert points[0].source == "provider:fx:2025-01-01"
    assert points[0].priced_at.isoformat() == "2025-01-01T00:00:00+00:00"


def test_price_package_classifies_exact_existing_and_conflict(tmp_path):
    store = DuckDbStore(tmp_path / "db.duckdb")
    points = module.load_package(_package(tmp_path))
    missing, matched, conflicts = module.classify_existing(store, points)
    assert len(missing) == 1 and not matched and not conflicts

    store.add_price_points(points)
    missing, matched, conflicts = module.classify_existing(store, points)
    assert not missing and len(matched) == 1 and not conflicts

    points[0].price_eur = points[0].price_eur + 1
    missing, matched, conflicts = module.classify_existing(store, points)
    assert not missing and not matched and len(conflicts) == 1
