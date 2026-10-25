from __future__ import annotations

from steuerreport_v2.private_settings import private_template

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from steuerreport_v2.contracts.import_policy import ImportPolicyAudit, ImportPolicyDecision
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.import_coverage import SUPPORTED_SUFFIXES


@dataclass(frozen=True)
class _PolicyRule:
    pattern: str
    category: str
    can_be_realimport: bool
    action: str
    reason: str


RULES: tuple[_PolicyRule, ...] = (
    _PolicyRule("Binance/export 2021/Binance-C2C-Order-History-*.xlsx", "parser_needed", False, "exclude", "C2C braucht eigenen Fiat-/Crypto-Parser."),
    _PolicyRule("Binance/export 2021/Binance-*.xlsx", "curated_primary", True, "curated_realimport", "Aktiver zusammengehoeriger Binance-Exportstand."),
    _PolicyRule("Binance/*.xlsx", "reference_only", False, "exclude", "Aeltere Binance-Root-Dateien bleiben Referenz oder Duplikat."),
    _PolicyRule("Binance-Deposit-History-*.xlsx", "reference_only", False, "exclude", "Aeltere Binance-Deposit-Snapshots bleiben Referenz."),
    _PolicyRule("legacy_daten/Cointracking/Export *.xlsx", "reference_only", False, "exclude", "Legacy-/CoinTracking-Kopien sind keine aktive Primaerquelle."),
    _PolicyRule("legacy_daten/Cointracking/deposit_history*.xlsx", "reference_only", False, "exclude", "Legacy-Deposit-Kopien sind keine aktive Primaerquelle."),
    _PolicyRule("legacy_daten/Steuer-2021/Binance exporte/*.xlsx", "reference_only", False, "exclude", "Legacy-Binance-Kopien sind keine aktive Primaerquelle."),
    _PolicyRule("legacy_daten/Steuer-2021/Binance-export/*.xlsx", "reference_only", False, "review_only", "Account-Statement-/Pivot-Dateien nur fuer dedizierte Reviewpfade."),
    _PolicyRule("pionex/deposit-withdraw.csv", "curated_primary", True, "curated_realimport", "Kanonische Pionex-Transferquelle."),
    _PolicyRule("pionex/dust-collector.csv", "curated_primary", True, "curated_realimport", "Kanonische Pionex-Dust-Quelle."),
    _PolicyRule("pionex/raw-trading-details.csv", "curated_primary", True, "curated_realimport", "Kanonische Pionex-Handelsdetailquelle."),
    _PolicyRule("pionex/*.csv", "reference_only", False, "exclude", "Pionex-Export ist abgeleitet, leer oder Referenz."),
    _PolicyRule("pionex_txn_*/*.csv", "reference_only", False, "exclude", "Generierte Pionex-Zwischenordner sind nicht kanonisch."),
    _PolicyRule("bitget/support/Spot Financial Record.csv", "curated_primary", True, "curated_realimport", "Aktiver Bitget-Spot-Ledger."),
    _PolicyRule("bitget/support/Futures Financial Record.csv", "curated_primary", True, "curated_realimport", "Aktiver Bitget-Futures-Cashflow-Ledger."),
    _PolicyRule("bitget/support/*.csv", "reference_only", False, "exclude", "Bitget-Export ist Beleg, Orderliste oder Strategiezusammenfassung."),
    _PolicyRule("Helium/helium-*-all-raw_*.csv", "curated_primary", True, "curated_realimport", "Aktiver konsolidierter Helium-Raw-Export."),
    _PolicyRule("legacy_daten/Heliumtracker/advance/Heliumtracker 2021.xlsx", "curated_primary", True, "curated_realimport", "Aktive enge Heliumtracker-Transferliste."),
    _PolicyRule("legacy_daten/Heliumtracker/advance/~$*.xlsx", "reference_only", False, "exclude", "Excel-Lock-/Tempdatei, kein Importbeleg."),
    _PolicyRule("legacy_daten/Export fuer Steuer/raw/helium-*.csv", "reference_only", False, "exclude", "Aeltere Helium-Jahres-Raw-Exports ueberlappen mit aktiver Quelle."),
    _PolicyRule("legacy_daten/Export fuer Steuer/Cointracking/helium-*.csv", "reference_only", False, "exclude", "Helium-CoinTracking-Exports sind Beleg-/Vergleichsschicht."),
    _PolicyRule("legacy_daten/Export fuer Steuer/cointracking-*.csv", "reference_only", False, "parity_reference", "CoinTracking-Export ist Altreport-Plausibilitaetsreferenz."),
    _PolicyRule("legacy_daten/Export fuer Steuer/helium-*.xls*", "reference_only", False, "exclude", "Helium-CoinTracking-Workbook ist Beleg-/Vergleichsschicht."),
    _PolicyRule("legacy_daten/Export fuer Steuer/helium-*.csv", "reference_only", False, "exclude", "Helium-CoinTracking-CSV ist Beleg-/Vergleichsschicht."),
    _PolicyRule("legacy_daten/Heliumtracker/advance/heliumtracker-report-advanced-*.csv", "reference_only", False, "exclude", "Heliumtracker-Monatsreports sind Beleg-/Kontrollquelle."),
    _PolicyRule("legacy_daten/Heliumtracker/advance/daily_hotspot_rewards_*.xlsx", "reference_only", False, "exclude", "Daily-Hotspot-Rewards sind Beleg-/Kontrollquelle."),
    _PolicyRule("legacy_daten/Heliumtracker/advance/Binance Export History Daten 2021 2022.xlsx", "reference_only", False, "exclude", "Heliumtracker-Binance-Historie ist Belegquelle."),
    _PolicyRule("legacy_daten/Heliumtracker/Auswertung 2022-2024.xlsx", "reference_only", False, "exclude", "Heliumtracker-Auswertung ist Beleg-/Analysequelle."),
    _PolicyRule("blockpit/blockpit 09052026 Transactions.csv", "staging_required", False, "blockpit_staging_only", "Blockpit/Solana darf nur ueber Staging-Preflight laufen."),
    _PolicyRule("2025 Transaktionen Blockpit.csv", "staging_required", False, "future_year_review", "Blockpit-2025 braucht eigene Jahres-/Quellenentscheidung."),
    _PolicyRule("MoonPay_trade-history.csv", "reference_only", False, "evidence_only", "MoonPay-Trade-History wird ausschliesslich ueber den spezialisierten Anschaffungsnachweis verarbeitet."),
    _PolicyRule("Sparkasse/*.CSV", "reference_only", False, "evidence_only", "Sparkassen-CAMT-Aggregate sind ausschliesslich read-only Fiat-/MoonPay-Belege und keine Krypto-Importquelle."),
    _PolicyRule("legacy_daten/Steuer-2022/Blockpit - Manual Import Template.xlsx", "reference_only", False, "exclude", "Blockpit-Template ist Arbeitsbeleg."),
    _PolicyRule(private_template('Wallet.{primary_solana_wallet}-month.csv'), "parser_needed", False, "exclude", "Wallet-Monatsaggregat braucht eigenen Parser."),
    _PolicyRule("jup/*.csv", "parser_needed", False, "exclude", "JUP-/Perps-Datei braucht Derivate-/Perps-Parser."),
    _PolicyRule("legacy_daten/Steuer-2022/export-solscan.csv", "parser_needed", False, "exclude", "Solscan braucht Mint-Mapping und Wallet-Richtungslogik."),
    _PolicyRule("wiso/*.csv", "reference_only", False, "parity_reference", "WISO ist Altreport-Plausibilitaetsreferenz, keine Bewegung."),
    _PolicyRule("legacy_daten/Steuer-2022/CoinTrackingSteuerExport.csv", "reference_only", False, "parity_reference", "CoinTracking-Steuerexport ist Altreport-Referenz."),
    _PolicyRule("legacy_daten/Steuer-2022/Berechnung Mining Wert.*", "reference_only", False, "evidence_only", "Manuelle Mining-Berechnung ist Beleg-/Analysequelle."),
    _PolicyRule("legacy_daten/Steuer-2021/CoinTracking*.xlsx", "reference_only", False, "parity_reference", "CoinTracking-Steuerreport ist Altreport-Referenz."),
    _PolicyRule("legacy_daten/Steuer-2021/CoinTracking/*.xlsx", "reference_only", False, "parity_reference", "CoinTracking-Report ist Altreport-Referenz."),
    _PolicyRule("legacy_daten/Cointracking/20220404-*.CSV", "reference_only", False, "exclude", "CoinTracking-Umsatzexport ist Legacy-Referenz."),
    _PolicyRule("legacy_daten/Cointracking/CoinTracking - *.xlsx", "reference_only", False, "parity_reference", "CoinTracking-Report ist Altreport-Referenz."),
)


class ImportPolicyService:
    def __init__(self, store: DuckDbStore | None = None) -> None:
        self.store = store

    def audit(self, root_path: str) -> ImportPolicyAudit:
        root = Path(root_path)
        imported_by_filename, imported_by_path = self._imported_indexes()
        files = [
            path
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ]
        decisions = [
            self.classify(root, path, imported_by_filename, imported_by_path) for path in files
        ]
        return ImportPolicyAudit(
            root_path=str(root),
            files_total=len(files),
            classified=sum(1 for item in decisions if item.category != "unclassified"),
            unclassified=sum(1 for item in decisions if item.category == "unclassified"),
            curated_primary=sum(1 for item in decisions if item.category == "curated_primary"),
            staging_required=sum(1 for item in decisions if item.category == "staging_required"),
            parser_needed=sum(1 for item in decisions if item.category == "parser_needed"),
            reference_only=sum(1 for item in decisions if item.category == "reference_only"),
            imported_files=sum(1 for item in decisions if item.imported),
            unused_curated_primary=sum(
                1 for item in decisions if item.category == "curated_primary" and not item.imported
            ),
            unused_staging_required=sum(
                1 for item in decisions if item.category == "staging_required" and not item.imported
            ),
            unused_parser_needed=sum(
                1 for item in decisions if item.category == "parser_needed" and not item.imported
            ),
            unused_reference_only=sum(
                1 for item in decisions if item.category == "reference_only" and not item.imported
            ),
            decisions=decisions,
        )

    def classify(
        self,
        root: Path,
        path: Path,
        imported_by_filename: dict[str, list[tuple[str, str]]] | None = None,
        imported_by_path: dict[str, list[tuple[str, str]]] | None = None,
    ) -> ImportPolicyDecision:
        relative_path = path.relative_to(root).as_posix()
        for rule in RULES:
            if fnmatch(relative_path, rule.pattern):
                imported_matches = self._import_matches(
                    path,
                    relative_path,
                    rule.category,
                    imported_by_filename or {},
                    imported_by_path or {},
                )
                return ImportPolicyDecision(
                    file_path=str(path),
                    relative_path=relative_path,
                    category=rule.category,
                    can_be_realimport=rule.can_be_realimport,
                    action=rule.action,
                    reason=rule.reason,
                    imported=bool(imported_matches),
                    imported_batch_ids=[batch_id for batch_id, _source in imported_matches],
                    imported_sources=sorted({source for _batch_id, source in imported_matches}),
                )
        imported_matches = self._import_matches(
            path,
            relative_path,
            "unclassified",
            imported_by_filename or {},
            imported_by_path or {},
        )
        return ImportPolicyDecision(
            file_path=str(path),
            relative_path=relative_path,
            category="unclassified",
            can_be_realimport=False,
            action="review_required",
            reason="Keine Import-Policy-Regel vorhanden.",
            imported=bool(imported_matches),
            imported_batch_ids=[batch_id for batch_id, _source in imported_matches],
            imported_sources=sorted({source for _batch_id, source in imported_matches}),
        )

    def _imported_indexes(
        self,
    ) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[tuple[str, str]]]]:
        if self.store is None:
            return {}, {}
        by_filename: dict[str, list[tuple[str, str]]] = {}
        by_path: dict[str, list[tuple[str, str]]] = {}
        for batch in self.store.list_import_batches():
            if not batch.filename:
                continue
            match = (batch.batch_id, batch.source)
            normalized_path = Path(batch.filename).as_posix()
            by_path.setdefault(normalized_path, []).append(match)
            by_filename.setdefault(Path(batch.filename).name, []).append(match)
        return by_filename, by_path

    def _import_matches(
        self,
        path: Path,
        relative_path: str,
        category: str,
        imported_by_filename: dict[str, list[tuple[str, str]]],
        imported_by_path: dict[str, list[tuple[str, str]]],
    ) -> list[tuple[str, str]]:
        exact = imported_by_path.get(path.as_posix()) or imported_by_path.get(relative_path)
        if exact:
            return exact
        # Reference-only files often share generic names with active imports in
        # other folders. Without an exact path, basename matches would hide
        # unused reference files as "already imported".
        if category == "reference_only":
            return []
        return imported_by_filename.get(path.name, [])
