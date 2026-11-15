# Stichtagsreferenzen und Zeitbelege

Entwicklungszweig vom 15.11.2026; noch kein Release oder produktives Update.
Die allgemeine [historische EUR-Sammlung](HISTORISCHE_EUR_PREISE.md) und
steuerliche Jahresfreigaben bleiben getrennte Ablaeufe.

## Warum ein vorhandener Preis noch kein strenger Stichtagsnachweis ist

Ein gespeicherter Referenzwert kann als Tagesanker auf 00:00 UTC stehen,
ohne dass der Anbieter genau zu dieser Uhrzeit einen Kurs beobachtet oder
veroeffentlicht hat. Auch ein frueherer FX-Quelltag, hohe Confidence oder
ein Quellenname beweisen dies nicht. Ein erfolgreicher Speicher-Checkpoint
beweist nur damalige Speicherung.

Die Anzeige trennt deshalb:

- Vorhandenen Referenzbetrag und gespeicherten Ledger-Zeitwert.
- Belegte Beobachtungszeit, Tagesperiode und Preis-/FX-Veroeffentlichung.
- Bewertungsmethode und deren Freigabe.
- Token-/Mintentscheidung, die keinen fehlenden Kurszeitbeleg ersetzt.

Ohne Originalbindung stehen die Belegfelder auf unbekannt / nicht belegt.
Es werden keine historischen Uhrzeiten, Methoden oder Belegpfade erfunden.

## Status lesen, ohne KI oder externen Abruf

1. Im vorhandenen Stichtagsbereich den gewuenschten Stichtag waehlen.
2. Unter Preis- und FIFO-Gates den Zaehler **Zeitbeleg offen** lesen.
   Dieser zaehlt Positionen; **Kurs-/FX-Zeitbeleg offen** im Preisbedarf
   zaehlt Assets. Mehrere Konten desselben Assets koennen daher mehrere
   Positionen, aber nur einen Asset-Pruefpunkt erzeugen.
3. Im Preisbedarf bleibt eine vorhandene Zahl als **Referenzwert** sichtbar.
   Ein fehlender Preis wird nicht als bekanntes 0 EUR dargestellt.
4. **Zeitbelege der Stichtagsreferenzen** oeffnen. Pro Asset stehen die
   gespeicherte Referenzzeit und die getrennten fehlenden Originalangaben.
   Ein Tagesreferenz-Hinweis stammt nur aus dem Quellenlabel, nicht aus
   einer dadurch bestaetigten Anbieterantwort.
5. Nicht durch wiederholte Tagesabrufe oder Tokenannahmen versuchen, ein
   fehlendes Originaldatum zu ersetzen. Diese Aktionen erteilen keine
   Intraday- oder Methodenfreigabe.

Ein ungepruefter kleiner Referenzwert beweist nicht, dass die tatsaechliche
Position unwesentlich ist. Daher darf er das strenge Gate nicht umgehen.

**EUR-Sonderfall:** Ein echter EUR-Bestand zum Identitaetswert 1 EUR = 1 EUR
benoetigt keinen historischen Marktkurs. Die Anzeige nennt das zeitlos und
zeigt keinen Epochenanker als Beobachtungszeit. Ein Stablecoin oder ein
fremdes Asset mit dem Label `fiat:EUR` ist nicht dieser Sonderfall.

## Alte Stichtagslaeufe

Ein Archiv bleibt unveraendert und unter seiner Laufkennung abrufbar. Ohne
die neue Zeitbelegpolicy liefert der Latest-API-Endpunkt standardmaessig
keinen aktuellen Freigabenachweis, sondern eine Warnung mit Archivverweis.
Die Oberflaeche fordert den alten Stand ausdruecklich mit
`include_archived=true` an und kennzeichnet ihn als **Zeitbelegpruefung
veraltet**. Der archivierte Download bleibt erreichbar, ohne dass daraus
eine aktuelle Freigabe abgeleitet wird. Ein ausdruecklich neuer Dossierlauf
erzeugt einen neuen Stand; Lesen startet ihn nicht.
Die Policykennung ist keine allgemeine Zusage, dass alte Daten inzwischen
vollstaendig oder mit dem aktuellen Datenstand identisch sind.

## Noch offener nutzbarer Belegablauf

Dieser Schritt prueft heutige Legacy-Referenzen konservativ. Er implementiert
noch keine positive Zulassung echter Nicht-EUR-Intradaybelege oder einer
fachlich freigegebenen Tagesmethode. Dafuer werden strukturierte und
unveraenderlich gebundene Originalantworten mit Asset-/FX-Identitaet,
Beobachtungszeit bzw. Periode und erforderlicher Veroeffentlichungs-/
Verfuegbarkeitszeit benoetigt. Vorhandene manuelle Preisvorschauen oder
Archivdateien ersetzen diese Zulassungspruefung nicht automatisch.

Das bleibt ausdruecklich Arbeit aus #44/#46 vor einer solchen Produktfreigabe.
Die bisherigen Steuer-/FIFO-Zahlen, Tagespreisregeln und Quellenentscheidungen
werden durch diese reine Stichtags-Zeitdiagnose nicht automatisch korrigiert.

[Vertrag](audit/ISSUE46_ZEITBELEG_VERTRAG_2026-11-15.md) und
[Integrationsnachweise](audit/ISSUE46_ZEITBELEG_INTEGRATION_2026-11-15.md).
