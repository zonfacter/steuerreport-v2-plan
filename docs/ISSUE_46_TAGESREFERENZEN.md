# Issue 46: begrenzter Schutz fuer Tagesreferenzen

Stand: Entwicklungsstand, keine fachliche oder produktive Freigabe. Bekannte
Quellmarker `:as_of_gate:`, `v1_fx_cache`, `bmf_event_price_anchor:` und
`bitget_strategy_basis_anchor:`
kennzeichnen im Stichtagsgate eine nicht ausreichend belegte Tagesreferenz.
Sie blockiert auch unterhalb der Materialitaetsschwelle. Der gespeicherte
Zeitstempel und Quellenstring bleiben unveraendert; bei bekannten Referenzen
ist `daily_reference_date` eine Tageszuordnung und `observed_price_at` null.
Provider- und FX-Zeitnachweise sind nicht verifiziert. Ein frueheres FX-Datum
allein belegt weder Veroeffentlichungszeit noch einen intrataeglichen Kurs.

Archivdateien werden nicht veraendert. Laeufe ohne die neue Gate-Version werden
in API-Leseansichten und im BMF-/Governance-Verbrauch konservativ blockiert;
historische Status und Preisgates sind separat abrufbar. Auch eingebettete
Preisgates der Projektion sind blockiert. Originale Belegdateien bleiben
historische Artefakte und koennen alte Freigaben enthalten.
Die Regelversion `known_daily_references_v2` umfasst den Bitget-Anker;
`known_daily_references_v1` und unversionierte Laeufe bleiben historische
Ergebnisse und werden in der aktuellen Projektion blockiert.

Der bestehende API-Vertrag aendert dadurch fuer alte Laeufe die Semantik von
`status` und `strict_ready` sowie eingebetteter Preisgates, obwohl Namen und
Typen erhalten bleiben. Altclients, die eine historische Bedeutung erwarten,
koennen daher anders reagieren; ein versionierter Migrationsvertrag und UI-
Integration sind offen. `current_validity=versioned_gate` bestaetigt nur die
verwendete begrenzte Gate-Version, keine erneute Pruefung gegen zwischenzeitlich
geaenderte Daten oder eine allgemeine fachliche Freigabe.

Nicht abgedeckt: unbekannte oder anders benannte Tagesquellen, Tax-, Portfolio-
und andere Preisleser, direkte Preiswrites, eine beweisbare Anbieter-/FX-
Zeitpunktkette und die fachliche Methodenregel. Auch bei unklassifizierten
Same-Day-Quellen beweist diese Aenderung keinen beobachteten Intraday-Kurs.
Gespeicherte Zahlen bleiben lesbar und duerfen nicht allein aufgrund dieses
Gates als exakter Stichtagskurs verstanden werden. Eine Aenderung der
gemeinsamen Preisleser ist wegen bestehender Vertraege gesondert zu klaeren.

## Gepruefte Kontextoptionen, nicht implementiert

- Ein neues versioniertes API-Format koennte historische Werte und eine
  separate konservative aktuelle Bewertung verbindlich trennen. Die bestehende
  V1-Semantik ist bereits geaendert und weiterhin unversioniert; Migrations-
  vertrag, Kompatibilitaet und Behandlung alter Clients sind vorher zu klaeren.
- Additive HTTP-Header oder ein Link zu einer Kontext-API koennten Original-
  downloads kennzeichnen, bleiben aber beim Weitergeben der Datei oft nicht
  erhalten und schuetzen Clients nicht, die sie ignorieren.
- Ein zusaetzliches neues Belegpaket mit unveraendertem Original, Hash und
  maschinenlesbarem Kontext koennte die Einordnung mitgeben. Es ersetzt weder
  schon verbreitete Originaldateien noch erzwingt es, dass der Kontext gelesen
  wird. Ein klar versionierter Paketvertrag und Integritaetspruefung sind offen.
- `HistoricalPriceLookup.at_or_before`, `DuckDbStore.latest_price_points`,
  Portfolio und auf dem Lookup aufbauende Tax-Pfade koennen bekannte Anker
  weiter als Preise auswaehlen. Die synthetische Gegenprobe dokumentiert Lookup,
  Latest und Portfolio; fuer Tax ist die verbleibende Nutzung anhand des Codes
  festgestellt, nicht durch eine neue End-to-End-Steuerrechnung bestaetigt.
  Ein pauschaler Ausschluss oder Fallback kann bestehende Bewertungen aendern
  und benoetigt einen gesonderten fachlichen und versionierten Vertrag.
