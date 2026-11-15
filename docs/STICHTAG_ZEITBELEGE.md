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

## Menschliche Bestaetigung im Entwicklungszweig

Voraussetzung ist eine neue, ausdruecklich uebernommene historische
Preisvorschau mit Preis-ID-Bindung und intakten Originalen. Alte Archive
erhalten keine erfundenen Bindungen. Ohne geeignete Originalunterlagen
bleibt die Bestaetigung gesperrt.

1. Im Preisarbeitsbereich die gespeicherte Vorschau und deren uebernommene
   Preiszeilen oeffnen. **Originalbindung pruefen** lesen und Originale
   herunterladen. Dieser Schritt schreibt nichts und ruft keinen Anbieter ab.
2. **Preiszeit und Methode menschlich bestaetigen** oeffnen. Netzwerk,
   Contract, Dezimalstellen und den exakten Bewertungszeitpunkt in UTC angeben.
   Es werden keine Uhrzeiten aus einem Quellenlabel ergaenzt.
3. Beobachteten Kurs oder eine dokumentierte Tagesperiode, Preiswaehrung,
   Publikationszeit, Originalhash/Fundstelle und Quelle erfassen. Bei USD ist
   der historische FX-Kurs mit Richtung, Referenz- und Publikationszeit sowie
   Originalbezug zusaetzlich erforderlich. Eine Tagesreferenz ist kein
   beobachteter Ausfuehrungskurs. Methodenzeitzone und Verfuegbarkeitsregel
   muessen zu den Originalen passen.
4. Das eigene Methodendokument (1 Byte bis 2 MiB), Person und Begruendung
   angeben. **Technische Vorschau vorbereiten** speichert ausschliesslich
   gebundene Belegartefakte. Es ist noch keine Bestaetigung gespeichert.
5. Die technische Vorschau und alle Originale pruefen. Nur bei korrektem
   Inhalt beide Erklaerungen bewusst aktivieren und **Menschliche Bestaetigung
   speichern** waehlen. Fehlende oder widerspruechliche Nachweise lassen
   sich damit nicht uebergehen. Das freie Personenfeld authentifiziert
   keine Identitaet; der API-Zugang braucht weiterhin LAN/VPN oder ein
   vorgeschaltetes authentifiziertes TLS-Gateway.
6. Status erneut lesen und den gewuenschten Stichtag pruefen. Eine gueltige
   Bestaetigung gilt nur fuer genau diese Preis-ID, Methode und diesen
   UTC-Zeitpunkt. Sie erzwingt keine andere Preiswahl. Same-Day-, Tokenrisiko-
   und weitere Dossier-Gates bleiben unabhaengig erforderlich.
7. Fehler nicht durch Aendern der alten Entscheidung korrigieren:
   **Bestaetigung ausdruecklich widerrufen**, Person/Grund/Erklaerung angeben
   und bewusst widerrufen. Die alte Entscheidung bleibt erhalten. Eine
   Korrektur erfordert eine neue Vorlage und erneute ausdrueckliche Zustimmung.

Server-Erfassungszeit, menschlich angegebene Publikationszeit und
Zustimmungszeit bleiben getrennt. Ein Hash belegt die Bindung der Bytes,
nicht deren inhaltliche Echtheit. Keine automatische KI-, Rechts- oder
Jahresfreigabe. Lesen startet weder Import noch Neuberechnung.

Wenn Originale, aktuelle Assetidentitaet, Preiszeile oder verwendete
Zulassungsregeln nicht mehr passen, wird die Bestaetigung nicht mehr als
aktuell positiv verwendet. Archivierte Dossierlaeufe bleiben unveraendert;
ihre fruehere Zustimmung ist keine aktuelle Freigabe. Die bisherigen
Steuer-/FIFO-Zahlen und Tagespreisregeln werden nicht automatisch korrigiert.

Vertrag und Grenzen:
[Menschliche Preisbestaetigung](audit/ISSUE46_MENSCHLICHE_PREISBESTAETIGUNG_VERTRAG_2026-11-15.md).

[Vertrag](audit/ISSUE46_ZEITBELEG_VERTRAG_2026-11-15.md) und
[Integrationsnachweise](audit/ISSUE46_ZEITBELEG_INTEGRATION_2026-11-15.md).
