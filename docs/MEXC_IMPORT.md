# MEXC-Dateiimport: erster nativer Durchlauf

Entwicklungsumfang zu Issue #4; keine pauschale Vollunterstuetzung aller
MEXC-Produkte und keine Zusicherung einer vollstaendigen eigenen Historie.
Die Implementierung wird separat von der produktiven rc35 geprueft.

## Bedienung

1. Unter Daten importieren die Quelle MEXC waehlen und ein stabiles eigenes
   Konto benennen. Unterschiedliche Konten nicht mit demselben Alias mischen.
2. XLSX oder UTF-8-CSV hinzufuegen, pro Datei die tatsaechliche Exportart
   bestaetigen und das passende Tabellenblatt waehlen. Der Dateiname allein
   ist kein Produktnachweis. Noch keine Daten werden gespeichert.
3. Fuer Funding Other mit der Spalte Time die belegte Zeitbasis zuordnen.
   Ein fester Headeroffset wie UTC+01:00 gilt auch im Sommer. Europe/Berlin
   ist eine andere Zuordnung; mehrdeutige/fehlende Zeiten bleiben blockiert.
4. Vorschau, Zeilenhinweise und Gesamtzahlen pruefen. Mengenbuchungen und
   fachlich offene Zeilen sind verschiedene Dimensionen und koennen sich
   ueberschneiden. Ein Airdrop kann mengenmaessig belegt, steuerlich aber
   weiterhin ungeklart sein.
5. Bei Kandidaten den vorhandenen Originalbeleg auswaehlen oder eine wirklich
   eigenstaendige Buchung bestaetigen. Begruendung mit mindestens zehn Zeichen
   erfassen und erneut pruefen. Gleiche Zeit/Menge bedeutet nicht automatisch
   Dublette. Zwei echte gleiche Buchungen bleiben erhalten.
   Jede Entscheidung benoetigt den input_digest der aktuellen Zeilenvorschau.
   Nach Datei-/Konto-/Kandidatenwechsel bewusst erneut bestaetigen; dieser
   Wert wird nicht still durch eine neue Serverantwort ersetzt.
6. Erst die geprueften Dateien freigeben und importieren. Der vorhandene
   Assistent speichert Rohbelege, normalisiert den Batch und fuehrt die
   bestehende Ledger-/Steuervorschau-Pipeline aus. Er akzeptiert keine
   fachlichen Reviews und erteilt keine Jahresfreigabe. Jede Datei wird vor
   Speicherung erneut geprueft; eine zweite Datei kann deshalb nach Import
   der ersten wegen eines nun erkannten Doppelbelegs blockieren.
7. Originaldatei und JSON-Belegspur herunterladen. Die Spur enthaelt Hash,
   Blatt, physische Zeile, Originalfelder und gegebenenfalls Vorwaerts- und
   Rueckverknuepfungen zu zusaetzlichen Belegen.

## Umfang und Grenzen

| Export | Behandlung |
| --- | --- |
| Spot Statement | Originalkopf mit expliziter Produktzuordnung; belegte Airdrop-Menge als unknown, keine automatische Mining-/Reward-/Einkunftsentscheidung |
| Funding Other | Derselbe erste Mengenpfad, jedoch keine stille UTC-Annahme bei Time |
| Asset Snapshots | Nur Bestandsbeleg; Date(UTC+8) ist ein Datum, kein erfundener Einzeltransaktionszeitpunkt; Total/USDT Valuation erzeugen keine Lots oder Anschaffungskosten |
| Futures Capital Flow | Nur Rohbelege; BONUS-Zuteilung und Ruecknahme bleiben erhalten, ohne ungesicherte Gewinne oder Erwerbe |
| Futures Statement, Earn Fixed/Flexible, Send History | Bei passenden Statement-Spalten nur Rohbelege mit offener fachlicher Zuordnung |
| Andere Buchungstypen/Layouts | Sichtbarer Review oder blockierte Vorschau; keine generische Ersatzinterpretation |
| Header-only | Gueltiger Leerexport, kein erfolgreicher Buchungsimport |

Spot-Ausfuehrungen mit Gegenwaehrung, Gebuehrenallokation, externe Ein- und
Auszahlungen, interne Transfers, Migrationen und echte Futures-Abrechnungen
sind mit diesem ersten Pfad nicht abschliessend normalisiert. Eine heutige
Bestandsmenge ersetzt weder Anfangshistorie noch Anschaffungsbelege.

Die nativen Header entsprechen dem MEXC-Export und muessen unveraendert
erhalten bleiben. Grenzen: 10000 Datenzeilen je nativer Datei, 25 MiB je
Datei, 100 MiB entpacktes XLSX, 256 Spalten; keine verschluesselten Dateien,
XLS oder Formeln als alleiniger Nachweis eines Pflichtwerts. CSV-Trennzeichen
Komma/Semikolon; Mengen mit eindeutigem Dezimalpunkt, keine Tausendertrenner.
Zahlen werden ohne Float-Roundtrip gelesen und innerhalb Decimal(38,18)
validiert; Werte ausserhalb dieser Praezision werden nicht still gerundet.

## Identitaet und Entscheidungen

UID identifiziert das Anbieter-Konto, nicht eine Transaktion. Konto und UID
bleiben getrennt in der Identitaet. Kontobezeichnungen werden eindeutig
codiert, damit etwa Doppelpunkte keine Konten zusammenfallen lassen.

Der Importfingerprint bindet Originalbytes, Blatt, Exportart, Konto und
Zeitbasis. Identische Wiederholung in diesem Kontext erzeugt keinen neuen
Batch. Andere Dateien mit passenden Buchungsmerkmalen werden Kandidaten.
Vorhandene Transaction ID / Record ID wird kontogebunden geprueft; zwei
verschiedene dokumentierte IDs werden nicht wegen gleicher Menge verworfen.
Widerspruechliche/mehrfache IDs bleiben blockiert.

Ohne eindeutige Buchungs-ID dienen UID, Konto, normalisierte UTC-Zeit, Asset,
vorzeichenbehaftete Menge und Quellbezeichnung nur zur Kandidatensuche. Die
explizite Entscheidung verknuepft auf ein passendes originales book-Objekt,
nicht auf eine weitere Verknuepfung. Fremde Ziele, veraltete Zeilenangaben
und leere Begruendungen werden abgewiesen. Zwei gleiche Zeilen in einer
ersten Datei werden ohne ID nicht pauschal entfernt.

Dieselbe belegte Provider-Buchungs-ID darf nicht durch separate als zweiter
Vorgang gebucht werden. IDs auf verknuepften Zusatzbelegen werden dem Root
zugerechnet und bei spaeteren Konflikten mitgeprueft. input_digest bindet
Datei, Kontext, physische Zeile und Kandidatenfakten. Die gespeicherte
Entscheidung erhaelt den Digest und die damaligen Fakten zur spaeteren Pruefung.

Originalfelder werden nicht ersetzt; zusaetzliche Interpretations-/Entscheidungs-
metadaten liegen als JSON-String im reservierten Raw-Feld _mexc. Originalbytes
liegen hashadressiert und privat neben der Datenbank in mexc_originals.
Batch und Raw-Zeilen werden gemeinsam transaktional gespeichert. Der
einprozessige Docker-/DuckDB-Betrieb bleibt Voraussetzung; der MEXC-
Importabschnitt wird innerhalb dieses Prozesses serialisiert.

Bereits vorhandene MEXC-Altbelege ohne native Bindung beduerfen zuerst einer
gesonderten Migration; sie werden nicht als ungefaehrlich ignoriert. Fuer
manuell unter anderen Quellen importierte Altbestaende ist eine eigene
Quellen-/Kontenzuordnung erforderlich. Dieser Pfad beweist keine globale
Dublettenfreiheit fremder, noch nicht zugeordneter Sammelimporte.

## API und Nachweise

Der vorhandene Assistent nutzt POST /api/v1/import/assistant/preview und
POST /api/v1/import/assistant/execute. Zusaetzlich zu source=mexc und Datei
enthaelt die Anfrage beispielsweise:

```json
{
  "mexc": {
    "export_kind": "funding_other",
    "account": "synthetic-spot",
    "timezone": "UTC+01:00",
    "decisions": {
      "2": {
        "action": "link_existing",
        "target_raw_object_id": "synthetic-existing-raw-id",
        "reason": "Beide Originalbelege wurden als dieselbe Buchung geprueft.",
        "input_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      }
    }
  }
}
```

Die Zeile 2 ist die erste Excel-Datenzeile. separate mit Begruendung bezeichnet
eine eigenstaendige Buchung und darf kein Linkziel enthalten. Entscheidungen
sind keine Steuerfreigaben und koennen vorhandene Raw-Objekte nicht aendern.
Erneutes Normalisieren konsumiert die gespeicherte Bindung; fehlende Linkziele
erzeugen eine Sperre, keine erfundene Ersatzbuchung.
Der beispielhafte Digest muss durch den tatsaechlichen Wert der vorherigen
Zeilenvorschau ersetzt werden. Bei decision_stale=true die veraenderten
Belege erneut ansehen, Zuordnung bewusst bestaetigen und neu pruefen lassen.

Reine Snapshots bleiben mit einem ausdruecklichen Bestands-/Historien-
Abgleichpunkt gesperrt. Fehlende, veraenderte oder symlinkte Originale
blockieren den Review-/Exportstatus ebenfalls, nicht erst den Download.
Ungueltige Rollen-/Kontextmetadaten duerfen keine Rohzeile unsichtbar machen.
Ein Original-Link bleibt bei spaeterer Canonical-Korrektur erhalten; weichen
Menge, Asset, Konto oder Zeitpunkt ab, gilt er bis zur Klaerung nicht als
aktueller Mengenabgleich. Eine reine Typklaerung bei unveraenderten Fakten
wird nicht pauschal gesperrt.

GET /api/v1/import/batches/{id}/trace.json liefert zusaetzlich mexc_evidence.
GET /api/v1/import/batches/{id}/original prueft den gespeicherten SHA256 vor
Auslieferung der unveraenderten Originaldatei. Fehlender oder geaenderter
Originalinhalt wird nicht als gueltiger Download ausgegeben.

## Herstellerbelege

Geprueft am 28.10.2026:

- [Account Data Export](https://www.mexc.com/support/article/how-to-use-mexc-s-account-data-export-function-410103096834075648): getrennte Produktansichten, Excel/PDF und Self-Service-Daten ab 01.10.2024. Das begrenzt die Quelle, nicht die Beweislast fuer eigene Vollstaendigkeit.
- [Spot Statement](https://www.mexc.com/support/article/how-to-use-the-spot-statement-441167547314136064): andere Sicht als Spot Orders, insbesondere abgeschlossene Bewegungen gegenueber auch offenen/stornierten Orders.

Dies ist Software-/Quellendokumentation, keine steuerrechtliche Bewertung.
