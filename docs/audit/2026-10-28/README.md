# Docker-Migrationsaudit 28.10.2026

Der eigenstaendige [Audit-Abschlussbericht](AUDIT_ABSCHLUSSBERICHT.md) enthaelt
Commit- und binaeren Diffbezug, PaketstatusA-F, alle25Referenzfaelle sowie
originale JUnit-Anlagen. Diese README ist nur der Einstieg, nicht die Abnahme.

**Unveroeffentlichter Entwicklungsstand 0.2.0rc33.dev0. Keine produktive
Umschaltung, Neuberechnung oder Methodenaktivierung. Keine fachliche Freigabe.**
Basis ist rc32 / `1aecfb131d189267a01a6303f5a9b67a5a99efe2`.
Implementierung auf Branch `audit/docker-migration-20261028`, separater Checkout.
Der Produktivcontainer auf Port18010 bleibt rc32. GitHub/main und Tags bleiben
unveraendert. Hoechstens drei ausfuehrende Agenten, getrennte Datenbanken.

## Einstieg Und Nachweise

- [Gemeinsamer Vertrag](VERTRAG.md): Identitaet, Preiszulassung, Frist,
  Datenbindung und Integrationsgrenzen, vor Agenten-Codeaenderungen abgestimmt.
- [Betriebsmanifest](deployment-manifest.json), [Funktionsmatrix](feature-parity.md),
  [Restore](backup-restore-proof.md), [Rueckweg](rollback.md).
- [Finales Entwicklungsimage](candidate-manifest.json), [Befundliste](BEFUNDE.md)
  und [Pruefprotokoll](PRUEFNACHWEISE.md).
- [Bewertung](PRICES_F02.md), [Methodenkatalog mit Primaerquellen](METHODENKATALOG.md).
- [Unabhaengige Abnahme G01-G25](ABNAHME_G01_G25.md): echte Teilproben,
  nicht gepruefte Umfaenge und verbleibende rote Faelle.
- [Reports-/UI-Nachweise](REPORTS_UX_HANDOFF.md): synthetische Antworten sind
  kein Nachweis einer steuerlichen Backend-Freigabe.

## Zuordnung Der Aenderungen

| Anforderung | Betroffene Bereiche | Validierung / Grenze |
| --- | --- | --- |
| F01 Installation identifizieren | `ops_inventory.py`, `ops_snapshot.py`, `ops_restore.py` | Read-only Istinventur; Offline-Restore/Neustart; keine behauptete Daten-/Methodenparitaet mit Legacy |
| F02 Altpreise nicht still nutzen | `domain/price_policy.py`, `price_lookup.py`, `derived_prices.py`, `valuation.py`, Preiscontracts | Gleicher positiver UTC-Tageskurs vor Ereignis; Lookup, SQL/Python-Coverage, Tax, Review und Export synthetisch geprueft |
| F03 Einheitliche Frist | `tax_time.py`, `tax_years.py`, `tax.py`, `reports.py`, CSV und Audit | Kalenderdatum Berlin, Jahrestag/Folgetag/Schaltjahr; alte Archive behalten gespeicherte Klassifikation |
| F04 Technisch nicht final | `filing_binding.py`, `product_readiness.py`, `exports.py`, `workspace.py`, API, Frontend | Ungebundener/veralteter Methodenstand nicht final; Vorschau im Paket; globale PDFs nie pauschale Jahresfreigabe |
| F05 V1 nicht als Soll definieren | Unabhaengige `acceptance_tests.py`, Methodenkatalog | Feste unabhaengige Sollwerte, keine Ruecksetzung auf V1-Ergebnisse |
| F06 Tagesreferenz offenlegen | Preisdiagnose und Readiness | Technische Zulassung ist keine genehmigte gleichmaessige Bewertungsmethode; historische Referenzpunkte erzeugen Reviewwarnung |
| EUR-Erwerbskosten | `tax.py` | Gesonderte EUR-Gebuehr zum EUR-Kauf einmal kapitalisiert; unabhaengiger G02-Fall |
| Unbelegte Nullbasis / Drittassetgebuehr | `review.py` | Zusaetzliche blockierende Hinweise; kein erfundener Erwerb, kein angeblich geloester Drittasset-Lotverbrauch |
| Jahresfreigrenzen | `private_disposal_threshold.py`, `tax_years.py`, API | Nur lesende Arithmetik mit ausdruecklich bestaetigtem Zusatzkontext, keine persoenliche Steuerprognose |

## Vertraege Und Grenzen

Bestehende Canonical-/Raw-/Preis-/Tax-Modelle bleiben massgeblich. Additiv sind
Preisdiagnosen, Methoden-/Eingangsbindung, Readiness-Dimensionen und Audit-
Klassifikationsmetadaten. Keine zweite Preisdatenbank, keine Schemamigration.
Gespeicherte Werte bleiben Decimal; frontendseitig keine neue Steuerrechnung.

`filing_state_binding_v1` bindet bestehende Daten, Entscheidungen, Ergebnisse
und Software-/Konfigurationsinputs. Export-/Archivmetadaten und laufende Job-
Fortschrittsdaten sind ausgenommen. Der Hash ist **kein pfadunabhaengiger
semantischer Finanzhash**. Exporte behalten ihren gespeicherten Bezug; eine
Inputaenderung sperrt die erneute Erzeugung alter gebundener PDFs. Historische
Abgabearchive werden nicht neu berechnet oder umetikettiert. Eine fehlende oder
unbekannte historische Klassifikation wird nicht still als steuerfrei gelesen.

`POST /api/v1/tax-years/{year}/private-disposal-threshold-assessment` ist lesend.
Nur mit `other_private_gain_loss_eur` und streng booleschem
`confirm_other_private_disposals_complete=true` wird ein Gesamtvergleich
angeboten. Ohne diesen Kontext: `context_required`, nicht angenommene Null.
Unterstuetzte Jahresregeln2009-2026; andere Jahre `unsupported_year`.
API-only, kein neues Eingabeformular; kein Verlustvortrag oder individueller
Steuersatz und niemals eine finale Freigabe durch diese Rechenhilfe.

## Offene Grenzen

Keine vollstaendige G01-G25-Abnahme: insbesondere Drittasset-Lotverbrauch,
vollstaendiger FX-Richtungs-/Wochenendpfad, Chain-/Contractidentitaet,
Migration/Wrapping, betrieblicher Scope, vollstaendige Kostenbasis und private
Alt-/Neu-Datenparitaet bleiben offen. Ein blockierender Hinweis ist eine
Absicherung, keine fachliche Fehlerbehebung. Keine neue Anbieterlastprobe.

Die benannte `BMF-Quellenpruefung-2026-10-28.md`, Docker-Nachpruefung,
Original-Reproordner und der separate API-Graph-Auftrag waren lokal nicht
auffindbar. Eigene Primaerrecherche und eigene Reproduktionen ersetzen nicht
die Behauptung, diese Dateien gelesen zu haben. Der Nutzer wurde nach dem Pfad
gefragt. Vorbestehende schmutzige Legacy-Checkouts blieben unveraendert.

## Pruefen Ohne Produktion

Projektvoraussetzungen aus `pyproject.toml` und `frontend/package-lock.json`
installieren. Alle Pfade/DBs fuer Tests ausserhalb der Software und getrennt
von produktiven Volumes halten. Keine `start_v2.sh`-Ausfuehrung: dieses Skript
veraendert die Legacy-Auslieferung und startet Prozesse neu.

```sh
python3 -m pytest tests/unit -q -n4 --dist loadfile --basetemp=/tmp/sr-audit-unit
python3 -m pytest docs/audit/2026-10-28/acceptance_tests.py -q --basetemp=/tmp/sr-audit-acceptance
python3 -m ruff check src tests scripts
python3 scripts/export_openapi_v2.py --check
python3 scripts/check_private_data_v2.py
```

Im Frontend: `npm ci`, `npm run build`. Browser: vorhandene
`check_ux_browser_v2.py --workspace-only` und
`check_migration_readiness_browser_v2.py --output /tmp/sr-audit-browser`.
Beide starten einen temporaeren lokalen Server, fangen API-Anfragen ab und
beenden ihn. Keine produktive Quelle als Browser-Testbasis verwenden.

Code-Review-Graph wurde lokal ohne Embeddings aufgebaut:505Dateien,
10546Knoten/141711Kanten, Status `ok`. Aufrufer der gemeinsamen Frist und
Importierer der Preispolicy wurden nachverfolgt. Der Graph ist ein lokales
Entwicklerhilfsmittel, kein steuerlicher Beleg und kein Releasebestandteil.
