# Gemeinsame Befundliste

Codefreeze: `b036b8ad4212d08d719fedec7dbc7115cf5704a9`.
Status bezieht sich auf den jeweiligen begrenzten Nachweis, nicht auf eine
Gesamtfreigabe. Keine Produktivdaten oder Originalentscheidungen geaendert.

| ID | Stand | Nachweis / Grenze |
| --- | --- | --- |
| F01 | Inventar und isolierter Restore abgenommen; Paritaet offen | Lokale Live-Image-ID, Frontend/API/Volume zugeordnet. Zwei rc32-Restores und separater Entwicklungsimage-Restore. Keine vollstaendige Legacy-Daten-/Methodenparitaet, kein frisch verifizierter Registrybezug. |
| F02 | Reproduziert, technisch behoben und vertikal synthetisch geprueft | Ungeeignete Alt-/Zukunftskurse nicht als Tax-Wert; SQL/Python-Coverage und Derived gleichgezogen. Vorhandene Alt-Derived-Elternprovenienz und vollstaendige FX-/Contractfaelle bleiben offen. |
| F03 | Private Kalenderfrist implementiert und synthetisch abgenommen | Berlin-Datum, Jahrestag/Folgetag,29Feb,DST,SQL/Python,CSV und Planung. Kein privater Scope allein aus Tokenlabel; Original-Zeitsemantik bleibt belegpflichtig. |
| F04 | Technisch behoben; keine persoenliche Abgabefreigabe | Technischer Export bleibt Vorschau. Daten-/Methodenbindung sperrt veraltete Downloads; Jahr/Loading/UI/ZIP/PDF unterscheiden final. Nicht alle persoenlichen Sachverhalte oder Grossberichte sind damit abgenommen. |
| F05 | V1-Sollannahme ausgeschlossen; Originalrepros offen | Eigene unabhaengige algebraische Sollwerte. Die benannten Original-Reprodateien waren nicht verfuegbar; kein behaupteter exakter Replay oder vollstaendiger V1-Quellaudit. |
| F06 | Methodische Grenze offengelegt, Review bleibt offen | Technisch zugelassener Tageskurs ist keine bestaetigte gleichmaessige steuerliche Methode. Historische Referenzpunkte erzeugen Readiness-Warnung, keine automatische Freigabe. |
| K01 | EUR-Erwerbsgebuehr behoben | Gesonderte EUR-Gebuehr eines EUR-Kaufs wird kapitalisiert, unabhaengiger G02-Fall. Keine pauschale Erweiterung auf Drittassetgebuehren. |
| K02 / G04 | Reproduziert, offen, abgesichert | Beim Folgeerwerb mitBNB0.1Gebuehr bleibt das globale BNB-Lot1statt0.9. Blockierender Reviewhinweis ist kein Lotverbrauchsfix. Kein Release-/Fachfreigabenachweis fuer diesen Umfang. |
| K03 / G17 | Teilweise abgesichert, nicht vollstaendig geloest | Unbelegte Nullkostenbasis wird explizit reviewpflichtig. Positive, aber unbelegte Markt-Basis sowie vollstaendige Herkunft fehlen weiterhin. |
| K04 / G24 | Begrenzte lesende Rechenhilfe geprueft | Jahresabhaengiger strikter Freigrenzenvergleich nur mit bestaetigtem Zusatzkontext. Keine persoenliche Steuerlast-/Verlustverrechnungs-/Freigabeentscheidung. |
| K05 | Integrationsregression behoben | Alte Stichtagsquote wird getrennt diagnostiziert, nicht wieder in Portfolio-/Taxwerte uebernommen. Alter Kleinstkurs kann keine Materialitaetsbefreiung erzeugen. |
| K06 | Guard implementiert und gezielt geprueft | Unbewertete Registryposition, auch expected_zero, erhaelt Review statt matched. Fehlende Bewertung wird nicht durch Altpreis/Null geheilt. |

## Bewusst Nicht Als Behoben Gezaehlt

- G08/G09: vollstaendiger unabhaengiger FX-Richtungs-/Wochenendverbrauch.
- G18/G19: Chain-/Contractkollision sowie belegte Migration/Wrapping.
- G11/G12/G13/G14: weitergehende Depot-, Gebuehren-, Herkunfts- und
  Privat-/Betriebssachverhalte ausserhalb der synthetischen Teilproben.
- Vollstaendige private Mengen-/Kostenbasis-/Methodenparitaet zwischen den
  verschiedenen laufenden Altbereitstellungen und Docker.
- Produktionswechsel, echte Anbieterberechtigungen/-historien und menschliche
  Jahresentscheidungen: nicht ausgefuehrt oder automatisch getroffen.

## Integration Und Regressionen

Der erste breite Integrationslauf meldete9Fehler/2434Pass/4Skips. Das waren
Integrationsregressionen dieser Aenderung, nicht ungeprueft als vorbestehend
eingestufte Produktfehler: vier Tageskurs-/Folgetags-Fixtures, zwei
Stale-Diagnosen, zwei Registry-Bewertungsanzeigen und eine
Versionskonsistenzpruefung (genaue Einzeltests im XML). Die Originalbetragsassertionen
blieben erhalten; explizite zusaetzliche synthetische Tagesanker ersetzen
nicht echte Preisbelege. Der erneute eingefrorene Gesamtlauf ist separat
unter PRUEFNACHWEISE.md dokumentiert.

Die unabhaengige52er-Probe bleibt rot, solangeG04offen ist. Ein gruener
Unit-Lauf oder ein erfolgreich startender Container beseitigt diesen Befund
nicht. Keine Methodenaktivierung zum Gruenmachen eines Gates.
