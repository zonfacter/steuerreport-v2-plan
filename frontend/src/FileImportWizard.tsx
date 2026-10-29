import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ChevronLeft, ChevronRight, ClipboardCheck, Download, FileDown, FolderOpen, LoaderCircle, Trash2, Upload } from "lucide-react";
import { API_BASE } from "./api-base";
import { HelpTip } from "./Help";

type Profile = { source: string; label: string };
const MEXC_KINDS = {
  spot_statement: "Spot Statement", funding_other: "Funding Other", asset_snapshot: "Asset Snapshots",
  futures_capital_flow: "Futures Capital Flow", futures_statement: "Futures Statement",
  earn_fixed: "Earn Fixed", earn_flexible: "Earn Flexible", send_history: "Send History",
} as const;
type MexcKind = keyof typeof MEXC_KINDS;
type MexcTimezone = "UTC" | "UTC+01:00" | "UTC+08:00" | "Europe/Berlin";
type MexcDecision = { action: "link_existing" | "separate"; target_raw_object_id?: string; reason: string };
type MexcRow = {
  row_number: number; status: "ready" | "review" | "duplicate_candidate" | "linked" | "evidence_only" | "invalid";
  reason: string; asset?: string; quantity?: string; event_time?: string;
  candidates: { raw_object_id: string; filename: string | null; row_number: number | null; export_kind: string }[];
};
type MexcPreview = {
  detected_kind: string | null; disposition: "transactions" | "evidence_only" | "empty" | "unsupported";
  raw_rows: number; bookable_rows: number; linked_rows: number; review_rows: number; snapshot_rows: number; bonus_rows: number;
  blocking_reasons: string[]; warnings: string[]; rows: MexcRow[];
};
type Preview = {
  can_execute: boolean; blocked_reason?: string; warnings: string[];
  preview?: { row_count: number; columns: string[]; sample_rows: Record<string, unknown>[];
    sheet_name?: string; sheet_names: string[]; duplicate_batch_id?: string;
    file_sha256?: string; import_fingerprint?: string; missing_required_groups: string[]; profile_label: string; mexc?: MexcPreview };
};
type Outcome = { batch: { batch_id: string }; run: { imported_rows: number; normalized_events: number; skipped_raw_objects: number } };
type Status = "pending" | "checking" | "ready" | "duplicate" | "blocked" | "empty" | "writing" | "imported" | "error";
type Item = {
  id: string; file: File; encoded?: string; sheet?: string; sheets?: string[]; preview?: Preview; status: Status; error?: string; result?: Outcome;
  exportKind?: MexcKind; timezone?: MexcTimezone; decisions?: Record<string, MexcDecision>; review?: MexcPreview;
};
const LABELS: Record<Status, string> = { pending: "Ungeprueft", checking: "Wird geprueft", ready: "Importierbar", duplicate: "Bereits vorhanden", blocked: "Nicht importierbar", empty: "Leer (kein Import)", writing: "Wird importiert", imported: "Importiert", error: "Fehler" };
const SOURCES = new Set(["manual-csv", "binance", "bitget", "mexc", "pionex", "coinbase", "helium", "solana_rpc"]);
const MEXC_ROW_LABELS: Record<MexcRow["status"], string> = { ready: "Mengenbewegung buchbar", review: "Fachlich zu pruefen", duplicate_candidate: "Moeglicher Doppelbeleg", linked: "Verknuepft", evidence_only: "Nur Beleg", invalid: "Ungueltig" };

function MexcReview({ item, disabled, onDecision }: { item: Item; disabled: boolean; onDecision: (row: number, decision?: MexcDecision) => void }) {
  const [page, setPage] = useState(0);
  const review = item.preview?.preview?.mexc || item.review;
  if (!review) return null;
  const pages = Math.max(1, Math.ceil(review.rows.length / 25));
  const activePage = Math.min(page, pages - 1);
  return <section aria-label={`MEXC-Pruefung fuer ${item.file.name}`} style={{ minWidth: 0, overflowWrap: "anywhere" }}>
    {!item.preview && <p role="status">Vorschau nicht mehr aktuell. Entscheidungen erneut pruefen lassen.</p>}
    {review.disposition !== "transactions" && <p>{review.disposition === "empty" ? "Leerer Export: keine Datenzeilen, kein erfolgreicher Import." : review.disposition === "evidence_only" ? "Nur Beleg / Bestandsabgleich, keine neuen Erwerbe." : "Export fachlich nicht unterstuetzt."}</p>}
    <dl className="importFileFacts" aria-label="MEXC-Gesamtzahlen">{[
      ["Rohzeilen", review.raw_rows], ["Mengenbuchungen", review.bookable_rows], ["Verknuepft", review.linked_rows],
      ["Doppelbeleg-Kandidaten", review.rows.filter((row) => row.status === "duplicate_candidate").length],
      ["fachlich offen", review.review_rows], ["Bestandszeilen", review.snapshot_rows], ["BONUS-Zeilen", review.bonus_rows],
    ].map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>
    <small>Zaehler sind nicht additiv: Mengenbuchungen koennen fachlich offen sein.</small>
    {review.blocking_reasons.map((reason, index) => <p role="status" className="importWarning" key={`block-${index}`}>{reason}</p>)}
    {review.warnings.map((warning, index) => <p className="importWarning" key={`warn-${index}`}>{warning}</p>)}
    <details><summary>Zeilenpruefung ({review.rows.length})</summary>
      <p>Erkannte Exportart: {review.detected_kind ? MEXC_KINDS[review.detected_kind as MexcKind] || review.detected_kind : "noch offen"}. Physische Dateizeilen einschliesslich Kopfzeile; Excel-Daten beginnen ab Zeile 2.</p>
      <p>Mengenbuchungen und fachlich offene Zeilen koennen sich ueberschneiden: eine belegte Menge ist noch keine freigegebene Fachklassifikation.</p>
      {review.disposition === "transactions" && <p>Airdrop bleibt zunaechst ein ungeklaerter Vorgang (unknown), keine automatische Mining-, Reward- oder Einkunftseinstufung.</p>}
      {review.rows.slice(activePage * 25, (activePage + 1) * 25).map((row) => {
        const decision = item.decisions?.[String(row.row_number)];
        const reasonInvalid = Boolean(decision && decision.reason.trim().length < 10);
        const reasonId = `mexc-reason-${item.id}-${row.row_number}`;
        return <div key={row.row_number} style={{ borderTop: "1px solid #d6ded9", paddingBlock: 12 }}>
          <strong>Zeile {row.row_number}: {MEXC_ROW_LABELS[row.status]}</strong>
          <p>{[row.asset, row.quantity, row.event_time].filter(Boolean).join(" / ")}</p><p>{row.reason}</p>
          {(row.status === "duplicate_candidate" || row.candidates.length > 0 || decision) && <div className="importSelection">
            <label>Belegzuordnung, Zeile {row.row_number}<select aria-label={`Belegzuordnung Zeile ${row.row_number} fuer ${item.file.name}`} disabled={disabled}
              value={decision?.action === "separate" ? "separate" : decision?.target_raw_object_id ? `raw:${decision.target_raw_object_id}` : ""}
              onChange={(event) => onDecision(row.row_number, !event.target.value ? undefined : {
                action: event.target.value === "separate" ? "separate" : "link_existing",
                ...(event.target.value.startsWith("raw:") ? { target_raw_object_id: event.target.value.slice(4) } : {}), reason: decision?.reason || "",
              })}>
              <option value="">Zuordnung offen</option><option value="separate">Eigenstaendige Buchung (separat)</option>
              {row.candidates.map((candidate) => <option key={candidate.raw_object_id} value={`raw:${candidate.raw_object_id}`}>{candidate.filename || "Beleg ohne Dateiname"} / Zeile {candidate.row_number ?? "unbekannt"} / {MEXC_KINDS[candidate.export_kind as MexcKind] || candidate.export_kind} / {candidate.raw_object_id}</option>)}
              {decision?.target_raw_object_id && !row.candidates.some((candidate) => candidate.raw_object_id === decision.target_raw_object_id) && <option value={`raw:${decision.target_raw_object_id}`}>{decision.target_raw_object_id} (erneut pruefen)</option>}
            </select></label>
            {decision && <label>Begruendung, Zeile {row.row_number}<input aria-label={`Begruendung Zeile ${row.row_number} fuer ${item.file.name}`} value={decision.reason} disabled={disabled} minLength={10} required
              aria-invalid={reasonInvalid} aria-describedby={reasonId} onChange={(event) => onDecision(row.row_number, { ...decision, reason: event.target.value })} />
              <small id={reasonId}>Mindestens 10 Zeichen; Beleggrund fuer die Zuordnung.</small></label>}
          </div>}
        </div>;
      })}
      <nav className="buttonRow" aria-label={`Zeilenseiten fuer ${item.file.name}`}>
        <button type="button" title="Vorherige Zeilenseite" aria-label="Vorherige Zeilenseite" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}><ChevronLeft size={16} /></button>
        <span role="status">Seite {activePage + 1} von {pages} / {review.rows.length} Zeilen</span>
        <button type="button" title="Naechste Zeilenseite" aria-label="Naechste Zeilenseite" disabled={activePage + 1 >= pages} onClick={() => setPage(activePage + 1)}><ChevronRight size={16} /></button>
      </nav>
    </details>
  </section>;
}

function fileProblem(file: File, source: string): string | undefined {
  if (source === "mexc" && !/\.(csv|xlsx)$/i.test(file.name)) return "MEXC unterstuetzt nur CSV oder XLSX (kein XLS).";
  const formats = source === "mexc" ? "CSV oder XLSX" : "CSV, XLSX oder XLS";
  return !/\.(csv|xlsx|xls)$/i.test(file.name) || file.size === 0 || file.size > 25 * 1024 * 1024
    ? `${formats} erforderlich; Datei darf nicht leer und hoechstens 25 MiB gross sein.` : undefined;
}

async function api<T>(path: string, payload?: unknown, timeout = 60000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  let safeError = "Anfrage fehlgeschlagen. Importverlauf pruefen und erneut versuchen.";
  try {
    const response = await fetch(API_BASE + path, payload === undefined ? { signal: controller.signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: controller.signal,
    });
    if (!response.ok) { safeError = `Anfrage fehlgeschlagen (HTTP ${response.status}). Importverlauf pruefen.`; throw new Error(); }
    const body = await response.json();
    if (body.status === "error") throw new Error();
    return body.data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("Zeitlimit erreicht. Importverlauf vor einem erneuten Versuch pruefen.");
    throw new Error(safeError);
  } finally { window.clearTimeout(timer); }
}

function encodedFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Datei konnte nicht geoeffnet werden."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.readAsDataURL(file);
  });
}

export function FileImportWizard({ onComplete }: { onComplete: () => void | Promise<void> }) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [source, setSource] = useState("");
  const [mexcAccount, setMexcAccount] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState("");
  const [details, setDetails] = useState<string | null>(null);
  const nextId = useRef(0);
  const generation = useRef(0);
  const gate = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    let mounted = true;
    const preferred = window.sessionStorage.getItem("steuerreport:import-source-once");
    window.sessionStorage.removeItem("steuerreport:import-source-once");
    if (preferred && SOURCES.has(preferred)) setSource(preferred);
    void api<Profile[]>("/api/v1/import/profiles").then((rows) => { if (mounted) setProfiles(rows.filter((row) => SOURCES.has(row.source))); })
      .catch(() => { if (mounted) setError("Importquellen konnten nicht geladen werden."); });
    return () => { mounted = false; generation.current += 1; };
  }, []);
  const ready = items.filter((item) => item.status === "ready");
  const imported = items.filter((item) => item.status === "imported");
  const current = items.find((item) => item.id === details);
  const stage = imported.length ? 4 : ready.length ? 3 : items.length ? 2 : 1;
  const update = (id: string, value: Partial<Item>) => setItems((rows) => rows.map((row) => row.id === id ? { ...row, ...value } : row));

  function resetItem(item: Item, selectedSource: string): Item {
    const problem = fileProblem(item.file, selectedSource);
    return { ...item, status: problem ? "error" : "pending", preview: undefined, review: undefined, decisions: undefined, error: problem };
  }

  function configureItem(id: string, value: Partial<Item>) {
    generation.current += 1; setApproved(false); setError("");
    setItems((rows) => rows.map((row) => row.id === id ? resetItem({ ...row, ...value }, source) : row));
  }

  function mexcPayload(item: Item) {
    // Missing configuration deliberately reaches the native server preview without a partial contract object.
    return source === "mexc" && item.exportKind && mexcAccount.trim() ? { mexc: {
      export_kind: item.exportKind, account: mexcAccount.trim(), ...(item.timezone ? { timezone: item.timezone } : {}), decisions: item.decisions || {},
    } } : {};
  }

  function addFiles(files: File[]) {
    setError(""); setApproved(false);
    if (items.length + files.length > 20 || [...items.map((item) => item.file), ...files].reduce((size, file) => size + file.size, 0) > 100 * 1024 * 1024) {
      setError("Hoechstens 20 Dateien und insgesamt 100 MiB pro Importvorgang."); return;
    }
    const added: Item[] = files.map((file) => ({ id: String(++nextId.current), file, status: "pending" }));
    for (const item of added) {
      const problem = fileProblem(item.file, source);
      if (problem) { item.status = "error"; item.error = problem; }
    }
    setItems((rows) => [...rows, ...added]);
  }

  async function checkFiles() {
    if (gate.current || !source) return;
    gate.current = true; setBusy(true); setApproved(false); setError("");
    const token = generation.current;
    const fingerprints = new Set<string>();
    try {
      for (const item of items.filter((row) => row.status !== "imported" && !fileProblem(row.file, source))) {
        if (token !== generation.current) break;
        update(item.id, { status: "checking", error: undefined });
        try {
          const encoded = item.encoded || await encodedFile(item.file);
          if (source === "mexc" && Object.values(item.decisions || {}).some((decision) => decision.reason.trim().length < 10 || (decision.action === "link_existing" && !decision.target_raw_object_id))) {
            update(item.id, { status: "pending", error: "Belegzuordnung mit Ziel und mindestens 10 Zeichen Begruendung vervollstaendigen." }); continue;
          }
          const preview = await api<Preview>("/api/v1/import/assistant/preview", { source, import_mode: "file", filename: item.file.name, content_base64: encoded, sheet_name: item.sheet, ...mexcPayload(item) });
          if (token !== generation.current) break;
          const fingerprint = preview.preview?.import_fingerprint;
          const repeated = Boolean(fingerprint && fingerprints.has(fingerprint));
          if (fingerprint) fingerprints.add(fingerprint);
          if (repeated) { preview.can_execute = false; preview.blocked_reason = "Identische Datei und dasselbe Tabellenblatt bereits in dieser Auswahl."; }
          const mexc = preview.preview?.mexc;
          const configured = source !== "mexc" || Boolean(item.exportKind && mexcAccount.trim() && mexc && !mexc.blocking_reasons.length && mexc.disposition !== "unsupported");
          update(item.id, { encoded, preview, review: mexc, sheets: preview.preview?.sheet_names, sheet: preview.preview?.sheet_name ?? item.sheet,
            status: mexc?.disposition === "empty" ? "empty" : repeated || preview.preview?.duplicate_batch_id ? "duplicate" : preview.can_execute && configured ? "ready" : "blocked" });
        } catch (caught) { if (token === generation.current) update(item.id, { status: "error", preview: undefined, error: caught instanceof Error ? caught.message : "Dateipruefung fehlgeschlagen." }); }
      }
    } finally { gate.current = false; if (token === generation.current) setBusy(false); }
  }

  async function importFiles() {
    if (gate.current || !approved || !ready.length) return;
    gate.current = true; setBusy(true); setApproved(false); setError("");
    const token = generation.current;
    try {
      for (const item of ready) {
        if (token !== generation.current) break;
        update(item.id, { status: "writing" });
        try {
          const result = await api<Outcome>("/api/v1/import/assistant/execute", { source, import_mode: "file", filename: item.file.name, content_base64: item.encoded, sheet_name: item.sheet, ...mexcPayload(item) }, 240000);
          if (token !== generation.current) break;
          update(item.id, { status: "imported", result });
        } catch (caught) { if (token === generation.current) update(item.id, { status: "error", preview: undefined, error: caught instanceof Error ? caught.message : "Import konnte nicht bestaetigt werden." }); }
      }
      if (token === generation.current) await onComplete();
    } catch { if (token === generation.current) setError("Importverlauf konnte nicht aktualisiert werden. Seite neu laden."); }
    finally { gate.current = false; if (token === generation.current) setBusy(false); }
  }

  return <section className="fileImportWizard" aria-label="Dateiimport">
    <div className="panelToolbar"><h2>Dateien importieren</h2><div className="buttonRow">
      <HelpTip label="Importquelle und Dateiformat">{`Die Quelle bestimmt Spalten und Bedeutung der Buchungen. ${source === "mexc" ? "MEXC unterstuetzt nur CSV oder XLSX (kein XLS)." : "CSV, XLSX und XLS werden nur mit passendem Layout verarbeitet."} Erst pruefen und die Vorschau kontrollieren; die Pruefung allein importiert noch keine Datei.`}</HelpTip>
      <a href="/benutzerleitfaden.html#import" target="_blank" rel="noreferrer" className="ghostButton"><FileDown size={16} /> Leitfaden</a>
      <a href={`/importformate.html${source ? `#${source}` : ""}`} target="_blank" rel="noreferrer" className="ghostButton"><FileDown size={16} /> Formate &amp; Spalten</a>
      <a href={source ? `/import-vorlagen/${source}.csv` : "/import-vorlage.csv"} download className="ghostButton"><Download size={16} /> CSV-Vorlage</a>
      <a href="/import-vorlagen/import-vorlagen.xlsx" download className="ghostButton"><Download size={16} /> Excel-Vorlagen</a>
    </div></div>
    <ol className="importStages" aria-label="Importfortschritt">{["Dateien", "Pruefung", "Freigabe", "Ergebnis"].map((label, index) => <li key={label} aria-current={stage === index + 1 ? "step" : undefined} className={stage > index + 1 ? "complete" : ""}><span>{stage > index + 1 ? <Check size={15} /> : index + 1}</span>{label}</li>)}</ol>
    <p className="actionRequirement" role="status">{busy ? "Dateivorgang wird verarbeitet." : !source ? "Zuerst die Quelle fuer deine Dateien waehlen." : !items.length ? "Dateien auswaehlen oder hierher ziehen." : ready.length && !approved ? "Vorschau und Warnungen pruefen, dann die geprueften Dateien freigeben." : ready.length ? "Freigegebene Dateien sind bereit fuer den Import." : imported.length === items.length ? "Import abgeschlossen. Ergebnis und offene Hinweise pruefen." : items.every((item) => item.status === "empty") ? "Leere Exporte enthalten keine Datenzeilen und werden nicht importiert." : items.some((item) => ["error", "blocked"].includes(item.status)) ? "Dateihinweise klaeren oder betroffene Dateien aus der Auswahl entfernen." : "Dateien pruefen und danach die Vorschau kontrollieren."}</p>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="importSelection"><label>Quelle<select aria-label="Importquelle" value={source} disabled={busy || imported.length > 0} onChange={(event) => { const selectedSource = event.target.value; generation.current += 1; setSource(selectedSource); setApproved(false); setError(""); setItems((rows) => rows.map((row) => resetItem(row, selectedSource))); }}>
      <option value="">Quelle auswaehlen</option>{profiles.map((profile) => <option key={profile.source} value={profile.source}>{profile.label}</option>)}
    </select></label>
    {source === "mexc" && <label>MEXC-Konto<input aria-label="MEXC-Konto" value={mexcAccount} maxLength={128} disabled={busy || imported.length > 0}
      onChange={(event) => { generation.current += 1; setMexcAccount(event.target.value); setApproved(false); setError(""); setItems((rows) => rows.map((row) => resetItem(row, source))); }} /></label>}
    <input ref={fileInput} hidden type="file" multiple accept={source === "mexc" ? ".csv,.xlsx" : ".csv,.xlsx,.xls"} aria-label="Importdateien auswaehlen" disabled={busy} onChange={(event) => { addFiles(Array.from(event.target.files || [])); event.target.value = ""; }} />
    <button type="button" disabled={busy || !source || !items.some((item) => item.status !== "imported" && !fileProblem(item.file, source))} onClick={() => void checkFiles()}><ClipboardCheck size={16} /> Dateien pruefen</button></div>
    {source === "mexc" && <>
      <p className="importWarning">Bestandsbelege und ungeklaerte Mengen sind keine Erwerbsbasis und erzeugen keine belegten Anschaffungskosten. Eine Belegzuordnung ist keine Steuerentscheidung; fehlende Anfangshistorie bleibt offen.</p>
      <HelpTip label="MEXC Exportart und Zeitbasis">Die Exportart muss zum tatsaechlichen Produkt passen; der Dateiname allein ist kein Nachweis. Ohne Konto und Exportart ist eine erste Vorschau moeglich, aber keine Freigabe. Bei Time ohne Offset bleibt die Zeitbasis offen. UTC+01:00 ist ein fester Offset, Europe/Berlin wechselt zwischen Sommer- und Winterzeit. Eine abweichende Header-Zeitbasis muss der Server pruefen. Sicherheitsgrenzen fuer MEXC: 10.000 Datenzeilen, 25 MiB je Datei und 100 MiB entpackter XLSX-Inhalt; serverseitige Pruefung.</HelpTip>
      {items.length > 1 && <p className="importWarning">Jede Datei wird beim Import serverseitig erneut geprueft. Nach der ersten Datei kann eine weitere Datei wegen eines neu entstandenen Dublettenkandidaten blockieren. Keine automatische Zusammenlegung; danach erneut pruefen und Belege zuordnen.</p>}
    </>}
    <div className={`fileDropZone ${busy ? "busy" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (!busy) addFiles(Array.from(event.dataTransfer.files)); }}>
      <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}><FolderOpen size={22} /> Dateien auswaehlen</button><span>{source === "mexc" ? "CSV / XLSX" : "CSV / XLSX / XLS"}</span>
    </div>
    {items.length > 0 && <div className="importFileList" aria-live="polite">{items.map((item) => <article className="importFile" key={item.id}>
      <div className="importFileHeading"><div><strong>{item.file.name}</strong><small>{(item.file.size / 1024).toFixed(1)} KB</small></div><span className={`statusPill ${item.status === "ready" || item.status === "imported" ? "ok" : item.status === "error" || item.status === "blocked" ? "blocked" : "pending"}`}>{["checking", "writing"].includes(item.status) && <LoaderCircle size={14} />}{LABELS[item.status]}</span>
        <button type="button" className="ghostButton" title="Datei aus Auswahl entfernen" aria-label={`Datei ${item.file.name} aus Auswahl entfernen`} disabled={busy || item.status === "imported"} onClick={() => { setItems((rows) => rows.filter((row) => row.id !== item.id)); setApproved(false); }}><Trash2 size={16} /></button></div>
      {source === "mexc" && <div className="importSelection" style={{ marginTop: 12 }}>
        <label>Exportart<select aria-label={`MEXC-Exportart fuer ${item.file.name}`} value={item.exportKind || ""} disabled={busy || item.status === "imported"}
          onChange={(event) => configureItem(item.id, { exportKind: (event.target.value || undefined) as MexcKind | undefined })}>
          <option value="">Exportart bestaetigen</option>{Object.entries(MEXC_KINDS).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}
        </select></label>
        <label>Zeitbasis<select aria-label={`MEXC-Zeitbasis fuer ${item.file.name}`} value={item.timezone || ""} disabled={busy || item.status === "imported"}
          onChange={(event) => configureItem(item.id, { timezone: (event.target.value || undefined) as MexcTimezone | undefined })}>
          <option value="">Offen / expliziter Header-Offset</option><option value="UTC">UTC</option><option value="UTC+01:00">UTC+01:00 (fest)</option>
          <option value="UTC+08:00">UTC+08:00 (fest)</option><option value="Europe/Berlin">Europe/Berlin (Sommer-/Winterzeit)</option>
        </select></label>
      </div>}
      {(item.preview?.preview || Boolean(item.sheets?.length)) && <div className="importFileFacts">
        {item.preview?.preview && <><span>{item.preview.preview.row_count} Zeilen</span><span>{item.preview.preview.profile_label}</span></>}
        {Boolean(item.sheets?.length) && <label>Tabellenblatt<select aria-label={`Tabellenblatt fuer ${item.file.name}`} value={item.sheet || ""} disabled={busy || item.status === "imported"} onChange={(event) => configureItem(item.id, { sheet: event.target.value })}>{item.sheets?.map((name) => <option key={name}>{name}</option>)}</select></label>}
        {item.preview?.preview && <button type="button" className="ghostButton" aria-expanded={details === item.id} disabled={busy} onClick={() => setDetails(details === item.id ? null : item.id)}><ArrowRight size={14} /> Vorschau</button>}</div>}
      {item.preview?.preview?.file_sha256 && <code className="importHash">{item.preview.preview.file_sha256}</code>}
      {item.error && <p role="alert" className="error">{item.error}</p>}
      {item.preview?.blocked_reason && <p role="status">{item.preview.blocked_reason}</p>}
      {item.preview?.warnings?.filter((warning) => !item.preview?.preview?.duplicate_batch_id || !warning.startsWith("Dublette erkannt:")).map((warning, index) => <p className="importWarning" key={index}>{warning}</p>)}
      {source === "mexc" && <MexcReview item={item} disabled={busy || item.status === "imported"} onDecision={(row, decision) => {
        const decisions = { ...item.decisions };
        if (decision) decisions[String(row)] = decision; else delete decisions[String(row)];
        generation.current += 1; setApproved(false); setError("");
        update(item.id, { decisions, preview: undefined, review: item.preview?.preview?.mexc || item.review, status: "pending", error: undefined });
      }} />}
      {item.result && <div className="importOutcome"><span>{item.result.run.imported_rows} Rohzeilen / {item.result.run.normalized_events} Ereignisse / {item.result.run.skipped_raw_objects} nicht zugeordnet</span>
        <a href={`${API_BASE}/api/v1/import/batches/${encodeURIComponent(item.result.batch.batch_id)}/trace.json`} download><Download size={16} /> {source === "mexc" ? "Belegspur (JSON)" : "Belegspur"}</a>
        {source === "mexc" && <a href={`${API_BASE}/api/v1/import/batches/${encodeURIComponent(item.result.batch.batch_id)}/original`} download><FileDown size={16} /> Originaldatei</a>}
      </div>}
    </article>)}</div>}
    {current?.preview?.preview && <section className="importSample" aria-label="Dateivorschau"><h3>{current.file.name}</h3><div className="tableScroll"><table><thead><tr>{current.preview.preview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{current.preview.preview.sample_rows.map((row, index) => <tr key={index}>{current.preview?.preview?.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>)}</tbody></table></div></section>}
    {items.length > 0 && <div className="importApproval">
      {source === "mexc" && <p id="mexc-import-effect" style={{ flexBasis: "100%" }}>Der Import speichert Rohbelege und fuehrt die bestehende Ledger-/Steuervorschau-Pipeline aus. Die Importfreigabe ist keine fachliche oder steuerliche Freigabe.</p>}
      <label><input type="checkbox" checked={approved} disabled={busy || !ready.length} aria-describedby={source === "mexc" ? "mexc-import-effect" : undefined} onChange={(event) => setApproved(event.target.checked)} /> Gepruefte Dateien freigeben ({ready.length})</label>
      <button type="button" className="primaryButton" disabled={busy || !approved || !ready.length} onClick={() => void importFiles()}>{busy ? <LoaderCircle size={16} /> : <Upload size={16} />}{busy ? "Vorgang laeuft" : `${ready.length} Datei(en) importieren`}</button>
      <button type="button" className="ghostButton" disabled={busy} onClick={() => { generation.current += 1; setItems([]); setApproved(false); setDetails(null); setError(""); }}>Neuer Import</button>
    </div>}
    {imported.length > 0 && <div className="buttonRow"><a className="ghostButton" href="#review"><ClipboardCheck size={16} /> Hinweise pruefen</a><a className="ghostButton" href="#tax"><ArrowRight size={16} /> Steuerjahr oeffnen</a></div>}
  </section>;
}
