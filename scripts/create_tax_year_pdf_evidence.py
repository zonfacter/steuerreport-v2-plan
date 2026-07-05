from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YEAR = 2025


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument(
        "--zip",
        dest="package",
        default=None,
        help="Path to tax-year evidence ZIP. Defaults to artifacts/tax-years/tax-year-YEAR-evidence-package.zip.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory. Defaults to artifacts/tax-year-YEAR.",
    )
    args = parser.parse_args()

    year = args.year
    package_path = Path(args.package) if args.package else ROOT / "artifacts" / "tax-years" / f"tax-year-{year}-evidence-package.zip"
    out_dir = Path(args.out) if args.out else ROOT / "artifacts" / f"tax-year-{year}"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = EvidencePackage(package_path, year)
    created = [
        create_cover_pdf(data, out_dir / f"finanzamt_{year}_01_eintragungshilfe.pdf"),
        create_fifo_pdf(data, out_dir / f"finanzamt_{year}_02_fifo_verlustnachweis.pdf"),
        create_income_pdf(data, out_dir / f"finanzamt_{year}_03_rewards_mining_staking_nachweis.pdf"),
        create_index_pdf(data, out_dir / f"finanzamt_{year}_04_belegindex_methodik.pdf"),
    ]

    # Backward-compatible names used by the existing artifact folder.
    (out_dir / f"steuerjahr-{year}-kurzbericht.pdf").write_bytes(created[0].read_bytes())
    (out_dir / f"steuerjahr-{year}-transaktionsnachweis.pdf").write_bytes(created[2].read_bytes())

    zip_path = out_dir / f"finanzamt_{year}_pdf_belege.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in created:
            zf.write(path, path.name)
        zf.write(package_path, package_path.name)

    print(f"created {len(created)} pdfs")
    for path in created:
        print(path)
    print(zip_path)


class EvidencePackage:
    def __init__(self, package_path: Path, year: int) -> None:
        self.package_path = package_path
        self.year = year
        with zipfile.ZipFile(package_path) as zf:
            self.filing_summary = self._json(zf, f"02_Steuerliche_CSVs/tax-year-{year}-filing-summary.json")
            self.evidence = self._json(zf, f"02_Steuerliche_CSVs/tax-year-{year}-evidence.json")
            self.manifest = self._json(zf, "00_Manifest/year-evidence-manifest.json")
            self.tax_lines = self._csv(zf, f"02_Steuerliche_CSVs/tax-year-{year}-tax-lines.csv")
            self.income_guide = self._csv(zf, f"02_Steuerliche_CSVs/tax-year-{year}-tax-income-guide.csv")
            self.reward_events = self._csv(zf, f"01_Transaktionen/tax-year-{year}-reward-mining-staking-events.csv")
            self.checklist = self._csv(zf, f"02_Steuerliche_CSVs/tax-year-{year}-filing-checklist.csv")

    @staticmethod
    def _json(zf: zipfile.ZipFile, name: str) -> dict:
        return json.loads(zf.read(name).decode("utf-8"))

    @staticmethod
    def _csv(zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
        text = zf.read(name).decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))


def create_cover_pdf(data: EvidencePackage, path: Path) -> Path:
    summary = data.filing_summary
    story = base_story(data.year, "Eintragungshilfe und Kernergebnis")
    story += [
        p(summary["plain_language_summary"]),
        Spacer(1, 5 * mm),
        table(
            [
                ["Position", "Betrag"],
                ["Private Veraeusserungen / Anlage SO", eur(summary["taxable_private_disposals_eur"])],
                ["Veraeusserungserloese", eur(summary["taxable_disposal_proceeds_eur"])],
                ["FIFO-Anschaffungskosten", eur(summary["acquisition_cost_eur"])],
                ["Rewards / Mining / Staking einzutragen", eur(summary["rewards_mining_staking_income_eur"])],
                ["Steuerfrei nach Haltefrist, nur nachrichtlich", eur(summary["tax_free_private_disposals_eur"])],
                ["Derivate / Termingeschaefte", eur(summary["derivative_pnl_eur"])],
            ],
            [95 * mm, 55 * mm],
        ),
        Spacer(1, 6 * mm),
        h2("Checkliste fuer die Steuererklaerung"),
        small_table(
            [["Kategorie", "Label", "Betrag", "Aktion"]]
            + [
                [
                    row["Category"],
                    row["Label"],
                    row["Amount_EUR"],
                    row["Action"],
                ]
                for row in data.checklist
            ],
            [22 * mm, 45 * mm, 25 * mm, 95 * mm],
        ),
        Spacer(1, 5 * mm),
        p(
            "Hinweis: Diese PDF ist ein technischer Nachweis aus Steuerreport V2 und keine Steuerberatung. "
            "Formularzeilen koennen je ELSTER-/Software-Version abweichen."
        ),
    ]
    build_doc(path, story)
    return path


def create_fifo_pdf(data: EvidencePackage, path: Path) -> Path:
    summary = data.filing_summary
    taxable = [row for row in data.tax_lines if row["Steuerpflichtig"].strip().lower() == "ja"]
    by_asset: dict[str, dict[str, Decimal | int]] = defaultdict(lambda: defaultdict(Decimal))
    for row in taxable:
        asset = row["Asset"]
        by_asset[asset]["menge"] += dec(row["Menge"])
        by_asset[asset]["ak"] += dec(row["Anschaffungskosten_EUR"])
        by_asset[asset]["erloes"] += dec(row["Veraeusserungserloes_EUR"])
        by_asset[asset]["gv"] += dec(row["Gewinn_Verlust_EUR"])
        by_asset[asset]["zeilen"] = int(by_asset[asset].get("zeilen", 0)) + 1

    story = base_story(data.year, "FIFO-Verlustnachweis private Veraeusserungen")
    story += [
        p(
            f"Steuerpflichtiger FIFO-Saldo: {eur(summary['taxable_private_disposals_eur'])}. "
            f"Erloese: {eur(summary['taxable_disposal_proceeds_eur'])}; "
            f"Anschaffungskosten: {eur(summary['acquisition_cost_eur'])}."
        ),
        Spacer(1, 5 * mm),
        h2("Asset-Summen steuerpflichtige FIFO-Zeilen"),
        small_table(
            [["Asset", "Menge", "Erloes EUR", "AK EUR", "G/V EUR", "Zeilen"]]
            + [
                [
                    asset,
                    qty(values["menge"]),
                    eur(values["erloes"]),
                    eur(values["ak"]),
                    eur(values["gv"]),
                    str(values["zeilen"]),
                ]
                for asset, values in sorted(by_asset.items(), key=lambda item: item[1]["gv"])
            ],
            [22 * mm, 34 * mm, 29 * mm, 29 * mm, 29 * mm, 15 * mm],
        ),
        PageBreak(),
        h2("Einzel-FIFO-Zeilen"),
        p("Die folgenden Zeilen belegen Kaufdatum, Verkaufsdatum, Menge, Anschaffungskosten, Erloes, Gewinn/Verlust und Haltedauer."),
    ]
    rows = [["Kauf", "Verkauf", "Asset", "Menge", "AK EUR", "Erloes EUR", "G/V EUR", "Tage", "Steuer"]]
    for row in data.tax_lines:
        rows.append(
            [
                short_dt(row["Datum_Kauf"]),
                short_dt(row["Datum_Verkauf"]),
                row["Asset"],
                qty(row["Menge"]),
                eur(row["Anschaffungskosten_EUR"]),
                eur(row["Veraeusserungserloes_EUR"]),
                eur(row["Gewinn_Verlust_EUR"]),
                row["Haltedauer_Tage"],
                row["Steuerpflichtig"],
            ]
        )
    story.append(small_table(rows, [22 * mm, 22 * mm, 15 * mm, 29 * mm, 25 * mm, 25 * mm, 25 * mm, 11 * mm, 15 * mm], repeat_rows=1))
    build_doc(path, story, pagesize=landscape(A4))
    return path


def create_income_pdf(data: EvidencePackage, path: Path) -> Path:
    summary = data.filing_summary
    story = base_story(data.year, "Rewards / Mining / Staking Nachweis")
    story += [
        p(f"Einzutragende Rewards / Mining / Staking: {eur(summary['rewards_mining_staking_income_eur'])}."),
        Spacer(1, 5 * mm),
        h2("Income Guide"),
        small_table(
            [["Asset", "Typ", "Klassifizierung", "Events", "Menge", "Wert EUR", "Behandlung", "Quellen"]]
            + [
                [
                    row["Asset"],
                    row["Event_Typ"],
                    row["Klassifizierung"],
                    row["Events"],
                    qty(row["Menge"]),
                    eur(row["Wert_EUR"]),
                    row["Steuerliche_Behandlung"],
                    row["Quellen"],
                ]
                for row in data.income_guide
            ],
            [16 * mm, 18 * mm, 42 * mm, 14 * mm, 30 * mm, 24 * mm, 48 * mm, 28 * mm],
            repeat_rows=1,
        ),
        PageBreak(),
        h2("Reward-/Mining-/Staking-Eventdetails"),
    ]
    rows = [["UTC", "Quelle", "Typ", "Asset", "Menge", "Account/Wallet", "Hinweis"]]
    for row in data.reward_events:
        rows.append(
            [
                str(row["Zeitpunkt_UTC"])[:19],
                row["Quelle"],
                row["Event_Typ"],
                row["Asset"],
                qty(row["Menge"]),
                row["Account"] or row["Wallet"],
                row["Steuerlicher_Hinweis"],
            ]
        )
    story.append(small_table(rows, [31 * mm, 38 * mm, 18 * mm, 15 * mm, 33 * mm, 53 * mm, 32 * mm], repeat_rows=1))
    build_doc(path, story, pagesize=landscape(A4))
    return path


def create_index_pdf(data: EvidencePackage, path: Path) -> Path:
    story = base_story(data.year, "Belegindex und Methodik")
    story += [
        p(f"Export-ready: {data.filing_summary['export_ready']}; Status: {data.filing_summary['status_label']}."),
        p(f"Evidence-Package: {data.package_path.name}"),
        Spacer(1, 5 * mm),
        h2("Evidence Items"),
        small_table(
            [["ID", "Kategorie", "Label", "Format", "Records", "Betrag", "Status", "Pflicht"]]
            + [
                [
                    item.get("evidence_id", ""),
                    item.get("category", ""),
                    item.get("label", ""),
                    item.get("file_format", ""),
                    str(item.get("record_count", "")),
                    eur(item.get("amount_eur")),
                    item.get("status", ""),
                    "ja" if item.get("required") else "nein",
                ]
                for item in data.evidence.get("items", [])
            ],
            [42 * mm, 22 * mm, 55 * mm, 17 * mm, 17 * mm, 28 * mm, 20 * mm, 14 * mm],
            repeat_rows=1,
        ),
        PageBreak(),
        h2("Manifest-Dateien"),
        small_table(
            [["Pfad", "Quelle", "Bytes", "SHA256"]]
            + [
                [
                    item.get("path", ""),
                    item.get("source_endpoint", ""),
                    str(item.get("size_bytes", "")),
                    item.get("sha256", "")[:16] + "...",
                ]
                for item in data.manifest.get("files", [])
            ],
            [78 * mm, 83 * mm, 18 * mm, 35 * mm],
            repeat_rows=1,
        ),
    ]
    build_doc(path, story, pagesize=landscape(A4))
    return path


def base_story(year: int, title: str) -> list:
    return [
        h1(f"Steuerjahr {year} - {title}"),
        p("Technische Auswertung aus Steuerreport V2. Keine Steuerberatung."),
        Spacer(1, 5 * mm),
    ]


def build_doc(path: Path, story: list, *, pagesize=A4) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=pagesize,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    doc.build(story)


def styles():
    return getSampleStyleSheet()


def h1(text: str) -> Paragraph:
    style = styles()["Heading1"]
    return Paragraph(escape(text), style)


def h2(text: str) -> Paragraph:
    style = styles()["Heading2"]
    return Paragraph(escape(text), style)


def p(text: str) -> Paragraph:
    return Paragraph(escape(text), styles()["BodyText"])


def table(rows: list[list[object]], col_widths: list[float], *, repeat_rows: int = 1) -> Table:
    converted = [[cell(c) for c in row] for row in rows]
    tbl = Table(converted, colWidths=col_widths, repeatRows=repeat_rows)
    tbl.setStyle(table_style())
    return tbl


def small_table(rows: list[list[object]], col_widths: list[float], *, repeat_rows: int = 1) -> Table:
    converted = [[small_cell(c) for c in row] for row in rows]
    tbl = Table(converted, colWidths=col_widths, repeatRows=repeat_rows)
    tbl.setStyle(table_style(font_size=7))
    return tbl


def table_style(*, font_size: int = 8) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#101828")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b9c2d0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]
    )


def cell(value: object) -> Paragraph:
    return Paragraph(escape(str(value or "")), styles()["BodyText"])


def small_cell(value: object) -> Paragraph:
    style = styles()["BodyText"]
    style.fontSize = 7
    style.leading = 8
    return Paragraph(escape(str(value or "")), style)


def dec(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def eur(value: object) -> str:
    if value is None or value == "":
        return ""
    amount = dec(value).quantize(Decimal("0.01"))
    return f"{amount:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")


def qty(value: object) -> str:
    amount = dec(value)
    normalized = amount.normalize()
    text = f"{normalized:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def short_dt(value: str) -> str:
    return str(value).replace("T", " ")[:16]


def escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


if __name__ == "__main__":
    main()
