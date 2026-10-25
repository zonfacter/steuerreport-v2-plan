import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ClipboardCheck, Download, FileDown, FolderOpen, LoaderCircle, Trash2, Upload } from "lucide-react";
import { API_BASE } from "./api-base";

type Profile = { source: string; label: string };
type Preview = {
  can_execute: boolean; blocked_reason?: string; warnings: string[];
  preview?: { row_count: number; columns: string[]; sample_rows: Record<string, unknown>[];
    sheet_name?: string; sheet_names: string[]; duplicate_batch_id?: string;
    file_sha256?: string; import_fingerprint?: string; missing_required_groups: string[]; profile_label: string };
};
type Outcome = { batch: { batch_id: string }; run: { imported_rows: number; normalized_events: number; skipped_raw_objects: number } };
type Status = "pending" | "checking" | "ready" | "duplicate" | "blocked" | "writing" | "imported" | "error";
type Item = { id: string; file: File; encoded?: string; sheet?: string; preview?: Preview; status: Status; error?: string; result?: Outcome };
const LABELS: Record<Status, string> = { pending: "Ungeprueft", checking: "Wird geprueft", ready: "Importierbar", duplicate: "Bereits vorhanden", blocked: "Nicht importierbar", writing: "Wird importiert", imported: "Importiert", error: "Fehler" };
const SOURCES = new Set(["manual-csv", "binance", "bitget", "pionex", "coinbase", "helium", "solana_rpc"]);

function fileProblem(file: File): string | undefined {
  return !/\.(csv|xlsx|xls)$/i.test(file.name) || file.size === 0 || file.size > 25 * 1024 * 1024
    ? "CSV, XLSX oder XLS erforderlich; Datei darf nicht leer und hoechstens 25 MB gross sein." : undefined;
}

async function api<T>(path: string, payload?: unknown, timeout = 60000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(API_BASE + path, payload === undefined ? { signal: controller.signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Anfrage fehlgeschlagen (HTTP ${response.status}). Importverlauf pruefen.`);
    const body = await response.json();
    if (body.status === "error") throw new Error(body.errors?.map((error: { message: string }) => error.message).join("; ") || "Datei konnte nicht verarbeitet werden.");
    return body.data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("Zeitlimit erreicht. Importverlauf vor einem erneuten Versuch pruefen.");
    throw error;
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
    void api<Profile[]>("/api/v1/import/profiles").then((rows) => { if (mounted) setProfiles(rows.filter((row) => SOURCES.has(row.source))); })
      .catch(() => { if (mounted) setError("Importquellen konnten nicht geladen werden."); });
    return () => { mounted = false; generation.current += 1; };
  }, []);
  const ready = items.filter((item) => item.status === "ready");
  const imported = items.filter((item) => item.status === "imported");
  const current = items.find((item) => item.id === details);
  const stage = imported.length ? 4 : ready.length ? 3 : items.length ? 2 : 1;
  const update = (id: string, value: Partial<Item>) => setItems((rows) => rows.map((row) => row.id === id ? { ...row, ...value } : row));

  function addFiles(files: File[]) {
    setError(""); setApproved(false);
    if (items.length + files.length > 20 || [...items.map((item) => item.file), ...files].reduce((size, file) => size + file.size, 0) > 100 * 1024 * 1024) {
      setError("Hoechstens 20 Dateien und insgesamt 100 MB pro Importvorgang."); return;
    }
    const added: Item[] = files.map((file) => ({ id: String(++nextId.current), file, status: "pending" }));
    for (const item of added) {
      const problem = fileProblem(item.file);
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
      for (const item of items.filter((row) => row.status !== "imported" && !fileProblem(row.file))) {
        if (token !== generation.current) break;
        update(item.id, { status: "checking", error: undefined });
        try {
          const encoded = item.encoded || await encodedFile(item.file);
          const preview = await api<Preview>("/api/v1/import/assistant/preview", { source, import_mode: "file", filename: item.file.name, content_base64: encoded, sheet_name: item.sheet });
          if (token !== generation.current) break;
          const fingerprint = preview.preview?.import_fingerprint;
          const repeated = Boolean(fingerprint && fingerprints.has(fingerprint));
          if (fingerprint) fingerprints.add(fingerprint);
          if (repeated) { preview.can_execute = false; preview.blocked_reason = "Identische Datei und dasselbe Tabellenblatt bereits in dieser Auswahl."; }
          update(item.id, { encoded, preview, sheet: preview.preview?.sheet_name, status: repeated || preview.preview?.duplicate_batch_id ? "duplicate" : preview.can_execute ? "ready" : "blocked" });
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
          const result = await api<Outcome>("/api/v1/import/assistant/execute", { source, import_mode: "file", filename: item.file.name, content_base64: item.encoded, sheet_name: item.sheet }, 240000);
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
      <a href="/benutzerleitfaden.html#import" target="_blank" rel="noreferrer" className="ghostButton"><FileDown size={16} /> Leitfaden</a>
      <a href={`/importformate.html${source ? `#${source}` : ""}`} target="_blank" rel="noreferrer" className="ghostButton"><FileDown size={16} /> Formate &amp; Spalten</a>
      <a href={source ? `/import-vorlagen/${source}.csv` : "/import-vorlage.csv"} download className="ghostButton"><Download size={16} /> CSV-Vorlage</a>
      <a href="/import-vorlagen/import-vorlagen.xlsx" download className="ghostButton"><Download size={16} /> Excel-Vorlagen</a>
    </div></div>
    <ol className="importStages" aria-label="Importfortschritt">{["Dateien", "Pruefung", "Freigabe", "Ergebnis"].map((label, index) => <li key={label} aria-current={stage === index + 1 ? "step" : undefined} className={stage > index + 1 ? "complete" : ""}><span>{stage > index + 1 ? <Check size={15} /> : index + 1}</span>{label}</li>)}</ol>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="importSelection"><label>Quelle<select aria-label="Importquelle" value={source} disabled={busy || imported.length > 0} onChange={(event) => { generation.current += 1; setSource(event.target.value); setApproved(false); setItems((rows) => rows.map((row) => fileProblem(row.file) ? row : ({ ...row, status: "pending", preview: undefined, error: undefined }))); }}>
      <option value="">Quelle auswaehlen</option>{profiles.map((profile) => <option key={profile.source} value={profile.source}>{profile.label}</option>)}
    </select></label>
    <input ref={fileInput} hidden type="file" multiple accept=".csv,.xlsx,.xls" aria-label="Importdateien auswaehlen" disabled={busy} onChange={(event) => { addFiles(Array.from(event.target.files || [])); event.target.value = ""; }} />
    <button type="button" disabled={busy || !source || !items.some((item) => item.status !== "imported")} onClick={() => void checkFiles()}><ClipboardCheck size={16} /> Dateien pruefen</button></div>
    <div className={`fileDropZone ${busy ? "busy" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (!busy) addFiles(Array.from(event.dataTransfer.files)); }}>
      <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}><FolderOpen size={22} /> Dateien auswaehlen</button><span>CSV / XLSX / XLS</span>
    </div>
    {items.length > 0 && <div className="importFileList" aria-live="polite">{items.map((item) => <article className="importFile" key={item.id}>
      <div className="importFileHeading"><div><strong>{item.file.name}</strong><small>{(item.file.size / 1024).toFixed(1)} KB</small></div><span className={`statusPill ${item.status === "ready" || item.status === "imported" ? "ok" : item.status === "error" || item.status === "blocked" ? "blocked" : "pending"}`}>{["checking", "writing"].includes(item.status) && <LoaderCircle size={14} />}{LABELS[item.status]}</span>
        <button type="button" className="ghostButton" title="Datei aus Auswahl entfernen" aria-label={`Datei ${item.file.name} aus Auswahl entfernen`} disabled={busy || item.status === "imported"} onClick={() => { setItems((rows) => rows.filter((row) => row.id !== item.id)); setApproved(false); }}><Trash2 size={16} /></button></div>
      {item.preview?.preview && <div className="importFileFacts"><span>{item.preview.preview.row_count} Zeilen</span><span>{item.preview.preview.profile_label}</span>
        {item.preview.preview.sheet_names.length > 0 && <label>Tabellenblatt<select aria-label={`Tabellenblatt fuer ${item.file.name}`} value={item.sheet || ""} disabled={busy || item.status === "imported"} onChange={(event) => { update(item.id, { sheet: event.target.value, status: "pending", preview: undefined }); setApproved(false); }}>{item.preview.preview.sheet_names.map((name) => <option key={name}>{name}</option>)}</select></label>}
        <button type="button" className="ghostButton" disabled={busy} onClick={() => setDetails(details === item.id ? null : item.id)}><ArrowRight size={14} /> Vorschau</button></div>}
      {item.preview?.preview?.file_sha256 && <code className="importHash">{item.preview.preview.file_sha256}</code>}
      {item.error && <p role="alert" className="error">{item.error}</p>}
      {item.preview?.blocked_reason && <p role="status">{item.preview.blocked_reason}</p>}
      {item.preview?.warnings?.filter((warning) => !item.preview?.preview?.duplicate_batch_id || !warning.startsWith("Dublette erkannt:")).map((warning, index) => <p className="importWarning" key={index}>{warning}</p>)}
      {item.result && <div className="importOutcome"><span>{item.result.run.imported_rows} Rohzeilen / {item.result.run.normalized_events} Ereignisse / {item.result.run.skipped_raw_objects} nicht zugeordnet</span><a href={`${API_BASE}/api/v1/import/batches/${encodeURIComponent(item.result.batch.batch_id)}/trace.json`} download><Download size={16} /> Belegspur</a></div>}
    </article>)}</div>}
    {current?.preview?.preview && <section className="importSample" aria-label="Dateivorschau"><h3>{current.file.name}</h3><div className="tableScroll"><table><thead><tr>{current.preview.preview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{current.preview.preview.sample_rows.map((row, index) => <tr key={index}>{current.preview?.preview?.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>)}</tbody></table></div></section>}
    {items.length > 0 && <div className="importApproval"><label><input type="checkbox" checked={approved} disabled={busy || !ready.length} onChange={(event) => setApproved(event.target.checked)} /> Gepruefte Dateien freigeben ({ready.length})</label>
      <button type="button" className="primaryButton" disabled={busy || !approved || !ready.length} onClick={() => void importFiles()}>{busy ? <LoaderCircle size={16} /> : <Upload size={16} />}{busy ? "Vorgang laeuft" : `${ready.length} Datei(en) importieren`}</button>
      <button type="button" className="ghostButton" disabled={busy} onClick={() => { generation.current += 1; setItems([]); setApproved(false); setDetails(null); setError(""); }}>Neuer Import</button>
    </div>}
    {imported.length > 0 && <div className="buttonRow"><a className="ghostButton" href="#review"><ClipboardCheck size={16} /> Hinweise pruefen</a><a className="ghostButton" href="#tax"><ArrowRight size={16} /> Steuerjahr oeffnen</a></div>}
  </section>;
}
