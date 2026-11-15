# #52: Vertrag fuer Audit-Integritaet und Identitaet

Basis: `8f3681d2d12be430cbb627ed731091bf0ba77a3f`. Entwicklungszweig,
keine Produktionsfreigabe und keine Datenmigration.

## Verbindliche Aussagen

- Sechs identische Summen bedeuten sechs exakt gleiche Aggregatwerte, nicht
  lediglich sechs erklaerte Differenzen. Eine Restdifferenz bleibt ein Fehler.
- Ohne Referenz sind Referenzwert, Aggregatdelta und Rest unbekannt, nicht null.
- Aktuelle gespeicherte Aggregate, Positionen und Quelldaten werden in einer
  gemeinsamen initialisierten, physisch schreibgeschuetzten DB-Transaktion gelesen.
  Keine implizite Schemaanlage, Neuberechnung oder Anbieterabfrage.
- Eine explizite Ereignis-ID wird niemals durch eine Zeit-/Asset-Heuristik ersetzt.
  Vorhandene archivierte Ereignis-, Lot- und Anschaffungs-IDs bleiben erhalten.
  Unterschiedliche IDs werden nicht aufgrund desselben Tages zusammengefuehrt.
- Fehlende IDs, Exporte und Provenienz bleiben Nachweisgrenzen. Ein vorhandener
  Importbeleg beweist nicht, dass dieser Import erst nach der Referenz erfolgte;
  eine Wertabweichung allein beweist keine Preis-/FX-Aenderung.
- Bestehendes Audit-JSON wird gegen seinen semantischen Inhaltsfingerprint und
  den neu ermittelten Vergleich geprueft. Markdown muss zum gespeicherten JSON
  und dessen Markdown-Hash passen. Abweichungen werden abgelehnt, nicht repariert.
- Neue Artefakte werden ohne Ueberschreiben publiziert. Unvollstaendige Paare,
  symbolische Links, Spezialdateien und zu grosse Dateien sind Fehler.
  Dies ist manipulationsaufdeckende Ablage, kein Schutz gegen einen Administrator,
  der Software und saemtliche Belege gemeinsam ersetzt.
- Geaenderte Regeln erhalten Schema `tax-filing-audit-v3` und neue Inhalts-IDs.
  Vorhandene Abgabepakete und Auditdateien werden nicht migriert oder veraendert.

## Noch kein vollstaendiger Detailvergleich

Historische Pakete koennen nur Summen oder aggregierte Rewardpositionen enthalten.
Laufzeit-UUIDs sind nicht automatisch neu berechnungsstabil. Ein vollstaendiger,
versionierter Detailvertrag fuer Ereignisse, Ursprungslots, Tax-Lines und
Preis-/FX-Provenienz sowie reale Legacy-Zuordnung bleiben gesondert offen.
Numerische Ueberleitung und identische Summen ersetzen diesen Nachweis nicht.
Die unabhängigen Rotproben werden unveraendert gegen die Korrektur wiederholt;
Original-JUnit und Testhash werden in der Uebergabe festgehalten.
