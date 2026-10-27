# Solana-Historienimport: Fehlerkorrektur

Stand: 27.10.2026. Ausgangsstand: `ec2544b` / `0.2.0rc19`.
Patch fuer `0.2.0rc20`. Die untenstehenden Funktionstests erfolgten vor der
Veroeffentlichung ausschliesslich isoliert. Kein produktiver Historienimport
und keine automatische Korrektur bestehender Finanzdaten. Release-/Deployment-
Nachweise werden gesondert am GitHub-Release bereitgestellt.

## Korrigierte Fehler

| Fehler | Umsetzung | Regressionstest |
| --- | --- | --- |
| Ueberlappende Seiten erhoehen einen bereits importierten Bestand erneut | Wallet/Signatur und vollstaendigen Rohzeilensatz vor Schreiben vergleichen; bekannte Transaktionen ueberspringen | A, Retry A, A+B, Retry, kompletter Rebuild |
| SOL-Gebuehr wird als Kaufgegenwert interpretiert | Gebuehr von nativer Bewegung abziehen, separat genau einmal als negative Gebuehr buchen | Tokenzufluss + nur SOL-Gebuehr; echter SOL-Abgang + Gebuehr |
| Tokenzufluss wird ohne Beleg Einkommen/Reward | Direkte Mapper-v2-Zeilen umgehen alte Income-/Swap-Heuristik | Keine Trade-/Income-/Reward-Events aus blossen Deltas |
| Fehlgeschlagene Transaktion wird als Trade verbucht | Bei `meta.err` nur nachgewiesene Gebuehr des Wallet-Gebuehrenzahlers | Failed-Transaktion mit bewusst widerspruechlichen Testdeltas |
| Nachgelagerte Preisheuristik deutet Gegenfluesse als Kaufpreis | Unklassifizierte v2-Transfers aus der Gegenfluss-Preisableitung ausschliessen | SOL-Preis vorhanden, aber kein erfundener Tokenpreis |
| Fehlendes Detail wird ausgelassen, Cursor laeuft weiter | Seite vor jedem Import vollstaendig lesen und validieren; sonst Fehler | Fehlendes/null/unvollstaendiges zweites Detail, Datenbank unveraendert |
| Unterbrochener Import gilt beim Retry als Erfolg | Erfolgscheckpoint erst nach kompletter Pipeline, vor erneuter Normalisierung invalidieren | Fehler beim Raw-Load; Fehler nach Loeschen abgeleiteter Events |
| Leere Seite ist beim zweiten Abruf Konflikt | Nur erfolgreich berechneten echten Leerabruf abschliessen | Leere Seite zweimal, zweite Anfrage ohne Datenveraenderung |
| Mehrere Store-Instanzen umgehen Importsperre | Gemeinsame POSIX-Dateisperre fuer Pruefung, Schreiben und Pipeline | Zweites Store-Handle wird abgewiesen; nach Freigabe wieder moeglich |
| Mint wird durch Grossschreibung/Kuerzung verwechselt | Exakte konfigurierte Solana-Mints; unbekannte Identitaeten als Hash des exakten Mints | Unterschiedliche Gross-/Kleinschreibung, fehlender Owner, exakte Mengen |

## Betroffene Komponenten

- `importers/solana_history_mapper.py`: defensive RPC-Validierung, Mengen,
  Gebuehren und unveraenderte Antwortinhalte als deterministisches JSON.
- `importers/solana_history_identity.py`: eindeutige Transaktionen,
  Konflikterkennung und gemeinsame Importsperre.
- `domain/portfolio.py`: Integration, begrenzter Seitenabruf, Wiederholungsstatus
  und exakte Mintzuordnung aus vorhandener Assetkonfiguration.
- `importers/raw_normalizer.py`: gezielte v2-Ausnahmen; bestehende Legacy-Regeln
  und Ausschluss fremder Transaktionen bleiben erhalten.
- `domain/derived_prices.py`: keine Gegenfluss-Preisannahme fuer ungeklaerte v2-Transfers.
- `domain/pipeline.py`: belastbarer Erfolgscheckpoint fuer Solana-Batches.
- `domain/review.py`: blockierender Hinweis fuer noch nicht fachlich eingeordnete Bewegungen.
- `api/app.py`: Konflikt 409, fehlende Wallet 422, unvollstaendige Seite 502.

## Pruefungen

- Neue Mapper-/Integrationstests: **83 bestanden**; ausschliesslich synthetische
  Antworten und temporaere DuckDBs, keine externen Provider-Aufrufe.
- Vollstaendige Testsuite am finalen Code: **1518 bestanden, 4 uebersprungen**
  in 470,85 Sekunden. Vier bestehende `load_module`-Deprecation-Warnungen,
  keine Testfehler.
- `ruff check src tests scripts`: erfolgreich.
- `git diff --check`: erfolgreich.
- `npm run build`: erfolgreich; bekannte Vite-Warnung fuer Bundle ueber 500 kB.
- OpenAPI-, Endpoint-, Importformat- und KI-Leitfaden-Pruefungen: erfolgreich.
- `scripts/check_private_data_v2.py`: keine Default-Privacy-Verletzungen.
- Gitleaks fuer Importer und neue Integrationstests: keine Funde.
- Gitleaks fuer den getrackten Source-/Test-Diff: keine Funde.
- Zusaetzlicher isolierter Zwei-Prozess-Smoke-Test: zweiter Prozess waehrend
  Importsperre abgewiesen, nach Freigabe erfolgreich; keine Provider-Aufrufe.
- Zusaetzlicher FastAPI-Smoke-Test mit gesperrtem Netzwerk: Erstimport,
  Ueberlappung und Retry jeweils HTTP 200; insgesamt vier Events (Transfers und
  Gebuehren), keine Trades. Fehlendes Detail: HTTP 502 ohne weitere Events oder
  Ausgabe der Testsignaturen im Fehlertext.
- Zwei zusaetzliche Agents fuer Mapper/Tests und unabhaengige Fehlerpruefung;
  `code-review-graph` zur Abhaengigkeits-/Aenderungspruefung verwendet.

Die erste, waehrend der Nacharbeit gelaufene Gesamtsuite hatte 1511 bestandene
und 4 uebersprungene Tests. Sie ersetzt nicht den erneuten Lauf am finalen Code.

## Grenzen

- Kein neuer Browser-Assistent, persistenter Historienjob, Pause/Resume oder
  kompletter Wallet-Abruf. Quellen-Sync liest weiterhin nur Bestaende.
- Keine automatische Behebung bereits vorhandener Doppelimporte. Abweichende
  Belege und unvollstaendige Vorimporte bleiben erhalten und erfordern Pruefung.
- Noch keine neue dauerhafte Konfliktakte: eine widerspruechliche Antwort wird
  abgewiesen; die bestehenden Originalbelege bleiben unveraendert.
- RPC-Antworten stehen an erzeugten Rohzeilen. Transaktionen ohne jede
  zurechenbare Bewegung/Gebuehr erzeugen weiterhin keine solche Rohzeile.
- Ungeklaerte Bewegungen bleiben exportblockierend. Keine automatische
  steuerliche Klassifizierung oder Anerkennung einer Review-Entscheidung.
- Die POSIX-Sperre verhindert konkurrierende Historienimporte, ist aber weder
  transaktionaler Rollback der gesamten Pipeline noch allgemeiner DuckDB-
  Mehrprozess-Schreibkoordinator. Fehler werden nicht als Erfolg bestaetigt.
- Keine Aussage ueber Vollstaendigkeit der realen Historie oder steuerliche
  Richtigkeit eines konkreten Nutzerbestands allein aufgrund dieser Tests.

## Lokal nachpruefen

In einer isolierten Entwicklungsinstallation mit den Projekt-Dev-Abhaengigkeiten:

```sh
python3 -m pytest tests/unit/test_solana_history_mapper.py tests/unit/test_solana_history_import_safety.py -q
python3 -m pytest tests/unit -n 4 --dist loadfile -q
ruff check src tests scripts
```

Die Tests setzen das synthetische Profil und sperren externe Netzwerke.
Keine dieser Pruefungen erfordert den produktiven Datenpfad oder API-Zugaenge.
