# Vertrag: menschliche Preiszeit-/Methodenbestaetigung

Basis Draft #65, `88c49a5470839af2f78e60dafe36c59ed1ada6ba`.
Unveroeffentlichte Entwicklung, keine Produktiventscheidungen oder Migration.
Bestehende reine Zulassungsregeln, Originalreader und Legacy-Zeitdiagnose
weiterverwenden. Keine Erweiterung steuerlicher Regeln, keine automatische KI.

## Wirkung und Grenzen

- Menschliche Bestandsaufnahme genau einer importgebundenen Preis-ID an genau
  einem expliziten UTC-Bewertungszeitpunkt. Netzwerk/Contract/Dezimalstellen,
  Beobachtung oder Tagesperiode, Publikation, Kurswert/-waehrung, FX und
  Methodendokument werden ausdruecklich erfasst; nichts davon aus einem
  Quellenlabel oder einer gespeicherten Referenzzeit erfinden.
- Preis- und FX-Originalhash muessen zu den Originalen dieser konkreten
  Preis-ID gehoeren. Ein separates Methodendokument bis 2 MiB wird vom Nutzer
  hinzugefuegt. Originalbytes bleiben unveraendert; Hash/Locator allein ist
  keine automatische inhaltliche Echtheitspruefung.
- Reine Bibliothek `assess_price_evidence` bleibt unveraendert. Unterstuetzt
  Direkt-EUR, USD/FX in beiden Richtungen, beobachtete Quotes sowie die dort
  validierten ausdruecklichen Tagesmethoden. API speichert nur nach positiver
  technischer Pruefung und zwei expliziten menschlichen Bestaetigungen.
- Keine Aenderung von Raw-Daten, Canonical Events, Preisen, Ledger, FIFO,
  Steuerzeilen oder Jahresfreigaben. Nur private Belegartefakte vorbereiten
  und append-only Review-Entscheidungen speichern. Kein Provider-/KI-Aufruf.
- Stichtags-Gates duerfen eine positive Bestaetigung nur fuer ihre bereits
  ausgewaehlte konkrete Preis-ID mit identischem Wert/Quelle/Referenzzeit und
  exakt gleichem Bewertungszeitpunkt konsumieren. Bestehende Preiswahl,
  Same-Day- und Token-Risikopruefung bleiben unabhaengige Voraussetzungen.
  Eine zulaessige Tagesmethode erzwingt keinen Ersatz eines nicht ausgewaehlten
  Preises; keine stillen Zukunfts-/Altpreisersatzwerte.

## API und Modelle

Root `.../api/v1/prices/historical/previews/{preview_id}/prices/{price_id}`:

- `POST /admission-previews`: `PriceAdmissionDraftRequest` mit `request_id`
  (UUID), erwartetem `preview_sha256` und `price_fingerprint`,
  `valuation_at` (offsetbewusst), `identity`, `observation`, `method`,
  `method_original` (`filename`, `media_type`, `content_base64`),
  `actor`, `rationale`. Pflichttexte nicht leer, keine Floats fuer Decimal.
  Methode und Original-SHA muessen zusammenpassen; Quellen-/FX-SHA muessen
  in der konkret gebundenen Originalmenge liegen. Erfassungszeiten werden
  serverseitig auf den Zeitpunkt der Vorlage gesetzt und nicht als fruehere
  Beschaffung ausgegeben. Beobachtungs-/Publikationszeiten sind menschliche
  Transkriptionen. Der Client sendet weder Preis-ID-Alternative noch Preiswert-
  Ersatz noch ein fertiges Zulassungsergebnis.
- `GET /admission-previews/{request_id}`: gespeicherte Vorschau erneut lesend
  pruefen, kein Revalidierungswriter. Bestaetigung ist bis ausdruecklichem
  Apply `not_approved`; fehlende/ungueltige Nachweise liefern Grundcodes und
  erlauben keine Zustimmung. Eingaben/Originaldaten nicht still korrigieren.
- `POST /admission-previews/{request_id}/apply`: erwartet `draft_sha256` und
  zwei echte Pflichtbooleans `acknowledge_original_verified` und
  `acknowledge_scope_limited`. Beide muessen true sein. Server waehlt ID und
  Zeitpunkt; Benutzer/Begruendung aus der gebundenen Vorschau. Alles nochmals
  gegen Originale, Preiszeile, Vorschau und reine Bibliothek pruefen.
- `GET /admissions?valuation_at=...`: gebundene Entscheidung fuer diese
  Preis-ID und diesen Bewertungszeitpunkt lesen. Keine geheime Freitextsuche
  in URLs; Zeit/UUID sind alleiniger Kontext. Rueckgabe zeigt `human_approved`,
  `not_approved`, `rejected` oder `revoked`, niemals einen Gesamtfreigabestatus.
- `POST /admissions/{request_id}/revoke`: ausdruecklicher Widerruf mit
  erwartetem Entscheidungs-/Draft-Hash, Pflichtbestaetigung, Person und
  Begruendung. Append-only Gegenentscheidung; alte Entscheidung und Artefakte
  bleiben unveraendert. Kein stilles Update/Loeschen bei Korrektur.
- `GET /admission-previews/{request_id}/method-original`: nur die gebundenen
  geprueften Methodendokumentbytes als Download, keine freie Pfadangabe.

Domain-Service `PriceAdmissionService(store)` und neue Contracts
`contracts/price_admissions.py`. Rueckgabemodell `PriceAdmissionReport`:
IDs/Hashes, konkrete Preis-ID, Bewertungszeitpunkt, Beobachtung/Methode,
reines Assessment, `can_apply`, gespeicherte Entscheidung/Widerruf soweit
vorhanden. Stabile, geheimnisfreie Fehlermeldungen; keine privaten Systempfade.

## Speicherung, Integritaet und Nebenlaeufigkeit

- Artefakte unter bestehendem privatem historischen Root,
  `admissions/{request_id}/draft.json` plus hashadressiertem Methodendokument.
  Strikte UUID-/SHA-Pruefung, Descriptor-Reader mit `O_NOFOLLOW/O_NONBLOCK`,
  regulaerer Dateityp, 2 MiB je Original / 6 MiB Gesamtbudget. Keine grossen
  vorbereiteten Datenbanken zum Lesen laden. Keine Altararchive nachtragen.
- Vorschau-Hash bindet Request, serverseitige Erfassungszeit, Point-Fingerprint,
  Originalmenge, Methode, Cutoff und Bibliotheks-Policy. Wiederholte gleiche
  Request-ID liefert denselben Stand, abweichender Inhalt ist Konflikt.
- Apply unter bestehender hostlokaler DB-/Mutationssperre und SQL-Transaktion;
  Source-/Original-/Preispruefung und Append-only-Entscheidung zusammen.
  Deterministische Entscheidung `price-time-admission:{request_id}`, Scope
  `price_time_admission:{price_id}:{valuation_at-UTC-microseconds}`. Payload
  bindet Draft-SHA und reines Approval. DB-Zeiten und JSON-Zeiten exakt pruefen,
  keine Reparatur durch `list_review_decisions()` und kein "latest wins".
- Ein aktiver Widerspruch oder mehrere aktive Entscheidungen sind keine
  Zustimmung. Wiederholter Apply ist nur bei identischem intaktem Original-
  entscheid idempotent; keine zweite Preis-/Reviewwirkung. Widerruf ist eigener
  reservierter Entscheidungstyp, Korrektur erfordert neue Vorschau.
- Neue Entscheidungstypen im generischen Review-POST sperren: nur dedizierter
  validierter Ablauf. Keine Behauptung von Manipulationssicherheit gegen einen
  Administrator, der Software, Originale und DB gemeinsam ersetzen kann.

## Gate- und Laufvertrag

- Legacy-Assessment v1 und seine eingefrorenen Gegenproben unveraendert.
  Additives `price_admission` in Stichtagskandidaten, gesonderte Herkunft
  `operator_confirmed`, Fakten/Methoden nicht mit Legacy-Labels vermischen.
- `PortfolioPosition.price_id` optional/additiv; Stichtagssnapshot bindet die
  tatsaechlich gewaehlte PricePoint-ID. Kein Rueckwaertsraten nach Betrag.
- Resolver-API: `PriceAdmissionService.assess_selected(*, price_id,
  valuation_at, asset, price_eur, price_source, priced_at)` liefert
  `PriceAdmissionReport | None`; None nur wenn keine einschlaegige Entscheidung
  vorliegt. Fehler/veraenderte Belege sind nicht positiv und duerfen das Gate
  nicht gruenschalten. Keine Preiswahl oder Originalaenderung durch Resolver.
- Resolver-API `state_fingerprint(valuation_at)` liefert str | None:
  relevant gespeicherte Entscheidungen/Widerrufe plus aktuelle Original-/Preis-
  pruefung binden. None nur ohne einschlaegige Entscheidungen. Begrenzte Anzahl,
  kein ausufernder Scan aller privaten Dokumente. Fehler nicht als leer werten.
- `DivorceValuationGate.price_admission_state_sha256` additiv/default None;
  neuer Lauf speichert Zustand beider Cutoffs in allen vier Gatekopien.
  Aktuelle Anzeige/Downloadkennzeichnung prueft neben bisheriger Zeitpolicy
  den aktuellen Belegzustand. Alte archivierte Bytes bleiben per ID lesbar,
  geaenderte Entscheidungen/Originale/Preise machen alte Erfolge veraltet.
- Ohne neue Entscheidungen bleibt bestehendes Legacy-Verhalten samt EUR-
  Identitaet erhalten. Keine universelle Steuer-/Jahres-/Rechtsfreigabe aus
  einem erfolgreichen Preiszeit-Gate ableiten.

## Benutzerablauf und Abnahme

Importbindung pruefen -> Fakten/Methode eingeben und Methodendokument waehlen
-> technische Vorschau pruefen -> zwei explizite Bestaetigungen -> speichern
-> erneuter lesender Status/Gate. Eingaben bei Fehler erhalten; nach Aenderung
oder Revalidation alte Zustimmung/Preview deaktivieren. Keine Auto-POSTs beim
Oeffnen, Raten fehlender Datumswerte oder Secrets in URL/Log/Fixtures.

Eigene Checkouts/DBs; unabhaengige feste Sollwerte fuer Direkt-EUR, beide FX-
Richtungen, Tagesmethoden, Berlin-Datumsgrenzen und Belegzeitgrenzen; Preis-/
Import-/Entscheidungs-/Methodenoriginalwechsel, falsche UUID, ungultige Acks,
Idempotenz, Widerruf, mehrere Entscheidungen, laufende/scheiternde Requests,
stale Run und archivierte Bytes. Voller echter synthetischer Weg bis Gate,
keine echten Zustimmungen. Browser 390/768/1280/1440 und Tastatur.
