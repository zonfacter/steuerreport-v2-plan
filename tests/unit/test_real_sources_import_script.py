from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "import_real_sources_v2.py"
SPEC = importlib.util.spec_from_file_location("import_real_sources_v2", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

curated_candidates = MODULE.curated_candidates


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder\n", encoding="utf-8")


def test_curated_real_sources_use_binance_export_2021_without_c2c_or_legacy(tmp_path) -> None:
    active_root = tmp_path / "Binance" / "export 2021"
    _touch(active_root / "Binance-Deposit-History-202605061836(UTC+2)_db80f010.xlsx")
    _touch(active_root / "Binance-Fiat-Buy-History-202605061831(UTC+2)_c87830e5.xlsx")
    _touch(active_root / "Binance-Fiat-Deposit-History-202605061832(UTC+2)_9311aa32.xlsx")
    _touch(active_root / "Binance-Fiat-Withdraw-History-202605061833(UTC+2)_2416f4a2.xlsx")
    _touch(active_root / "Binance-Transaction-History-202605061835(UTC+2)_344d77e2.xlsx")
    _touch(active_root / "Binance-C2C-Order-History-202605061836(UTC+2)_2ff01768.xlsx")
    _touch(tmp_path / "Binance" / "BINANCE - Export Trade History-2022-04-04 10_41_01.xlsx")
    _touch(tmp_path / "Binance-Deposit-History-202604130513(UTC+2)_5875b5ca.xlsx")
    _touch(tmp_path / "legacy_daten" / "Cointracking" / "Export Trade History-2022-04-04 10_41_01.xlsx")
    _touch(tmp_path / "legacy_daten" / "Steuer-2021" / "Binance-export" / "BINANCE - TRADING - Export - PIVOT.xlsx")

    candidates = curated_candidates(tmp_path)
    binance_paths = [
        candidate.path.relative_to(tmp_path).as_posix()
        for candidate in candidates
        if candidate.source == "binance"
    ]

    assert binance_paths == [
        "Binance/export 2021/Binance-Deposit-History-202605061836(UTC+2)_db80f010.xlsx",
        "Binance/export 2021/Binance-Fiat-Buy-History-202605061831(UTC+2)_c87830e5.xlsx",
        "Binance/export 2021/Binance-Fiat-Deposit-History-202605061832(UTC+2)_9311aa32.xlsx",
        "Binance/export 2021/Binance-Fiat-Withdraw-History-202605061833(UTC+2)_2416f4a2.xlsx",
        "Binance/export 2021/Binance-Transaction-History-202605061835(UTC+2)_344d77e2.xlsx",
    ]


def test_curated_real_sources_use_v1_canonical_pionex_root_files(tmp_path) -> None:
    _touch(tmp_path / "pionex" / "deposit-withdraw.csv")
    _touch(tmp_path / "pionex" / "dust-collector.csv")
    _touch(tmp_path / "pionex" / "raw-trading-details.csv")
    _touch(tmp_path / "pionex" / "trading.csv")
    _touch(tmp_path / "pionex" / "for-cointracker.csv")
    _touch(tmp_path / "pionex" / "for-cointracking.csv")
    _touch(tmp_path / "pionex_txn_2021-12-31_2022-12-30_gen_2026-05-05" / "deposit-withdraw.csv")
    _touch(tmp_path / "pionex_txn_2021-12-31_2022-12-30_gen_2026-05-05" / "raw-trading-details.csv")

    candidates = curated_candidates(tmp_path)
    pionex_paths = [candidate.path.relative_to(tmp_path).as_posix() for candidate in candidates]

    assert pionex_paths == [
        "pionex/deposit-withdraw.csv",
        "pionex/dust-collector.csv",
        "pionex/raw-trading-details.csv",
    ]


def test_curated_real_sources_use_bitget_financial_ledgers_not_reference_exports(tmp_path) -> None:
    bitget_root = tmp_path / "bitget" / "support"
    _touch(bitget_root / "Deposit-Withdrawal History.csv")
    _touch(bitget_root / "Spot Financial Record.csv")
    _touch(bitget_root / "Spot Trading History.csv")
    _touch(bitget_root / "Futures Financial Record.csv")
    _touch(bitget_root / "Futures Trading History.csv")
    _touch(bitget_root / "Strategy.csv")

    candidates = curated_candidates(tmp_path)
    bitget_paths = [
        candidate.path.relative_to(tmp_path).as_posix()
        for candidate in candidates
        if candidate.source == "bitget"
    ]

    assert bitget_paths == [
        "bitget/support/Spot Financial Record.csv",
        "bitget/support/Futures Financial Record.csv",
    ]


def test_curated_real_sources_use_helium_raw_and_transfer_proof_only(tmp_path) -> None:
    _touch(
        tmp_path
        / "Helium"
        / "helium-1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV-all-raw_12122024.csv"
    )
    heliumtracker_root = tmp_path / "legacy_daten" / "Heliumtracker" / "advance"
    _touch(heliumtracker_root / "Heliumtracker 2021.xlsx")
    _touch(heliumtracker_root / "heliumtracker-report-advanced-2021-12.csv")
    _touch(heliumtracker_root / "daily_hotspot_rewards_2022-03-21T17_52_18.702901-04_00.xlsx")
    _touch(
        tmp_path
        / "legacy_daten"
        / "Export fuer Steuer"
        / "raw"
        / "helium-1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV-2021-raw.csv"
    )
    _touch(
        tmp_path
        / "legacy_daten"
        / "Export fuer Steuer"
        / "helium-1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV-2021-2023 cointracking.xlsx"
    )

    candidates = curated_candidates(tmp_path)
    helium_paths = [
        candidate.path.relative_to(tmp_path).as_posix()
        for candidate in candidates
        if candidate.source == "helium"
    ]

    assert helium_paths == [
        "Helium/helium-1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV-all-raw_12122024.csv",
        "legacy_daten/Heliumtracker/advance/Heliumtracker 2021.xlsx",
    ]


def test_curated_real_sources_exclude_blockpit_solana_and_jupiter_reference_files(tmp_path) -> None:
    _touch(tmp_path / "2025 Transaktionen Blockpit.csv")
    _touch(tmp_path / "blockpit" / "blockpit 09052026 Transactions.csv")
    _touch(tmp_path / "Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv")
    _touch(tmp_path / "jup" / "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY.csv")
    _touch(tmp_path / "legacy_daten" / "Steuer-2022" / "Blockpit - Manual Import Template.xlsx")
    _touch(tmp_path / "legacy_daten" / "Steuer-2022" / "export-solscan.csv")

    candidates = curated_candidates(tmp_path)
    candidate_paths = {candidate.path.relative_to(tmp_path).as_posix() for candidate in candidates}

    assert not candidate_paths & {
        "2025 Transaktionen Blockpit.csv",
        "blockpit/blockpit 09052026 Transactions.csv",
        "Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv",
        "jup/G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY.csv",
        "legacy_daten/Steuer-2022/Blockpit - Manual Import Template.xlsx",
        "legacy_daten/Steuer-2022/export-solscan.csv",
    }


def test_curated_real_sources_exclude_wiso_and_tax_report_reference_files(tmp_path) -> None:
    _touch(tmp_path / "wiso" / "WISO Steuer CSV 2021 - ref.csv")
    _touch(tmp_path / "wiso" / "WISO Steuer CSV 2022 - ref.csv")
    _touch(tmp_path / "legacy_daten" / "Steuer-2022" / "CoinTrackingSteuerExport.csv")
    _touch(tmp_path / "legacy_daten" / "Steuer-2022" / "Berechnung Mining Wert.csv")
    _touch(tmp_path / "legacy_daten" / "Steuer-2022" / "Berechnung Mining Wert.xlsx")
    _touch(tmp_path / "legacy_daten" / "Steuer-2021" / "CoinTracking - Missing Transactions.xlsx")
    _touch(tmp_path / "legacy_daten" / "Steuer-2021" / "CoinTracking - Auszug für die Steuererklärung - 2022.xlsx")
    _touch(
        tmp_path
        / "legacy_daten"
        / "Steuer-2021"
        / "CoinTracking"
        / "CoinTracking - Kapitalertragsbericht.xlsx"
    )
    _touch(
        tmp_path
        / "legacy_daten"
        / "Steuer-2021"
        / "CoinTracking"
        / "CoinTracking - Detaillierter Bericht.xlsx"
    )

    candidates = curated_candidates(tmp_path)
    candidate_paths = {candidate.path.relative_to(tmp_path).as_posix() for candidate in candidates}

    assert not candidate_paths & {
        "wiso/WISO Steuer CSV 2021 - ref.csv",
        "wiso/WISO Steuer CSV 2022 - ref.csv",
        "legacy_daten/Steuer-2022/CoinTrackingSteuerExport.csv",
        "legacy_daten/Steuer-2022/Berechnung Mining Wert.csv",
        "legacy_daten/Steuer-2022/Berechnung Mining Wert.xlsx",
        "legacy_daten/Steuer-2021/CoinTracking - Missing Transactions.xlsx",
        "legacy_daten/Steuer-2021/CoinTracking - Auszug für die Steuererklärung - 2022.xlsx",
        "legacy_daten/Steuer-2021/CoinTracking/CoinTracking - Kapitalertragsbericht.xlsx",
        "legacy_daten/Steuer-2021/CoinTracking/CoinTracking - Detaillierter Bericht.xlsx",
    }
