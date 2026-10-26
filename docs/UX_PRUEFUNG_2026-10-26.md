# UX-Pruefung: Benutzerfuehrung und Hilfe

## Umfang

Geprueft wurden Navigation, Hilfeeinstieg, Importassistent, KI-Aufgaben,
Korrekturauswahl und Einrichtung. Grundlage ist der Softwarestand nach RC12.
Es wurden keine steuerlichen Methoden, persoenlichen Einstellungen oder
Finanzdatensaetze geaendert. Die initiale Pruefung erfolgte im Arbeitsbaum;
die Aenderungen werden mit RC13 ausgeliefert. CI-, Image- und produktive
Deploymentnachweise gehoeren zum separaten Release-Pruefbericht.

## Feststellungen und Umsetzung

| Feststellung | Umsetzung |
| --- | --- |
| Hilfe war auf mehrere Dokumente und Browser-Titel verteilt. | Eigene Seite `/#help`: 13 Arbeitsablaeufe, 5 haeufige Fragen, 10 Begriffserklaerungen; Suche und Bereichsfilter. |
| Ein Zusammenhang zwischen Einrichtung, Import, Pruefung und Export war schwer zu erkennen. | Direkte Ablaufnavigation mit aktuellem Schritt, ohne eine erledigte Pruefung vorzutaeuschen; mobil aufklappbar. |
| Bereichshilfe konnte einen Wechsel aus ungespeicherten Formularen erfordern. | `Hilfe zum Bereich` oeffnet das passende Thema in einem separaten Tab und erhaelt den Arbeitsbereich. |
| Browser-Titel helfen Touch- und Tastaturnutzern nur begrenzt. | Eigene Fragezeichen-Hilfen: Hover, Fokus, Touch, Escape und Aussenklick; beschraenkte Breite und Positionierung im sichtbaren Bereich. |
| Deaktivierte Aktionen erklaerten ihre Voraussetzungen nicht direkt. | Zustandsabhaengige Hinweise fuer Import, KI-Textauftrag, Korrekturvorschlag und verbindliche Uebernahme. |
| Die vollstaendige KI-Einrichtung stand immer vor den eigentlichen Aufgaben. | Gespeicherte Verbindung im Assistenten eingeklappt; bei neuer Installation und in Einrichtung weiterhin offen. |
| Technische Administration ueberlagerte normale Einrichtung. | Boersenzugang direkt bei der Kontoeinrichtung; Diagnose, rohe Admin-Settings und technische Werkzeuge eingeklappt. |
| Die Navigation bot eine leere Expertenwerkzeug-Gruppe. | Leeren Umschalter entfernt; aktive Navigation mit `aria-current` markiert. |
| Die mobile Ablaufnavigation nahm viel Hoehe ein. | Kompakter aktueller Schritt mit aufklappbaren Zielen; erfolgreiches Ladeprotokoll mobil verkuerzt, Fehler bleiben sichtbar. |

## Nachpruefung

- TypeScript und Produktionsbuild: `cd frontend` und `npm run build`.
- Python-Lint: `ruff check src tests scripts`.
- CI-Konfiguration: `actionlint .github/workflows/ci.yml`.
- Fachliche Regression: 47 Tests fuer Import, KI-Korrekturen, Agenten und
  KI-Leitfaden bestanden. Kein vollstaendiger Backend-Gesamtlauf in dieser
  rein oberflaechenbezogenen Aenderung.
- Browser: `python scripts/check_ux_browser_v2.py` startet den gebauten
  Frontendstand auf einem lokalen freien Port. Playwright/Chromium muessen
  separat installiert sein. Optional `--base-url` fuer einen Dev-Server
  und `--browser-executable` fuer einen vorhandenen Chromium-Browser.
- Alle `/api`-Antworten im Browser-Smoke-Test sind synthetisch. Kein echter
  Import, keine echte Modellanfrage und kein Schreibzugriff auf Nutzerdaten.
- Pruefung bei 320, 390 und 1440 Pixeln: kein horizontaler Seitenueberlauf;
  zusaetzliche echte Touch-Events fuer die mobile Navigation und Tooltips.
- Geprueft werden auch Kontextwechsel ohne Eingabeverlust, vorhandene
  HTML-/PDF-Dokumente, Einrichtungszustand, Cloud-Freigabeschranke und
  Importpruefung ohne anschliessende Importausfuehrung.
- CI fuehrt denselben Browser-Test aus und archiviert die synthetischen
  Screenshots sowie `verification.json` als Workflow-Artefakt.
- Gitleaks fuer `frontend/src` und `scripts`: keine Funde. Der vorhandene
  Guard fuer private Konto-Voreinstellungen meldet keine Verletzung.

## Grenzen

Die Hilfe erklaert die vorhandenen Funktionen; sie erweitert keine
KI-Berechtigung und ersetzt weder fachliche Belegpruefung noch individuelle
steuerliche oder rechtliche Freigabe. Die Ablaufnavigation markiert nur den
aktuellen Bereich, keinen nachgewiesenen Bearbeitungsfortschritt.

Der Produktionsbuild meldet weiterhin den bestehenden grossen Haupt-Chunk.
Aufteilung des umfangreichen Hauptmoduls und durchgaengige Formular-
Verlassenswarnungen fuer alle Altansichten sind separate Folgearbeiten.
Die neue Bereichshilfe verlaesst das aktuelle Formular deshalb bewusst nicht.
