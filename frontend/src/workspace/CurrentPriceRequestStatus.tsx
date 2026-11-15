import { useEffect, useId, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { API_BASE } from "../api-base";

type RequestKind = "current_portfolio" | "historical";
const settings = {
  current_portfolio: {
    key: "steuerreport:current-price-request",
    event: "steuerreport:current-price-request-changed",
    path: "current-portfolio",
    title: "Portfolio-Preisauftrag prüfen",
  },
  historical: {
    key: "steuerreport:external-historical-price-request",
    event: "steuerreport:external-historical-price-request-changed",
    path: "external",
    title: "Historischer Direktabruf: Preisauftrag prüfen",
  },
};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
function validRequestId(value: string) { return value.length === 36 && uuid.test(value); }
function remembered(kind: RequestKind) {
  try {
    const value = sessionStorage.getItem(settings[kind].key);
    return value && validRequestId(value) ? value : "";
  } catch { return ""; }
}
function store(kind: RequestKind, id: string) {
  try { sessionStorage.setItem(settings[kind].key, id); } catch { /* Sessionablage ist optional. */ }
}
function remember(kind: RequestKind, id: string) {
  if (!validRequestId(id)) return;
  // Pro Auftragstyp nur die letzte UUID, keine Antworten oder unbegrenzte Historie.
  store(kind, id);
  window.dispatchEvent(new CustomEvent(settings[kind].event, { detail: id }));
}
export function rememberCurrentPriceRequest(id: string) { remember("current_portfolio", id); }
export function rememberHistoricalPriceRequest(id: string) { remember("historical", id); }

const pipelineLabels = {
  not_started: "Pipeline damals nicht gestartet.",
  running_or_interrupted: "Pipelinebeginn vorgemerkt; Lauf und Abschluss nicht bestätigt.",
  completed: "Pipeline damals abgeschlossen.",
  failed: "Pipeline fehlgeschlagen; Folgen unbekannt oder teilweise.",
};
type Checkpoint = {
  format_version: 1;
  operation_kind: RequestKind;
  stored_at: string;
  stored_price_ids: string[];
  pipeline_status: keyof typeof pipelineLabels;
};
type Status = {
  status: "recorded" | "checkpointed" | "unknown_or_running" | "not_found";
  explanation: string;
  warnings: { message: string }[];
  result?: { pipeline_status: string; imported_prices: number; failed: number; skipped: number; stored_price_ids: string[] } | null;
  checkpoint?: Checkpoint | null;
  checkpoint_sha256?: string | null;
};
const statusLabels: Record<Status["status"], string> = {
  recorded: "Finale damalige Antwort gespeichert.",
  checkpointed: "Preisspeicherung belegt; finale Antwort fehlt.",
  unknown_or_running: "Ausgang unbekannt oder Auftrag noch in Arbeit; Abschluss nicht bestätigt.",
  not_found: "Kein gespeicherter Auftrag zu dieser Kennung gefunden; kein Abschlussnachweis.",
};
function pipelineLabel(value: string) {
  return Object.hasOwn(pipelineLabels, value)
    ? pipelineLabels[value as keyof typeof pipelineLabels]
    : "Pipelinezustand unbekannt; Abschluss nicht bestätigt.";
}
function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function validIds(value: unknown, limit: number): value is string[] {
  return Array.isArray(value) && value.length <= limit
    && value.every((id) => typeof id === "string" && validRequestId(id) && id === id.toLowerCase())
    && new Set(value).size === value.length;
}
function explicitUtc(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) return false;
  const date = new Date(value);
  // Date.parse normalisiert z.B. den 30. Februar, statt ihn zu verwerfen.
  return Number.isFinite(date.getTime()) && date.getUTCFullYear() > 0 && date.toISOString().slice(0, 19) === value.slice(0, 19);
}
function readStatus(body: unknown, kind: RequestKind): Status {
  if (!isObject(body) || (body.status !== "ok" && body.status !== "warning") || !isObject(body.data)) throw new Error("status_unknown");
  const data = body.data;
  if (typeof data.status !== "string" || !Object.hasOwn(statusLabels, data.status)
    || typeof data.explanation !== "string") throw new Error("status_unknown");
  const checkpoint = data.checkpoint;
  const result = data.result;
  const hash = data.checkpoint_sha256;
  const limit = kind === "historical" ? 1000 : 250;
  // Der SHA gehoert zu den gespeicherten Originalbytes, nicht zu einer JSON-Neukodierung im Browser.
  if ((checkpoint != null) !== (hash != null)
    || (hash != null && (typeof hash !== "string" || hash.length !== 64 || !/^[a-f0-9]{64}$/.test(hash)))) throw new Error("checkpoint_hash_invalid");
  if (checkpoint != null) {
    const fields = ["format_version", "operation_kind", "stored_at", "stored_price_ids", "pipeline_status"];
    if (!isObject(checkpoint) || Object.keys(checkpoint).length !== fields.length || !fields.every((field) => Object.hasOwn(checkpoint, field))
      || checkpoint.format_version !== 1 || checkpoint.operation_kind !== kind || !explicitUtc(checkpoint.stored_at)
      || !validIds(checkpoint.stored_price_ids, limit) || typeof checkpoint.pipeline_status !== "string"
      || !Object.hasOwn(pipelineLabels, checkpoint.pipeline_status)
      || (checkpoint.stored_price_ids.length === 0 && checkpoint.pipeline_status !== "not_started")) throw new Error("checkpoint_invalid");
  }
  if (result != null) {
    if (!isObject(result) || typeof result.pipeline_status !== "string" || !["not_started", "completed", "failed"].includes(result.pipeline_status)
      || ![result.imported_prices, result.failed, result.skipped].every((count) => typeof count === "number" && Number.isSafeInteger(count) && count >= 0)
      || !validIds(result.stored_price_ids, limit)
      || (result.pipeline_status === "completed" && (!isObject(result.pipeline) || result.pipeline_effects !== "completed"))
      || (result.pipeline_status === "failed" && (result.pipeline != null || result.pipeline_effects !== "unknown_or_partial"))
      || (result.pipeline_status === "not_started" && (result.pipeline != null || result.pipeline_effects !== "not_started"))) throw new Error("result_invalid");
  }
  if (data.status === "recorded") {
    if (!isObject(result)) throw new Error("result_missing");
    if (isObject(checkpoint)) {
      const storedIds = checkpoint.stored_price_ids as string[];
      const resultIds = result.stored_price_ids as string[];
      if (result.operation_kind !== kind || result.dry_run !== false || result.result_journal_status !== "recorded"
        || result.pipeline_status !== checkpoint.pipeline_status || result.imported_prices !== storedIds.length
        || resultIds.length !== storedIds.length || !resultIds.every((id, index) => id === storedIds[index])
        || (resultIds.length > 0 && result.pipeline_status === "not_started")) throw new Error("result_checkpoint_mismatch");
    }
  } else if (data.status === "checkpointed") {
    if (!isObject(checkpoint) || result != null || !["not_started", "running_or_interrupted"].includes(checkpoint.pipeline_status as string)) throw new Error("checkpoint_state_invalid");
  } else if (result != null || checkpoint != null || hash != null) throw new Error("unknown_state_has_evidence");
  const warnings = body.warnings ?? [];
  if (!Array.isArray(warnings) || !warnings.every((warning) => isObject(warning) && typeof warning.message === "string")) throw new Error("warnings_invalid");
  return {
    status: data.status as Status["status"], explanation: data.explanation,
    result: result as Status["result"], checkpoint: checkpoint as Status["checkpoint"], checkpoint_sha256: hash as Status["checkpoint_sha256"],
    warnings: warnings.map((warning) => ({ message: warning.message as string })),
  };
}

export function CurrentPriceRequestStatus({ kind = "current_portfolio" }: { kind?: RequestKind }) {
  // Ein Typwechsel verwirft auch laufende Antworten des vorherigen Typs.
  return <PriceRequestStatus key={kind} kind={kind} />;
}
function PriceRequestStatus({ kind }: { kind: RequestKind }) {
  const [id, setId] = useState(() => remembered(kind));
  const [result, setResult] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const hintId = useId();
  const config = settings[kind];
  function change(value: string) {
    request.current?.abort(); request.current = null;
    setBusy(false); setResult(null); setError(null); setId(value);
  }
  useEffect(() => {
    const update = (event: Event) => {
      const value: unknown = (event as CustomEvent).detail;
      if (typeof value === "string" && validRequestId(value)) change(value);
    };
    window.addEventListener(config.event, update);
    return () => { request.current?.abort(); request.current = null; window.removeEventListener(config.event, update); };
  }, [config]);
  async function check() {
    if (!validRequestId(id) || request.current) return;
    const controller = new AbortController(); request.current = controller;
    store(kind, id);
    setBusy(true); setError(null); setResult(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/prices/backfill/${config.path}/status`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: id }), signal: controller.signal,
      });
      if (!response.ok) throw new Error("status_unknown");
      const data = readStatus(await response.json(), kind);
      if (!controller.signal.aborted && request.current === controller) setResult(data);
    } catch {
      if (!controller.signal.aborted && request.current === controller) setError("Auftragsstatus nicht sicher lesbar. Vor einem neuen Abruf den Preisbestand prüfen.");
    } finally {
      if (!controller.signal.aborted && request.current === controller) { request.current = null; setBusy(false); }
    }
  }
  return <section aria-label={config.title} style={{ minWidth: 0, overflowWrap: "anywhere" }}>
    <h3>{config.title}</h3>
    <label>Auftragskennung<input value={id} maxLength={36} onChange={(event) => change(event.target.value.trim())}
      autoComplete="off" spellCheck={false} aria-invalid={!!id && !validRequestId(id)} aria-describedby={hintId} /></label>
    <p id={hintId}>{id && !validRequestId(id) ? "Eine gültige Auftragskennung (UUID) eingeben." : "Nur Statusauskunft: kein Anbieterabruf und keine Neuberechnung."}</p>
    <button className="statusButton" type="button" disabled={busy || !validRequestId(id)} onClick={() => void check()}
      title="Liest nur den gespeicherten Auftrag; kein Anbieterabruf und keine Neuberechnung"><RefreshCw size={16} aria-hidden="true" /> {busy ? "Status wird gelesen" : "Auftragsstatus lesen"}</button>
    <div aria-live="polite" aria-atomic="true" aria-busy={busy}>
      {error && <p className="wsInlineWarning">{error}</p>}
      {result && <>
        <p><strong>{statusLabels[result.status]}</strong></p>
        <p>{result.explanation}</p>
        {result.result && <p>Damals gespeichert: {result.result.imported_prices} Preise. Fehlgeschlagen: {result.result.failed}. Übersprungen: {result.result.skipped}. {pipelineLabel(result.result.pipeline_status)}</p>}
        {result.checkpoint && <>
          <p>Speicherbeleg: {result.checkpoint.stored_price_ids.length} damals gespeicherte Preis-IDs. {pipelineLabel(result.checkpoint.pipeline_status)}</p>
          {result.checkpoint.stored_price_ids.length === 0 && <p>Bekannt leer: In dieser Transaktion wurden keine Preise gespeichert.</p>}
          <details><summary>Speicherbeleg und damalige Preis-IDs</summary>
            <p>Formatversion: {result.checkpoint.format_version}. Auftragstyp: {result.checkpoint.operation_kind === "historical" ? "Historischer Direktabruf" : "Aktuelles Portfolio"}.</p>
            <p>Gespeichert (UTC): <time dateTime={result.checkpoint.stored_at}>{new Date(result.checkpoint.stored_at).toISOString()}</time></p>
            {result.checkpoint.stored_price_ids.length > 0 && <ul aria-label="Damals gespeicherte Preis-IDs" style={{ maxHeight: "16rem", overflowY: "auto" }} tabIndex={0}>{result.checkpoint.stored_price_ids.map((priceId) => <li key={priceId}><code>{priceId}</code></li>)}</ul>}
            {result.checkpoint_sha256 && <p>Checkpoint-SHA256 (gespeicherte UTF-8-JSON-Bytes): <code>{result.checkpoint_sha256}</code></p>}
          </details>
        </>}
        {result.result && !result.checkpoint && <p>Kein zusätzlicher Speicherbeleg vorhanden (älteres Ergebnisjournal).</p>}
        {(result.result || result.checkpoint) && <p className="wsInlineWarning">Damals gespeicherte IDs bestätigen weder den heutigen Fortbestand noch die heutige Preisgültigkeit oder fachliche Freigabe. Dies ist keine Jahresfreigabe.</p>}
        {result.warnings.map((warning, index) => <p className="wsInlineWarning" key={index}>{warning.message}</p>)}
      </>}
    </div>
  </section>;
}
