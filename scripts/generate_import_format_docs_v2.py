#!/usr/bin/env python3
"""Generate import documentation and empty templates from the actual profiles."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from html import escape
from io import BytesIO, StringIO
from pathlib import Path
import tomllib
import zipfile

from openpyxl import Workbook

from steuerreport_v2.importers.source_profiles import PROFILES


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("manual-csv", "binance", "bitget", "pionex", "coinbase", "helium", "solana_rpc")
# Examples are deliberately fictitious; downloads contain headers only.
LAYOUTS = {
    "manual-csv": {
        "headers": "time,asset,amount,type,quote_asset,quote_quantity,fee_asset,fee_quantity,account,tx_id",
        "example": "2025-01-15T10:00:00Z,BTC,0.001,buy,EUR,70,EUR,0.10,beispiel-konto,beispiel-manuell",
        "note": "Eigene belegte Tabellen. buy/sell/trade/convert werden als Handel, deposit/withdrawal/transfer als Transfer, reward/mining/staking als entsprechende Ereignisart erkannt. type ist technisch nicht Pflicht, ohne erkennbaren Typ kann aber unknown entstehen. Bei Verkaeufen negative Asset-Menge oder sell; Auszahlungen negativ oder withdrawal. Gegenmenge und Gebuehr als positive Betraege mit eigenem Asset angeben. Betrag ist eine Tokenmenge, nicht automatisch ein EUR-Wert.",
    },
    "binance": {
        "headers": "UTC_Time,Account,Operation,Coin,Change,Remark,tx_id",
        "example": "2025-01-15T10:00:00Z,Spot,Deposit,EUR,100,Rein fiktives Beispiel,beispiel-binance",
        "note": "Transaktionshistorie mit Operation/Coin/Change. Change ist die vorzeichenbehaftete Bestandsaenderung, nicht der Geldwert. Einen Mehrzeilen-Trade nicht zu einer zusaetzlichen erfundenen Kaufzeile verdoppeln. Handelsgegenwerte und Gebuehren nur aus belegten Zeilen oder den unten genannten Zusatzfeldern uebernehmen. Das Beispiel ist ein Transfer, kein Einkommen. Nicht jeder Binance-Bericht besitzt dieses Layout.",
    },
    "bitget": {
        "headers": "Timestamp UTC+8 (Completion),Coin,Quantity,Type,Transaction hash(txid),Account",
        "example": "2025-01-15 18:00:00,USDT,100,Deposit,beispiel-bitget,beispiel-konto",
        "note": "Beispiel fuer Ein-/Auszahlungshistorie. Handelslisten koennen stattdessen Trading pair und Executed sowie Action und Transacted amount verwenden. Fuer einen Trade wird ein belegter Gegenwert benoetigt, nicht ein beliebiger USD-Schaetzwert. Spot-Finanzhistorie, Orders und Derivate nicht als identische Vorgangsarten behandeln. Ohne explizite Zeitzone nimmt dieses Profil UTC+8 an, auch bei einer Spalte Time. ISO-Zeitstempel mit Z oder Offset haben Vorrang; im Beispiel ist 18:00 UTC+8 gleich 10:00 UTC.",
    },
    "pionex": {
        "headers": "time,coin,change,type,quote_asset,quote_quantity,fee_asset,fee_quantity,account,tx_id",
        "example": "2025-01-15T10:00:00Z,USDT,100,deposit,,,,,beispiel-konto,beispiel-pionex",
        "note": "Unterstuetzt sind allgemeine Mengenzeilen und spezifische Paar-/Tauschlayouts: Received Currency + Received Quantity mit Sent Currency + Sent Quantity oder Buy Currency + Buy Amount mit Sell Currency + Sell Amount. Ein weiteres Transferlayout nutzt Amount_USDT + Direction; Direction ist kein Nachweis eines Trades. Stornierte Orders ohne Ausfuehrung erzeugen keine Ausfuehrung. Bot-Orders und deren bereits exportierte Einzeltrades nicht doppelt erfassen.",
    },
    "coinbase": {
        "headers": "Timestamp,Asset,Quantity Transacted,Transaction Type,Spot Price Currency,Subtotal,Fees and/or Spread,Account,Transaction ID",
        "example": "2025-01-15T10:00:00Z,BTC,0.001,Buy,EUR,70,0.10,beispiel-konto,beispiel-coinbase",
        "note": "Transaction Type mit Buy/Sell/Convert kennzeichnet Handel, Send/Receive einen Transfer. Subtotal ist der Handelsgegenwert; ein Spot-Preis je Token ist nicht dasselbe. Spot Price Currency bezeichnet hier die Waehrung von Subtotal und Fees and/or Spread, nicht das gehandelte Asset. Die Gegenmenge nicht erneut mit der Tokenmenge multiplizieren. Das Profil besitzt keine allgemeine Handelspaar-Spalte als Ersatz fuer Asset.",
    },
    "helium": {
        "headers": "timestamp,token,amount,type,wallet,tx_id",
        "example": "2025-01-15T10:00:00Z,HNT,0.25,Reward,beispiel-wallet,beispiel-helium",
        "note": "Legacy-/Fairspot- und tabellarische Reward-Daten, nicht jede beliebige Hotspot-Datei. Reward wird in diesem Profil als mining normalisiert; das entscheidet nicht ueber die individuelle steuerliche Vermoegenszuordnung. Alternative assetlose Layouts koennen z. B. hnt_amount, iot_amount, mobile_amount oder Mining Rewards HNT/IOT/MOBILE verwenden; keine Preis-/Oracle-Hilfsspalte als Tokenmenge einsetzen. Bei Period Start (UTC) wird auf das Monatsende 23:59:59 UTC datiert: Ein Monatsbericht belegt keinen exakten Einzelzufluss. Sender + Receiver + Amount ist ein besonderes Transferlayout; eigene Walletzuordnung und Richtung pruefen.",
    },
    "solana_rpc": {
        "headers": "timestamp_utc,asset,quantity,event_type,side,fee_asset,fee,wallet_address,tx_id",
        "example": "2025-01-15T10:00:00Z,SOL,-0.1,sol_transfer,out,SOL,0.000005,beispiel-wallet,beispiel-solana",
        "note": "Bereits aufbereitete RPC-Tabellendaten, nicht rohe JSON-RPC-Antworten und keine pauschale Solscan-CSV-Unterstuetzung. event_type z. B. sol_transfer, token_transfer, swap_in_aggregated oder swap_out_aggregated; side in/out und Wallet/Signatur beleggetreu angeben. Swaps brauchen beide zusammengehoerigen Legs mit derselben Signatur. Ein positiver token_transfer kann als income/reward klassifiziert werden; eine vorhandene Claim-/Reward-Instruktion ist nicht durch einen beliebigen Spaltennamen ersetzbar. Wallet-Eigentum, Rohbelege und erzeugte Klassifikation pruefen. Die Kopfzeile allein garantiert keine fachlich vollstaendige Onchain-Rekonstruktion.",
    },
}
FIELDS = (
    ("time", "Zeitpunkt: technisch erforderlich"),
    ("asset", "Asset: erforderlich oder passende Paar-/Spezialableitung"),
    ("quantity", "Tokenmenge: technisch erforderlich"),
    ("type", "Ereignisart: fuer die Zuordnung wesentlich"),
    ("pair", "Handelspaar: optionaler Asset-Ersatz"),
    ("quote_asset", "Gegenasset: bei Handel erforderlich zur Rekonstruktion"),
    ("quote_quantity", "Gegenmenge: bei Handel erforderlich zur Rekonstruktion"),
    ("fee_asset", "Gebuehrenasset: sofern eine Gebuehr anfaellt"),
    ("fee_quantity", "Gebuehrenmenge: sofern eine Gebuehr anfaellt"),
    ("account", "Konto / Wallet: fuer nachvollziehbare Zuordnung"),
    ("tx_id", "Transaktions-ID: fuer Nachweis und Abgleich"),
    ("source_ref", "Quellreferenz: optional, z. B. Order-ID"),
)
COMMON = (
    "Unterstuetzte Dateitypen: .csv, .xlsx und .xls. CSV: UTF-8 mit oder ohne BOM, Komma oder Semikolon als Trennzeichen. Bei Komma als Trennzeichen muessen Felder mit Kommas in doppelte Anfuehrungszeichen eingeschlossen sein. Keine PDF-, ZIP-, JSON-, ODS-, Bild- oder Wallet-Backup-Dateien; Umbenennen aendert das Format nicht.",
    "Tabellenlayout: eine eindeutige Kopfzeile, darunter je Rohposition eine Datenzeile. Spaltenreihenfolge frei; keine verbundenen Zellen, Summenzeilen oder mehreren Tabellen nebeneinander. Zusaetzliche Spalten bleiben Rohdaten, werden aber nicht automatisch fachlich ausgewertet. Excel: richtiges Blatt waehlen; CSV: kein Tabellenblatt. Vorlagenblattnamen sind identisch mit der auszuwaehlenden Quelle. In Excel Datumswerte vorzugsweise als ISO-Text speichern, keine Formeln als einzige Datenquelle oder Passwortverschluesselung verwenden.",
    "Technisches Minimum je Profil: gueltiger Zeitpunkt, Asset (oder unterstuetztes Paar-/Speziallayout) und gueltige Menge. Eine vorhandene Spalte mit leeren oder unlesbaren Werten reicht nicht. type ist nicht fuer die Spaltenerkennung verpflichtend, aber fuer eine belastbare Zuordnung wesentlich. Ein importierbarer Spaltenkopf beweist weder vollstaendige Einzelzeilen noch vollstaendige Steuerdaten.",
    "Spaltennamen: Gross-/Kleinschreibung wird ignoriert, Unterstriche werden zu Leerzeichen, fuehrende/nachfolgende und wiederholte Leerzeichen normalisiert. Andere Satzzeichen und Klammern sind nicht frei austauschbar. Die Tabellen zeigen echte Profil-Aliase in Suchreihenfolge, nicht zusaetzliche Pflichtspalten. In der Regel genuegt ein Alias je Feld. Konkurrierende Alias-Spalten vermeiden; quellenspezifische Sonderregeln koennen Vorrang haben.",
    "Zeitpunkt: empfohlen 2025-01-15T10:00:00Z oder 2025-01-15T11:00:00+01:00. Beide Beispiele meinen denselben Zeitpunkt. Weitere erkannte Formen sind YYYY-MM-DD HH:MM:SS, YYYY/MM/DD HH:MM:SS, DD.MM.YYYY HH:MM:SS und DD.MM.YYYY HH:MM. Ohne Offset gilt normalerweise UTC; Bitget verwendet UTC+8. Erkannte UTC+/-Angaben in Spaltennamen, bei Binance auch im Dateinamen, koennen die Standardzeitzone vorgeben. Bewahren Sie diese Angaben im Original auf. Unix-Sekunden/-Millisekunden nicht als allgemein unterstuetzt voraussetzen. Ein Datum ohne Uhrzeit ersetzt keine genaue Ausfuehrungszeit.",
    "Zahlen: vorzugsweise Dezimalpunkt ohne Tausendertrennzeichen, z. B. 0.001 oder -25.50; Dezimalkomma nur mit korrekt getrennten/quotierten Feldern. Keine Waehrungszeichen oder Textzusatz in eigenen Mengenfeldern. Mengen, Handelsgegenwert und Preis je Token sind verschiedene Groessen. Vorzeichen aus dem Beleg erhalten; type kann die Richtung zusaetzlich bestimmen. Ein positiver Zufluss ist nicht automatisch Einkommen, Handelsvolumen keine EUR-Auszahlung.",
    "Fuer eine vollstaendige Auswertung: Konto/Wallet, Original-ID, Ereignisart, beide Handelsseiten, Gebuehren und benoetigte historische Preise/Anschaffungen belegen. Fehlende Anschaffungswerte oder Preise nicht erfinden und nicht beliebig in quote_quantity eintragen. Die Technik kann ohne diese Angaben Zeilen lesen, waehrend die steuerliche Auswertung offen bleibt. Getrennte Exporte von Trades, Transfers, Rewards und Derivaten gemeinsam auf Vollstaendigkeit und Ueberschneidungen pruefen.",
    "Grenzen: maximal 20 Dateien, je 25 MiB und zusammen 100 MiB im normalen Importdialog. Erst Vorschau pruefen, dann ausdruecklich freigeben; danach Ereignisse, nicht zugeordnete Zeilen und Review-Hinweise kontrollieren. Eine reine Kopfzeile ist absichtlich nicht importierbar. Die Downloads enthalten keine Beispieltransaktionen, Konten oder Geheimnisse.",
    "Originale niemals fuer eine Layoutanpassung ueberschreiben. Eine normalisierte Kopie mit Bezug auf Originaldatei und Hash getrennt sichern. Kein anderes Profil waehlen, um eine Pruefung zu umgehen. Blockpit und andere Sammelplattformen sind hier keine weitere primaere Handelshistorie; nicht als zweite Buchung derselben Transaktionen einschleusen. Identische Dateihashes verhindern nicht jede Doppelbuchung aus ueberlappenden Exporten.",
)


def csv_text(source: str, *, example: bool = False) -> str:
    layout = LAYOUTS[source]
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(next(csv.reader([layout["headers"]])))
    if example:
        writer.writerow(next(csv.reader([layout["example"]])))
    return output.getvalue()


def workbook_bytes() -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.creator = "Steuerreport"
    workbook.properties.lastModifiedBy = "Steuerreport"
    workbook.properties.created = datetime(2026, 10, 25)
    workbook.properties.modified = datetime(2026, 10, 25)
    for source in SOURCES:
        sheet = workbook.create_sheet(source)
        sheet.append(next(csv.reader([LAYOUTS[source]["headers"]])))
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(36, max(18, len(column[0].value) + 2))
    buffer = BytesIO()
    workbook.save(buffer)
    # ZIP timestamps and core properties must not change on each regeneration.
    output = BytesIO()
    with zipfile.ZipFile(buffer) as archive, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as stable:
        for name in sorted(archive.namelist()):
            content = archive.read(name)
            if name == "docProps/core.xml":
                from xml.etree import ElementTree as ET

                root = ET.fromstring(content)
                for item in root:
                    if item.tag.endswith("}modified"):
                        item.text = "2026-10-25T00:00:00Z"
                content = ET.tostring(root, encoding="utf-8")
            info = zipfile.ZipInfo(name, (2026, 10, 25, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            stable.writestr(info, content)
    return output.getvalue()


def render() -> dict[str, bytes]:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    html = ["<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
            "<title>Steuerreport - Importformate und Spaltenlayouts</title><style>",
            "*{box-sizing:border-box}body{margin:0;background:#fff;color:#19241e;font:16px/1.6 Arial,sans-serif;letter-spacing:0}main{max-width:960px;margin:auto;padding:28px 24px 60px}h1{font-size:30px;line-height:1.2}h2{font-size:23px;margin-top:36px;border-top:1px solid #cdd8d1;padding-top:18px}a{color:#176348}nav ul{display:flex;flex-wrap:wrap;gap:12px 24px;padding:0;list-style:none}table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:14px}td,th{vertical-align:top;text-align:left;border-bottom:1px solid #cdd8d1;padding:9px;overflow-wrap:anywhere}th:first-child{width:31%}code,pre{font:13px/1.6 monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f1f5f2;padding:12px}li{margin-bottom:12px}h2,h3{break-after:avoid}tr,pre{break-inside:avoid}@page{size:A4;margin:16mm}@media(max-width:600px){main{padding:20px 14px}h1{font-size:25px}table{font-size:12px}td,th{padding:6px}}@media print{body{font-size:10pt}main{padding:0}h1{font-size:22pt}h2{font-size:15pt}table{font-size:8.5pt}pre{font-size:8pt}.downloads{display:none}a{color:inherit;text-decoration:none}}",
            f"</style></head><body><main><header><p>Steuerreport / Version {escape(version)}</p><h1>Importformate und Spaltenlayouts</h1>",
            "<p>Verbindliche technische Referenz der im normalen Dateiimport angebotenen Profile. Keine Zusage fuer beliebige Exporte eines Anbieters.</p>",
            "<p class='downloads'><a href='/benutzerleitfaden.html#formate'>Benutzerleitfaden</a> | <a href='/importformate.pdf' download>Formatreferenz als PDF</a> | <a href='/import-vorlagen/import-vorlagen.xlsx' download>Leere Excel-Vorlagen (7 Blaetter)</a></p></header><nav aria-label='Importprofile'><ul>"]
    md = [f"# Importformate und Spaltenlayouts ({version})", "", "Generiert aus den tatsaechlichen Importprofilen. Keine Zusage fuer beliebige Exporte eines Anbieters.", "", "## Allgemeine Regeln", ""]
    for source in SOURCES:
        html.append(f"<li><a href='#{source}'>{escape(PROFILES[source].label)}</a></li>")
    html.append("</ul></nav><h2>Allgemeine Regeln</h2><ol>")
    for rule in COMMON:
        html.append(f"<li>{escape(rule)}</li>")
        md.extend([f"- {rule}", ""])
    html.append("</ol>")
    files = {}
    for source in SOURCES:
        profile = PROFILES[source]
        note = LAYOUTS[source]["note"]
        example = csv_text(source, example=True)
        html.extend([f"<section id='{source}'><h2>{escape(profile.label)} <code>{source}</code></h2>",
                     f"<p>{escape(note)}</p><p class='downloads'><a href='/import-vorlagen/{source}.csv' download>Leere CSV-Vorlage fuer {escape(profile.label)}</a></p>",
                     "<h3>Konkretes Layout und fiktives Beispiel</h3><p>Nur Erlaeuterung, keine echten Transaktionen. Die herunterladbare Vorlage enthaelt ausschliesslich die erste Zeile.</p>",
                     f"<pre>{escape(example)}</pre><h3>Erkannte Spaltennamen</h3><table><thead><tr><th>Feld / Bedeutung</th><th>Alternative Namen in Profil-Suchreihenfolge</th></tr></thead><tbody>"])
        md.extend([f"## {profile.label} (`{source}`)", "", note, "", f"Leere CSV: `frontend/public/import-vorlagen/{source}.csv`", "", "Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:", "", "```csv", example.rstrip(), "```", "", "| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |", "| --- | --- |"])
        for field, label in FIELDS:
            aliases = list(dict.fromkeys(getattr(profile, f"{field}_columns")))
            cells = " / ".join(f"<code>{escape(alias)}</code>" for alias in aliases) or "Keine allgemeine Spaltenzuordnung in diesem Profil."
            html.append(f"<tr><td>{escape(label)}</td><td>{cells}</td></tr>")
            md.append(f"| {label} | " + (" / ".join(f"`{alias}`" for alias in aliases) or "Keine allgemeine Spaltenzuordnung in diesem Profil.") + " |")
        html.append("</tbody></table></section>")
        md.append("")
        files[f"frontend/public/import-vorlagen/{source}.csv"] = csv_text(source).encode()
    html.append("<footer><p>Pflege: scripts/generate_import_format_docs_v2.py --check prueft Profile, Dokumentation und leere Vorlagen auf Gleichstand. Vorschau, Ereignispruefung und Originalnachweise bleiben erforderlich.</p></footer></main></body></html>\n")
    files["frontend/public/importformate.html"] = "\n".join(html).encode()
    files["docs/IMPORTFORMATE.md"] = "\n".join(md).encode()
    files["frontend/public/import-vorlagen/import-vorlagen.xlsx"] = workbook_bytes()
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = []
    for name, content in render().items():
        path = ROOT / name
        if not path.is_file() or path.read_bytes() != content:
            changed.append(name)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    if args.check and changed:
        raise SystemExit("Importdokumentation/Vorlagen nicht aktuell: " + ", ".join(changed))
    print(f"Importdokumentation/Vorlagen: {'aktuell' if args.check else str(len(changed)) + ' Dateien aktualisiert'}")


if __name__ == "__main__":
    main()
