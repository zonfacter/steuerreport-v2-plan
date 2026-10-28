# Gemeinsamer Implementierungsvertrag

Status: Koordinatorentwurf fuer isolierte Umsetzung, keine produktive
Methodenfreigabe. Ausgangscommit: 1aecfb131d189267a01a6303f5a9b67a5a99efe2.
Jeder Agent bestaetigt den Vertrag vor Codeaenderungen; Aenderungsbedarf wird
zuerst abgestimmt. Originalimporte, Abgabepakete und Produktivbetrieb bleiben
unveraendert. Eigene Checkouts und eigene Datenbanken, maximal drei Ausfuehrende.

## Identitaet Und Herkunft

Bestehende event_id, raw_object_id, source_ref/tx_id, Importbatch und Hashes
sind massgeblich. Asset-Symbol ist keine neue Contract-/Mint-Identitaet.
Korrekturen bilden neue abgeleitete Staende, keine Umschreibung von Raw-Daten.
Tokenmigrationen, Wrapping, Eigenuebertraege und Wirtschaftsscope bleiben
belegpflichtige Sachverhalte; keine pauschale Freigabe oder neue FIFO-Aktivierung.

## Preisvertrag

Bestehende PricePoint/CanonicalEvent-Modelle und Preis-Ledger weiterverwenden.
Monetaere Werte bleiben Decimal. Belegte EUR-Gegenleistungen haben Vorrang
vor einer synthetischen Marktbewertung; Gebühren bleiben eigene Beine.

Konservativer Standard fuer historische Ersatzkurse: gleicher UTC-Tag,
positiv und nicht nach dem Ereignis. Keine implizite Wiederverwendung alter
Kurse, keine Zukunftsquote und kein FX-1-Fallback. Das ist eine ausdrueckliche
technische Zulassungsregel, NICHT die Behauptung, das BMF verbiete andere
dokumentierte Tageskursmethoden. Eine andere Tageszeit-/Tagesschlussmethode
benoetigt einen eigenen gebundenen Methodenvertrag und Freigabenachweis.

Lookup, Coverage (Python UND SQL), Steuerverbraucher und Review muessen
denselben Standard anwenden. Preis-/Ableitungskonflikte werden nicht durch
groessere Altersfenster verborgen. Bewertungsentscheidungen enthalten
Policy-ID/-Version, Status/Grund, Ereigniszeit, ausgewählten PricePoint,
Kurszeit und Quelle. Vorhandene Rohantwort-/FX-Belege und Hashes verlinken;
nicht vorhandene Provenienz wird als fehlend markiert, nicht erfunden.
Begleitende Diagnose darf abgelehnte Kandidaten zeigen, aber nicht als
zugelassenen steuerlichen Wert zurueckgeben. Fehlende Bewertung kann eine
vorlaeufige Rechenzeile erzeugen, muss aber finale Freigabe blockieren.

## Fristvertrag

holding_days ist ein beschreibender Abstand, keine eigenstaendige Steuerregel.
Eine zentrale Funktion fuer die bestehende private Jahresfrist verwendet
Kalenderdaten in Europe/Berlin, einschliesslich Schaltjahr und Februarende.
Python-Klassifikation, Planungszeitpunkt und SQL-Praedikat sind aequivalent.
Jahrestag noch innerhalb, Folgetag ausserhalb der modellierten Jahresfrist;
die amtliche Herleitung und Grenzen werden vor Integration dokumentiert.
Keine pauschale Anwendung dieser Privatvermoegensregel auf Betriebsvermoegen,
Derivate oder ungeklärte Rewards. Geltungsjahre und Freigrenzen getrennt.

## Readiness Und Artefakte

Technischer Download, Datenabdeckung, Preisqualitaet, Anschaffungskosten,
Methodenpruefung und menschliche Jahresfreigabe bleiben getrennte Dimensionen.
Eine leere Reviewliste allein erteilt keine finale Freigabe. Vorlaeufige
Pakete kennzeichnen Status und offene Punkte im Inhalt, nicht nur im Button.
PDF/CSV/JSON konsumieren denselben gebundenen Run und dieselbe Klassifikation.
Alte Snapshot- und Paketdateien werden weder geaendert noch neu etikettiert.
Ein Offline-Neulauf ist durch semantische Ergebnisse/Inputbindungen zu
vergleichen, nicht durch zufaellige UUIDs und PDF-Erstellungszeitpunkte.

## Integrationsgrenzen

Koordinator: zentrale Contracts, db/duckdb_store.py/Schema, api/app.py,
Frontend-Einstieg, Versionen und Integration. Betrieb: nur Betrieb/Restore/
Inventar. Bewertung: price_lookup.py, valuation.py und Preisdiagnosen, NICHT
tax.py. Steuerlogik: tax_time.py, tax.py, tax_years.py, reports.py und
tax_wallet_fifo.py/fifo_methods.py, NICHT Preisquellen oder aktive Methoden.
Tests/Fixtures je Agent separat. Agenten committen ausschliesslich ihren
eigenen Bereich und senden Commit/Tests/Handoff; kein Push/Release/Deployment.

## Noch Nicht Zugaengliche Eingaben

Die erwaehnte BMF-Quellenpruefung, Docker-Nachpruefung, isolierten V1-/V2-
Reprodateien und der gesonderte API-Pruefauftrag wurden lokal noch nicht
gefunden. Der Nutzer wurde nach dem Pfad gefragt. Keine Behauptung, diese
Dateien gelesen oder die gelieferten Repros exakt wiederholt zu haben.
Unabhaengige eigene Repros und amtliche Primärrecherche sind moeglich.

## Primaerquellen Fuer Die Weitere Pruefung

- BMF 06.03.2025, insbesondere Rz. 43, 53-61, 90-91:
  https://amtliche-handbuecher.bundesfinanzministerium.de/esth/2025/B-Anhaenge/Anhang-04/anhang-4.html
- EStG §23: https://www.gesetze-im-internet.de/estg/__23.html
- BGB §§187-188: https://www.gesetze-im-internet.de/bgb/__187.html
  und https://www.gesetze-im-internet.de/bgb/__188.html

Die Quellen sind keine Genehmigung einer individuellen Steuererklaerung.

## Abgestimmte Ergaenzungen Im Audit

Alle drei Erstrollen bestaetigten den Vertrag vor ihren Edits (Handoffs).
Der Koordinator integriert anschliessend ausschliesslich auf dem Auditbranch.
Globaler PDF-Export bleibt technisch/provisorisch; alte ungebundene Pakete
werden nicht nachtraeglich als freigegeben ausgegeben. Nullkostenbasis und
nicht vollstaendige Gebuehren-Token-Buchung erzeugen explizite Reviewgrenzen.
Die Freigrenzenprobe ist reine Arithmetik mit bestaetigtem Zusatzkontext,
keine persoenliche Steuer-/Verlustverrechnungs- oder Fachentscheidung.
Der unterschiedliche Scope von Preiszulassung und steuerlicher Freigabe
einer gleichmaessigen Tageskursmethode bleibt als F06-Review sichtbar.
