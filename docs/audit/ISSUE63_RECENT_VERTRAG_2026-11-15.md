# Vertrag: gespeicherte Preisvorschauen mit Teilfehlern

Basis `d870c539644bfba4c03d197b22182d776d1aa008`, 15.11.2026.
Keine produktiven Daten, Originale, Methoden oder Container aendern.

## Backend und Kompatibilitaet

`GET /api/v1/prices/historical/previews` behaelt `data` als Liste, maximal
20 angezeigte Vorschauen. Gueltige Eintraege behalten ihre bisherigen Felder.
Jeder Eintrag erhaelt `integrity_status="verified"|"unavailable"` und
`error_code=None|<konstanter Code>`. Dies ist nur Integritaet/Importbindung,
keine Inhalts-, Methoden- oder Jahresfreigabe.

Unlesbare/beschaedigte/anders gebundene Vorschauen unter gueltiger UUID
bleiben als Eintrag sichtbar: `id`, `status="unavailable"`,
`integrity_status="unavailable"`, sicherer `error_code`. `created_at`,
`prices_count`, `applied`, `preview_sha256`, `pending_count`, `open_count`,
`parent_preview_id`, `collection_complete`, `manual` sind dann **None**.
Kein Dateisystemzeitpunkt als Dokumentdatum, kein falsches `applied=False`
oder `prices_count=0`. Originalinhalte/Pfade/Fehlermeldungen nicht ausgeben.

Modell `HistoricalPricePreviewListItem` in `contracts/historical_prices.py`,
`extra=forbid`, strikte Zaehl-/Booleanfelder und Konsistenzvalidator.
Normaler Erfolg ist `verified` und `error_code=None`; Fehlerpayload darf
keine ungeprueften Metadaten behalten. Errorcodes nur
`historical_price_evidence_changed`, `historical_price_apply_decision_invalid`,
`historical_price_preview_unavailable`. `recent()` liefert weiter Dicts.

Defekter/symlinkter Root ist ein konkreter Dienstfehler, nicht leere Liste.
Verzeichnis-IDs nur kanonische UUIDs; keine ungeprueften Namen in Antworten.
Sortierung nach Dateimetadaten ist nur Listenreihenfolge, kein Belegdatum.
Per-Datei-OSError/JSON-/Belegfehler als unavailable behandeln; DB-Ausfall
nicht als beschaedigtes Einzeldokument verschleiern. Keine Reparaturversuche.

Routerintegration uebernimmt der Koordinator: typisierte Liste, zusaetzlich
API-Warnung `historical_price_recent_partial`, wenn eine Zeile unavailable
ist. Die Zeilen selbst tragen den Zustand auch fuer Clients ohne Warnhandling.

## Oberflaeche

Initiales Laden, geladene leere Liste, Teilfehler/alle unverfuegbar und
gescheiterter Abruf getrennt anzeigen. Kein vorzeitiges "Noch keine".
Nach fehlgeschlagenem Refresh vorhandene Liste als vorherigen Stand markieren.
Unavailable-Zeilen: Datum/Preisanzahl unbekannt, Uebernahme nicht bestaetigt,
konkreter Hinweis und lesendes "Erneut pruefen". Keine Apply-/Provideraktion
durch Listendarstellung oder Wiederholung der Belegpruefung.

Bei erfolgreicher neuer Pruefung normale Anzeige wiederherstellen. Alte
Antworten ohne Integritaetsmarker nicht als aktuell geprueft bezeichnen.
Bestehender Preview-/Filter-/Freigabekontext bleibt erhalten.

## Pflichtproben

Gueltig + beschaedigt nebeneinander; ausschliesslich beschaedigte Originale;
gefaelschte Importentscheidung; unlesbares JSON; fehlende Datei; echte
Null-Preisanzahl einer gueltigen Vorschau vs unbekannte Anzahl; initiales
Laden und globaler Fehler; Wiederherstellung im disponiblen Fixture und
Neupruefung. 390/768/1280/1440 Pixel, Tastaturzugang und kein Seitenoverflow.
Original-/Preis-/Reviewdaten nach den lesenden Aktionen unveraendert.
