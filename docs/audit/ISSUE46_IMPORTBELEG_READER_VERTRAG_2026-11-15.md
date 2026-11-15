# Vertrag: konkrete Preis-ID und urspruenglicher Importbeleg

Basis `d870c539644bfba4c03d197b22182d776d1aa008`, Entwicklung 15.11.2026.
Dieser Schritt macht Importbelege lesend zuordenbar, erteilt aber keine
Preiszeit-/Methodenzulassung. Produktion und alte Archive bleiben unveraendert.

- Nur **neu erstellte** historische Vorschauen erhalten `price_bindings` mit
  genau einer konkreten UUID und einem semantischen PricePoint-Fingerprint je
  neuem Preis. Aus den tatsaechlich gespeicherten, quantisierten Clone-Zeilen
  nach der Pipeline lesen; Rueckgabewerte des Inserters koennen noch ungerundet
  sein. Metadaten vor Bildung des Vorschauhashes hinzufuegen.
- Alte Vorschauen werden nicht ergaenzt; fehlende Bindung bleibt explizite
  Altformatgrenze. Keine Ersatzzuordnung nach gleichem Symbol/Wert/Quellenlabel.
- `price_point_fingerprint` in der vorhandenen reinen Belegbibliothek bindet
  Preis-ID, Asset, EUR-Wert, gespeicherte UTC-Referenzzeit, Quelle und Konfidenz.
  Gleiche Decimal-Zahlen/UTC-Instanten haben gleiche semantische Bindung.
- Neuer lesender Vertrag:
  `GET /api/v1/prices/historical/previews/{preview_id}/prices/{price_id}/evidence`.
  Die Preis-ID muss in der hashgeprueften Vorschau eindeutig gebunden sein,
  der originale Importentscheid muss zum Vorschauhash passen und die aktuelle
  Preiszeile muss denselben Fingerprint besitzen. Fehlend/mehrdeutig/geaendert
  ist keine bestaetigte Zuordnung. Kein aktueller Mengen-/Jahresnachweis daraus.
- Nur die fuer diese konkrete Preiszeile gespeicherten Originalhashes und
  vorhandenen Bytes verknuepfen. Kein willkuerliches Original aus derselben
  Vorschau. Mindestens ein zugeordneter Originalbeleg erforderlich.
- Dateien nur unter dem bestehenden privaten historischen Belegroot. Keine
  Dateipfade aus Clientparametern; UUID/SHA validieren, Symlinks ablehnen,
  Groessen begrenzen, Hash und Bytes zusammen pruefen. Keine grossen
  `calculation.prepared`-Dateien zum blossen Beleglesen laden.
- Preis-/Reviewdaten innerhalb eines gemeinsamen Read-only-Snapshots lesen.
  Neuer `read_initialized_snapshot()` darf keine Schemainitialisierung
  ausloesen; nicht initialisierter Store ist ein klarer Fehler. Dies ist keine
  allgemeine physische Write-Protection unbekannter/offline Datenbanken.
- Ausgabe `PriceImportEvidenceReport`: ID/Fingerprint, Asset/EUR-Wert,
  gespeicherte Referenzzeit und sichere Original-Downloadreferenzen.
  `status="verified_import_binding"`, `strict_eligible=False`,
  `admission_status="not_reviewed"`. Kein ungeprueftes Beobachtungs-/Publikations-
  datum ableiten. Keine URLs/Params/Originalinhalte aus privaten Metadaten
  ausgeben. Originaldownload bleibt an Vorschau und Hash gebunden.

Pflichtproben: echte manuelle Vorschau -> ausdruecklicher Apply in disponibler
DB -> lesender Originalbeleg; vorher kein Applynachweis; alte fehlende Bindung;
fremde Preis-ID, geaenderte Preiswerte und gefaelschte Entscheidung; falsche
Originalhashes, fehlende/mehrdeutige Referenz und Symlink; Datenschema bleibt
unberuehrt, Original-/Preis-/Reviewdaten bleiben durch Lesen unveraendert.
Die Benutzeroberflaeche fuer die **menschliche Methodenannahme** bleibt ein
separater noch offener Schritt; dieser Reader darf sie nicht vortaeuschen.
