# R1-Nachweise

Ausschließlich synthetische Daten. Keine fachliche Freigabe.

| Bild | Viewport | Zustand |
| --- | --- | --- |
| [R1-source-loading-1440.png](R1-source-loading-1440.png) | 1440 × 1000 | Quelle → Aufgabe, kontrolliert verzögerte Antwort |
| [R1-source-loading-390.png](R1-source-loading-390.png) | 390 × 844 | Derselbe Ladezustand mobil |
| [R1-return-ready-390.png](R1-return-ready-390.png) | 390 × 844 | Rückkehr aus Ledger; Aufgabe trotz nicht passendem Listenfilter geöffnet |
| [R1-missing-390.png](R1-missing-390.png) | 390 × 844 | Erfolgreiche leere ID-Antwort, nicht während des Ladens |
| [R1-error-1440.png](R1-error-1440.png) | 1440 × 1000 | HTTP-503-Fehler mit Wiederholen |
| [R1-retry-ready-1440.png](R1-retry-ready-1440.png) | 1440 × 1000 | Erfolgreiche Antwort nach Wiederholen |
| [R1-LAN-loading-1440.png](R1-LAN-loading-1440.png) | 1440 × 1000 | Echte LAN-Vorschau, unveränderte ID-Antwort kontrolliert zurückgehalten |
| [R1-LAN-return-loading-390.png](R1-LAN-return-loading-390.png) | 390 × 844 | Echte LAN-Vorschau, Laden beim Ledger-Rückweg |
| [R1-LAN-ready-390.png](R1-LAN-ready-390.png) | 390 × 844 | Echte LAN-Vorschau, negative EUR-Aufgabe nach Laden |

[`review-panel-verification.json`](review-panel-verification.json) enthält die
genauen Routen, Dimensionen und kontrollierten R1-Testfälle.
[`LAN-verification.json`](LAN-verification.json) belegt den zusätzlichen lesenden
Test der laufenden Vorschau mit echten, kontrolliert verzögerten Antworten.
[`backend-review-verification.json`](backend-review-verification.json) enthält
den erneut ausgeführten F1–F3-Test gegen den tatsächlichen isolierten Backendstand.
[`workspace-verification.json`](workspace-verification.json) und
[`verification.json`](verification.json) betreffen die bestehende synthetische
Browserregression einschließlich Hilfe, Importvorschau und KI-Bedienung.
