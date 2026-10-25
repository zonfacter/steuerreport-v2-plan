#!/usr/bin/env python3
"""Generate the user-facing AI purpose guide without contacting a model."""
from __future__ import annotations

import argparse
from html import escape
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
INTRO = (
    "Der KI-Bereich bietet Textaufgaben und Datenkorrekturen. Textaufgaben erklaeren und strukturieren bereitgestellte Informationen. Datenkorrekturen verbinden ausgewaehlte Datenbankzeilen mit einem kontrollierten Vorschlags-, Berechnungs- und Freigabeverfahren. Der Assistent ist kein autonomer Steuerpruefer und keine zweite Berechnungsinstanz.",
    "Bei Textaufgaben sieht das Modell nur den eingegebenen Text und eine feste Systemanweisung. Im Modus Datenkorrekturen kommen ausschliesslich die zuvor angezeigten und ausgewaehlten Transaktions- oder Preiszeilen hinzu. Kein unbeschraenkter Datenbankzugriff: Dateien, Wallets, andere Steuerjahre und eingegebene URLs werden nicht automatisch gelesen.",
    "Jede Aufgabe steht fuer sich. Fruehere Aufgaben und Antworten werden nicht automatisch als Chatverlauf uebermittelt. Fuer eine Folgefrage muessen die benoetigten Angaben erneut im Aufgabentext stehen.",
)
CASES = (
    {
        "id": "bericht", "title": "Berichtsauszug verstehen", "type": "review",
        "input": "Ein kurzer, selbst ausgewaehlter Text- oder Tabellenauszug aus einem Bericht, einschliesslich Ueberschriften und bekannter Belegstellen.",
        "benefit": "Begriffe erklaeren, Kernaussagen zusammenfassen und benennen, welche Informationen im Auszug fehlen.",
        "check": "Alle Aussagen und Zahlen am Original pruefen. Die KI bestaetigt weder den Gesamtbericht noch dessen Vollstaendigkeit.",
        "prompt": "Erklaere den folgenden Berichtsauszug in verstaendlichem Deutsch. Verwende nur den bereitgestellten Text. Trenne ausdruecklich genannte Angaben von offenen Fragen. Erfinde keine fehlenden Belege, Werte oder Ursachen.\n\nAuszug mit Ueberschriften und Belegkennungen:\n[HIER DEN VORHER GEPRUEFTEN UND DATENSPARSAMEN AUSZUG EINFUEGEN]",
    },
    {
        "id": "hinweis", "title": "Pruefhinweis oder Fehlermeldung einordnen", "type": "risk_scan",
        "input": "Der genaue Hinweis aus der Anwendung, betroffene Quelle und die schon geprueften Umstaende, ohne Zugangsdaten.",
        "benefit": "Eine nachvollziehbare Checkliste fuer die manuelle Ursachenpruefung und die noch benoetigten Nachweise erstellen.",
        "check": "Moegliche Ursachen sind Hypothesen. Die KI beseitigt keine Import-, Preis- oder FIFO-Luecke und ruft keinen Connector auf.",
        "prompt": "Ordne diesen Hinweis ein. Nenne moegliche Ursachen ausschliesslich als Hypothesen und erstelle eine priorisierte Pruefliste: Was muss ich wo an welchem Originalbeleg pruefen? Schlage keine erfundenen Anschaffungen oder Preise und keine Loeschung vor.\n\nWortlaut des Hinweises:\n[HINWEIS]\nQuelle und bereits gepruefte Tatsachen:\n[KONTEXT]",
    },
    {
        "id": "import", "title": "Importspalten zuordnen lassen", "type": "import_mapping",
        "input": "Spaltenkopf, Quellbezeichnung und gegebenenfalls wenige pseudonymisierte Beispielzeilen als Text sowie die passende Spaltenliste aus der Importformat-Referenz.",
        "benefit": "Eine moegliche Zuordnung von Zeitpunkt, Asset, Menge, Ereignisart, Gegenwert und Gebuehren beschreiben und fehlende Felder auflisten.",
        "check": "Nur ein Vorschlag. Er aendert weder Importprofil noch Datei. Massgeblich bleiben Importformat-Referenz, Parser-Vorschau, erzeugte Ereignisse und Originalbelege. Originale nicht ueberschreiben.",
        "prompt": "Vergleiche den folgenden Spaltenkopf mit dem angegebenen Importprofil. Gib eine Zuordnungstabelle aus: Originalspalte, Zielfeld, Begruendung, Unsicherheit. Kennzeichne fehlende Pflichtangaben. Eine Tokenmenge ist kein Preis; Handelsvolumen ist kein Einkommen oder ausgezahltes Geld. Erfinde keine Werte und erzeuge keine zusaetzlichen Transaktionen.\n\nQuelle und Spaltenkopf:\n[QUELLE UND KOPFZEILE]\nZugelassene Felder und Regeln aus der Importformat-Referenz:\n[PASSENDEN REFERENZAUSZUG EINFUEGEN]",
    },
    {
        "id": "dubletten", "title": "Moegliche Dubletten oder Transfers besprechen", "type": "risk_scan",
        "input": "Eine kleine, zusammenhaengende Tabelle mit Quelle, Zeit, Asset, Menge, Richtung, Gebuehren und konsistenten Ersatzkennungen fuer Konten und Transaktions-IDs.",
        "benefit": "Aehnlichkeiten und Widersprueche im bereitgestellten Ausschnitt markieren und Prueffragen fuer den Belegabgleich formulieren.",
        "check": "Kein vollstaendiger Dubletten- oder Onchain-Abgleich. Gleiche Betraege beweisen keine Dublette. Transfer-Gegenbuchungen und Gebuehren muessen an den Originalen verifiziert werden; nicht allein aufgrund der Antwort loeschen.",
        "prompt": "Pruefe nur die folgenden Zeilen auf moegliche Ueberschneidungen oder zusammengehoerige Transfers. Bezeichne jeden Treffer als Pruefkandidat, nicht als bewiesene Dublette. Liste pro Kandidat Gemeinsamkeiten, Unterschiede und den noch benoetigten Gegenbeleg auf. Erfinde keine Gegenbuchung.\n\nZusammenhaengender pseudonymisierter Ausschnitt:\n[TABELLE MIT KONSISTENTEN ERSATZKENNUNGEN]",
    },
    {
        "id": "summen", "title": "Gepruefte Ergebnisse verstaendlich zusammenfassen", "type": "review",
        "input": "Bereits gepruefte Summen mit Jahr, Kategorie, Einheit, Berechnungsstand und Belegkennungen als Text.",
        "benefit": "Eine lesbare Erlaeuterung formulieren und unklare Kategorien oder im Ausschnitt erkennbare Widersprueche ansprechen.",
        "check": "Keine verlaessliche exakte Summenpruefung durch das Sprachmodell. Ergebnisse mit den deterministischen Berechnungen und Belegen der Anwendung abgleichen. Die KI entscheidet nicht ueber steuerliche Einordnung oder Korrekturpflichten.",
        "prompt": "Formuliere eine sachliche Zusammenfassung dieser bereits geprueften Angaben. Uebernimm Zahlen unveraendert und erfinde keine Berechnung. Trenne Handels-/Swapvolumen, tatsaechliche EUR-Einzahlungen und EUR-Auszahlungen, Gewinne/Verluste und interne Transfers. Leite aus Handelsvolumen weder Einkommen noch eine Auszahlung ab. Kennzeichne fehlende Informationen.\n\nJahr, Stand, Kategorien, Einheiten und Belegkennungen:\n[GEPRUEFTE ANGABEN]",
    },
    {
        "id": "notiz", "title": "Pruefnotiz oder Fragenliste entwerfen", "type": "documentation",
        "input": "Die von Ihnen bereits festgestellten Tatsachen, offenen Punkte und zugehoerigen lokalen Belegkennungen.",
        "benefit": "Einen strukturierten Entwurf fuer die eigene Pruefung, den Support oder ein Fachgespraech erstellen.",
        "check": "Entwurf selbst redigieren und Belegstellen pruefen. Die KI erstellt oder versendet keine Nachricht, kein freigegebenes Nachweispaket und keinen amtlichen Bericht.",
        "prompt": "Erstelle aus meinen Angaben einen neutralen Entwurf einer Pruefnotiz. Gliedere in: festgestellte Tatsachen mit meinen Belegkennungen, offene Fragen, ausdruecklich als solche bezeichnete Hypothesen, benoetigte Nachweise und naechste menschliche Pruefschritte. Erfinde keine Belegstellen und treffe keine steuerliche Entscheidung.\n\nMeine geprueften Angaben:\n[FAKTEN UND BELEGKENNUNGEN]\nNoch offen:\n[OFFENE PUNKTE]",
    },
)
TYPES = (
    ("Review", "review"), ("Risikopruefung", "risk_scan"),
    ("Importzuordnung", "import_mapping"), ("Dokumentation", "documentation"),
)
TYPE_NOTE = "Diese Aufgabentypen sind derzeit nur organisatorische Kennzeichnungen im Verlauf. Sie aktivieren keine unterschiedliche Spezialanalyse, keinen anderen Datenzugriff und keine eigene Berechnungspipeline. Die konkrete Anweisung muss im Aufgabentext stehen; das gespeicherte Modell wird verwendet."
LIMITS = (
    "Keine automatische Gesamtauswertung: 'Pruefe alle meine Transaktionen' gibt der KI noch keinen Zugriff auf diese Transaktionen.",
    "Keine Datei- oder Bildanhaenge im KI-Formular. Eine genannte PDF, CSV, Dateiablage oder URL wird nicht gelesen. Benoetigte Auszuege muessen als Text eingefuegt werden.",
    "Keine angeschlossene Websuche und keine selbststaendige Binance-, Bitget-, Helium-, Helius- oder Solscan-Abfrage durch den Assistenten. Andere Funktionen der Anwendung sind davon getrennt.",
    "Kein vollstaendiger FIFO-Lauf, kein garantiert exakter Summenabgleich und keine verlaessliche Feststellung von Gewinn, Bestandsvollstaendigkeit oder steuerlicher Zuordnung durch die Modellantwort.",
    "Keine Erfindung fehlender Anschaffungen, Preise, Wechselkurse oder Belege zulassen. Unbekannte Werte bleiben offen und muessen an Quellen geklaert werden.",
    "Keine ungeprueften Direktbuchungen oder Loeschungen durch Modellantworten. Die KI hat keine SQL-, Datei- oder Shell-Werkzeuge. Nur der ausdruecklich freigegebene Datenkorrekturpfad darf unterstuetzte Felder aktualisieren und anschliessend die fachlichen Auswertungen neu berechnen.",
    "Keine steuerliche oder rechtliche Freigabe. Die Antwort beweist weder die Richtigkeit einer Erklaerung noch eine Pflicht, sie zu berichtigen. Solche Entscheidungen nicht allein auf das Modell stuetzen.",
    "Ein plausibel klingender Satz, eine Belegkennung, ein Link oder ein Hash in der Antwort ist kein Beweis einer Quellenpruefung. Nicht im Eingabetext belegte Aussagen am Original verifizieren.",
)
WORKFLOW = (
    "Ziel klein und konkret waehlen. Den benoetigten Bericht, Hinweis oder Beleg zuerst selbst in der Anwendung oeffnen und einen geeigneten Ausschnitt bestimmen.",
    "Angaben datensparsam vorbereiten: relevante Ueberschriften, Einheiten, Kontext und eigene Belegkennungen beibehalten. Namen, Konten und Transaktionskennungen gegebenenfalls konsistent ersetzen; die Originalzuordnung lokal aufbewahren.",
    "Im KI-Assistenten einen Aufgabentyp und eine konkrete Anweisung zusammen mit dem benoetigten Text eingeben. Maximal 32000 Zeichen je Aufgabentext. Platzhalter in den Vorlagen muessen durch geeignete eigene Angaben ersetzt werden.",
    "Vor Cloud-Versand den gesamten Text selbst pruefen. Erst danach die ausdrueckliche Freigabe fuer diesen Text setzen und die Aufgabe ausfuehren. Eine Modell- oder Texteinstellung ist keine automatische Freigabe aller Daten.",
    "Die Antwort im Aufgabenverlauf lesen. Jede verwendete Aussage und Zahl an den eigenen Belegen oder den deterministischen Anwendungsergebnissen pruefen. Hypothesen als Hypothesen belassen.",
    "Nur selbst gepruefte Inhalte in eine eigene Notiz uebernehmen. Fuer eine Folgefrage den notwendigen Kontext erneut angeben; es gibt keinen automatisch uebermittelten Chatverlauf.",
)
PRIVACY = (
    "Der Prompt wird nicht automatisch anonymisiert. Namen, Kontonummern, Wallet-Adressen, Steuernummern, persoenliche Dateipfade und andere vertrauliche Inhalte werden nicht automatisch aus dem Aufgabentext entfernt.",
    "Keine API-Keys, Passwoerter, Seed-Phrasen oder privaten Schluessel in den Aufgabentext schreiben. Der Provider-Key gehoert ausschliesslich in das dafuer vorgesehene Passwortfeld der Einrichtung.",
    "Bei OpenRouter/Cloud werden der freigegebene Aufgabentext und die feste Systemanweisung an den konfigurierten Dienst uebermittelt. Eigene Regeln des Anbieters und der Modellprovider zu Verarbeitung und Aufbewahrung vorab pruefen.",
    "Ein lokaler Endpunkt ist keine automatische Offline- oder Datenschutzgarantie: Ein Proxy kann seinerseits Cloud-Modelle aufrufen. Der Betreiber muss seine Serverkonfiguration und den Anwendungszugriff kontrollieren.",
    "Free beschreibt die Katalogpreise, nicht Datenschutz, fachliche Richtigkeit oder Verfuegbarkeit. Auch kostenlose Modelle koennen falsche Antworten liefern und Anbieterlimits haben. Keine automatische kostenpflichtige Ersatzmodellwahl durch die Anwendung.",
    "Die Anwendung speichert Aufgabentext, Status und Antwort lokal im Aufgabenverlauf; Konfiguration und Zugangsdaten werden getrennt verwaltet. Das Speichern einer KI-Aufgabe ist keine Aenderung von Transaktionen oder Steuerzeilen.",
)
STATUS = (
    "'Verbindung erfolgreich' bedeutet, dass das Modell auf einen neutralen Test mit sichtbarem Text geantwortet hat. Es bestaetigt keine fachliche Eignung oder Pruefung Ihrer Daten.",
    "'Abgeschlossen' bedeutet, dass eine sichtbare Antwort empfangen und gespeichert wurde. Es bedeutet nicht, dass die gestellte Sachfrage richtig oder vollstaendig geloest wurde.",
    "Eine Antwort am Tokenlimit kann unvollstaendig sein. Fehlgeschlagene oder nach Serverabbruch noch als laufend angezeigte Aufgaben nicht blind wiederholen; zuerst den Verlauf pruefen. Ein neuer Auftrag kann erneut Kosten oder Kontingent verbrauchen.",
    "Einrichtung und Modellwahl allein starten keine Analyse. Weder beim Oeffnen der Seite noch beim Speichern der Einstellungen wird automatisch ein Steuerbericht an die KI gesendet.",
    "Bei Datenkorrekturen bedeuten Vorgeschlagen und Vorschau bereit noch keine fachliche Datenbankaenderung. Erst Uebernommen bestaetigt das gemeinsame Speichern der Korrektur, der neu berechneten Auswertungen und des Freigabenachweises. Ein blockierter Export bleibt gesondert zu klaeren.",
)
CORRECTIONS = (
    "Im KI-Bereich den Modus Datenkorrekturen waehlen. Datenart Transaktionen oder Preise, Jahr sowie optional Asset und Quelle festlegen; Daten laden. Die Jahresgrenzen entsprechen Europe/Berlin. Je Seite werden 20 Zeilen angezeigt, hoechstens 25 Zeilen duerfen in einem Auftrag ausgewaehlt werden.",
    "Unter Datensatz und Freizugebender Datenkontext die genauen Inhalte pruefen: stabile ID, Feldwerte, Quelle und, soweit importiert, Dateiname, Datei-Hash, Rohzeilen-Hash und Zeilennummer. Nur angekreuzte Zeilen werden an das Modell gesendet. Dieser Kontext wird nicht automatisch anonymisiert und kann echte Konten oder Wallet-Adressen enthalten. Zugangsdaten und Rohdaten-Payloads werden nicht aus der Datenbank angehaengt.",
    "Den Korrekturauftrag mit konkreten, selbst belegten Angaben formulieren. Beispiel: Beim ausgewaehlten Ereignis ist laut meinem Originalbeleg die Ereignisart [RICHTIGE ART] statt [ALTE ART] zu verwenden. Begruende den Vorschlag mit [BELEGSTELLE], ohne Mengen oder Preise zu erfinden. Platzhalter ersetzen. Bei Cloud-Versand Auftrag und ausgewaehlte Daten ausdruecklich freigeben; anschliessend KI-Vorschlaege erstellen. Dieselbe Auftragskennung wird nicht doppelt ausgefuehrt. Ein bewusst neu gestarteter Auftrag kann erneut Kosten verursachen.",
    "Der Modelltext wird als strukturiertes JSON gegen erlaubte Felder, Datenzeilen, Datentypen und den zuvor gezeigten Stand validiert. Unvollstaendige oder ungueltige Antworten werden nicht als Aenderungen ausgefuehrt. Ein Vorschlag kann auch ueber Manuell vorbereiten ohne Modellaufruf erstellt werden.",
    "Vorher, Vorschlag, Grund und Belegstelle je Position pruefen. Einzelpositionen abwaehlen oder Vorschlag bearbeiten. Eine Bearbeitung wird als neue Vorschlagsrevision gespeichert, nicht ueber das Original geschrieben. Belegstellen im Modellvorschlag muessen unabhaengig am Original kontrolliert werden.",
    "Vorschau berechnen erstellt eine private lokale Datenbankkopie und verwendet die bestehenden Berechnungsfunktionen fuer Preise, Bestaende, Flows, FIFO und Derivate. Die Fachdaten der laufenden Datenbank bleiben dabei unveraendert. Anschaffungskosten, Erloese und Gewinne werden vorher/nachher angezeigt; Geldbetraege in der Anzeige haben zwei Dezimalstellen, Exakte Summen behaelt die volle Genauigkeit. Handelsvolumen ist dabei kein Einkommen oder ausgezahltes Geld.",
    "Steuerzeilen-Aenderungen zeigen die stabilen Ereignis-/Anschaffungsreferenzen, Zeitpunkte, Haltefrist, Pool und Methode. Identische Lot-Aufteilungen werden zusammengefasst; technische Zufalls-IDs gelten nicht als fachliche Aenderung. Die Detaildifferenzen muessen mit den Kosten-, Erloes- und Gewinndifferenzen exakt uebereinstimmen. Andernfalls lautet der Fehler reconciliation_failed und es gibt keine Uebernahme.",
    "Freigebende Person und Pruefvermerk eintragen. Originalbelege und Auswirkungen selbst geprueft sowie die verbindliche Datenbankuebernahme bestaetigen. Erst Freigegebene Aenderungen uebernehmen aktualisiert Zeilen und abgeleitete Auswertungen gemeinsam in einer Transaktion. Abweichende Datenbank-, Methoden- oder Konfigurationsstaende und eine manipulierte Vorschau sperren die Uebernahme; eine neue Pruefung ist erforderlich.",
    "Aktualisierbar sind vorhandene Transaktionen: Ereignisart, Zeitpunkt mit expliziter Zeitzone, Asset/Menge, Quote- und Gebuehrenfelder sowie Account/Wallet-Zuordnung. Bei vorhandenen nicht abgeleiteten Preisen sind EUR-Preis und Konfidenz korrigierbar. Ursprung, Rohzeilen-ID und Transaktions-ID bleiben erhalten. Es gibt hier noch keine Erstellung/Loeschung von Transaktionen, keine Importprofil-Aenderung, keinen Connector-Aufruf, keine Einstellungen und keine beliebigen Tabellen-, SQL-, Server- oder Programmcodeaenderungen.",
    "Freigegebene Korrekturen werden als separate Ueberlagerung gespeichert und bei erneuten Laeufen wieder angewendet. Fehlende oder widersprechende Zielzeilen fuehren zu einem Konflikt und blockieren den Export. Betroffene Quellen/Preise lassen sich nicht einfach entfernen; vorher ist die Ruecknahme zu pruefen. Neue oder geaenderte Quellstaende koennen eine erneute Zuordnung erfordern.",
    "Audit-JSON herunterladen bewahrt vorherige Zeilen, Herkunft und Quellen-Hashes, Modell-/Konfigurationsstand, Auswahl, Berechnungsvorschau und Freigabe mit SHA256-Nachweis. Ruecknahme vorbereiten erzeugt einen neuen Gegenvorschlag; sie benoetigt wieder Vorschau und Freigabe und darf spaetere Aenderungen nicht ueberschreiben. Rohdateien und abgelegte Steuer-Snapshots werden nicht veraendert.",
    "Die eingetragene Person ist eine Selbstauskunft: Die Anwendung hat keine globale Anmeldung oder kryptografische Identitaetspruefung. Ein Hash ist keine externe Signatur und keine WORM-Sicherung. Betreiber muessen Zugriffsschutz, Sicherungen und Aufbewahrung selbst absichern. Diese Funktion ersetzt keinen uneingeschraenkten Coding-Agenten wie einen persoenlich betreuten Terminalzugang.",
)


def render() -> dict[str, bytes]:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    html = ["<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
            "<title>Steuerreport - KI: Einsatz und Grenzen</title><style>",
            "*{box-sizing:border-box}body{margin:0;color:#19241e;background:#fff;font:16px/1.65 Arial,sans-serif;letter-spacing:0}main{max-width:960px;margin:auto;padding:28px 24px 64px}h1{font-size:30px;line-height:1.2}h2{font-size:23px;border-top:1px solid #cdd8d1;margin-top:36px;padding-top:18px}h3{font-size:18px;margin-top:26px}a{color:#176348}nav ol{columns:2;padding-left:24px}li{margin-bottom:10px}code,pre{font:13px/1.6 monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f1f5f2;padding:14px}dt{font-weight:600}dd{margin:0 0 10px}table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:14px}td,th{vertical-align:top;text-align:left;border-bottom:1px solid #cdd8d1;padding:9px;overflow-wrap:anywhere}.notice{border-left:4px solid #b07c25;background:#fff9ed;padding:10px 16px}.downloads{display:flex;gap:12px 24px;flex-wrap:wrap}h2,h3{break-after:avoid}pre,tr,.notice{break-inside:avoid}@page{size:A4;margin:16mm}@media(max-width:600px){main{padding:20px 16px}h1{font-size:26px}nav ol{columns:1}table{font-size:12px}td,th{padding:6px}}@media print{main{padding:0}body{font-size:10pt;line-height:1.5}h1{font-size:22pt}h2{font-size:15pt}h3{font-size:12pt}pre{font-size:8.5pt}.downloads{display:none}a{color:inherit;text-decoration:none}}",
            f"</style></head><body><main><header><p>Steuerreport / Version {escape(version)}</p><h1>KI: Einsatz und Grenzen</h1>",
            "<p class='downloads'><a href='/ki-einsatzleitfaden.pdf' download>Leitfaden als PDF</a><a href='/benutzerleitfaden.html#ki'>Einrichtung und Modellwahl</a><a href='/#ai'>KI-Assistent oeffnen</a></p></header>"]
    md = [f"# KI: Einsatz und Grenzen ({version})", "", "## Kurz Gesagt", ""]
    html.append("<section id='kurz'><h2>Kurz gesagt</h2>")
    for paragraph in INTRO:
        html.append(f"<p>{escape(paragraph)}</p>")
        md.extend([paragraph, ""])
    html.append("<p class='notice'><strong>Die KI-Antwort ist ein Vorschlag, kein Pruefnachweis.</strong> Fachliche Datenbankaenderungen benoetigen eine validierte Vorschau und menschliche Freigabe. Massgeblich bleiben Originalbelege, nachvollziehbare Berechnungen und menschliche Pruefung.</p></section>")
    md.extend(["> Die KI-Antwort ist ein Vorschlag, kein Pruefnachweis. Fachliche Datenbankaenderungen benoetigen eine validierte Vorschau und menschliche Freigabe. Massgeblich bleiben Originalbelege, nachvollziehbare Berechnungen und menschliche Pruefung.", ""])
    html.append("<section id='korrekturen'><h2>Datenkorrekturen pruefen und uebernehmen</h2><ol>")
    md.extend(["## Datenkorrekturen pruefen und uebernehmen", ""])
    for index, paragraph in enumerate(CORRECTIONS, 1):
        html.append(f"<li>{escape(paragraph)}</li>")
        md.extend([f"{index}. {paragraph}", ""])
    html.append("</ol></section>")
    html.append("<nav aria-label='Inhalt'><ol><li><a href='#einsatz'>Konkrete Einsatzfaelle und Beispielaufgaben</a></li><li><a href='#typen'>Was die Aufgabentypen bedeuten</a></li><li><a href='#grenzen'>Wofuer die KI nicht geeignet ist</a></li><li><a href='#ablauf'>Ein sinnvoller Arbeitsablauf</a></li><li><a href='#datenschutz'>Daten, Modellwahl und Kosten</a></li><li><a href='#status'>Antworten und Status richtig lesen</a></li></ol></nav>")
    html.append("<section id='einsatz'><h2>Konkrete Einsatzfaelle</h2><p>Die folgenden Vorlagen enthalten keine echten Belege oder Transaktionen. Ohne passenden Eingabetext kann das Modell keine Aussagen ueber Ihren Bestand treffen.</p>")
    md.extend(["## Konkrete Einsatzfaelle", "", "Die folgenden Vorlagen enthalten keine echten Belege oder Transaktionen. Ohne passenden Eingabetext kann das Modell keine Aussagen ueber Ihren Bestand treffen.", ""])
    for case in CASES:
        html.append(f"<section id='{case['id']}'><h3>{escape(case['title'])}</h3><p>Aufgabentyp: <code>{case['type']}</code></p><dl>")
        md.extend([f"### {case['title']}", "", f"Aufgabentyp: `{case['type']}`", ""])
        for key, label in (("input", "Was Sie bereitstellen"), ("benefit", "Wobei die KI helfen kann"), ("check", "Was Sie selbst pruefen muessen")):
            html.append(f"<dt>{label}</dt><dd>{escape(case[key])}</dd>")
            md.extend([f"- **{label}:** {case[key]}", ""])
        html.append(f"</dl><p>Beispielaufgabe:</p><pre>{escape(case['prompt'])}</pre></section>")
        md.extend(["Beispielaufgabe:", "", "```text", case["prompt"], "```", ""])
    html.append("</section><section id='typen'><h2>Was die Aufgabentypen bedeuten</h2><table><thead><tr><th>Auswahl</th><th>Kennung</th></tr></thead><tbody>")
    md.extend(["## Was Die Aufgabentypen Bedeuten", "", "| Auswahl | Kennung |", "| --- | --- |"])
    for label, value in TYPES:
        html.append(f"<tr><td>{label}</td><td><code>{value}</code></td></tr>")
        md.append(f"| {label} | `{value}` |")
    html.append(f"</tbody></table><p>{escape(TYPE_NOTE)}</p></section>")
    md.extend(["", TYPE_NOTE, ""])
    sections = (("grenzen", "Wofuer die KI nicht geeignet ist", LIMITS, False),
                ("ablauf", "Ein sinnvoller Arbeitsablauf", WORKFLOW, True),
                ("datenschutz", "Daten, Modellwahl und Kosten", PRIVACY, False),
                ("status", "Antworten und Status richtig lesen", STATUS, False))
    for section_id, title, paragraphs, numbered in sections:
        tag = "ol" if numbered else "ul"
        html.append(f"<section id='{section_id}'><h2>{title}</h2><{tag}>")
        md.extend([f"## {title}", ""])
        for index, paragraph in enumerate(paragraphs, 1):
            html.append(f"<li>{escape(paragraph)}</li>")
            md.extend([f"{str(index) + '.' if numbered else '-'} {paragraph}", ""])
        html.append(f"</{tag}></section>")
    html.append("<footer><p>Weitere Nachweise und Funktionen: <a href='/benutzerleitfaden.html#pruefen'>Hinweise und Transfers pruefen</a>, <a href='/benutzerleitfaden.html#jahre'>Steuerjahre und Berichte</a>, <a href='/importformate.html'>Importformate und Spaltenlayouts</a>.</p><p>Diese Anleitung beschreibt den implementierten KI-Arbeitsbereich. Sie bestaetigt weder die Qualitaet eines bestimmten Modells noch die Richtigkeit einer einzelnen Antwort.</p></footer></main></body></html>\n")
    md.extend(["Weitere Anleitung: `frontend/public/benutzerleitfaden.html#pruefen`, `#jahre` und `frontend/public/importformate.html`.", "", "Diese Anleitung beschreibt den implementierten KI-Arbeitsbereich. Sie bestaetigt weder die Qualitaet eines bestimmten Modells noch die Richtigkeit einer einzelnen Antwort.", ""])
    return {"frontend/public/ki-einsatzleitfaden.html": "\n".join(html).encode(), "docs/KI_EINSATZLEITFADEN.md": "\n".join(md).encode()}


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
        raise SystemExit("KI-Einsatzleitfaden nicht aktuell: " + ", ".join(changed))
    print(f"KI-Einsatzleitfaden: {'aktuell' if args.check else str(len(changed)) + ' Dateien aktualisiert'}")


if __name__ == "__main__":
    main()
