# KI: Einsatz und Grenzen (0.2.0rc31)

## Kurz Gesagt

Der KI-Bereich bietet Textaufgaben und Datenkorrekturen. Textaufgaben erklaeren und strukturieren bereitgestellte Informationen. Datenkorrekturen verbinden ausgewaehlte Datenbankzeilen mit einem kontrollierten Vorschlags-, Berechnungs- und Freigabeverfahren. Der Assistent ist kein autonomer Steuerpruefer und keine zweite Berechnungsinstanz.

Bei Textaufgaben sieht das Modell nur den eingegebenen Text und eine feste Systemanweisung. Im Modus Datenkorrekturen kommen ausschliesslich die zuvor angezeigten und ausgewaehlten Transaktions- oder Preiszeilen hinzu. Kein unbeschraenkter Datenbankzugriff: Dateien, Wallets, andere Steuerjahre und eingegebene URLs werden nicht automatisch gelesen.

Jede Aufgabe steht fuer sich. Fruehere Aufgaben und Antworten werden nicht automatisch als Chatverlauf uebermittelt. Fuer eine Folgefrage muessen die benoetigten Angaben erneut im Aufgabentext stehen.

> Die KI-Antwort ist ein Vorschlag, kein Pruefnachweis. Fachliche Datenbankaenderungen benoetigen eine validierte Vorschau und menschliche Freigabe. Massgeblich bleiben Originalbelege, nachvollziehbare Berechnungen und menschliche Pruefung.

## Datenkorrekturen pruefen und uebernehmen

1. Im KI-Bereich den Modus Datenkorrekturen waehlen. Datenart Transaktionen oder Preise, Jahr sowie optional Asset und Quelle festlegen; Daten laden. Die Jahresgrenzen entsprechen Europe/Berlin. Je Seite werden 20 Zeilen angezeigt, hoechstens 25 Zeilen duerfen in einem Auftrag ausgewaehlt werden.

2. Unter Datensatz und Freizugebender Datenkontext die genauen Inhalte pruefen: stabile ID, Feldwerte, Quelle und, soweit importiert, Dateiname, Datei-Hash, Rohzeilen-Hash und Zeilennummer. Nur angekreuzte Zeilen werden an das Modell gesendet. Dieser Kontext wird nicht automatisch anonymisiert und kann echte Konten oder Wallet-Adressen enthalten. Zugangsdaten und Rohdaten-Payloads werden nicht aus der Datenbank angehaengt.

3. Den Korrekturauftrag mit konkreten, selbst belegten Angaben formulieren. Beispiel: Beim ausgewaehlten Ereignis ist laut meinem Originalbeleg die Ereignisart [RICHTIGE ART] statt [ALTE ART] zu verwenden. Begruende den Vorschlag mit [BELEGSTELLE], ohne Mengen oder Preise zu erfinden. Platzhalter ersetzen. Bei Cloud-Versand Auftrag und ausgewaehlte Daten ausdruecklich freigeben; anschliessend KI-Vorschlaege erstellen. Dieselbe Auftragskennung wird nicht doppelt ausgefuehrt. Ein bewusst neu gestarteter Auftrag kann erneut Kosten verursachen.

4. Der Modelltext wird als strukturiertes JSON gegen erlaubte Felder, Datenzeilen, Datentypen und den zuvor gezeigten Stand validiert. Unvollstaendige oder ungueltige Antworten werden nicht als Aenderungen ausgefuehrt. Ein Vorschlag kann auch ueber Manuell vorbereiten ohne Modellaufruf erstellt werden.

5. Vorher, Vorschlag, Grund und Belegstelle je Position pruefen. Einzelpositionen abwaehlen oder Vorschlag bearbeiten. Eine Bearbeitung wird als neue Vorschlagsrevision gespeichert, nicht ueber das Original geschrieben. Belegstellen im Modellvorschlag muessen unabhaengig am Original kontrolliert werden.

6. Vorschau berechnen erstellt eine private lokale Datenbankkopie und verwendet die bestehenden Berechnungsfunktionen fuer Preise, Bestaende, Flows, FIFO und Derivate. Die Fachdaten der laufenden Datenbank bleiben dabei unveraendert. Anschaffungskosten, Erloese und Gewinne werden vorher/nachher angezeigt; Geldbetraege in der Anzeige haben zwei Dezimalstellen, Exakte Summen behaelt die volle Genauigkeit. Handelsvolumen ist dabei kein Einkommen oder ausgezahltes Geld.

7. Steuerzeilen-Aenderungen zeigen die stabilen Ereignis-/Anschaffungsreferenzen, Zeitpunkte, Haltefrist, Pool und Methode. Identische Lot-Aufteilungen werden zusammengefasst; technische Zufalls-IDs gelten nicht als fachliche Aenderung. Die Detaildifferenzen muessen mit den Kosten-, Erloes- und Gewinndifferenzen exakt uebereinstimmen. Andernfalls lautet der Fehler reconciliation_failed und es gibt keine Uebernahme.

8. Freigebende Person und Pruefvermerk eintragen. Originalbelege und Auswirkungen selbst geprueft sowie die verbindliche Datenbankuebernahme bestaetigen. Erst Freigegebene Aenderungen uebernehmen aktualisiert Zeilen und abgeleitete Auswertungen gemeinsam in einer Transaktion. Abweichende Datenbank-, Methoden- oder Konfigurationsstaende und eine manipulierte Vorschau sperren die Uebernahme; eine neue Pruefung ist erforderlich.

9. Aktualisierbar sind vorhandene Transaktionen: Ereignisart, Zeitpunkt mit expliziter Zeitzone, Asset/Menge, Quote- und Gebuehrenfelder sowie Account/Wallet-Zuordnung. Bei vorhandenen nicht abgeleiteten Preisen sind EUR-Preis und Konfidenz korrigierbar. Ursprung, Rohzeilen-ID und Transaktions-ID bleiben erhalten. Es gibt hier noch keine Erstellung/Loeschung von Transaktionen, keine Importprofil-Aenderung, keinen Connector-Aufruf, keine Einstellungen und keine beliebigen Tabellen-, SQL-, Server- oder Programmcodeaenderungen.

10. Freigegebene Korrekturen werden als separate Ueberlagerung gespeichert und bei erneuten Laeufen wieder angewendet. Fehlende oder widersprechende Zielzeilen fuehren zu einem Konflikt und blockieren den Export. Betroffene Quellen/Preise lassen sich nicht einfach entfernen; vorher ist die Ruecknahme zu pruefen. Neue oder geaenderte Quellstaende koennen eine erneute Zuordnung erfordern.

11. Audit-JSON herunterladen bewahrt vorherige Zeilen, Herkunft und Quellen-Hashes, Modell-/Konfigurationsstand, Auswahl, Berechnungsvorschau und Freigabe mit SHA256-Nachweis. Ruecknahme vorbereiten erzeugt einen neuen Gegenvorschlag; sie benoetigt wieder Vorschau und Freigabe und darf spaetere Aenderungen nicht ueberschreiben. Rohdateien und abgelegte Steuer-Snapshots werden nicht veraendert.

12. Die eingetragene Person ist eine Selbstauskunft: Die Anwendung hat keine globale Anmeldung oder kryptografische Identitaetspruefung. Ein Hash ist keine externe Signatur und keine WORM-Sicherung. Betreiber muessen Zugriffsschutz, Sicherungen und Aufbewahrung selbst absichern. Diese Funktion ersetzt keinen uneingeschraenkten Coding-Agenten wie einen persoenlich betreuten Terminalzugang.

## Fachagenten und Anwendungswissen

1. Sieben Fachrollen stehen unter Fachagent bereit: Koordinator, Import- und Quellenpruefung, Krypto-Forensik, Wallet- und FIFO-Pruefung, Steuer-/Mining-/Reward-Pruefung, Preis-/Stichtagspruefung sowie Dokumentation/Audit. Die Auswahl veraendert die fachliche Systemanweisung, nicht die zugelassenen Daten oder Rechte.

2. Agentenprofile einrichten oeffnet Name, Aufgabenbeschreibung, Aktivierung und Agentenmodell. Nach Aenderungen Agentenprofile speichern. Ungespeicherte Profilaenderungen sperren neue Modellauftraege. Eine deaktivierte Rolle kann nicht ausgefuehrt werden.

3. Das Agentenmodell kann aus der geladenen Modellliste gewaehlt oder unter Modell-IDs je Anbieter eingetragen werden. Es gibt getrennte IDs fuer Lokal, OpenRouter und andere Cloud-Anbieter. Leer bedeutet Standardmodell der aktiven Verbindung; Verbindung und globales Standardmodell muessen zuerst eingerichtet sein. Rollen speichern keine eigenen Keys oder Dienstadressen und schalten nicht automatisch zwischen Verbindungen um.

4. Alle Rollen verwenden die aktive lokale oder Cloud-Verbindung samt deren Freigaben und Zeit-/Tokenlimits. Ein manuell zugeordnetes Modell kann kostenpflichtig sein; Preis unbekannt ist nicht Free. Kein automatischer bezahlter Modellwechsel, keine parallele Agentenkette und kein automatisches Delegieren weiterer Modellauftraege.

5. Anwendungswissen ist einsehbar: Datenmodell, unveraenderte Rohquellen, zugelassene Korrekturfelder, Vorschau, Freigabe und Grenzen. Es wird mit der Software versioniert und gemeinsam mit der Rolle an das Modell gegeben. Es enthaelt keine Betreiber-Keys oder vorgegebenen Privatkonten. Es ersetzt weder vollstaendige Belege noch einen unbeschraenkten Blick in den gesamten Bestand.

6. Erfolgreiche Textaufgaben und erstellte KI-Korrekturvorschlaege speichern die verwendete Rolle mit Aufgabenbeschreibung, Wissens-Hash, Profilrevision und Modellzuordnung. Geaenderte Profile sperren veraltete Auftraege. Dies sind Systemprofile fuer vorhandene Modelle, keine zusaetzlich trainierten oder fachlich zertifizierten Modelle.

## Konkrete Einsatzfaelle

Die folgenden Vorlagen enthalten keine echten Belege oder Transaktionen. Ohne passenden Eingabetext kann das Modell keine Aussagen ueber Ihren Bestand treffen.

### Berichtsauszug verstehen

Aufgabentyp: `review`

- **Was Sie bereitstellen:** Ein kurzer, selbst ausgewaehlter Text- oder Tabellenauszug aus einem Bericht, einschliesslich Ueberschriften und bekannter Belegstellen.

- **Wobei die KI helfen kann:** Begriffe erklaeren, Kernaussagen zusammenfassen und benennen, welche Informationen im Auszug fehlen.

- **Was Sie selbst pruefen muessen:** Alle Aussagen und Zahlen am Original pruefen. Die KI bestaetigt weder den Gesamtbericht noch dessen Vollstaendigkeit.

Beispielaufgabe:

```text
Erklaere den folgenden Berichtsauszug in verstaendlichem Deutsch. Verwende nur den bereitgestellten Text. Trenne ausdruecklich genannte Angaben von offenen Fragen. Erfinde keine fehlenden Belege, Werte oder Ursachen.

Auszug mit Ueberschriften und Belegkennungen:
[HIER DEN VORHER GEPRUEFTEN UND DATENSPARSAMEN AUSZUG EINFUEGEN]
```

### Pruefhinweis oder Fehlermeldung einordnen

Aufgabentyp: `risk_scan`

- **Was Sie bereitstellen:** Der genaue Hinweis aus der Anwendung, betroffene Quelle und die schon geprueften Umstaende, ohne Zugangsdaten.

- **Wobei die KI helfen kann:** Eine nachvollziehbare Checkliste fuer die manuelle Ursachenpruefung und die noch benoetigten Nachweise erstellen.

- **Was Sie selbst pruefen muessen:** Moegliche Ursachen sind Hypothesen. Die KI beseitigt keine Import-, Preis- oder FIFO-Luecke und ruft keinen Connector auf.

Beispielaufgabe:

```text
Ordne diesen Hinweis ein. Nenne moegliche Ursachen ausschliesslich als Hypothesen und erstelle eine priorisierte Pruefliste: Was muss ich wo an welchem Originalbeleg pruefen? Schlage keine erfundenen Anschaffungen oder Preise und keine Loeschung vor.

Wortlaut des Hinweises:
[HINWEIS]
Quelle und bereits gepruefte Tatsachen:
[KONTEXT]
```

### Importspalten zuordnen lassen

Aufgabentyp: `import_mapping`

- **Was Sie bereitstellen:** Spaltenkopf, Quellbezeichnung und gegebenenfalls wenige pseudonymisierte Beispielzeilen als Text sowie die passende Spaltenliste aus der Importformat-Referenz.

- **Wobei die KI helfen kann:** Eine moegliche Zuordnung von Zeitpunkt, Asset, Menge, Ereignisart, Gegenwert und Gebuehren beschreiben und fehlende Felder auflisten.

- **Was Sie selbst pruefen muessen:** Nur ein Vorschlag. Er aendert weder Importprofil noch Datei. Massgeblich bleiben Importformat-Referenz, Parser-Vorschau, erzeugte Ereignisse und Originalbelege. Originale nicht ueberschreiben.

Beispielaufgabe:

```text
Vergleiche den folgenden Spaltenkopf mit dem angegebenen Importprofil. Gib eine Zuordnungstabelle aus: Originalspalte, Zielfeld, Begruendung, Unsicherheit. Kennzeichne fehlende Pflichtangaben. Eine Tokenmenge ist kein Preis; Handelsvolumen ist kein Einkommen oder ausgezahltes Geld. Erfinde keine Werte und erzeuge keine zusaetzlichen Transaktionen.

Quelle und Spaltenkopf:
[QUELLE UND KOPFZEILE]
Zugelassene Felder und Regeln aus der Importformat-Referenz:
[PASSENDEN REFERENZAUSZUG EINFUEGEN]
```

### Moegliche Dubletten oder Transfers besprechen

Aufgabentyp: `risk_scan`

- **Was Sie bereitstellen:** Eine kleine, zusammenhaengende Tabelle mit Quelle, Zeit, Asset, Menge, Richtung, Gebuehren und konsistenten Ersatzkennungen fuer Konten und Transaktions-IDs.

- **Wobei die KI helfen kann:** Aehnlichkeiten und Widersprueche im bereitgestellten Ausschnitt markieren und Prueffragen fuer den Belegabgleich formulieren.

- **Was Sie selbst pruefen muessen:** Kein vollstaendiger Dubletten- oder Onchain-Abgleich. Gleiche Betraege beweisen keine Dublette. Transfer-Gegenbuchungen und Gebuehren muessen an den Originalen verifiziert werden; nicht allein aufgrund der Antwort loeschen.

Beispielaufgabe:

```text
Pruefe nur die folgenden Zeilen auf moegliche Ueberschneidungen oder zusammengehoerige Transfers. Bezeichne jeden Treffer als Pruefkandidat, nicht als bewiesene Dublette. Liste pro Kandidat Gemeinsamkeiten, Unterschiede und den noch benoetigten Gegenbeleg auf. Erfinde keine Gegenbuchung.

Zusammenhaengender pseudonymisierter Ausschnitt:
[TABELLE MIT KONSISTENTEN ERSATZKENNUNGEN]
```

### Gepruefte Ergebnisse verstaendlich zusammenfassen

Aufgabentyp: `review`

- **Was Sie bereitstellen:** Bereits gepruefte Summen mit Jahr, Kategorie, Einheit, Berechnungsstand und Belegkennungen als Text.

- **Wobei die KI helfen kann:** Eine lesbare Erlaeuterung formulieren und unklare Kategorien oder im Ausschnitt erkennbare Widersprueche ansprechen.

- **Was Sie selbst pruefen muessen:** Keine verlaessliche exakte Summenpruefung durch das Sprachmodell. Ergebnisse mit den deterministischen Berechnungen und Belegen der Anwendung abgleichen. Die KI entscheidet nicht ueber steuerliche Einordnung oder Korrekturpflichten.

Beispielaufgabe:

```text
Formuliere eine sachliche Zusammenfassung dieser bereits geprueften Angaben. Uebernimm Zahlen unveraendert und erfinde keine Berechnung. Trenne Handels-/Swapvolumen, tatsaechliche EUR-Einzahlungen und EUR-Auszahlungen, Gewinne/Verluste und interne Transfers. Leite aus Handelsvolumen weder Einkommen noch eine Auszahlung ab. Kennzeichne fehlende Informationen.

Jahr, Stand, Kategorien, Einheiten und Belegkennungen:
[GEPRUEFTE ANGABEN]
```

### Pruefnotiz oder Fragenliste entwerfen

Aufgabentyp: `documentation`

- **Was Sie bereitstellen:** Die von Ihnen bereits festgestellten Tatsachen, offenen Punkte und zugehoerigen lokalen Belegkennungen.

- **Wobei die KI helfen kann:** Einen strukturierten Entwurf fuer die eigene Pruefung, den Support oder ein Fachgespraech erstellen.

- **Was Sie selbst pruefen muessen:** Entwurf selbst redigieren und Belegstellen pruefen. Die KI erstellt oder versendet keine Nachricht, kein freigegebenes Nachweispaket und keinen amtlichen Bericht.

Beispielaufgabe:

```text
Erstelle aus meinen Angaben einen neutralen Entwurf einer Pruefnotiz. Gliedere in: festgestellte Tatsachen mit meinen Belegkennungen, offene Fragen, ausdruecklich als solche bezeichnete Hypothesen, benoetigte Nachweise und naechste menschliche Pruefschritte. Erfinde keine Belegstellen und treffe keine steuerliche Entscheidung.

Meine geprueften Angaben:
[FAKTEN UND BELEGKENNUNGEN]
Noch offen:
[OFFENE PUNKTE]
```

## Was Die Aufgabentypen Bedeuten

| Auswahl | Kennung |
| --- | --- |
| Review | `review` |
| Risikopruefung | `risk_scan` |
| Importzuordnung | `import_mapping` |
| Dokumentation | `documentation` |

Diese Aufgabentypen sind derzeit nur organisatorische Kennzeichnungen im Verlauf. Sie aktivieren keine unterschiedliche Spezialanalyse, keinen anderen Datenzugriff und keine eigene Berechnungspipeline. Die konkrete Anweisung muss im Aufgabentext stehen; das gespeicherte Modell wird verwendet.

## Wofuer die KI nicht geeignet ist

- Keine automatische Gesamtauswertung: 'Pruefe alle meine Transaktionen' gibt der KI noch keinen Zugriff auf diese Transaktionen.

- Keine Datei- oder Bildanhaenge im KI-Formular. Eine genannte PDF, CSV, Dateiablage oder URL wird nicht gelesen. Benoetigte Auszuege muessen als Text eingefuegt werden.

- Keine angeschlossene Websuche und keine selbststaendige Binance-, Bitget-, Helium-, Helius- oder Solscan-Abfrage durch den Assistenten. Andere Funktionen der Anwendung sind davon getrennt.

- Kein vollstaendiger FIFO-Lauf, kein garantiert exakter Summenabgleich und keine verlaessliche Feststellung von Gewinn, Bestandsvollstaendigkeit oder steuerlicher Zuordnung durch die Modellantwort.

- Keine Erfindung fehlender Anschaffungen, Preise, Wechselkurse oder Belege zulassen. Unbekannte Werte bleiben offen und muessen an Quellen geklaert werden.

- Keine ungeprueften Direktbuchungen oder Loeschungen durch Modellantworten. Die KI hat keine SQL-, Datei- oder Shell-Werkzeuge. Nur der ausdruecklich freigegebene Datenkorrekturpfad darf unterstuetzte Felder aktualisieren und anschliessend die fachlichen Auswertungen neu berechnen.

- Keine steuerliche oder rechtliche Freigabe. Die Antwort beweist weder die Richtigkeit einer Erklaerung noch eine Pflicht, sie zu berichtigen. Solche Entscheidungen nicht allein auf das Modell stuetzen.

- Ein plausibel klingender Satz, eine Belegkennung, ein Link oder ein Hash in der Antwort ist kein Beweis einer Quellenpruefung. Nicht im Eingabetext belegte Aussagen am Original verifizieren.

## Ein sinnvoller Arbeitsablauf

1. Ziel klein und konkret waehlen. Den benoetigten Bericht, Hinweis oder Beleg zuerst selbst in der Anwendung oeffnen und einen geeigneten Ausschnitt bestimmen.

2. Angaben datensparsam vorbereiten: relevante Ueberschriften, Einheiten, Kontext und eigene Belegkennungen beibehalten. Namen, Konten und Transaktionskennungen gegebenenfalls konsistent ersetzen; die Originalzuordnung lokal aufbewahren.

3. Im KI-Assistenten einen Aufgabentyp und eine konkrete Anweisung zusammen mit dem benoetigten Text eingeben. Maximal 32000 Zeichen je Aufgabentext. Platzhalter in den Vorlagen muessen durch geeignete eigene Angaben ersetzt werden.

4. Vor Cloud-Versand den gesamten Text selbst pruefen. Erst danach die ausdrueckliche Freigabe fuer diesen Text setzen und die Aufgabe ausfuehren. Eine Modell- oder Texteinstellung ist keine automatische Freigabe aller Daten.

5. Die Antwort im Aufgabenverlauf lesen. Jede verwendete Aussage und Zahl an den eigenen Belegen oder den deterministischen Anwendungsergebnissen pruefen. Hypothesen als Hypothesen belassen.

6. Nur selbst gepruefte Inhalte in eine eigene Notiz uebernehmen. Fuer eine Folgefrage den notwendigen Kontext erneut angeben; es gibt keinen automatisch uebermittelten Chatverlauf.

## Daten, Modellwahl und Kosten

- Der Prompt wird nicht automatisch anonymisiert. Namen, Kontonummern, Wallet-Adressen, Steuernummern, persoenliche Dateipfade und andere vertrauliche Inhalte werden nicht automatisch aus dem Aufgabentext entfernt.

- Keine API-Keys, Passwoerter, Seed-Phrasen oder privaten Schluessel in den Aufgabentext schreiben. Der Provider-Key gehoert ausschliesslich in das dafuer vorgesehene Passwortfeld der Einrichtung.

- Bei OpenRouter/Cloud werden der freigegebene Aufgabentext und die feste Systemanweisung an den konfigurierten Dienst uebermittelt. Eigene Regeln des Anbieters und der Modellprovider zu Verarbeitung und Aufbewahrung vorab pruefen.

- Ein lokaler Endpunkt ist keine automatische Offline- oder Datenschutzgarantie: Ein Proxy kann seinerseits Cloud-Modelle aufrufen. Der Betreiber muss seine Serverkonfiguration und den Anwendungszugriff kontrollieren.

- Free beschreibt die Katalogpreise, nicht Datenschutz, fachliche Richtigkeit oder Verfuegbarkeit. Auch kostenlose Modelle koennen falsche Antworten liefern und Anbieterlimits haben. Keine automatische kostenpflichtige Ersatzmodellwahl durch die Anwendung.

- Die Anwendung speichert Aufgabentext, Status und Antwort lokal im Aufgabenverlauf; Konfiguration und Zugangsdaten werden getrennt verwaltet. Das Speichern einer KI-Aufgabe ist keine Aenderung von Transaktionen oder Steuerzeilen.

## Antworten und Status richtig lesen

- 'Verbindung erfolgreich' bedeutet, dass das Modell auf einen neutralen Test mit sichtbarem Text geantwortet hat. Es bestaetigt keine fachliche Eignung oder Pruefung Ihrer Daten.

- 'Abgeschlossen' bedeutet, dass eine sichtbare Antwort empfangen und gespeichert wurde. Es bedeutet nicht, dass die gestellte Sachfrage richtig oder vollstaendig geloest wurde.

- Eine Antwort am Tokenlimit kann unvollstaendig sein. Fehlgeschlagene oder nach Serverabbruch noch als laufend angezeigte Aufgaben nicht blind wiederholen; zuerst den Verlauf pruefen. Ein neuer Auftrag kann erneut Kosten oder Kontingent verbrauchen.

- Einrichtung und Modellwahl allein starten keine Analyse. Weder beim Oeffnen der Seite noch beim Speichern der Einstellungen wird automatisch ein Steuerbericht an die KI gesendet.

- Bei Datenkorrekturen bedeuten Vorgeschlagen und Vorschau bereit noch keine fachliche Datenbankaenderung. Erst Uebernommen bestaetigt das gemeinsame Speichern der Korrektur, der neu berechneten Auswertungen und des Freigabenachweises. Ein blockierter Export bleibt gesondert zu klaeren.

Weitere Anleitung: `frontend/public/benutzerleitfaden.html#pruefen`, `#jahre` und `frontend/public/importformate.html`.

Diese Anleitung beschreibt den implementierten KI-Arbeitsbereich. Sie bestaetigt weder die Qualitaet eines bestimmten Modells noch die Richtigkeit einer einzelnen Antwort.
