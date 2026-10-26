# Browsernachweise zum Review

Alle dargestellten Konten und Ereignisse sind synthetisch. Keine fachliche
Produktfreigabe. Der echte Backend-Test verwendet FastAPI TestClient und eine
temporäre Datenbank; die zusätzlichen LAN-Bilder zeigen die laufende Vorschau.

| Bild | Viewport (CSS-Pixel) | Route / Zustand |
| --- | --- | --- |
| [F1-sources-1440.png](F1-sources-1440.png) | 1440 × 1000 | `#sources?status=reconciliation`; eigene Quelle mit einer blockierenden Review-Aufgabe |
| [F1-source-issues-1440.png](F1-source-issues-1440.png) | 1440 × 1000 | Quelldetail, Hinweise / Abgleich; Quellenbewertung und Review getrennt |
| [F1-source-issues-390.png](F1-source-issues-390.png) | 390 × 844 | Gleiches Detail mobil, negativer EUR-Hinweis mit direkter Aktion |
| [F2-context-ledger-1440.png](F2-context-ledger-1440.png) | 1440 × 1000 | `#flows?tab=ledger`; Quelle + Konto + EUR, 22 Bewegungen |
| [F2-context-ledger-390.png](F2-context-ledger-390.png) | 390 × 844 | Gleicher Ledger mobil; breite Tabelle in eigenem horizontalen Scrollbereich |
| [F3-dashboard-1440.png](F3-dashboard-1440.png) | 1440 × 1000 | `#dashboard`; fester EUR-Referenzwert neben historischen Preisen |
| [F3-dashboard-390.png](F3-dashboard-390.png) | 390 × 844 | Dashboard mobil |
| [F1-after-funding-1440.png](F1-after-funding-1440.png) | 1440 × 1000 | Quelldetail nach echtem synthetischem Korrekturimport, null Review-Aufgaben |
| [LAN-F1-source-1440.png](LAN-F1-source-1440.png) | 1440 × 1000 | Laufende LAN-Vorschau auf Port 18014, Quellenhinweis |
| [LAN-F2-ledger-1440.png](LAN-F2-ledger-1440.png) | 1440 × 1000 | Laufende LAN-Vorschau, kontextbezogener EUR-Ledger |
| [LAN-F3-dashboard-390.png](LAN-F3-dashboard-390.png) | 390 × 844 | Laufende LAN-Vorschau, EUR-Referenz mobil |

Vollseitenbilder können höher sein als der Viewport. Panels werden im
angegebenen Viewport aufgenommen, nicht aus einem Desktopbild zugeschnitten.
Exakte Detail-URLs und tatsächliche API-Abfragen stehen in
[`review-verification.json`](review-verification.json).

- [`LAN-verification.json`](LAN-verification.json): zusätzliche lesende Prüfung der laufenden Vorschau.
- [`workspace-verification.json`](workspace-verification.json): bestehende A01–A23-Regression mit kontrollierten synthetischen API-Antworten; vier Breiten.
- [`legacy-ux-verification.json`](legacy-ux-verification.json): Hilfe, Importvorschau und KI-Bedienung mit synthetischen Antworten.
- [`backend-junit.xml`](backend-junit.xml): vollständige Backend-Suite, einschließlich Fachberechnungsregressionen.

Die Berichte unterscheiden tatsächliche Backend-Prüfung und gemockte
Schreibabläufe. Sie belegen keine echten Exchange-Synchronisierungen oder
Vollständigkeit privater Finanzdaten.
