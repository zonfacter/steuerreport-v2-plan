# Steuerreport V2 0.2.0rc36

Releasekandidat vom 29.10.2026. Diese Version enthaelt mehrere issuebezogene
Import-, Konfigurations-, Bewertungs- und Docker-Pruefpfade. Sie ist weder eine
amtliche Zertifizierung noch eine steuerliche Freigabe eines Jahres.

## Aenderungen

- **GitHub #4:** MEXC Spot- und Funding-Dateien koennen in einer isolierten
  Vorschau mit Konto-, Exportart- und Zeitbasisbindung geprueft werden.
  Die Exportart wird vor der ersten Pruefung je Datei festgelegt; ein Wechsel
  des Pruefkontexts verwirft die alte Vorschau und Zeilenentscheidungen.
  Dubletten, unklare Statuswerte und nicht belegte Erwerbe werden nicht still
  bestandswirksam. Es wurde kein produktiver MEXC-Zugang verwendet.
- **GitHub #9:** Der Image-Publish verlangt einen synthetischen Benutzerpfad
  vom Dateiimport bis zum Jahresbericht und Abgabepaket sowie einen
  Neustart-Persistenztest in einem frischen, netzwerkisolierten Container.
- **GitHub #10 / PR #21:** Ein fehlender oder unpassender Vault-Schluessel darf
  vorhandene Daten nicht teilweise wiederherstellen oder durch einen neuen
  Schluessel ersetzen. Vorhandene verschluesselte Werte werden vor dem Start
  lesend auf Entschluesselbarkeit geprueft.
- **GitHub #12 / PR #24:** Solana-Ownership-Konfigurationen werden typisiert
  validiert. Eine unlesbare optionale Datei blockiert nicht mehr die gesamte
  Installationsseite; der betroffene Dateiabruf meldet den konkreten Fehler.
- **GitHub #13 (Teilumfang):** Binance-Spot-Dateiimporte lassen sich an eine
  explizit ausgewaehlte Verbindung binden. Ein globaler CSV/API-Abgleich und
  persistente quellenuebergreifende Matchentscheidungen bleiben offen.
- **GitHub #14:** Binance-Earn-Historien werden in verbindungsgebundenen
  HistoryJobs verarbeitet. Live-Anbieterabdeckung und Produktivdaten wurden
  nicht getestet.
- **GitHub #15:** Offene historische EUR-/FX-Preise koennen mit getrennten,
  hashgebundenen Originalbelegen in einer isolierten Vorschau bearbeitet
  werden. Es gibt keinen stillen Wechselkurs und keine automatische Uebernahme.
- **GitHub #16:** Ein gebundener Methoden-Pruefstand fuer 2021 bis 2025 kann
  ausdruecklich erzeugt oder erneuert werden. Er genehmigt keine Methode und
  gibt kein Steuerjahr frei.
- **GitHub #17:** Manuelle Korrekturentwuerfe behalten den exakten Ziel-,
  Aufgaben-, Quellen- und Belegkontext. Veraltete Ziele werden nicht
  automatisch ueberschrieben.
- **GitHub #18:** Steuerjahresbezogene PDF-Vorschauen und zugehoerige
  Manifest-/Hash-Artefakte werden an denselben Lauf gebunden und archiviert.
  Sie sind keine finale Abgabe. Jedes PDF bleibt auf hoechstens 100 Seiten
  begrenzt.
- **GitHub #22 (Teilumfang):** Leere zusaetzliche CSV-Endfelder bleiben als
  Raw-Zeile nachvollziehbar; nichtleere unbekannte Endfelder werden nicht
  still verworfen. Zeitzone, Produkt-/Kontoscope, Margin-Gebuehren und
  Quote-Leg-Paarung bleiben offen.

## Pruefstand

Die lokale Integration wurde gezielt mit synthetischen Daten getestet. Die
Veroeffentlichung und das Containerpaket sind erst bestaetigt, wenn der
GitHub-CI-Lauf fuer genau diesen Release-Commit erfolgreich ist und dessen
Image-Digest als Release-Nachweis vorliegt. Vorhandene lokale Tests und
Browserproben sind kein Ersatz fuer diesen CI-Nachweis.

Der Docker-Benutzerpfad wurde zusaetzlich lokal auf einem separaten frischen
rc35-Testcontainer mit anonymem Datenvolume, deaktiviertem Netzwerk und
schreibgeschuetztem Root-Dateisystem erfolgreich ausgefuehrt. Dieser Nachweis
gilt fuer das Ausgangsimage rc35, nicht fuer rc36. Das produktive rc35-Volume
wurde dabei nicht verwendet oder veraendert.

## Noch offen

- **GitHub #8, #19 und #20:** Die native Legacy-Laufzeit, die tatsaechlich
  verwendete Datenbank und eine semantische Alt-/Neu-Datenparitaet sind noch
  nicht eindeutig nachgewiesen. Daher gibt es keinen belegten Restore- oder
  Migrationsnachweis fuer Betreiberbestandsdaten.
- **GitHub #22:** Die oben genannten Bitget-CSV-Teilprobleme bleiben offen.
- **GitHub #13:** Der quellenuebergreifende Abgleich zwischen CSV und API sowie
  eine dauerhafte Matchentscheidung sind nicht enthalten.
- Es erfolgte keine produktive Neuberechnung, Methodenaktivierung, Aenderung
  historischer Finanzdaten oder automatische Review-Entscheidung.
- Keine vollstaendige fachliche Steuerabnahme fuer reale Nutzerbestandsdaten.

## Bereitstellung

Image-Referenz nach erfolgreicher Veroeffentlichung: `ghcr.io/zonfacter/steuerreport-v2:0.2.0rc36`.
Der konkrete Digest und Quellcommit muessen aus dem erfolgreichen
Publish-Workflow uebernommen werden. Ein Produktivupdate erfordert zusaetzlich
eine konsistente Sicherung einschliesslich DuckDB, Profil, Konfigurationen,
Originalbelegen und Vault-Schluessel sowie einen nachgewiesenen Rollback.
