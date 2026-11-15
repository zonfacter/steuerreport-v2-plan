# Issue #52: begrenzter Teilfix der Referenz-Aggregatbindung

Historischer Handoff zur Vorstufe `6ee5146`. Der aktuelle Reviewstand und die
wiederhergestellte Vergleichsfunktion sind in
[ISSUE52_VERGLEICH_INTEGRATION_2026-11-15.md](ISSUE52_VERGLEICH_INTEGRATION_2026-11-15.md)
beschrieben; die untenstehende pauschale Aggregatsperre ist dort ersetzt.

## Arbeitsstand und Isolation

- Eigene Branch: `codex/issue52-archive-binding-20261115`.
- Eigener Worktree: `/root/steuerreport-issue52-archive-binding-20261115`.
- Ausgangscommit: `541011c`, mit lokalem `origin/main` auf `96c5ad5`.
  Kein Fetch, Push, Deployment oder Providerzugriff.
- Ausgangsworktree `/root/steuerreport-issue20-reconciliation-20261102` hatte
  zehn uncommittete Dateien. Status und `AGENTS.md` wurden vorab gelesen.
  Er blieb unveraendert. Sein vorhandener Snapshot-Entwurf aus
  `domain/tax_filing_snapshots.py`, `contracts/tax_filing_snapshots.py`,
  `tests/unit/test_tax_filing_snapshots.py` und `docs/API_CONTRACTS_V2.md`
  wurde in den eigenen Worktree kopiert und dort weiter geprueft/gehaertet.
  API-/Frontendaenderungen des Ausgangsworktrees wurden nicht uebernommen.
- Domain-Sicherungen fuer Audit und Methodik entsprechen den dort bereits
  vorhandenen Guard-Entwuerfen; der Audit-Guard greift vor der Zusatzberechnung.
  Keine Bearbeitung der parallelen #49-Worktrees.

## Gesicherte Eigenschaft

`TaxFilingSnapshotService._to_contract` liest das Archiv einmal, prueft seinen
Paket-SHA-256 und validiert genau diese Bytes. Werte werden nur ausgegeben,
wenn Manifest-Hash, Register-Summary und archivierte Summary zusammenpassen.
Die Summary muss eindeutig manifestiert sein; alle manifestierten Dateihashes
und Groessen werden erneut geprueft. Die ausgegebenen Geldwerte stammen aus
der archivierten Summary, nicht aus den numerischen DB-Spalten.

Fehlende, ungueltige, nicht endliche oder nicht gebundene Referenzwerte ergeben
`values=null`. Es gibt keine finanzielle Null-Ergaenzung. Bei neuen Paketen
werden solche Summaries vor Archiv- und Registerschreibzugriffen abgewiesen.
Bereits gespeicherte Altarchive bleiben unveraendert lesbar/herunterladbar,
wenn ihr Paket-Hash stimmt, liefern aber keine vertrauenswuerdigen Werte.
JSON-Dezimalzahlen werden ohne Float-Rundung gelesen. Doppelte JSON-Schluessel
und Manifestpfade werden nicht still auf einen vermeintlichen Gewinner reduziert.

Falsches Jahr, fehlende explizite Felder und ungueltige aktuelle Summaries
liefern ebenfalls keine Ersatznullen. Weil die aktuelle Berechnung weiterhin
nicht an einen konsistenten Datenstand gebunden ist, bleibt der Vergleich
konservativ `not_compared`, mit leeren Deltas und unbekannten (`null`)
Aenderungsflags. Das behauptet weder Gleichheit noch Unterschied.

## Synthetische Pruefung

`tests/unit/test_tax_filing_archive_binding.py` erzeugt seine Pakete und
Erwartungen unabhaengig von den Paket-/Feldhelfern des Produktivcodes.
Verwendet werden ausschliesslich temporaere synthetische DuckDBs und ZIPs.

- Gegencheck in eigenem, detached Basis-Worktree
  `/root/steuerreport-issue52-counterexample-base-20261115` auf `541011c`:
  Alle sechs DB-only-Feldmanipulationen scheitern erwartungsgemaess am
  Sicherheitsanspruch. Der separate Gegenfall Archiv 100 EUR / Register 0 EUR /
  aktuelle Summe 0 EUR liefert dort nachweislich faelschlich `equal`.
- Im Teilfix bestehen alle 46 unabhaengigen Faelle, einschliesslich dieses
  100/0/0-Gegenfalls, expliziter echter Null, JSON-Praezision, fehlender Felder,
  null/ungueltiger Werte, Altarchive mit falschem Jahr, unmanifestierter Summary,
  Dateihash-/Groessenfehler, Mehrdeutigkeiten und fehlendem aktuellem Summary.
- Ein ungebundener bestaetigter Stand blockiert die Methodik fuer sein Jahr;
  kein stiller Rueckfall auf eine aeltere bestaetigte Revision. Der Auditdienst
  verweigert die Verarbeitung ungebundener Referenzwerte.
- Der bestehende Cross-Year-Gegenfall behaelt unabhaengig vorgegebene,
  gegenlaeufige Einzelabweichungen und prueft weiterhin bytegleiche Archivpakete.
  Er erwartet keinen positiven Aggregatvergleich mehr.

Reproduktion im eigenen Worktree, mit eigener `.venv` (Systempakete plus lokal
installiertem `PyNaCl==1.6.2`, da es der Testumgebung fehlte):

```bash
.venv/bin/python -m pytest tests/unit/test_tax_filing_archive_binding.py tests/unit/test_tax_filing_snapshots.py tests/unit/test_tax_filing_audit.py tests/unit/test_tax_methodology.py tests/unit/test_cross_year_offsetting_parity.py tests/unit/test_cross_year_fifo_parity.py tests/unit/test_bmf_compliance.py -q --tb=short
```

Finales Ergebnis: **109 bestanden, 1 xfailed**, Laufzeit 146,58 Sekunden.
Der erwartete Fehler ist ausschliesslich die fehlende CSV-Statusausgabe.
Eine bestehende `load_module()`-Deprecation-Warnung wurde ausgegeben.
Ruff fuer alle geaenderten Python-Dateien und `git diff --check` bestanden.
API-/Frontend-Diff ist leer; der eigene Worktree wird nach dem lokalen Commit
sauber hinterlassen. Autor und Committer: `Code Contributor`,
`contributor@example.invalid` (nur fuer diesen Commit gesetzt).

## Offene Grenzen vor Integration

- Keine vollstaendige Loesung von #52 und keine Deploymentfreigabe.
- `src/steuerreport_v2/api/app.py`: Die CSV schreibt bei leeren Deltas nur ihre
  Kopfzeile, keinen Nichtvergleichsstatus. Der gezielte CSV-Gegenfall ist mit
  `xfail(strict=True)` explizit offen und darf nicht als bestanden gelten.
  HTML uebernimmt Domain-Warnungen, zeigt aber fuer leere Deltas faelschlich
  einen fehlenden Archivstand; auch die Ton-/Farbwahl muss angepasst werden.
- `frontend/src/main.tsx`: Leere Deltas und unbekannte Aenderungsflags werden
  weiterhin als fehlende Cent-Abweichung dargestellt. Nullable Werte und neuer
  Status sind in den bisherigen TypeScript-Vertraegen nicht abgebildet.
  Beides liegt ausserhalb dieses Schreibauftrags und wurde nicht geaendert.
- `comparison_scope` ist zum Einlesen alter Antworten optional; unbekannter
  Umfang bedeutet nicht Paritaet. Geldfelder haben keine Null-Defaults mehr.
  Diese Aenderungen sind in `docs/API_CONTRACTS_V2.md` beschrieben und muessen
  von Verbrauchern vor Integration uebernommen werden.
- Aktueller Datenbankstand/Cache, Ereignisse, Lots, Tax-Lines und historische
  Eingaben/Methoden sind nicht miteinander reconciliert. Auch der separate
  Auditdienst schliesst diese Provenienzluecke nicht.
- Die Register-Hashes sind keine unabhaengige Signatur. Koordinierte Aenderung
  aller Hashanker und des Archivs ist nicht abgedeckt. Keine neuen ZIP-Limits,
  Produktionsdatenpruefung, echte V1-Ausfuehrung oder Remote-CI.
