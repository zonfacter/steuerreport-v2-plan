# Vertrag: positiver, menschlich gepruefter Stichtagsbeleg

Entwicklungsvertrag vom 15.11.2026 auf `376bea69e80d7172049adfb3b57e70ca2b14d9eb`.
Er ersetzt weder den Legacy-Guard noch eine fachliche Methodenfreigabe.
Produktion, Originalimporte, Preise, Tax-/FIFO-Werte und Archivlaeufe bleiben
unveraendert. Kein allgemeines Verbot belegter Tagesmethoden implementieren.

## Wiederverwendung und Abgrenzung

Die vorhandenen historischen Preisvorschauen archivieren Originalbytes,
Metadaten, Vorschauhash und Apply-Entscheidung. `historical_price_import`
ist keine Preiszeit-/Methodenzulassung. Eine Tokenentscheidung ist es ebenso
wenig. Keine zweite Preisdatenbank oder ungebundene Freitextfreigabe einfuehren.

Der naechste Baustein ist eine reine Zulassungspruefung mit expliziten Inputs:
ausgewaehlter `PricePoint`, Original-Assetidentitaet, Bewertungszeitpunkt,
strukturierte Beobachtung, dokumentierte Methode, bestehende menschliche
Review-Entscheidung und Originalbytes. Kein DB-/Datei-/Providerzugriff in
dieser reinen Funktion. Reader, API, Bedienablauf und Speicherung folgen als
separate Integration und sind durch diesen Vertrag noch nicht implementiert.

## Nachweis und Vertrauensgrenze

PDF-/CSV-Fakten lassen sich nicht allein aus einem Dateihash bestaetigen.
Die strukturierte Transkription wird daher ausdruecklich als **menschlich
geprueft** gekennzeichnet, nicht als automatisch bestaetigte Anbieterantwort.
Eine spaetere API darf eine Clientbehauptung ueber eine Freigabe nicht als
gespeicherte Entscheidung behandeln: Der Server muss sie aus dem bestehenden
Review-Store laden und die Inputs/Originale erneut pruefen. Ein reiner Parser
oder ein bestandener Hashvergleich ist keine steuerliche/rechtliche Abnahme.

## Eingaben

- Assetidentitaet: Netzwerk, Contract/Mint beziehungsweise explizite native
  Identitaet und Dezimalstellen. Nicht allein Symbolgleichheit verwenden.
- Kurs: konkrete Preis-ID, unveraenderter vollstaendiger PricePoint-Fingerprint
  inklusive Wert, Zeit, Quelle und Konfidenz. Decimal; keine Floatrechnung.
- Beobachtung: Originalhash, genaue Fundstelle, Originalquelle, Quote-Waehrung,
  Wert, Beobachtungszeit oder Tagesperiode, eigenstaendige Veroeffentlichungszeit
  und Erfassungszeit. Naive Zeiten ablehnen, nicht als UTC erfinden.
- Direkter EUR-Preis eines Nicht-EUR-Assets benoetigt keinen FX-Beleg; er ist
  aber keine zeitlose EUR-Identitaet.
- USD benoetigt einen separaten FX-Originalbeleg mit Basis, Quote, positivem
  Rohkurs, Referenz-/Veroeffentlichungs-/Erfassungszeit und dokumentierter
  maximaler Referenztagsabweichung. Beide Quotierungsrichtungen unterstuetzen.
  Keine implizite USD-/Stablecoin-Paritaet oder stillen FX-1-Fallbacks.
- Methode: ID/Version, Originalhash einer Methodenbeschreibung, Referenzart,
  Zeitzone und ausdrueckliche Verfuegbarkeitsregel. Tagesdurchschnitt,
  Tageszeit und Tagesschluss getrennt benennen. Eine beobachtete Quote hat
  keine erfundene Tagesperiode; ein Tageswert keine erfundene Beobachtungszeit.
- Entscheidung: eigener Typ `stichtag_price_time_admission`, ID, Actor,
  Begruendung und ausdrueckliche Bestaetigungen der Originalpruefung sowie
  beschraenkten Wirkung. Bindung an den kanonischen Hash aller obigen Inputs
  einschliesslich genauem Bewertungszeitpunkt, Methode und Identitaet.
  Eine aktualisierte/fehlende/anders gebundene Entscheidung reicht nicht.

## Zeit- und Wertregeln

1. `available_at_cutoff`: Beobachtung beziehungsweise Referenzperiode sowie
   Preis-/FX-Veroeffentlichung liegen spaetestens am Bewertungszeitpunkt.
   Spaetere Erfassung kann eine fruehe Veroeffentlichung weder beweisen noch
   ersetzen. Erfassung darf nicht vor der angegebenen Veroeffentlichung liegen.
2. `retrospective_daily_reference`: nur fuer ausdruecklich beschriebene und
   menschlich fuer diesen Zweck zugelassene Tagesmethoden. Eine spaetere
   Veroeffentlichung bleibt sichtbar. Keine Umbenennung zum Intraday-Kurs.
3. Tagesperioden umfassen genau einen lokalen Kalendertag der Methoden-
   Zeitzone; Sommerzeitwechsel beachten. Der Bewertungszeitpunkt und der
   gespeicherte Tagesanker gehoeren zu dieser Periode. Keine implizite
   Uebernahme einer steuerlichen Tagesregel fuer familienrechtliche Zwecke.
4. Beobachtete Direktkurse stimmen mit Zeitpunkt und Wert des ausgewaehlten
   Preisobjekts ueberein. Direkte EUR-Werte stimmen exakt ueberein; USD/FX
   muessen nach dokumentierter DECIMAL(38,18)-Quantisierung denselben Wert
   ergeben (explizit `ROUND_HALF_EVEN`, keine Abhaengigkeit vom globalen
   Decimal-Kontext). Nicht endliche, nicht positive oder nicht darstellbare
   Werte sperren.
5. Alle benoetigten Originalbytes werden gegen ihre SHA256 geprueft. Fehlende,
   geaenderte oder mehrdeutige Inputs sperren. Keine Suche nach einem guenstigeren
   Ersatzbeleg und keine automatische Anerkennung der methodischen Entscheidung.

## Ausgabe und Integration

Separater versionierter `PriceEvidenceAdmission`-Vertrag. Der bestehende
`PriceTimeAssessment` bleibt die Legacy-Diagnose ohne nacherfundene Felder.
Ein positiver Beleg ist als menschlich gepruefte Originalzuordnung sichtbar;
kein amtliches Guetesiegel und keine globale Jahres-/Dossierfreigabe.
Ohne gueltige Bindung bleibt der Legacy-Guard unveraendert wirksam.

Vor Anbindung an ein Gate sind erforderlich: serverseitiger Reader mit
Original- und Reviewbindung, expliziter Vorschau-/Annahmeablauf, verstaendliche
UI, gemeinsame Freshness-/Policy-Marker fuer alle vier Run-Gates und native
API-/Browser-Gegenproben. Ein reiner Modul-/Unitnachweis reicht nicht.

## Unabhaengige Pflichtproben

Direkt-EUR positiv mit gebundener menschlicher Zustimmung, ohne Zustimmung
negativ; spaete Veroeffentlichung im Verfuegbarkeitsmodus negativ; dokumentierter
retrospektiver Tageswert positiv und als solcher benannt; Aenderungen an
Original, Wert, Identitaet, Zeitpunkt, Methode oder Zustimmung negativ;
USD in beiden Richtungen mit identischem EUR-Ergebnis; FX-/Originalluecken
und unbekannte Provenienz negativ. Naive Zeiten, Sommerzeitgrenzen und
Boolean-/Float-/nicht endliche Werte gesondert pruefen. Legacy-43er-Proben
und alle bestehenden unabhaengigen Referenzdateien unveraendert erhalten.

## Abgestimmte reine Python-Schnittstelle

Neue Dateien `contracts/price_evidence.py` und `domain/price_evidence.py`:

```python
price_evidence_binding(*, point: PricePoint, identity: PriceEvidenceIdentity,
                       valuation_at: datetime, observation: PriceEvidenceObservation,
                       method: PriceEvidenceMethod) -> str
assess_price_evidence(*, point: PricePoint, identity: PriceEvidenceIdentity,
                     valuation_at: datetime, observation: PriceEvidenceObservation,
                     method: PriceEvidenceMethod, approval: PriceEvidenceApproval | None,
                     originals: Mapping[str, bytes]) -> PriceEvidenceAdmission
```

Pydantic-Modelle, `extra=forbid`, keine Float-/Boolean-Werte fuer Decimal- und
Versionsfelder. Ablehnung fehlerhafter Vertragsinputs per ValidationError;
gueltig geformte, aber unpassende Belege ergeben eine negative Admission.
Hashes binden kanonisch normalisierte UTC-Zeiten und Decimal-Zahlenwerte,
nicht unterschiedliche Schreibweisen desselben Zahlen-/Zeitwerts.

- `PriceEvidenceIdentity`: `asset`, `network`, `contract`, `decimals`.
- `PriceEvidenceFx`: `base`, `quote`, `rate`, `reference_at`, `published_at`,
  `captured_at`, `evidence_sha256`, `locator`, `source`. Genau USD/EUR oder
  EUR/USD, niemals gleiche Waehrungen.
- `PriceEvidenceObservation`: `identity`, `quote_currency` (EUR/USD), `value`,
  `kind` (`observed_quote`/`daily_reference`), `observed_at`, `period_start`,
  `period_end`, `published_at`, `captured_at`, `evidence_sha256`, `locator`,
  `source`, `fx`. Optionale Zeitfelder und `fx` standardmaessig `None`.
- `PriceEvidenceMethod`: `method_id`, `version`, `kind`, `daily_statistic`
  (`daily_mean`/`daily_fixed_time`/`daily_close` oder `None`), `daily_time`
  (lokale Uhrzeit nur fuer `daily_fixed_time`), `timezone`,
  `availability_rule`, `fx_max_age_days` (explizit 0..7 bei USD),
  `evidence_sha256`. Optionale Felder standardmaessig `None`.
- `PriceEvidenceApproval`: `decision_id`,
  `decision_type="stichtag_price_time_admission"`, `binding_sha256`, `actor`,
  `rationale`, `approved_at`, `updated_at=None`,
  `acknowledge_original_verified`, `acknowledge_scope_limited` (beide
  erforderliche Eingaben, kein automatisch bestaetigender Default).
  Nur echte Booleans `True` gelten als Zustimmung. Eine nachtraeglich veraenderte
  Entscheidung wird nicht als unveraenderte Zustimmung verwendet.
- `PriceEvidenceAdmission`: eigene Policy-ID/-Version, `status`,
  `strict_eligible`, `binding_sha256`, `decision_id`, `reason_codes`,
  `original_integrity_verified`, `evidence_origin` (`operator_confirmed`
  nur bei Erfolg, sonst `unverified`). Keine Originalbytes in der Ausgabe.

Positive Ausgabe: `status="human_approved"`. Fehlende Zustimmung:
`status="not_approved"`. Andere negative Status und konstante Reasoncodes
sind technische Diagnose; keine Originalinhalte in Fehlermeldungen loggen.
Alle gelieferten Originale zusammen maximal 6 MiB und je Original maximal
2 MiB; zusaetzliche unbenoetigte Originale ebenfalls validieren. Bindungs- und
Assessmentfunktionen lesen/schreiben nichts ausserhalb ihrer Inputs.

Fuer die reine Funktion werden Preis-DB-Zeiten vom kuenftigen Reader anhand
der dokumentierten DB-UTC-Semantik normalisiert. Die Funktion selbst akzeptiert
keine naiven Datetimes. Erfassungszeit ist nicht automatisch historische
Verfuegbarkeit. Approval darf nach dem historischen Stichtag erfolgen, aber
nicht vor Erfassung der von ihr bestaetigten Originale.

Die Tagesperiode ist `[Start, naechste lokale Mitternacht)`. Eine
lokal doppelte Mitternacht beginnt bei ihrer ersten Instanz; eine
Mitternachtsluecke bei der ersten gueltigen lokalen Tageszeit. Der gesamte
lokale Kalendertag muss enthalten sein, nicht pauschal 24 Stunden.
Fuer das Basisasset `EUR` bleibt ausschliesslich die vorhandene EUR-
Identitaetspolicy zustaendig; dieser Nicht-EUR-Belegpfad darf es nicht durch
menschliche Zustimmung auf einen anderen EUR-Eigenwert umdefinieren.
Eine
Veroeffentlichung kann nicht vor der behaupteten Quote-/FX-Beobachtung liegen.
Bei Tagesmittel/-schluss nicht vor Ende der Periode; bei Tageszeit nicht vor
dem dokumentierten lokalen Messzeitpunkt. Das ist eine Konsistenzpruefung
der eingereichten Angaben, keine automatisch belegte Originalzeit.
