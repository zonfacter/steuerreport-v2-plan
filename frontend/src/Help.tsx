import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, BookOpen, Download, HelpCircle, Search, X } from "lucide-react";

export const WORKFLOW = [
  { id: "admin", label: "Einrichten" },
  { id: "import", label: "Importieren" },
  { id: "review", label: "Hinweise pruefen" },
  { id: "tax", label: "Steuerjahr pruefen" },
  { id: "export", label: "Exportieren" }
] as const;

export const HELP_TOPICS = [
  { id: "dashboard", title: "Uebersicht und erster Einstieg", keywords: "start beginnen neu status", steps: [
    "Beginne unter Quellen & Wallets mit Quelle hinzufügen. Der Anbieter-Katalog wird erst dort geöffnet; Einrichtung enthält die weiterführende Konfiguration.",
    "Importiere die vollstaendige Historie einschliesslich der Anschaffungen vor dem gewaehlten Steuerjahr.",
    "Pruefe offene Hinweise und danach das jeweilige Steuerjahr. Erstelle erst anschliessend die Berichte."
  ], caution: "Die Ablaufleiste dient der Orientierung. Sie bestaetigt weder Vollstaendigkeit noch eine steuerliche Freigabe." },
  { id: "admin", title: "Konten, Wallets und Zugangsdaten einrichten", keywords: "einrichtung api key secret vault neustart docker connector setup token schreibfreigabe passwort version update release rc", steps: [
    "Für eine Solana-Adresse unter Quellen & Wallets → Quelle hinzufügen die Eingabeart Öffentliche Adresse speichern verwenden. Optional Name und öffentliche Adresse eingeben und bestätigen. Keine Signatur und kein Setup-Passwort nötig; kein automatischer Abruf oder Eigentumsnachweis.",
    "Speichere API-Keys im vorgesehenen Zugangsdatenbereich, nicht in Kontonamen, Dienstadressen oder JSON-Belegtexten.",
    "Für Wallet-Nachweise den Bereich Wallet-Eigentumsnachweis prüfen. Neue Docker-Installationen bereiten das Einrichtungspasswort vor; bestehende Installationen brauchen den ausdrücklichen lokalen init-Befehl. show-token zeigt es nur in der privaten interaktiven Serverkonsole, niemals über die Web-API. Danach in Connector-Setup-Token einfügen und die Wallet-Nachricht signieren.",
    "Beachte die Rueckmeldung nach dem Speichern: Konto- und Dateizuordnungen koennen einen API- oder Container-Neustart erfordern. Bestehende Auswertungen werden dadurch nicht automatisch neu berechnet.",
    "Die Versionsanzeige im Kopfbereich öffnet Version & Updates. Wähle stabile Releases oder zusätzlich RC und speichere eine gewünschte automatische Prüfung ausdrücklich. Sie ist anfangs aus; Jetzt prüfen fragt nur öffentliche GitHub-Release-Metadaten ab. Die Wartefrist ist keine Verbindungssperre.",
    "Wähle ein konkretes Zielrelease und kopiere den KI-Updateauftrag oder lade TXT/JSON. Ohne Zwischenablage wird der vollständige Text zur manuellen Auswahl angezeigt. Das Ziel bleibt gebunden, auch wenn später eine neuere Version erscheint. Kein Button installiert Software; unbekannte Quellcommits und Image-Digests müssen vor einem separaten Update geprüft werden."
  ], caution: "Erweiterte Quellen- und Belegkonfiguration sowie technische Einstellungen nur mit gepruefter Zuordnung aendern." },
  { id: "sources", title: "Quellen und Live-Abgleich verstehen", keywords: "wallet boerse binance bitget api verbindung snapshot", steps: [
    "Die Liste enthält eigene importierte, registrierte oder konfigurierte Quellen. Suche, Quellenstatus und Sortierung grenzen sie ein. Öffne eine Quelle für Bestände, Transaktionen, Hinweise und Einstellungen.",
    "Quelle hinzufügen führt durch Anbieter, Eingabeart, Pflichtfelder und Zusammenfassung. Zugangsdaten werden erst nach Bestätigung gespeichert; Dateiimporte bleiben im Importassistenten ausdrücklich freizugeben. Ein Wallet-Eigentumsnachweis aktiviert keine steuerliche Quelle.",
    "Für den automatischen Import die konkrete Quelle öffnen und Transaktionen abrufen wählen. Zeitraum und gegebenenfalls Handelspaare angeben, externe Anfrage bestätigen und Vorschau abrufen. Nur die ausgewählte Wallet oder einzelne Kontoverbindung wird verwendet.",
    "Nach dem Abruf Stichprobe, neue Datensätze, Duplikate, Abdeckung und offene Hinweise prüfen. Freigebende Person eintragen sowie Import und Neuberechnung getrennt bestätigen. Erst Importieren und neu berechnen übernimmt die Vorschau. Pause, Fortsetzen und Abbruch sind am Auftrag verfügbar; nach Serverneustart ausdrücklich fortsetzen.",
    "Unterscheide den aktuellen API-Bestand vom aus importierten Ereignissen berechneten Bestand. Ein aktueller Snapshot ersetzt keine historische Transaktionsliste.",
    "Untersuche Differenzen anhand fehlender Zeitraeume, offener Orders, Earn-Produkte und interner Transfers, bevor du Daten korrigierst."
  ], caution: "Ein erfolgreicher Verbindungscheck beweist nicht, dass die Quelle alle historischen Geschaefte liefert." },
  { id: "import", title: "Automatischer Abruf und ergänzender Dateiimport", keywords: "api automatisch historie csv xlsx xls spalten layout excel format dublette tabellenblatt", steps: [
    "Für einen automatischen Abruf unter Quellen & Wallets die konkrete Quelle öffnen und Transaktionen abrufen wählen. Solana-RPC sowie Spot-Historien von Binance, Bitget Classic, Pionex und Coinbase Advanced sind vorgesehen; API-Grenzen, Handelspaare und fehlende historische Produkte beachten. Ein erfolgreicher Abruf bestätigt keine vollständige Steuerhistorie.",
    "Waehle die passende Quelle und anschliessend CSV-, XLSX- oder XLS-Dateien. Die erforderlichen Spalten sind je Importprofil unterschiedlich: oeffne Formate & Spalten oder lade die passende Vorlage.",
    "Klicke auf Dateien pruefen. Kontrolliere Quelle, Zeitraum, Vorschau, Tabellenblatt, Zeilenzahl und Warnungen. Bei einem anderen Tabellenblatt erneut pruefen.",
    "Gib nur gepruefte Dateien frei und starte den Import ausdruecklich. Kontrolliere danach das Ergebnis und die Belegspur; bearbeite offene Hinweise."
  ], caution: "Die Dateiendung allein reicht nicht. Dublettenpruefungen ersetzen keinen fachlichen Abgleich ueberlappender Quellen; referenzierte Vergleichsdaten duerfen Bestaende nicht doppelt erhoehen." },
  { id: "flows", title: "Transaktionen, Transfers und Geldfluesse", keywords: "eur einzahlung auszahlung volumen swap einkommen", steps: [
    "Transaktionen zeigt kanonische Ereignisse, Ledger deren einzelne Buchungsbewegungen. Geldflüsse und Transferkandidaten bleiben eigene Tabs; unterschiedliche Zeilenzahlen sind nicht automatisch Datenverlust.",
    "Filtere nach Jahr, Datum (Europe/Berlin), Quelle, Asset, Typ oder Datenhinweis. Suche bleibt ausschließlich im Arbeitsspeicher dieses Tabs und wird beim Neuladen geleert; andere Listenfilter und Seiten bleiben in der URL erhalten.",
    "Öffne Ereignisdetails für Originaldatei, Hash, Originalzeile, Ledger, FIFO-Lot und vorhandene Änderungshistorie. Exportieren unterscheidet alle Filterergebnisse, Auswahl und vollständige Historie; CSV bleibt auf 25.000 Zeilen je Export begrenzt.",
    "Gleiche Transfers zwischen eigenen Wallets und Boersen nach Transaktions-ID, Zeit, Menge und Gebuehren ab.",
    "Unterscheide tatsaechliche EUR-Ein- und Auszahlungen, interne Transfers und Handels- beziehungsweise Swapvolumen."
  ], caution: "Handelsvolumen ist weder Einkommen noch ausgezahltes Geld. Gewinn oder Verlust ist eine separate Berechnung." },
  { id: "review", title: "Hinweise und blockierte Auswertungen bearbeiten", keywords: "blockiert fehler warnung export gate preis fehlt unmatched", steps: [
    "Oeffne einen Hinweis und lies Ursache, betroffene Quelle sowie die verknuepfte Belegspur.",
    "Beschaffe fehlende Originalbelege oder pruefe Importzuordnung, Preis und Transferbezug. Dokumentiere eine Entscheidung mit Begruendung und Belegstelle.",
    "Berechne nach einer fachlichen Korrektur neu und kontrolliere, ob der Hinweis und seine Auswirkungen nachvollziehbar geklaert sind."
  ], caution: "Ein Hinweis darf nicht allein fuer einen Export bestaetigt werden. Ein blockiertes Gate zeigt eine offene Voraussetzung und ist keine automatisch zu uebergehende Fehlermeldung." },
  { id: "tax", title: "Ein Steuerjahr nachvollziehen", keywords: "fifo lot gewinn verlust rewards mining staking derivate anschaffungskosten", steps: [
    "Waehle zuerst das Steuerjahr. Beginne mit der gefuehrten Ansicht; nutze Belege und Details fuer die Nachpruefung einzelner Zahlen.",
    "Pruefe Gewinn/Verlust, Erloese, Anschaffungskosten, Rewards und Derivate getrennt. Verfolge auffaellige Betraege bis zum Ereignis und dessen Quelle.",
    "Kontrolliere fehlende Anschaffungen, Preisabdeckung und die verwendete Methode. Vergleiche vorhandene Abgabestaende mit der aktuellen Auswertung."
  ], caution: "Die Softwareauswertung ist keine individuelle steuerliche Freigabe. Insbesondere betriebliche Zuordnung und Korrekturen bereits abgegebener Erklaerungen fachlich pruefen lassen." },
  { id: "export", title: "Berichte und pruefbare Belege exportieren", keywords: "pdf zip csv json download bericht anlagen finanzamt manifest hash", steps: [
    "Prüfe das gemeinsame Steuerjahr und die getrennten Voraussetzungen für Datenabdeckung, Berechnung, Review, Jahresbestätigung und Export. Eine Vorschau ist keine finale Jahresfreigabe.",
    "Jahresvorschau, Jahrescheckliste und Jahres-Belegpaket beziehen sich auf das gewählte Jahr, nicht auf Filter der Transaktionsliste. Die globalen PDF-Werkzeuge sind gesondert gekennzeichnet. Das ZIP-Paket speichert einen lokalen Cache und verlangt eine Bestätigung.",
    "Waehle den passenden Bericht oder das Jahres-Belegpaket. Nutze PDF fuer die Leseansicht und strukturierte Dateien fuer die Nachpruefung.",
    "Bewahre Bericht, Quelldateien und Manifest gemeinsam auf. Kontrolliere Jahr, Methode und Erstellungsstand vor einer Weitergabe."
  ], caution: "Ein heruntergeladenes Dokument beweist fuer sich allein weder Vollstaendigkeit noch eine steuerliche oder rechtliche Freigabe." },
  { id: "portfolio", title: "Portfolio und Preisabdeckung pruefen", keywords: "bestand haltefrist saldo preis kurs live ledger", steps: [
    "Vergleiche Bestaende nach Asset und Konto. Beruecksichtige technische Belegkonten nicht als zusaetzliches Vermoegen.",
    "Pruefe fuer einen EUR-Wert den verwendeten Preis, dessen Zeitpunkt und die Preisabdeckung.",
    "Öffne EUR-Preise ermitteln und wähle Alle erkannten Token sowie ein Jahr oder Alle Jahre. Preisbedarf planen erfasst auch Token aus Transfers, ohne sie als Rewards oder Trades anzuerkennen. Vorhandene, fehlende und blockierte Tagespreise bleiben getrennt.",
    "Bestätige den externen Abruf. Weitere Abschnitte ergänzen dieselbe kombinierte Vorschau; fehlgeschlagene Zeilen werden nur nach ausdrücklichem erneutem Versuch abgefragt. Lade Jahresdateien und Originalbelege als ZIP oder die Auswertung als JSON/Markdown herunter. Dafür ist keine KI erforderlich.",
    "Prüfe Preise und Berechnungsänderungen. Erst freigebende Person und getrennte Bestätigungen für Preise und Neuberechnung erlauben die Übernahme. Rohbelege und Ereignisklassifikationen bleiben unverändert; offene Einordnungen und Jahresfreigaben bleiben offen.",
    "Ordne unbekannte Token einer exakten Preisquelle zu. Historische EUR-Preise benoetigen keine V1-Installation. Der manuelle Portfolio-Kursabruf speichert Preise im gemeinsamen Ledger und startet eine Neuberechnung. Sein Anbieter-Kurszeitpunkt wird nicht geprueft.",
    "Untersuche Bestandsabweichungen im Quellenabgleich. Fehlende Anschaffungsbelege nicht durch geschaetzte Kaeufe ersetzen."
  ], caution: "Aktueller Marktwert, steuerlicher Gewinn und tatsaechlicher Geldzufluss sind verschiedene Groessen." },
  { id: "stichtage", title: "Historische Stichtagswerte", keywords: "datum bewertung kurs historisch", steps: [
    "Waehle den benoetigten Stichtag und pruefe den bis dahin berechneten Bestand.",
    "Kontrolliere fuer wesentliche Positionen Preisdatum und Bewertungsquelle. Fehlende oder veraltete Preise als offene Bewertung dokumentieren."
  ], caution: "Ein heutiger Kurs darf nicht stillschweigend als historischer Kurs verwendet werden." },
  { id: "zugewinn", title: "Stichtagsdossier und Herkunftsnachweise", keywords: "erbe erb geld vermoegen kapitalherkunft", steps: [
    "Pruefe die konfigurierten Stichtage und den belegten Verlauf der Ein- und Auszahlungen.",
    "Ordne Herkunftsnachweise den konkreten Geldbewegungen und Anschaffungen zu. Pruefe offene Preis- und Beleganforderungen vor dem Export."
  ], caution: "Die technische Zuordnung von Vermoegen ersetzt keine rechtliche Bewertung des Zugewinns." },
  { id: "ai", title: "KI einrichten und Aufgaben freigeben", keywords: "openrouter lokal cloud free modell agent textaufgabe datenschutz token", steps: [
    "Waehle Anbieter und Verbindung, trage bei Bedarf den API-Key ein, aktiviere den vorgesehenen Zugriff und speichere. Lade dann die Modelle, filtere bei OpenRouter bei Bedarf auf Free, waehle ein Modell und speichere erneut.",
    "Pruefe die Verbindung und waehle einen Fachagenten. Ohne eigene Modell-ID nutzt ein Agent das gespeicherte Modell der aktiven Verbindung; es laufen nicht automatisch mehrere Agenten zusammen.",
    "Textaufgaben verarbeiten den eingegebenen Text, nicht automatisch die gesamte Datenbank. Pruefe bei Cloud-Aufgaben die zu sendenden Inhalte und erteile die ausdrueckliche Freigabe."
  ], caution: "Free ist eine Preiskennzeichnung, keine Zusage zu Datenschutz oder Richtigkeit. Verbindungstests und Aufgaben koennen Anbieterzugriffe ausloesen; die Hilfeseite selbst tut dies nicht." },
  { id: "corrections", title: "Datenkorrekturen mit Vorschau und Freigabe", keywords: "ki datenbank aendern ruecknahme audit freigabe sql", steps: [
    "Oeffne im KI-Assistenten Datenkorrekturen. Lade gefilterte Transaktionen oder Preise und waehle hoechstens 25 Zeilen aus.",
    "Beschreibe den Korrekturauftrag mit mindestens zehn Zeichen. Pruefe den Datenkontext vor einer Cloud-Freigabe. Alternativ kannst du die Aenderung manuell vorbereiten.",
    "Pruefe jeden Vorschlag mit Begruendung und Beleg. Waehle die Positionen fuer eine Berechnungsvorschau und kontrolliere die Summen und Einzelabweichungen.",
    "Erst die ausdrueckliche menschliche Freigabe uebernimmt die geprueften Aenderungen. Lade das Audit herunter. Eine Ruecknahme ist ein eigener Vorschlag mit neuer Vorschau und Freigabe."
  ], caution: "Keine freien SQL-Befehle, keine neuen oder geloeschten Transaktionen und keine Serversteuerung. Bei geaendertem Datenstand ist eine neue Vorschau erforderlich; Rohbelege und alte Abgabestaende bleiben unveraendert." }
] as const;

export const GLOSSARY = [
  ["Ledger", "Aus den importierten Ereignissen berechnete Buchungs- oder Bestandsdaten; nicht automatisch identisch mit einem aktuellen API-Snapshot."],
  ["FIFO und Lot", "FIFO ordnet Abgaenge zuerst angeschafften Bestaenden zu. Ein Lot ist ein Anschaffungsbestand mit Zeit, Menge und Anschaffungskosten."],
  ["Unmatched", "Fuer einen Abgang konnte kein ausreichend belegter Anschaffungsbestand zugeordnet werden. Die Luecke ist zu pruefen, nicht durch einen erfundenen Kauf zu schliessen."],
  ["Snapshot", "Ein gespeicherter Stand zu einem bestimmten Zeitpunkt. Ein Live-Bestandssnapshot ist nicht dasselbe wie ein Abgabestand einer Steuererklaerung."],
  ["Reconciliation / Summenabgleich", "Pruefung, ob Einzelpositionen und Summen exakt zueinander passen. reconciliation_failed bedeutet, dass diese Ueberleitung nicht aufgeht."],
  ["Gate / blockiert", "Eine fachliche Voraussetzung ist offen. Die zugehoerigen Hinweise nennen, was vor einer Freigabe geklaert werden muss."],
  ["Hash / SHA256", "Pruefsumme eines konkreten Inhalts. Gleiche Hashes belegen identischen Inhalt, nicht dessen sachliche Richtigkeit."],
  ["Canonical Event", "Ein aus einer Quelle vereinheitlichtes Ereignis mit stabiler Zuordnung und Verweis auf den Rohbeleg."],
  ["Handelsvolumen", "Umfang von Kaeufen, Verkaeufen oder Swaps; nicht gleich Gewinn, Einkommen oder EUR-Auszahlung."],
  ["FX", "Umrechnung zwischen Waehrungen. USDT und USDC sind keine EUR-Betraege und koennen eine eigene Preis- oder Umrechnungsquelle benoetigen."]
] as const;

const FAQ = [
  ["Warum ist eine Schaltflaeche deaktiviert?", "Pruefe Pflichtfelder, noch nicht gespeicherte Einstellungen und Freigaben. Beim Import sind zuerst Quelle, Dateien und Pruefung erforderlich. KI-Aufgaben benoetigen eine gespeicherte aktive Verbindung; Cloud-Aufgaben ausserdem eine ausdrueckliche Sendefreigabe. Eine Datenkorrektur erfordert zusaetzlich eine passende Vorschau und menschliche Bestaetigung."],
  ["Warum sehe ich keine Modelle zur Auswahl?", "Speichere zuerst eine aktivierte Verbindung und lade die Modelle. Pruefe Suchtext und Free-Filter. Bei einem Server ohne Modellkatalog kann die Modell-ID manuell eingetragen werden. Speichere das gewaehlte Modell, bevor du eine Aufgabe startest."],
  ["Warum weicht der Bericht trotz 0,00 EUR Differenz ab?", "Eine auf zwei Stellen gerundete Summe beschreibt nicht den gesamten Bericht. Positionen, Zuordnungen, Methode oder Belegstand koennen abweichen; gegenlaeufige Aenderungen koennen sich aufheben. Vergleiche auch Ereignisse, Tax-Lines und Quellen des konkreten Abgabestands."],
  ["Kann ich dieselben Daten aus mehreren Quellen importieren?", "Nur nach Pruefung der Ueberlappung und der Rolle jeder Quelle. Dieselbe wirtschaftliche Transaktion kann in Boersen-, Wallet- und Vergleichsexporten vorkommen. Ein Datei-Hash erkennt identische Dateien, aber nicht jede fachliche Doppelzaehlung."],
  ["Veraendert Aktualisieren meine Steuerdaten?", "Die globale Schaltflaeche Aktualisieren laedt den angezeigten Zustand erneut. Ein Import, eine Neuberechnung, ein API-Abruf oder eine freigegebene Korrektur sind separate Aktionen; beachte jeweils deren Bezeichnung und Bestaetigung."]
] as const;

/** Hover/focus tooltip that can also be pinned on touch without leaving the form. */
export function HelpTip({ label, children }: { label: string; children: string }) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const cancel = () => clearTimeout(timer.current);
  const show = () => { cancel(); document.dispatchEvent(new CustomEvent("steuerreport:help-open", { detail: id })); setOpen(true); };
  const hide = () => { cancel(); if (!pinned) timer.current = setTimeout(() => setOpen(false), 160); };
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); setPinned(false); } };
    const outside = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node) && !tip.current?.contains(event.target as Node)) { setOpen(false); setPinned(false); }
    };
    const other = (event: Event) => { if ((event as CustomEvent<string>).detail !== id) { cancel(); setOpen(false); setPinned(false); } };
    document.addEventListener("keydown", close);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("steuerreport:help-open", other);
    return () => { document.removeEventListener("keydown", close); document.removeEventListener("pointerdown", outside); document.removeEventListener("steuerreport:help-open", other); };
  }, [open, id]);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      if (!trigger.current || !tip.current) return;
      const anchor = trigger.current.getBoundingClientRect();
      const box = tip.current.getBoundingClientRect();
      setPosition({ left: Math.max(8, Math.min(anchor.left, window.innerWidth - box.width - 8)),
        top: Math.max(8, Math.min(anchor.bottom + 6 + box.height > window.innerHeight - 8 ? anchor.top - box.height - 6 : anchor.bottom + 6, window.innerHeight - box.height - 8)) });
    };
    place(); window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, children]);
  return <span className="helpTipAnchor"><button ref={trigger} type="button" className="helpTipButton" aria-label={`Hilfe: ${label}`}
    aria-describedby={open ? id : undefined} aria-expanded={open} onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}
    onClick={() => { cancel(); setOpen(!pinned); setPinned(!pinned); }}><HelpCircle size={17} aria-hidden="true" /></button>
    {open && createPortal(<div ref={tip} id={id} role="tooltip" className="helpTooltip" style={position} onMouseEnter={cancel} onMouseLeave={hide}>
      <strong>{label}</strong><span>{children}</span>
    </div>, document.body)}</span>;
}

export function WorkflowNavigation({ active }: { active: string }) {
  const index = WORKFLOW.findIndex((step) => step.id === active);
  if (index < 0) return null;
  const steps = <ol>{WORKFLOW.map((step, at) => <li key={step.id}><a href={`#${step.id}`} aria-current={active === step.id ? "step" : undefined}>
    <span>{at + 1}</span>{step.label}</a>{at < WORKFLOW.length - 1 && <ArrowRight size={14} aria-hidden="true" />}</li>)}</ol>;
  return <nav className="workflowNavigation" aria-label="Arbeitsablauf">
    <div className="workflowWide">{steps}</div>
    <details className="workflowCompact"><summary>{`Schritt ${index + 1} von 5: ${WORKFLOW[index].label}`}</summary>{steps}</details>
    <HelpTip label="Arbeitsablauf">Die Schritte dienen der Orientierung, nicht als Nachweis erledigter Pruefungen. Du kannst jederzeit zwischen den Bereichen wechseln.</HelpTip>
  </nav>;
}

function matches(query: string, value: string) {
  const normalize = (text: string) => text.toLowerCase().replaceAll("ä", "ae").replaceAll("ö", "oe").replaceAll("ü", "ue").replaceAll("ß", "ss").replace(/[^a-z0-9]+/g, " ").trim();
  return normalize(query).split(/\s+/).every((word) => normalize(value).includes(word));
}

export function HelpCenter({ initialTopic = "all" }: { initialTopic?: string }) {
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState(initialTopic);
  const topics = HELP_TOPICS.filter((item) => (topic === "all" || item.id === topic) && matches(query, [item.title, item.keywords, ...item.steps, item.caution].join(" ")));
  const glossary = topic === "all" ? GLOSSARY.filter((item) => matches(query, item.join(" "))) : [];
  const faqs = topic === "all" ? FAQ.filter((item) => matches(query, item.join(" "))) : [];
  const count = topics.length + glossary.length + faqs.length;
  return <section className="helpCenter" aria-label="Hilfe und Anleitungen">
    <div className="helpSearch"><label><span>Hilfe durchsuchen</span><span className="helpSearchInput"><Search size={18} aria-hidden="true" /><input type="search" value={query} aria-label="Hilfe durchsuchen" placeholder="Zum Beispiel Import, FIFO oder Free-Modelle" onChange={(event) => setQuery(event.target.value)} /></span></label>
      <label>Bereich<select aria-label="Hilfebereich" value={topic} onChange={(event) => setTopic(event.target.value)}><option value="all">Alle Bereiche</option>{HELP_TOPICS.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
      {(query || topic !== "all") && <button type="button" className="ghostButton" onClick={() => { setQuery(""); setTopic("all"); }}><X size={16} /> Filter zuruecksetzen</button>}
    </div>
    <p className="helpResults" role="status">{count ? `${count} Hilfethemen` : "Keine passenden Hilfethemen. Anderen Suchbegriff waehlen oder die Filter zuruecksetzen."}</p>
    {!!topics.length && <section className="helpSection"><h2>Arbeitsablaeufe</h2>{topics.map((item) => <details key={`${item.id}:${!!query}:${topic}`} className="helpArticle" open={query || topic !== "all" ? true : undefined}>
      <summary>{item.title}</summary><ol>{item.steps.map((step) => <li key={step}>{step}</li>)}</ol><p className="helpCaution">{item.caution}</p>
      <a className="helpAction" href={`#${item.id === "corrections" ? "ai" : item.id}`}><ArrowRight size={16} /> {item.id === "corrections" ? "KI-Assistent oeffnen" : "Bereich oeffnen"}</a>
      {item.id === "import" && <a className="helpAction" href="/importformate.html" target="_blank" rel="noreferrer"><BookOpen size={16} /> Formate und Pflichtspalten</a>}
      {(item.id === "ai" || item.id === "corrections") && <a className="helpAction" href="/ki-einsatzleitfaden.html" target="_blank" rel="noreferrer"><BookOpen size={16} /> Ausfuehrlicher KI-Leitfaden</a>}
    </details>)}</section>}
    {!!faqs.length && <section className="helpSection"><h2>Haeufige Fragen</h2>{faqs.map(([title, text]) => <details key={`${title}:${!!query}`} className="helpArticle" open={query ? true : undefined}><summary>{title}</summary><p>{text}</p></details>)}</section>}
    {!!glossary.length && <section className="helpSection"><h2>Begriffe</h2><dl className="helpGlossary">{glossary.map(([term, text]) => <div key={term}><dt>{term}</dt><dd>{text}</dd></div>)}</dl></section>}
    <section className="helpSection"><h2>Anleitungen zum Nachlesen</h2><div className="helpDocuments">{[
      ["Benutzerleitfaden", "benutzerleitfaden"], ["Importformate und Vorlagen", "importformate"], ["KI: Einsatz und Grenzen", "ki-einsatzleitfaden"]
    ].map(([label, file]) => <div key={file}><a href={`/${file}.html`} target="_blank" rel="noreferrer"><BookOpen size={18} />{label}</a><a href={`/${file}.pdf`} download aria-label={`${label} als PDF herunterladen`} title="PDF herunterladen"><Download size={18} /><span>PDF</span></a></div>)}</div></section>
  </section>;
}
