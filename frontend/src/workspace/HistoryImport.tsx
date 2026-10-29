import { useEffect, useRef, useState } from "react";
import { AlertCircle, Check, Download, LoaderCircle, Pause, Play, RefreshCw, Upload, X } from "lucide-react";
import { HelpTip } from "../Help";
import { ApiReadError, canonicalDecimal, readApi, timestamp, useResource } from "./resource";
import { Badge, ExactQuantity, ResourceNotice } from "./Ui";
import "./history-import.css";

// Local mirrors of contracts/history.py; the source is always taken from the panel.
type RpcProvider = "public" | "helius" | "alchemy" | "custom";
type HistoryRateState = {
  available: boolean; config_revision?: number | null; requests_per_second?: number | null;
  requests_per_10_seconds?: number | null; requests_per_minute?: number | null; max_concurrency?: number | null;
  effective_max_requests_per_second?: number | null; budget_groups?: string[]; bottlenecks?: string[];
  blocking_reasons?: string[]; waiting_requests?: number | null; in_flight?: number | null;
  wait_seconds?: number | null; retry_at?: string | null;
};
type HistoryRpcOption = {
  id: RpcProvider | "legacy"; label: string; kind: "public" | "configured" | "legacy";
  provider_id?: string | null; configured: boolean; ready: boolean; blocked_reason?: string | null;
  pinned: boolean; tariff_verified: false; limits?: HistoryRateState | null;
};
type HistoryProgress = {
  phase: "discovery" | "fetch" | "preparing" | "complete" | "paused" | "cancelled" | "error" | "unknown";
  references_discovered?: number | null; signatures_discovered?: number | null; signatures_total?: number | null;
  signatures_completed?: number | null; addresses_completed?: number | null; addresses_total?: number | null;
  inventory_complete: boolean; fetch_elapsed_seconds?: number | null; observed_details_per_second?: number | null;
  estimated_fetch_remaining_seconds?: number | null;
  estimate_status: "unknown_total" | "warming_up" | "estimated" | "paused" | "fetch_complete" | "not_supported" | "unavailable";
  estimate_scope: "available_rpc_transaction_details"; updated_at?: string | null;
};
type HistoryCapability = {
  source_ref: string; label: string; provider: string | null; supported: boolean; ready: boolean;
  blocked_reason: string | null; requires_symbols: boolean; supports_binance_earn: boolean;
  coverage_notes: string[]; default_start: string;
  rpc_options?: HistoryRpcOption[];
};
type HistoryJob = {
  requires_repreview?: boolean;
  id: string; source_ref: string; label: string; provider: string;
  status: "queued" | "running" | "paused" | "ready" | "importing" | "succeeded" | "failed" | "cancelled";
  phase: string; created_at: string; updated_at: string; start: string; end: string;
  records_fetched: number; pages_fetched: number; new_records: number; duplicate_records: number;
  imported_events: number; requests: number; max_records: number; preview_sha256: string | null;
  includes_binance_earn: boolean; provider_requests_reserved: number; provider_request_limit: number;
  sample_rows: Record<string, unknown>[]; before_summary: Record<string, unknown> | null;
  after_summary: Record<string, unknown> | null; review_issues_open: number | null;
  error_code: string | null; coverage_notes: string[]; complete_history_proven: boolean; can_resume?: boolean;
  approval: Record<string, unknown> | null;
  transport?: HistoryRpcOption | null; progress?: HistoryProgress | null;
};
type HistoryView = { capability: HistoryCapability; jobs: HistoryJob[] };
type HistoryStart = { request_id: string; confirm_external_request: true; start: string; end: string | null; symbols: string[]; public_rpc_only: boolean; rpc_provider?: RpcProvider | null; max_records: number; include_binance_earn: boolean };
type HistoryResume = { confirm_external_request: true; max_records?: number };
type HistoryApprove = { preview_sha256: string; actor: string; confirm_import: true; confirm_recalculation: true };
type Props = { sourceRef: string; sourceLabel: string; onApplied: () => void };

const polling = new Set<HistoryJob["status"]>(["queued", "running", "importing"]);
const unfinished = new Set<HistoryJob["status"]>(["queued", "running", "paused", "ready", "importing"]);
const statusNames: Record<HistoryJob["status"], string> = {
  queued: "Wartet auf Abruf", running: "Abruf läuft", paused: "Pausiert", ready: "Vorschau bereit",
  importing: "Import / Neuberechnung läuft", succeeded: "Import abgeschlossen", failed: "Fehlgeschlagen", cancelled: "Abgebrochen",
};
const errors: Record<string, string> = {
  history_external_confirmation_required: "Der externe Anbieterabruf muss ausdrücklich bestätigt werden.",
  history_import_confirmation_required: "Import und Neuberechnung müssen getrennt bestätigt werden.",
  history_symbols_invalid: "Handelspaare müssen aus 2 bis 40 Buchstaben, Ziffern, /, _ oder - bestehen.",
  history_symbols_required: "Für diesen Anbieter sind Handelspaare erforderlich.",
  history_date_range_invalid: "Das Enddatum darf nicht vor dem Startdatum liegen.",
  history_not_supported: "Für diese Quelle ist kein automatischer Historienabruf verfügbar.",
  history_not_ready: "Die Quelle ist noch nicht für den Historienabruf eingerichtet.",
  history_job_not_found: "Dieser Auftrag ist nicht mehr verfügbar. Auftragsliste aktualisieren.",
  history_job_conflict: "Der Auftrag hat sich geändert oder ein anderer Vorgang läuft bereits. Status aktualisieren.",
  history_preview_mismatch: "Die Vorschau hat sich geändert. Neu laden und erneut prüfen und bestätigen.",
  history_preview_hash_mismatch: "Die Vorschau hat sich geändert. Neu laden und erneut prüfen und bestätigen.",
  history_preview_required: "Es liegt noch keine freigabefähige Vorschau vor.",
  history_record_limit: "Das Abruflimit wurde erreicht. Limit prüfen und bei Bedarf fortsetzen.",
  history_source_mismatch: "Die Antwort gehört nicht zur ausgewählten Quelle. Status erneut laden.",
  history_provider_not_supported: "Für diesen Anbieter ist kein automatischer Historienabruf verfügbar. Originaldateien können weiterhin importiert werden.",
  history_connection_required: "Für diese Quelle fehlt eine eingerichtete API-Verbindung. Die bestehende Einrichtung prüfen.",
  history_select_individual_connection: "Für den Historienabruf muss eine einzelne eingerichtete Kontoverbindung als Quelle ausgewählt werden, keine Sammelquelle.",
  history_source_not_found: "Die ausgewählte Quelle ist nicht mehr verfügbar. Quellenliste aktualisieren.",
  history_source_job_exists: "Für diese Quelle besteht bereits ein offener Auftrag. Diesen fortsetzen, seine Vorschau importieren oder ihn abbrechen, bevor ein neuer Abruf startet.",
  history_job_state_conflict: "Diese Aktion passt nicht zum aktuellen Auftragsstatus oder der Auftrag kann nicht fortgesetzt werden. Status aktualisieren.",
  history_preview_stale: "Die Vorschau ist veraltet, weil sich die Datenbasis geändert hat. Den Auftrag abbrechen und eine neue Vorschau abrufen; anschließend erneut prüfen und bestätigen.",
  history_preview_changed: "Die gespeicherte Vorschau stimmt nicht mehr mit der Freigabe überein. Status aktualisieren und die Vorschau erneut prüfen; keine Freigabe übernommen.",
  history_source_changed: "Die Quellen- oder Kontenzuordnung hat sich seit Auftragsbeginn geändert. Den alten Auftrag abbrechen und einen neuen Abruf für die aktuelle Quelle starten.",
  history_legacy_account_assignment_required: "Ältere Importdaten müssen zuerst eindeutig einem Konto zugeordnet werden. Der Historienimport nimmt keine automatische Zuordnung vor.",
  history_worker_stopped: "Der Abruf wurde unterbrochen, etwa durch einen Serverneustart. Gespeicherten Fortschritt prüfen und den Auftrag ausdrücklich fortsetzen.",
  history_worker_running: "Dieser Auftrag wird bereits verarbeitet. Status aktualisieren; keinen zweiten Abruf starten.",
  history_worker_superseded: "Ein neuer Verarbeitungslauf hat den bisherigen ersetzt. Den aktuellen Auftragsstatus laden.",
  history_run_deadline: "Der Abrufabschnitt wurde unterbrochen. Auftragsstatus prüfen; nur einen tatsächlich pausierten Auftrag ausdrücklich fortsetzen.",
  history_paused: "Der Abruf wurde pausiert. Gespeicherten Fortschritt prüfen und bei Bedarf ausdrücklich fortsetzen.",
  history_cancelled: "Der Auftrag wurde abgebrochen. Es erfolgt keine Importfreigabe.",
  history_coordination_unavailable: "Der Server konnte den Auftragsstatus nicht sicher koordinieren. Status aktualisieren und die Serververfügbarkeit prüfen.",
  history_existing_evidence_conflict: "Bereits importierte Originalbelege widersprechen den abgerufenen Daten. Die Belege müssen vor einem weiteren Import geprüft werden; nichts wird still überschrieben.",
  history_evidence_conflict: "Der Anbieter liefert widersprüchliche Daten für denselben Originalbeleg. Der Import bleibt zur Prüfung gesperrt.",
  history_evidence_changed: "Gespeicherte Originalbelege stimmen nicht mehr mit ihren Prüfsummen überein. Belegspeicher prüfen; keine Importfreigabe erteilen.",
  history_evidence_missing: "Gespeicherte Originalbelege fehlen. Belegspeicher prüfen; keine Importfreigabe erteilen.",
  history_storage_invalid: "Der Belegspeicher ist nicht sicher verfügbar. Die serverseitige Speichereinrichtung prüfen.",
  history_storage_insufficient: "Für die isolierte Importvorschau fehlt Speicherplatz auf dem Server. Speicherplatz prüfen.",
  history_record_too_large: "Ein Anbieterbeleg überschreitet die zulässige Größe. Die Originaldaten müssen geprüft werden.",
  history_record_identity_invalid: "Ein Anbieterbeleg lässt sich nicht eindeutig identifizieren. Keine automatische Übernahme möglich.",
  history_cursor_stalled: "Der Anbieterabruf kommt nicht zur nächsten Seite. Der Auftrag wurde angehalten, damit keine Seiten endlos wiederholt werden.",
  history_request_id_conflict: "Diese Anfragekennung gehört bereits zu anderen Abrufparametern. Den bestehenden Auftragsstatus und die Eingaben prüfen.",
  history_job_id_invalid: "Die Auftragskennung ist ungültig. Den Auftrag erneut aus der gespeicherten Liste auswählen.",
  history_job_storage_limit: "Die maximale Zahl gespeicherter Historienaufträge ist erreicht. Die serverseitige Auftragsverwaltung prüfen.",
  history_job_capacity: "Alle verfügbaren Abrufplätze sind belegt. Laufende Aufträge abwarten und später erneut versuchen.",
  history_binance_earn_connection_required: "Simple Earn ist nur mit einer ausdrücklich ausgewählten Binance-Kontoverbindung verfügbar. Globale oder Legacy-Zugangsdaten werden dafür nicht verwendet.",
  history_provider_request_budget_exhausted: "Das sichere Kontingent von 10.000 Anbieteranfragen für diesen Historienauftrag ist erreicht. Der Auftrag wird nicht weiter abgerufen; Umfang und gespeicherten Fortschritt prüfen.",
  history_binance_earn_product_limit: "Die Zahl der Earn-Produktanker überschreitet die Sicherheitsgrenze. Produkte dieser Verbindung prüfen; kein Abruf gestartet.",
  history_binance_earn_product_anchor_invalid: "Ein gespeicherter Earn-Produktanker ist ungültig. Verbindungssnapshot und Originalbelege prüfen.",
  missing_credentials: "API-Zugangsdaten fehlen. Die bestehende Einrichtung prüfen.",
  missing_configuration: "Die bestehende Quellen- und Anbietereinrichtung ist noch unvollständig.",
  history_missing_credentials: "API-Zugangsdaten fehlen. Die bestehende Einrichtung prüfen.",
  solana_wallet_address_required: "Für diese Quelle fehlt die gespeicherte öffentliche Wallet-Adresse.",
  solana_time_window_invalid: "Den Zeitraum des Solana-Abrufs prüfen.",
  solana_transaction_missing: "Der Anbieter hat nicht alle Transaktionen geliefert. Der Auftrag bleibt ungeprüft.",
  solana_transaction_incomplete: "Der Anbieter hat unvollständige Transaktionsdaten geliefert.",
  solana_signature_cursor_loop: "Der Anbieter wiederholt eine bereits abgerufene Seite. Der Abruf wurde angehalten.",
  solana_asset_filter_not_supported: "Der Solana-Historienabruf unterstützt keinen Assetfilter. Die Historie wird ohne Symbolfilter abgerufen.",
  solana_rpc_failed: "Der Solana-RPC-Anbieter ist nicht erreichbar oder hat die Anfrage abgelehnt. Anbieterstatus und Abruflimits prüfen und später fortsetzen.",
  solana_transaction_fetch_failed: "Eine Solana-Transaktion konnte nicht beim RPC-Anbieter abgerufen werden. Anbieterstatus und Abruflimits prüfen und später fortsetzen.",
  solana_owner_accounts_invalid: "Der Solana-Anbieter hat unvollständige oder ungültige Wallet-Kontodaten geliefert. Keine gesicherte Historienabdeckung.",
  solana_owner_accounts_conflict: "Die vom Solana-Anbieter gelieferten Kontozuordnungen widersprechen sich. Die Wallet-Historie muss geprüft werden.",
  solana_signatures_invalid: "Die Solana-Transaktionsliste des Anbieters ist unvollständig oder ungültig. Der Abruf wurde zur Prüfung angehalten.",
  solana_signatures_not_finalized: "Der Solana-Anbieter hat noch nicht endgültig bestätigte Transaktionen geliefert. Später erneut prüfen.",
  solana_cursor_invalid: "Der gespeicherte Fortsetzungspunkt der Solana-Historie ist ungültig. Den Auftrag und die Belege prüfen; nicht ungeprüft fortsetzen.",
  solana_inventory_storage_unavailable: "Der private Belegspeicher ist vorübergehend nicht verfügbar. Freien Speicherplatz und Serverressourcen prüfen; gesicherten Auftrag danach ausdrücklich fortsetzen.",
  solana_inventory_storage_invalid: "Der private Inventarspeicher ist nicht sicher verfügbar. Pfad, Berechtigungen und Belege serverseitig prüfen; keine Importfreigabe erteilen.",
  solana_inventory_invalid: "Das gesicherte Signaturinventar ist nicht konsistent. Originalbelege und Prüfsummen prüfen; keine automatische Übernahme.",
  solana_inventory_limit: "Das Sicherheitslimit des privaten Signaturinventars wurde erreicht. Umfang und Belegspeicher serverseitig prüfen; keine vollständige Historie bestätigt.",
  solana_address_limit: "Die Zahl zu prüfender Solana-Konten überschreitet die Abrufgrenze. Wallet-Abdeckung und serverseitige Grenzen prüfen.",
  cex_history_connection_required: "Für diese Quelle fehlt die eingerichtete API-Verbindung.",
  cex_history_account_required: "Die gespeicherte Kontenzuordnung dieser Quelle ist unvollständig.",
  cex_history_symbols_required: "Für diesen Anbieter sind Handelspaare erforderlich.",
  cex_history_symbols_invalid: "Die angegebenen Handelspaare werden vom Anbieter nicht unterstützt.",
  cex_history_provider_unsupported: "Dieser Anbieter unterstützt hier noch keinen automatischen Historienabruf.",
  cex_history_provider_error: "Der Anbieter hat die Anfrage nicht erfolgreich beantwortet. Später erneut versuchen.",
  cex_history_market_metadata_missing: "Die Marktdaten zur eindeutigen Zuordnung der Handelspaare fehlen.",
  cex_history_quantity_inexact: "Eine Menge ist nicht exakt belegbar. Der Abruf wurde zur Prüfung angehalten.",
  cex_history_coinbase_proof_required: "Für diese Coinbase-Historie fehlen die erforderlichen Herkunftsnachweise.",
  rate_limited: "Der Anbieter begrenzt die Anfragen. Später erneut versuchen.",
  history_rpc_choice_conflict: "Modus und Anbieter passen nicht zusammen. Die Abrufauswahl erneut prüfen.",
  history_rpc_not_configured: "Der gewählte RPC-Anbieter ist nicht eingerichtet. Zugang in der Einrichtung prüfen; kein automatischer Ersatzanbieter.",
  history_rpc_configuration_changed: "Die gespeicherte Anbietereinrichtung hat sich geändert. Für einen Anbieterwechsel ist ein neuer Auftrag erforderlich.",
  history_rpc_provider_not_supported: "Dieser RPC-Anbieter unterstützt den Historienabruf hier nicht. Die Einrichtung prüfen; kein automatischer Ersatzanbieter.",
  history_rpc_choice_invalid: "Den gewünschten RPC-Anbieter ausdrücklich auswählen.",
  history_rpc_key_missing: "Für diesen Dienst fehlt der API-Key. Zugang in der Einrichtung hinterlegen; kein automatischer Ersatzanbieter.",
  history_rpc_key_unavailable: "Der gespeicherte API-Key ist nicht verfügbar. Zugang und Schlüsselspeicher in der Einrichtung prüfen.",
  history_rpc_url_missing: "Für den eigenen RPC fehlt die gespeicherte Verbindung. Die Einrichtung prüfen.",
  history_rpc_url_invalid: "Die gespeicherte RPC-Verbindung ist ungültig. Die Einrichtung prüfen.",
  history_rpc_profile_unavailable: "Das gespeicherte RPC-Profil ist nicht verfügbar. Die Einrichtung prüfen.",
};
function errorText(code: unknown, fallback = "Der Vorgang konnte nicht abgeschlossen werden. Status aktualisieren und erneut versuchen.") {
  const value = code instanceof ApiReadError ? code.code ?? code.message : code instanceof Error ? code.message : code;
  if (typeof value !== "string") return fallback;
  return errors[value] || (/^solana_[a-z0-9_]+$/.test(value)
    ? "Der Solana-Anbieterabruf konnte nicht sicher abgeschlossen werden. RPC-Verfügbarkeit, Anbieterlimits und gespeicherten Auftragsstatus prüfen; keine vollständige Historie bestätigt."
    : /^cex_history_[a-z0-9_]+$/.test(value)
      ? "Die Börsenhistorie konnte nicht sicher abgerufen oder eindeutig zugeordnet werden. Anbieterzugang, Handelspaare und Originalbelege prüfen."
      : fallback);
}
function uuid() {
  // getRandomValues also works on existing HTTP installations without randomUUID.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
const textValue = (value: unknown) => value == null ? "Nicht verfügbar" : typeof value === "object" ? "Siehe technische Details" : String(value);
let sessionActor = "";
const pendingRequests = new Map<string, { key: string; id: string }>();

export function HistoryImport(props: Props) {
  return <SourceHistory key={props.sourceRef} {...props} />;
}

function SourceHistory({ sourceRef, sourceLabel, onApplied }: Props) {
  const base = `/api/v1/workspace/sources/${encodeURIComponent(sourceRef)}/history`;
  const mutationEpoch = useRef(0);
  const resource = useResource<HistoryView & { epoch: number }>("source-history:" + sourceRef, async (signal) => {
    const epoch = mutationEpoch.current;
    try {
      const view = await readApi<HistoryView>(base, signal);
      if (view?.capability?.source_ref !== sourceRef) throw new Error("history_source_mismatch");
      return { ...view, epoch, jobs: view.jobs.filter((job) => job.source_ref === sourceRef) };
    } catch (caught) {
      throw new Error(errorText(caught, "Die Historienaufträge konnten nicht geladen werden. Erneut versuchen; gespeicherte Daten bleiben erhalten."));
    }
  });
  const capability = resource.data?.capability.source_ref === sourceRef ? resource.data.capability : undefined;
  const [jobs, setJobs] = useState<HistoryJob[]>([]), [selectedId, setSelectedId] = useState("");
  const [start, setStart] = useState(""), [end, setEnd] = useState(new Date().toISOString().slice(0, 10));
  const [symbols, setSymbols] = useState(""), [rpcMode, setRpcMode] = useState<"public" | "configured" | "">("");
  const [includeEarn, setIncludeEarn] = useState(false);
  const [configuredProvider, setConfiguredProvider] = useState<Exclude<RpcProvider, "public"> | "">("");
  const [maxRecords, setMaxRecords] = useState("100000");
  const [externalConsent, setExternalConsent] = useState(false), [resumeConsent, setResumeConsent] = useState("");
  const [resumeRecords, setResumeRecords] = useState<Record<string, string>>({});
  const [actor, setActor] = useState(sessionActor);
  const [approval, setApproval] = useState({ key: "", importing: false, recalculating: false });
  const [busy, setBusy] = useState(""), [commandError, setCommandError] = useState("");
  const [pollError, setPollError] = useState(""), [refresh, setRefresh] = useState(0);
  const lifetime = useRef<AbortController | null>(null), pollController = useRef<AbortController | null>(null);
  const running = useRef(false), request = useRef(pendingRequests.get(sourceRef));
  const notified = useRef(new Set<string>()), pendingApply = useRef(new Set<string>());
  const onAppliedRef = useRef(onApplied); onAppliedRef.current = onApplied;

  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    return () => { controller.abort(); pollController.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!capability) return;
    setStart((value) => value || capability.default_start);
  }, [capability]);
  const receive = (job: HistoryJob) => {
    if (job.source_ref !== sourceRef) throw new Error("history_source_mismatch");
    setJobs((previous) => mergeJobs(previous, [job]));
  };
  useEffect(() => {
    if (resource.data?.capability.source_ref === sourceRef && resource.data.epoch === mutationEpoch.current) {
      setJobs((previous) => mergeJobs(previous, resource.data!.jobs));
    }
  }, [resource.data, sourceRef]);
  const ordered = [...jobs].filter((job) => job.source_ref === sourceRef).sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
  const job = ordered.find((item) => item.id === selectedId) || ordered.find((item) => polling.has(item.status)) || ordered.find((item) => unfinished.has(item.status)) || ordered[0];
  const jobId = job?.id, jobStatus = job?.status;
  useEffect(() => { if (jobId && !selectedId) setSelectedId(jobId); }, [jobId, selectedId]);
  const approvalKey = job ? `${sourceRef}:${job.id}:${job.preview_sha256}:${job.status}` : "";
  const importChecked = approval.key === approvalKey && approval.importing;
  const recalcChecked = approval.key === approvalKey && approval.recalculating;
  useEffect(() => {
    setApproval({ key: "", importing: false, recalculating: false }); setResumeConsent("");
  }, [approvalKey]);

  useEffect(() => {
    if (!jobId || busy) return;
    const controller = new AbortController(); pollController.current = controller;
    let timer: number | undefined;
    const load = async () => {
      try {
        const next = await readApi<HistoryJob>(`${base}/jobs/${encodeURIComponent(jobId)}`, controller.signal);
        if (controller.signal.aborted) return;
        if (next.id !== jobId || next.source_ref !== sourceRef) throw new Error("history_source_mismatch");
        receive(next); setPollError("");
        if (polling.has(next.status)) timer = window.setTimeout(() => void load(), 2000);
      } catch (caught) {
        if (controller.signal.aborted) return;
        setPollError(errorText(caught, "Der Auftragsstatus konnte nicht aktualisiert werden.") + " Der gespeicherte Auftrag bleibt sichtbar.");
        if (jobStatus && polling.has(jobStatus)) timer = window.setTimeout(() => void load(), 2000);
      }
    };
    // Persisted jobs are checked once on selection; only running work is polled.
    if (jobStatus && polling.has(jobStatus)) timer = window.setTimeout(() => void load(), 2000);
    else void load();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [base, sourceRef, jobId, jobStatus, busy, refresh]);

  useEffect(() => {
    for (const item of jobs) {
      if (item.status === "importing") pendingApply.current.add(item.id);
      if (item.status === "succeeded" && pendingApply.current.has(item.id) && !notified.current.has(item.id)) {
        notified.current.add(item.id); pendingApply.current.delete(item.id);
        window.dispatchEvent(new Event("steuerreport:refresh")); onAppliedRef.current();
      }
    }
  }, [jobs]);

  const command = async (action: "start" | "pause" | "resume" | "cancel" | "import" | "repreview", payload: HistoryStart | HistoryResume | HistoryApprove | Record<string, never>) => {
    const controller = lifetime.current;
    if (running.current || !controller || controller.signal.aborted) return;
    running.current = true; mutationEpoch.current += 1; pollController.current?.abort(); setBusy(action); setCommandError(""); setPollError("");
    setApproval({ key: "", importing: false, recalculating: false }); setResumeConsent(""); setExternalConsent(false);
    const target = action === "start" ? undefined : jobId;
    if (action === "import" && target) pendingApply.current.add(target);
    try {
      const next = await readApi<HistoryJob>(action === "start" ? `${base}/jobs` : `${base}/jobs/${encodeURIComponent(target!)}/${action}`, controller.signal, payload);
      if (controller.signal.aborted) return;
      if (next.source_ref !== sourceRef || (target && next.id !== target)) throw new Error("history_source_mismatch");
      receive(next); setSelectedId(next.id);
      if (action === "start") { request.current = undefined; pendingRequests.delete(sourceRef); }
    } catch (caught) {
      if (!controller.signal.aborted) setCommandError(errorText(caught, "Die Anfrage ist fehlgeschlagen oder ihr Ergebnis ist unklar. Auftragsstatus vor einem erneuten Versuch aktualisieren."));
    } finally {
      running.current = false;
      if (!controller.signal.aborted) {
        setBusy(""); setRefresh((value) => value + 1);
        if (action === "start") resource.reload();
      }
    }
  };
  const parsedSymbols = capability?.requires_symbols ? [...new Set(symbols.split(",").map((value) => value.trim().toUpperCase()).filter(Boolean))] : [];
  const symbolError = parsedSymbols.length > 200 || parsedSymbols.some((value) => !/^[A-Z0-9_/-]{2,40}$/.test(value));
  const limit = Number(maxRecords), validLimit = Number.isInteger(limit) && limit >= 1 && limit <= 1000000;
  const resumeValue = jobId && resumeRecords[jobId] !== undefined ? resumeRecords[jobId] : String(job?.max_records ?? 100000);
  const resumeLimit = Number(resumeValue), validResumeLimit = Number.isInteger(resumeLimit) && resumeLimit >= 1 && resumeLimit <= 1000000;
  const validDates = /^\d{4}-\d{2}-\d{2}$/.test(start) && (!end || /^\d{4}-\d{2}-\d{2}$/.test(end) && end >= start);
  const blockingJob = ordered.some((item) => unfinished.has(item.status));
  const isSolana = capability?.provider?.toLowerCase().includes("solana");
  const rpcOptions = capability?.rpc_options ?? [];
  const rpcProvider: RpcProvider | "" = rpcMode === "public" ? "public" : rpcMode === "configured" ? configuredProvider : "";
  const selectedRpc = rpcOptions.find((option) => option.id === rpcProvider && option.kind !== "legacy");
  const configuredOptions = rpcOptions.filter((option) => option.kind === "configured" && option.id !== "legacy" && option.id !== "public");
  const canStart = resource.status === "ready" && capability?.supported && capability.ready && validDates && validLimit && !symbolError && (!capability.requires_symbols || parsedSymbols.length > 0) && (!isSolana || !!selectedRpc?.ready) && externalConsent && !blockingJob && !busy;
  const refreshStatus = () => { setPollError(""); setRefresh((value) => value + 1); resource.reload(); };
  const changeStartOptions = () => { request.current = undefined; pendingRequests.delete(sourceRef); setExternalConsent(false); };

  return <section className="hiWorkflow" aria-label={`Automatischer Import: ${sourceLabel}`}>
    <div className="hiContext"><span>Ausgewählte Quelle / Konto</span><strong>{sourceLabel}</strong><code>{sourceRef}</code></div>
    <ResourceNotice resource={resource} label="Historienabruf" />
    {capability && <>
      {!!capability.coverage_notes.length && <Coverage notes={capability.coverage_notes} />}
      {!capability.supported ? <div className="wsInlineWarning"><strong>Automatischer Import nicht verfügbar</strong><p>{errorText(capability.blocked_reason, "Für diese Quelle ist kein automatischer Historienabruf verfügbar. Originaldateien können weiterhin importiert werden.")}</p></div>
        : !capability.ready ? <div className="wsInlineWarning"><strong>Einrichtung erforderlich</strong><p>{errorText(capability.blocked_reason, "Die gespeicherte Quellen- und Anbietereinrichtung prüfen. Es wurde kein externer Abruf gestartet.")}</p><a className="wsButton" href="#admin">Einrichtung öffnen</a></div>
          : <form className="hiStart" onSubmit={(event) => {
            event.preventDefault(); if (!canStart) return;
            const options: Omit<HistoryStart, "request_id" | "confirm_external_request"> = { start, end: end || null, symbols: parsedSymbols, public_rpc_only: !isSolana || rpcProvider === "public", max_records: limit,
              include_binance_earn: !!capability.supports_binance_earn && includeEarn,
              ...(isSolana && rpcProvider ? { rpc_provider: rpcProvider } : {}) };
            const key = JSON.stringify(options);
            if (request.current?.key !== key) request.current = { key, id: uuid() };
            pendingRequests.set(sourceRef, request.current);
            const payload: HistoryStart = { ...options, request_id: request.current.id, confirm_external_request: true };
            void command("start", payload);
          }}>
            <h3>Transaktionshistorie abrufen</h3>
            <div className="hiFields"><label>Von<input type="date" required value={start} onChange={(event) => { setStart(event.target.value); changeStartOptions(); }} /></label><label>Bis<input type="date" min={start || undefined} value={end} onChange={(event) => { setEnd(event.target.value); changeStartOptions(); }} /></label><label>Datensatzlimit<input type="number" min={1} max={1000000} step={1} required value={maxRecords} onChange={(event) => { setMaxRecords(event.target.value); changeStartOptions(); }} /></label></div>
            {capability.requires_symbols && <label>Handelspaare (kommagetrennt)<input type="text" placeholder={capability.provider === "pionex" ? "BTC_USDT, ETH_USDT" : "BTCUSDT, ETHUSDT"} maxLength={8200} value={symbols} required aria-invalid={symbolError} onChange={(event) => { setSymbols(event.target.value); changeStartOptions(); }} /></label>}
            {symbolError && <p className="wsWarning">{errorText("history_symbols_invalid")} Höchstens 200 Handelspaare.</p>}
            {start && end && end < start && <p className="wsWarning">{errorText("history_date_range_invalid")}</p>}
            {capability.supports_binance_earn && <fieldset className="hiModes" disabled={!!busy}>
              <legend>Zusätzliche Historie</legend>
              <label className="hiCheck"><input type="checkbox" checked={includeEarn} onChange={(event) => { setIncludeEarn(event.target.checked); changeStartOptions(); }} /><span>Binance Simple Earn (Flexible und Locked) in diesem Kontoauftrag einbeziehen</span></label>
              <p className="wsMuted">Nur Produkte aus dem gespeicherten Snapshot dieser Verbindung und bereits kontogebundenen Earn-Belegen. Anbieter-Retention und Vollständigkeit sind nicht nachgewiesen; unbekannte Produkte und mögliche Überschneidungen mit Dateiimporten bleiben zur Prüfung.</p>
            </fieldset>}
            {isSolana && <div className="hiRpcChoice">
              <fieldset className="hiModes" disabled={!!busy}><legend>Abrufmodus</legend>
                <label className={`hiMode${rpcMode === "public" ? " hiModeSelected" : ""}`}><input type="radio" name="history-rpc-mode" value="public" checked={rpcMode === "public"} onChange={() => { setRpcMode("public"); changeStartOptions(); }} /><span>Öffentlicher RPC (Free)</span></label>
                <label className={`hiMode${rpcMode === "configured" ? " hiModeSelected" : ""}`}><input type="radio" name="history-rpc-mode" value="configured" checked={rpcMode === "configured"} onChange={() => { setRpcMode("configured"); changeStartOptions(); }} /><span>Eigener Anbieter (Free/Premium)</span></label>
              </fieldset>
              {rpcMode === "configured" && <>
                <label>Eingerichteter Dienst<select value={configuredProvider} disabled={!!busy} required onChange={(event) => { setConfiguredProvider(event.target.value as typeof configuredProvider); changeStartOptions(); }}>
                  <option value="">Dienst wählen</option>
                  {configuredOptions.map((option) => <option key={option.id} value={option.id}>{rpcName(option.id)}{!option.ready ? " · nicht verfügbar" : ""}</option>)}
                </select></label>
                {!configuredOptions.some((option) => option.ready) && <p className="wsInlineWarning">Kein eingerichteter Dienst ist abrufbereit. Zugang und Limits in der Einrichtung prüfen.</p>}
                <p className="wsMuted">Ein API-Key belegt keinen bezahlten Tarif. Free-/Premium-Tarif und mögliche Kosten beim Anbieter prüfen.</p>
              </>}
              {!rpcMode && <p className="wsMuted">Abrufmodus ausdrücklich wählen.</p>}
              {selectedRpc && <>
                <p><strong>Gewählter Anbieter: {rpcName(selectedRpc.id)}</strong></p>
                {!selectedRpc.ready && <p className="wsInlineWarning">{errorText(selectedRpc.blocked_reason, "Dieser Dienst ist nicht abrufbereit. Die gespeicherte Einrichtung prüfen; kein automatischer Ersatzanbieter.")}</p>}
                <RateLimits limits={selectedRpc.limits} />
              </>}
              {!!rpcMode && !selectedRpc && <p className="wsMuted">Anbieter- und Limitinformationen fehlen. Dienst wählen oder Status aktualisieren; kein Abruf freigegeben.</p>}
              <div className="hiActions"><a className="wsButton" href="#admin">Einrichtung öffnen</a><HelpTip label="Anbieter und Tarif">Die Auswahl ändert keine gespeicherten Limits und startet keinen Abruf. Ein eingerichteter Zugang kann Free oder Premium sein; der Tarif ist nicht verifiziert. Alle gemeinsamen Budgets gelten zusätzlich. Ein anderer Anbieter erfordert einen neuen Auftrag, keinen Wechsel beim Fortsetzen.</HelpTip></div>
            </div>}
            <p className="wsMuted">Der Abruf erstellt zunächst eine isolierte Vorschau. Noch kein Import und keine steuerliche Quellenaktivierung. Anbieterlimits und mögliche Kosten beachten.</p>
            <label className="hiCheck"><input type="checkbox" checked={externalConsent} onChange={(event) => setExternalConsent(event.target.checked)} /><span>Ich bestätige den externen Anbieterabruf für {sourceLabel} im gewählten Zeitraum.</span></label>
            {blockingJob && <p className="wsMuted">Für diese Quelle besteht bereits ein offener Auftrag. Diesen zuerst fortsetzen, seine Vorschau importieren oder ihn abbrechen.</p>}
            <div className="hiActions"><button type="submit" className="wsPrimary" disabled={!canStart}>{busy === "start" ? <LoaderCircle size={16} className="spin" /> : <Download size={16} />} Vorschau abrufen</button></div>
          </form>}
    </>}
    <div className="hiActions"><button type="button" disabled={!!busy} onClick={refreshStatus}><RefreshCw size={16} /> Status aktualisieren</button><a className="wsButton" href="#import"><Upload size={16} /> Dateien importieren</a></div>
    {commandError && <p className="wsResource error" role="alert"><AlertCircle size={16} />{commandError}</p>}
    {pollError && <p className="wsResource error" role="alert"><AlertCircle size={16} />{pollError}</p>}
    {!!ordered.length && <label>Gespeicherte Aufträge<select value={jobId || ""} disabled={!!busy} onChange={(event) => { setSelectedId(event.target.value); setPollError(""); setCommandError(""); setResumeConsent(""); setApproval({ key: "", importing: false, recalculating: false }); }}>
      {ordered.map((item) => <option key={item.id} value={item.id}>{timestamp(item.created_at)} · {statusNames[item.status]} · {item.id.slice(0, 8)}</option>)}
    </select></label>}
    {resource.status === "ready" && !ordered.length && !resource.data?.jobs.length && <p className="wsMuted">Für diese Quelle ist noch kein Historienauftrag gespeichert.</p>}
    {job && <section className="hiJob" aria-label="Ausgewählter Historienauftrag">
      <div className="hiJobHeading"><h3>Auftrag für {sourceLabel}</h3><Badge tone={job.status === "failed" ? "danger" : job.status === "paused" ? "warning" : "neutral"}>{jobStatusText(job)}</Badge></div>
      <p className="wsMuted">{job.start} bis {job.end} · Stand: {timestamp(job.updated_at)}{job.includes_binance_earn ? " · Simple Earn eingeschlossen" : ""}</p>
      <p role="status" aria-live="polite">{jobStatusText(job)} · {job.records_fetched} Datensätze · {job.pages_fetched} Seiten</p>
      {job.provider.toLowerCase().includes("solana") && <><PinnedJobProvider job={job} /><JobProgress job={job} stale={!!pollError} /></>}
      <dl className="hiCounts"><div><dt>Datensätze</dt><dd>{job.records_fetched}</dd></div><div><dt>Seiten</dt><dd>{job.pages_fetched}</dd></div><div><dt title="Anfragen der gespeicherten Seiten, ohne notwendigerweise alle Wiederholungen abzubilden">Anfragen gespeicherter Seiten</dt><dd>{job.requests}</dd></div>{job.includes_binance_earn && <div><dt title="Vor jeder HTTP-Sendung einschließlich Wiederholung reserviert; die gemeinsamen Anbieterlimits gelten zusätzlich">Reserviertes Anbieterbudget</dt><dd>{job.provider_requests_reserved} / {job.provider_request_limit}</dd></div>}<div><dt>Neu</dt><dd>{job.new_records}</dd></div><div><dt>Duplikate</dt><dd>{job.duplicate_records}</dd></div><div><dt>Importierte Ereignisse</dt><dd>{job.imported_events}</dd></div></dl>
      {job.phase && <p className="wsMuted">Phase: {job.phase}</p>}
      {job.error_code && <p className="wsInlineWarning" role="alert">{errorText(job.error_code, "Der Anbieterabruf wurde nicht vollständig abgeschlossen. Einrichtung und technischen Fehlercode prüfen.")}</p>}
      {!job.complete_history_proven && <p className="wsInlineWarning">Verfügbare Anbieterhistorie, Vollständigkeit nicht bestätigt</p>}
      <Coverage notes={job.coverage_notes} />
      <div className="hiActions">
        {(["queued", "running", "paused"] as string[]).includes(job.status) && <button type="button" disabled={!!busy || job.status === "paused"} onClick={() => void command("pause", {})}><Pause size={16} /> Pausieren</button>}
        {unfinished.has(job.status) && job.status !== "importing" && <button type="button" disabled={!!busy} onClick={() => void command("cancel", {})}><X size={16} /> Auftrag abbrechen</button>}
      </div>
      {(job.status === "paused" || job.status === "failed") && job.can_resume !== false && <div className="hiResume"><label>Datensatzlimit beim Fortsetzen<input type="number" min={1} max={1000000} step={1} value={resumeValue} onChange={(event) => { setResumeRecords((previous) => ({ ...previous, [job.id]: event.target.value })); setResumeConsent(""); }} /></label><label className="hiCheck"><input type="checkbox" checked={resumeConsent === job.id} onChange={(event) => setResumeConsent(event.target.checked ? job.id : "")} /><span>Ich bestätige weitere externe Anbieteranfragen für {sourceLabel}.</span></label><button type="button" disabled={!!busy || resumeConsent !== job.id || !validResumeLimit} onClick={() => { const payload: HistoryResume = { confirm_external_request: true, max_records: resumeLimit }; void command("resume", payload); }}><Play size={16} /> Abruf fortsetzen</button></div>}
      {job.status === "ready" && job.requires_repreview && <p className="wsWarning">Diese Vorschau stammt aus einer anderen Softwareversion. Vor einer Freigabe die gespeicherten Originalbelege lokal erneut berechnen.</p>}
      {job.status === "ready" && <button type="button" disabled={!!busy} onClick={() => { if (window.confirm("Vorschau aus den gespeicherten Originalbelegen lokal neu berechnen? Kein erneuter Anbieterabruf, kein Import. Die bisherige Vorschau bleibt als Nachweis erhalten.")) void command("repreview", {}); }}><RefreshCw size={16} /> Vorschau erneut berechnen</button>}
      {job.status === "ready" && !job.requires_repreview && <>
        <h3>Importvorschau</h3>
        {job.sample_rows.length ? <SampleTable rows={job.sample_rows} /> : <p className="wsMuted">Keine Beispielzeilen in dieser Vorschau. Datensatzzahlen und Abdeckung vor einer Freigabe prüfen.</p>}
        {job.review_issues_open !== null && <p className="wsMuted">{job.review_issues_open} offene Review-Hinweise</p>}
        <div className="hiApproval">
          <strong>Freigabe dieser Vorschau</strong><code aria-label="SHA-256 der Vorschau">{job.preview_sha256 || "Vorschauhash fehlt – keine Freigabe möglich"}</code>
          <label>Freigebende Person (Importprotokoll)<input type="text" maxLength={120} required autoComplete="off" value={actor} onChange={(event) => { setActor(event.target.value); sessionActor = event.target.value; setApproval({ key: "", importing: false, recalculating: false }); }} /></label>
          <label className="hiCheck"><input type="checkbox" checked={importChecked} onChange={(event) => setApproval({ key: approvalKey, importing: event.target.checked, recalculating: recalcChecked })} /><span>Ich bestätige den Import dieser Vorschau für {sourceLabel}.</span></label>
          <label className="hiCheck"><input type="checkbox" checked={recalcChecked} onChange={(event) => setApproval({ key: approvalKey, importing: importChecked, recalculating: event.target.checked })} /><span>Ich bestätige die Neuberechnung der betroffenen Bestands- und Steuerauswertungen.</span></label>
          <p className="wsMuted">Keine automatische Quellenaktivierung oder fachliche Steuerfreigabe. Offene Review-Aufgaben bleiben separat zu prüfen.</p>
          <button type="button" className="wsPrimary" disabled={!!busy || !!pollError || resource.status !== "ready" || !importChecked || !recalcChecked || !actor.trim() || !/^[a-f0-9]{64}$/.test(job.preview_sha256 || "")} onClick={() => {
            if (!job.preview_sha256 || approval.key !== approvalKey || !importChecked || !recalcChecked) return;
            const payload: HistoryApprove = { preview_sha256: job.preview_sha256, actor: actor.trim(), confirm_import: true, confirm_recalculation: true };
            void command("import", payload);
          }}>{busy === "import" ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />} Importieren und neu berechnen</button>
        </div>
      </>}
      {job.status === "succeeded" && <><p role="status">{job.imported_events} Ereignisse importiert. Abdeckung und offene Review-Aufgaben bleiben zu prüfen.{typeof job.approval?.actor === "string" && ` Freigegeben von: ${job.approval.actor}.`}</p><a className="wsButton" href="#portfolio?tab=prices">Historische EUR-Preise ermitteln</a></>}
      <details className="wsTechnical"><summary>Technische Auftragsdetails</summary><pre>{JSON.stringify({ source_ref: job.source_ref, id: job.id, provider: job.provider, phase: job.phase, max_records: job.max_records, error_code: job.error_code, preview_sha256: job.preview_sha256, complete_history_proven: job.complete_history_proven, before_summary: job.before_summary, after_summary: job.after_summary, approval: job.approval, sample_rows: job.sample_rows }, null, 2)}</pre></details>
    </section>}
    {capability?.blocked_reason && <details className="wsTechnical"><summary>Technische Einrichtungshinweise</summary><code>{capability.blocked_reason}</code></details>}
  </section>;
}

function rpcName(id: HistoryRpcOption["id"]) {
  return ({ public: "Öffentlicher RPC (Free)", helius: "Helius", alchemy: "Alchemy", custom: "Eigener RPC", legacy: "Älterer RPC-Auftrag (Anbieter nicht eindeutig ausgewiesen)" })[id] ?? "Anbieter unbekannt";
}
const measuredNumber = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) && value >= 0;
const numberText = (value: number | null | undefined) => measuredNumber(value) ? new Intl.NumberFormat("de-DE", { maximumFractionDigits: 3 }).format(value!) : "Unbekannt";
const safeGroups = (values?: string[]) => (values ?? []).filter((value) => /^(?:provider|ip|project|account|endpoint|budget):[a-zA-Z0-9_.:-]{1,100}$/.test(value));
const budgetReasons: Record<string, string> = {
  requests_per_second: "Sekundenbudget", rolling_second: "Sekundenbudget", requests_per_10_seconds: "10-Sekunden-Budget",
  rolling_10_seconds: "10-Sekunden-Budget", requests_per_minute: "Minutenbudget", rolling_minute: "Minutenbudget",
  weighted_cost_per_minute: "Lokales Kostenbudget", burst: "Burst-Grenze", max_concurrency: "Parallelitätsgrenze", concurrency: "Parallelitätsgrenze",
  provider_pause: "Anbieter-Wartehinweis (z. B. 429)", clock_rollback: "Systemzeit zurückgestellt",
};
function hasBudgetPause(limits?: HistoryRateState | null) {
  if (!limits?.available) return false;
  if (limits.blocking_reasons?.includes("provider_pause")) return true;
  // Admission limits for the next request do not imply the active request is paused.
  if (measuredNumber(limits.wait_seconds)) return limits.wait_seconds! >= 1;
  return (limits.waiting_requests ?? 0) > 0 && limits.in_flight === 0;
}
function RateLimits({ limits }: { limits?: HistoryRateState | null }) {
  if (!limits?.available) return <p className="wsMuted">Wirksame Limits: derzeit nicht verfügbar. Keine zugesicherte Abrufrate.</p>;
  const groups = safeGroups(limits.budget_groups), bottlenecks = safeGroups(limits.bottlenecks);
  const waiting = hasBudgetPause(limits);
  return <div className="hiLimits" aria-label="Wirksame Abruflimits">
    <div className="hiJobHeading"><strong>Wirksame lokale Limits</strong><HelpTip label="Wirksame Abruflimits">Die serverseitigen Grenzen gelten gleichzeitig: Anbieter, gemeinsame IP und gegebenenfalls weitere Budgetgruppen oder Endpunkte. Das niedrigste passende Budget begrenzt. Die rechnerische Obergrenze ist keine gemessene Geschwindigkeit und keine verifizierte Hersteller- oder Tarifgrenze. Andere Nutzer desselben Budgets können den Abruf weiter verlangsamen.</HelpTip></div>
    <dl className="hiLimitValues">
      <div><dt>Anfragen / Sekunde</dt><dd>{numberText(limits.requests_per_second)}</dd></div>
      <div><dt>Anfragen / 10 Sekunden</dt><dd>{limits.requests_per_10_seconds == null ? "Keine zusätzliche Grenze gemeldet" : numberText(limits.requests_per_10_seconds)}</dd></div>
      <div><dt>Anfragen / Minute</dt><dd>{numberText(limits.requests_per_minute)}</dd></div>
      <div><dt>Parallel</dt><dd>{numberText(limits.max_concurrency)}</dd></div>
      <div><dt>Rechnerische Obergrenze</dt><dd>{numberText(limits.effective_max_requests_per_second)}{measuredNumber(limits.effective_max_requests_per_second) && " Anfragen/s"}</dd></div>
    </dl>
    {!!groups.length && <p className="wsMuted">Gemeinsam genutzte Budgets: {groups.map((group, index) => <span key={group}>{index > 0 && ", "}<code>{group}</code></span>)}</p>}
    {!!bottlenecks.length && <p className="hiBottleneck">Begrenzendes Budget: {bottlenecks.map((group, index) => <span key={group}>{index > 0 && ", "}<code>{group}</code></span>)}</p>}
    {waiting && <div className="wsInlineWarning" role="status">
      <strong>Abruf wartet auf Budget / Anbieter</strong>
      {!!limits.blocking_reasons?.length && <p>{[...new Set(limits.blocking_reasons.map((reason) => budgetReasons[reason] ?? "Weitere Budgetgrenze"))].join(" · ")}</p>}
      <p>{(limits.wait_seconds ?? 0) > 0 ? `Gemeldete Wartezeit: ca. ${Math.ceil(limits.wait_seconds!)} s.` : "Wartezeit unbekannt."}{limits.retry_at && ` Frühester neuer Versuch: ${timestamp(limits.retry_at)}.`}</p>
    </div>}
    {(limits.waiting_requests != null || limits.in_flight != null) && <p className="wsMuted">Wartende Anfragen: {numberText(limits.waiting_requests)} · Laufende Anfragen: {numberText(limits.in_flight)}</p>}
    {limits.config_revision != null && <p className="wsMuted">Limitkonfiguration: Revision {limits.config_revision}</p>}
  </div>;
}
function PinnedJobProvider({ job }: { job: HistoryJob }) {
  const pinned = job.transport?.pinned === true && job.transport.kind !== "legacy";
  return <div className="hiTransport" aria-label="Gebundener Auftragsanbieter">
    <strong>Auftragsanbieter: {job.transport ? job.transport.label : "Nicht gespeichert (älterer Auftrag)"}</strong>
    {pinned ? <p className="wsMuted">Fest gebunden. Fortsetzen behält die gespeicherte Anbieterbindung. Ein Anbieterwechsel erfordert einen neuen Auftrag; die Auswahl oben ändert diesen Auftrag nicht.</p>
      : <p className="wsInlineWarning">Für diesen älteren Auftrag ist keine eindeutige Anbieterbindung dokumentiert. Die Auswahl oben ändert ihn nicht. Für eine explizite Anbieterwahl einen neuen Auftrag anlegen.</p>}
    {job.transport?.kind === "configured" && <p className="wsMuted">Tarif nicht verifiziert. Ein eingerichteter API-Key belegt keinen Premium-Tarif.</p>}
    {job.transport && !job.transport.ready && <p className="wsInlineWarning">{errorText(job.transport.blocked_reason, "Der gebundene Dienst ist derzeit nicht abrufbereit. Einrichtung prüfen; kein stiller Wechsel auf einen anderen Anbieter.")}</p>}
    <RateLimits limits={job.transport?.limits} />
  </div>;
}
function jobStatusText(job: HistoryJob) {
  return job.status === "running" && (job.progress?.phase === "preparing" || /vorschau.*berechnet/i.test(job.phase))
    ? "Abruf beendet · Vorschau wird berechnet" : statusNames[job.status];
}
function durationText(seconds: number) {
  if (seconds < 60) return "unter 1 Minute";
  const minutes = Math.ceil(seconds / 60);
  return minutes < 60 ? `${minutes} Minuten` : `${Math.floor(minutes / 60)} Std. ${minutes % 60} Min.`;
}
function JobProgress({ job, stale }: { job: HistoryJob; stale: boolean }) {
  const progress = job.progress;
  if (!progress) return <section className="hiProgress" aria-label="Abruffortschritt"><h3>Abruffortschritt</h3><p className="wsMuted">Für diesen älteren Auftrag fehlen detaillierte Fortschrittsmetadaten. Gesamtzahl und Restzeit: unbekannt.</p><p className="wsMuted">Messstand: {timestamp(job.updated_at)}</p></section>;
  const total = progress?.inventory_complete && measuredNumber(progress.signatures_total) ? progress.signatures_total! : null;
  const completed = measuredNumber(progress?.signatures_completed) ? progress!.signatures_completed! : null;
  const discovery = progress?.phase === "discovery" || progress?.estimate_status === "unknown_total";
  const stopped = ["paused", "failed", "cancelled"].includes(job.status) || ["paused", "cancelled", "error"].includes(progress?.phase ?? "");
  const waiting = hasBudgetPause(job.transport?.limits);
  const fetchComplete = progress?.estimate_status === "fetch_complete" || ["preparing", "complete"].includes(progress?.phase ?? "");
  const canEstimate = !stale && !stopped && !waiting && job.status === "running" && progress?.phase === "fetch" && total !== null && completed !== null && completed > 0
    && (progress.observed_details_per_second ?? 0) > 0 && progress.estimate_status === "estimated" && measuredNumber(progress.estimated_fetch_remaining_seconds);
  const percent = !discovery && total !== null && total > 0 && completed !== null ? Math.min(100, Math.max(0, completed / total * 100)) : null;
  return <section className="hiProgress" aria-label="Abruffortschritt">
    <div className="hiJobHeading"><h3>Abruffortschritt</h3><HelpTip label="Restzeitschätzung">Zuerst wird die verfügbare Signaturliste ermittelt. Dabei ist die Gesamtzahl unbekannt; es gibt keinen Gesamtprozentsatz. Erst nach abgeschlossener Liste und gemessenen Detailabrufen wird die Restzeit für diese Details geschätzt. Wartezeiten können sie verlängern. Die anschließende Vorschauberechnung ist nicht enthalten. Auch eine abgearbeitete Liste beweist keine vollständige Wallet-Historie.</HelpTip></div>
    <ol className="hiPhases">
      <li aria-current={discovery ? "step" : undefined}><strong>1. Signaturliste ermitteln</strong><span>{progress?.inventory_complete ? "Verfügbare Liste ermittelt" : "Gesamtzahl noch unbekannt"}</span>
        {measuredNumber(progress?.signatures_discovered) && <span>{numberText(progress?.signatures_discovered)} eindeutige Signaturen gefunden</span>}
        {measuredNumber(progress?.references_discovered) && <span>{numberText(progress?.references_discovered)} Referenzen geprüft</span>}
        {measuredNumber(progress?.addresses_completed) && <span>{numberText(progress?.addresses_completed)} / {numberText(progress?.addresses_total)} Adressen geprüft</span>}
      </li>
      <li aria-current={progress?.phase === "fetch" ? "step" : undefined}><strong>2. Transaktionsdetails abrufen</strong><span>{total === null ? "Wartet auf bekannte Gesamtzahl" : `${numberText(completed)} / ${numberText(total)} Details abgerufen`}</span>
        {percent !== null && <><progress value={Math.min(completed!, total!)} max={total!} aria-label="Fortschritt der verfügbaren Transaktionsdetails" /><span>{numberText(Math.floor(percent))} % der verfügbaren Details, nicht der gesamten Historie</span></>}
      </li>
    </ol>
    <p className="hiEstimate"><strong>Restzeit Abruf: </strong>{canEstimate ? `ca. ${durationText(progress!.estimated_fetch_remaining_seconds!)}` : stopped ? "Angehalten, keine laufende Schätzung" : fetchComplete ? "Detailabruf beendet" : waiting ? "Wartet auf Budget / Anbieter, Schätzung ausgesetzt" : "Noch nicht schätzbar"}</p>
    {canEstimate && <p className="wsMuted">Gemessene Rate: {numberText(progress?.observed_details_per_second)} Details/s. Schätzung nur für verbleibende verfügbare Transaktionsdetails.</p>}
    {!fetchComplete && !stopped && !waiting && !canEstimate && <p className="wsMuted">Eine Schätzung benötigt eine bekannte Gesamtzahl und gemessene Detailabrufe.</p>}
    {job.status !== "succeeded" && job.status !== "ready" && <p className="wsMuted">Gesamt-Restzeit einschließlich Vorschauberechnung: unbekannt.</p>}
    {fetchComplete && job.status === "running" && <p className="wsInlineWarning">Abruf beendet. Die isolierte Vorschau wird separat berechnet; noch keine Importfreigabe möglich.</p>}
    {stopped && <p className="wsInlineWarning">{job.status === "cancelled" ? "Auftrag abgebrochen." : job.status === "failed" || progress?.phase === "error" ? "Abruf wegen eines Fehlers angehalten." : "Abruf pausiert."} Der gespeicherte Fortschritt ist kein laufender Countdown.</p>}
    {stale && <p className="wsInlineWarning">Statusaktualisierung fehlgeschlagen. Angezeigte Zähler stammen vom letzten gespeicherten Stand; Restzeit derzeit unbekannt.</p>}
    <p className="wsMuted">Messstand: {timestamp(progress.updated_at ?? job.updated_at)}</p>
  </section>;
}

function mergeJobs(previous: HistoryJob[], incoming: HistoryJob[]) {
  const merged = new Map(previous.map((job) => [job.id, job]));
  for (const job of incoming) {
    const old = merged.get(job.id);
    if (!old || job.updated_at >= old.updated_at) merged.set(job.id, job);
  }
  return [...merged.values()];
}
function Coverage({ notes }: { notes: string[] }) {
  return notes.length ? <ul className="hiCoverage" aria-label="Historienabdeckung">{notes.map((note, index) => <li key={`${index}:${note}`}>{note}</li>)}</ul> : null;
}
function SampleTable({ rows }: { rows: Record<string, unknown>[] }) {
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const columns = ["timestamp_utc", "event_time", "timestamp", "event_type", "asset", "quantity", "quote_asset", "quote_quantity", "fee_asset", "fee_quantity", "side"].filter((key) => keys.includes(key));
  const names: Record<string, string> = { timestamp_utc: "Zeitpunkt", event_time: "Zeitpunkt", timestamp: "Zeitpunkt", event_type: "Typ", asset: "Asset", quantity: "Menge", quote_asset: "Gegenasset", quote_quantity: "Gegenmenge", fee_asset: "Gebührenasset", fee_quantity: "Gebührenmenge", side: "Richtung" };
  if (!columns.length) return <p className="wsMuted">{rows.length} Beispielzeilen vorhanden; Einzelheiten in den technischen Auftragsdetails.</p>;
  return <div className="wsTableScroll hiSample" role="region" aria-label="Beispielzeilen der Importvorschau" tabIndex={0}><table><caption>Beispielzeilen der Vorschau, noch nicht importiert</caption><thead><tr>{columns.map((key) => <th scope="col" key={key}>{names[key]}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{key.includes("quantity") && canonicalDecimal(row[key]) !== null ? <><ExactQuantity value={String(row[key])} /><code className="hiExact">{String(row[key])}</code></> : textValue(row[key])}</td>)}</tr>)}</tbody></table></div>;
}
