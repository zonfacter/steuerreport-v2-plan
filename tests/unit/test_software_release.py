import importlib.util
from pathlib import Path
import zipfile


def _builder():
    path = Path(__file__).resolve().parents[2] / "scripts/build_software_release_v2.py"
    spec = importlib.util.spec_from_file_location("software_release_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_excludes_case_work_runtime_and_originals():
    builder = _builder()
    for name in (
        "src/steuerreport_v2/domain/family_law_disclosure.py",
        "tests/unit/test_legal_email_archive.py",
        "scripts/build_lawyer_crypto_disclosure_package_v2.py",
        "docs/729_CONFIDENTIAL_FAMILY_LAW_DISCLOSURE_PACKAGE_2026-09-24.md",
        "data/steuerreport.duckdb", "frontend/node_modules/a.js",
        "frontend/dist/index.html", ".env", "src/steuerreport_v2.egg-info/PKG-INFO",
        "tests/evidence.pdf", "tests/export.csv", "../secret.py",
        "frontend/public/import-vorlagen/private.csv",
        "frontend/public/import-vorlagen/private.xlsx",
        "configs/source_registry.json", "configs/solana_v1_ownership_scope.json",
    ):
        assert not builder.software_path(name), name
    for name in (
        "src/steuerreport_v2/domain/tax_filing_audit.py",
        "src/steuerreport_v2/domain/mobile_documents.py",
        "tests/unit/test_tax_filing_audit.py", "frontend/package-lock.json",
        "docs/openapi/steuerreport-v2-openapi.json", ".env.example",
        "configs/source_registry.example.json",
        "configs/binance_small_assets_price_evidence_20260710.json",
        "frontend/public/benutzerleitfaden.pdf", "frontend/public/import-vorlage.csv",
        "frontend/public/importformate.pdf", "docs/IMPORTFORMATE.md",
        "frontend/public/ki-einsatzleitfaden.pdf", "docs/KI_EINSATZLEITFADEN.md",
        "frontend/public/import-vorlagen/import-vorlagen.xlsx",
        "frontend/public/import-vorlagen/bitget.csv",
    ):
        assert builder.software_path(name), name


def test_release_zip_is_reproducible_and_preserves_bytes(tmp_path):
    builder = _builder()
    source = tmp_path / "source.py"
    source.write_bytes(b"print('software')\n")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    builder.write_zip(first, [("src/source.py", source)])
    builder.write_zip(second, [("src/source.py", source)])
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.testzip() is None
        assert archive.read("src/source.py") == source.read_bytes()


def test_privacy_guard_rejects_new_hardcoded_wallet_defaults(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/check_private_data_v2.py"
    spec = importlib.util.spec_from_file_location("private_data_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    package = tmp_path / "src/steuerreport_v2"
    package.mkdir(parents=True)
    code = package / "example.py"
    code.write_text('PRIMARY_SOLANA_WALLET = "' + "1" * 32 + '"\n')
    assert module.violations(tmp_path) == ["src/steuerreport_v2/example.py:1:hardcoded_account"]
    code.write_text('PRIMARY_SOLANA_WALLET = private_value("primary_solana_wallet")\n')
    assert module.violations(tmp_path) == []
