import { useEffect, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Download, LoaderCircle, RefreshCw, Save } from "lucide-react";
import { HelpTip } from "../Help";
import { API_BASE } from "../api-base";
import { ApiReadError, readApi, timestamp } from "./resource";
import { ExactQuantity } from "./Ui";
import { listenView, useViewState } from "./view-state";

const base = "/api/v1/prices/historical";
type HistoricalPriceQuery = { year: number | null; assets: string[]; provider: "defillama" | "coingecko"; max_requests: number; max_total_requests: number | null; strategy: "standard" | "automatic"; scope: "tax_required" | "all_observed" };
type LookupAttempt = { provider_id?: string; search?: string | number | null; status?: string; reason?: string | null; evidence_sha256?: string | string[] | null };
type Row = { asset: string; price_date: string; event_count: number; event_types?: string[]; event_year_counts?: Record<string, number>; identity_basis?: string; years?: number[]; mint?: string | null; mints?: string[]; provider_id?: string; resolved_provider_id?: string | null; lookup_attempts?: LookupAttempt[]; lookup_stage?: string; status: string; fetch_state?: string; reason?: string; price_eur?: string; priced_at?: string; fx_date?: string; source?: string; evidence_sha256?: string[] };
type YearSummary = { year: number; events_count: number; tokens_count: number; requirements_count: number; covered_count: number; fetchable_count: number; blocked_count: number; open_count?: number };
type Plan = { plan_sha256: string; requirements_count: number; fetchable_count: number; events_count: number; max_requests: number; rows: Row[]; rows_truncated?: boolean; time_basis: string; page: number; page_size: number; year_summary: YearSummary[]; source_event_types: Record<string, number>; source_events_count: number; rows_total: number; row_offset: number; rows_limit: number; next_offset: number | null; inventory_count: number };
type Preview = { id: string; preview_sha256: string; prices_count: number; requests_started: number; section_requests_started?: number; max_total_requests?: number | null; created_at: string; rows: Row[]; status: string; applied: boolean; pending_count?: number; open_count?: number; total_rows?: number; year_summary?: YearSummary[]; collection_complete?: boolean; parent_preview_id?: string; source_event_types?: Record<string, number>; query?: Partial<HistoricalPriceQuery>; remaining_requirements?: number; review_issues_open?: number; before_summary?: unknown; after_summary?: unknown; before_valuation_summary?: unknown; after_valuation_summary?: unknown; canonical_events_unchanged?: boolean; frozen_source_sha256?: string; tax_line_deltas?: unknown[] };
type CollectionStatus = { status: "running" | "ready" | "interrupted" | "not_found"; rows_processed: number; total_rows: number; requests_started: number; section_requests_started?: number; phase: string; preview_id: string };
type CollectionRun = { section: number; previousRequests?: number; budget?: number };
type CollectionRequest = { id: string; path: string; body: Record<string, unknown>; label: string };
const sessionKey = "steuerreport:historical-price-request";
const uuidPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const rowStatuses: Record<string, string> = { covered: "Bereits abgedeckt", planned: "Geplant", fetched: "Belegt; Übernahme separat", pending: "Nächster Abschnitt", open: "Abruf offen / fehlgeschlagen", blocked: "Blockiert" };
const eventTypes: Record<string, string> = { trade: "Handel", transfer: "Transfer", fee: "Gebühr", reward: "Reward", income: "Einkommen", staking: "Staking", mining: "Mining", derivative: "Derivat", unknown: "Unbekannt" };
function rememberedRequest() {
  try { const value = sessionStorage.getItem(sessionKey); return value && uuidPattern.test(value) ? value : ""; } catch { return ""; }
}
function rememberRequest(id: string) {
  try { if (id) sessionStorage.setItem(sessionKey, id); else sessionStorage.removeItem(sessionKey); } catch { /* Ohne Browserspeicher bleibt die aktuelle Anfrage im Arbeitsspeicher. */ }
}
function eventTypeText(types?: Record<string, number>) {
  return Object.entries(types || {}).filter(([, count]) => count > 0).map(([type, count]) => `${eventTypes[type] || type}: ${count}`).join(" · ");
}
function rowStatus(row: Row) { return row.fetch_state || (row.lookup_stage === "pending" ? "pending" : row.status); }
function requestCount(value: unknown): number | undefined { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : undefined; }
function requestBudget(value: unknown): number | undefined { const count = requestCount(value); return count != null && count >= 1 && count <= 1000 ? count : undefined; }
function previewBudget(preview?: Preview) {
  const budgets = [requestBudget(preview?.max_total_requests), requestBudget(preview?.query?.max_total_requests)].filter((value): value is number => value != null);
  return budgets.length ? Math.min(...budgets) : undefined;
}
function phaseLabel(phase: string) {
  const labels: Record<string, string> = { fetching: "Preisabruf", collecting: "Preisabruf", preparing: "Isolierte Neuberechnung", calculating: "Isolierte Neuberechnung", ready: "Vorschau bereit" };
  return labels[phase] || phase;
}
const reasons: Record<string, string> = {
  asset_not_configured: "Preisquelle zuordnen", token_risk_spam_review: "Token zunächst prüfen – Spamverdacht",
  asset_identity_conflict: "Gleiches Symbol auf verschiedenen Chains oder Contracts: Identität klären",
  asset_decimals_conflict: "Widersprüchliche Token-Dezimalstellen: Originaldaten prüfen",
  asset_quantity_decimals_mismatch: "Tokenmenge passt nicht zu Rohmenge und Dezimalstellen",
  price_mapping_identity_mismatch: "Preiszuordnung widerspricht der belegten Chain-/Contractidentität",
  price_mapping_identity_unbound: "CoinGecko-Zuordnung zuerst an Netzwerk und Contractadresse binden",
  asset_mint_conflict: "Mehrere Mint-Adressen für dasselbe Asset: Tokenidentität prüfen",
  solana_mint_invalid: "Solana-Mint-Adresse ist ungültig",
  solana_mint_identity_mismatch: "Solana-Mint stimmt nicht mit der nachgewiesenen Tokenidentität überein",
  solana_mint_missing: "Solana-Mint-Adresse fehlt: Tokenidentität belegen",
  price_mapping_mint_mismatch: "Preiszuordnung und nachgewiesener Token-Mint stimmen nicht überein",
  future_date: "Heutiger oder zukünftiger Tag: historischen Tagesabschluss abwarten",
  historical_price_timestamp_mismatch: "Kein zeitlich passender Kurs geliefert",
  historical_price_fx_date_invalid: "Wechselkursdatum unzulässig oder zu alt",
  historical_price_value_invalid: "Kein gültiger positiver Preis geliefert",
  historical_price_identity_mismatch: "Anbieter-ID stimmt nicht überein",
  historical_price_http_401: "Preiszugang fehlt oder ist ungültig", historical_price_http_403: "Anbieterzugang oder Historie nicht freigeschaltet",
  historical_price_http_404: "Anbieter hat keinen Datensatz gefunden", historical_price_http_429: "Anbieterlimit erreicht – später erneut planen",
  request_budget_or_limiter_unavailable: "Abrufbudget erreicht oder Abrufsteuerung nicht verfügbar",
  historical_price_provider_unavailable: "Preisantwort fehlt oder ist unvollständig",
  historical_price_quote_missing: "Passender historischer Preisnachweis fehlt",
  historical_price_quote_conflict: "Widersprüchliche historische Preisnachweise: Belege prüfen",
  historical_price_source_changed: "Rohdaten oder Ereigniseinordnung weichen ab. Keine Übernahme; Datenstand prüfen.",
  historical_price_collection_incomplete: "Zuerst die noch nicht abgefragten Preisabschnitte sammeln.",
  historical_price_report_invalid_or_too_large: "Bericht kann nicht vollständig geprüft oder innerhalb der Exportgrenze erstellt werden.",
  historical_price_incomplete_request: "Abruf unterbrochen oder unvollständig gespeichert. Status prüfen; vorhandene Belege bleiben erhalten.",
  historical_price_nothing_to_continue: "Keine ausstehenden Abrufe für diesen Abschnitt. Vorschau und offene Abrufe prüfen.",
  historical_price_total_budget_exhausted: "Gesamtes HTTP-Budget erreicht. Keine weiteren externen Abrufe in diesem Lauf; gespeicherte Vorschau prüfen.",
  historical_price_plan_stale: "Datenbasis geändert. Preisbedarf erneut planen.",
  historical_price_preview_stale: "Vorschau ist veraltet. Eine neue Planung und Vorschau sind erforderlich.",
  historical_price_not_found: "Vorschau nicht gefunden oder noch nicht vollständig gespeichert.",
  historical_price_evidence_changed: "Belegprüfung fehlgeschlagen. Keine Übernahme möglich.",
  historical_price_operation_running: "Dieser Vorgang läuft bereits. Gespeicherte Vorschauen später aktualisieren.",
  historical_price_demo_read_only: "Testumgebung: externe Abrufe und Übernahmen sind gesperrt.",
  historical_price_plan_too_large: "Mehr als 50.000 Tagespositionen. Bitte Jahr oder Asset eingrenzen.",
  historical_price_storage_insufficient: "Zu wenig freier Speicher für eine sichere Berechnungsvorschau. Installation prüfen.",
  historical_price_request_conflict: "Die Vorgangs-ID gehört zu einer anderen Anfrage. Gespeicherten Status prüfen und neu planen."
};
function message(error: unknown) { return error instanceof ApiReadError ? reasons[error.code || ""] || "Vorgang nicht abgeschlossen. Status prüfen und erneut versuchen." : "Vorgang nicht abgeschlossen. Gespeicherte Daten bleiben erhalten."; }
function uuid() {
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((n) => n.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function PriceWorkspace({ onCurrentPrices }: { onCurrentPrices: (requests: string, dryRun: boolean, assets: string) => void }) {
  const { view, set } = useViewState("portfolio");
  const { year, asset } = view;
  const [provider, setProvider] = useState<HistoricalPriceQuery["provider"]>("defillama"), [limit, setLimit] = useState("50");
  const [totalLimit, setTotalLimit] = useState("200"), [autoContinue, setAutoContinue] = useState(true);
  const [scope, setScope] = useState<HistoricalPriceQuery["scope"]>("all_observed");
  const [plan, setPlan] = useState<Plan>(), [preview, setPreview] = useState<Preview>();
  const [planPage, setPlanPage] = useState(1);
  const [recent, setRecent] = useState<Preview[]>([]), [busy, setBusy] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [external, setExternal] = useState(false), [prices, setPrices] = useState(false), [recalculate, setRecalculate] = useState(false), [actor, setActor] = useState("");
  const [mappingAsset, setMappingAsset] = useState(""), [coinId, setCoinId] = useState(""), [mintId, setMintId] = useState(""), [originalMint, setOriginalMint] = useState("");
  const [mappingNetwork, setMappingNetwork] = useState(""), [mappingContract, setMappingContract] = useState(""), [mappingDecimals, setMappingDecimals] = useState("");
  const [mappings, setMappings] = useState<Record<string, { coingecko_id?: string; defillama_id?: string; solana_mint?: string | null; network?: string | null; contract_address?: string | null; decimals?: number | null }>>({});
  const [recoveryId, setRecoveryId] = useState(rememberedRequest), [pollingId, setPollingId] = useState("");
  const [progress, setProgress] = useState<CollectionStatus>(), [pollingStopped, setPollingStopped] = useState(false);
  const [collectionRun, setCollectionRun] = useState<CollectionRun>();
  const operation = useRef<CollectionRequest>();
  const active = useRef(false), serial = useRef(0), mounted = useRef(true);
  const key = JSON.stringify([year, asset, provider, limit, totalLimit, scope]);
  const query: HistoricalPriceQuery = { year: year === "all" ? null : Number(year), assets: asset.trim() ? [asset.trim()] : [], provider, max_requests: Math.min(Number(limit), Number(totalLimit)), max_total_requests: Number(totalLimit), strategy: "automatic", scope };
  const validTotalLimit = requestBudget(Number(totalLimit)) != null;
  const validLimit = Number.isInteger(Number(limit)) && Number(limit) >= 1 && Number(limit) <= 50 && validTotalLimit && Number(limit) <= Number(totalLimit);
  const observedPreview = preview?.query?.scope === "all_observed" || preview?.query?.strategy === "automatic";
  const pendingCount = preview?.pending_count ?? 0, openCount = preview?.open_count ?? 0;
  const savedBudget = previewBudget(preview);
  const budgetExhausted = savedBudget != null && preview != null && preview.requests_started >= savedBudget;
  const applyBlocked = observedPreview && (preview?.collection_complete !== true || pendingCount > 0);
  const sectionRequests = progress ? requestCount(progress.section_requests_started ?? progress.requests_started) : undefined;
  const totalRequests = sectionRequests != null && collectionRun?.previousRequests != null ? collectionRun.previousRequests + sectionRequests : undefined;
  const refreshRecent = async () => { const result = await readApi<Preview[]>(base + "/previews"); if (mounted.current) setRecent(result); };
  useEffect(() => { ++serial.current; setPlan(undefined); setPlanPage(1); setPreview(undefined); setExternal(false); setPrices(false); setRecalculate(false); setError(""); setNotice(""); }, [key]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; ++serial.current; }; }, []);
  useEffect(() => {
    let hash = window.location.hash;
    const invalidate = () => {
      ++serial.current; setPlan(undefined); setPreview(undefined); setExternal(false); setPrices(false); setRecalculate(false); setPollingId("");
      if (active.current) setNotice("Ansicht oder Datenstand geändert. Es werden keine weiteren Preisabschnitte automatisch gestartet. Den laufenden Vorgang bei Bedarf über seine ID prüfen.");
    };
    const unlisten = listenView(() => { if (hash !== window.location.hash) { hash = window.location.hash; invalidate(); } });
    window.addEventListener("steuerreport:refresh", invalidate);
    window.addEventListener("pagehide", invalidate);
    return () => { unlisten(); window.removeEventListener("steuerreport:refresh", invalidate); window.removeEventListener("pagehide", invalidate); };
  }, []);
  useEffect(() => { const controller = new AbortController(); void readApi<Preview[]>(base + "/previews", controller.signal).then(setRecent).catch((e) => { if (!controller.signal.aborted) setError(message(e)); }); return () => controller.abort(); }, []);
  useEffect(() => { const controller = new AbortController(); void readApi<typeof mappings>(base + "/mappings", controller.signal).then(setMappings).catch((e) => { if (!controller.signal.aborted) setError(message(e)); }); return () => controller.abort(); }, []);
  useEffect(() => {
    if (!pollingId) return;
    let stopped = false, attempts = 0, timer: number | undefined;
    const version = serial.current;
    const current = () => !stopped && mounted.current && version === serial.current && operation.current?.id === pollingId;
    const controller = new AbortController();
    // Nur den laufenden synchronen Abruf beobachten; kein neuer Abruf durch Polling.
    const poll = async () => {
      const timeout = window.setTimeout(() => controller.abort(), 5000);
      try {
        const status = await readApi<CollectionStatus>(base + "/previews/" + pollingId + "/status", controller.signal);
        if (!current()) return;
        setProgress(status);
        if (status.status === "ready" || status.status === "interrupted") return;
      } catch { if (current()) setPollingStopped(true); return; }
      finally { window.clearTimeout(timeout); }
      if (current() && ++attempts < 40) timer = window.setTimeout(() => void poll(), 3000);
      else if (current()) setPollingStopped(true);
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { stopped = true; window.clearTimeout(timer); controller.abort(); };
  }, [pollingId]);
  const command = async (name: string, fn: () => Promise<void>) => {
    if (active.current) return; active.current = true; setBusy(name); setError(""); setNotice("");
    const version = serial.current;
    try { await fn(); } catch (e) { if (mounted.current && version === serial.current) setError(message(e)); } finally { active.current = false; if (mounted.current) setBusy(""); }
  };
  const acceptPreview = (result: Preview) => {
    setPreview(result); setPrices(false); setRecalculate(false); setExternal(false);
    setRecoveryId(""); setProgress(undefined); setCollectionRun(undefined); operation.current = undefined; rememberRequest(result.id);
  };
  const loadPreview = (id: string) => command("Vorschau laden", async () => {
    const version = serial.current;
    const result = await readApi<Preview>(base + "/previews/" + encodeURIComponent(id));
    if (!mounted.current || version !== serial.current) return;
    acceptPreview(result);
    setPlan(undefined);
  });
  const loadPlan = (page = 1) => command("Preisbedarf planen", async () => {
    const version = serial.current;
    const result = await readApi<Plan>(base + "/plan", undefined, { ...query, page, page_size: 25 });
    if (!mounted.current || version !== serial.current) return;
    setPlan(result); setPlanPage(result.page ?? page); setPreview(undefined); setExternal(false); rememberRequest("");
  });
  const collect = (request: CollectionRequest) => command(request.label, async () => {
    const version = serial.current;
    const current = () => mounted.current && version === serial.current;
    let next = request;
    let previous = request.path === base + "/previews" ? undefined : preview;
    let budget = requestBudget(request.body.max_total_requests) ?? previewBudget(previous);
    let previousRequests = previous ? requestCount(previous.requests_started) : request.path === base + "/previews" ? 0 : undefined;
    let previousPending = previous?.pending_count ?? (request.path === base + "/previews" ? plan?.fetchable_count : undefined);
    try {
      // Die Einwilligung gilt nur fuer diesen seriellen Lauf; nie aus gespeicherten IDs rekonstruieren.
      for (let section = 1; section <= 1000 && current(); section++) {
        operation.current = next; rememberRequest(next.id); setRecoveryId(next.id);
        setExternal(false); setPrices(false); setRecalculate(false); setProgress(undefined); setPollingStopped(false); setPollingId(next.id);
        setCollectionRun({ section, previousRequests, budget });
        const result = await readApi<Preview>(next.path, undefined, next.body);
        if (!current()) return;
        setPollingId(""); acceptPreview(result);
        const reportedBudget = previewBudget(result);
        if (reportedBudget != null) budget = Math.min(budget ?? reportedBudget, reportedBudget);
        const started = requestCount(result.requests_started);
        if (result.applied || !(result.pending_count != null && result.pending_count > 0) || !autoContinue || result.query?.strategy !== "automatic" || request.body.confirm_external_request !== true) break;
        if (budget == null || started == null) { setNotice("Automatische Fortsetzung gestoppt: Gesamtbudget oder kumulativer HTTP-Stand fehlen. Vorschau prüfen."); break; }
        if (started >= budget) { setNotice("Gesamtes HTTP-Budget erreicht. Ausstehende Preispositionen bleiben offen; keine automatische Übernahme."); break; }
        const progressed = (previousPending != null && result.pending_count < previousPending) || (previousRequests != null && started > previousRequests);
        if (!progressed || result.id === previous?.id) { setNotice("Automatische Fortsetzung gestoppt: kein Fortschritt bei ausstehenden Positionen oder gestarteten HTTP-Anfragen. Vorschau prüfen."); break; }
        if (section === 1000) { setNotice("Automatische Fortsetzung nach 1000 Abschnitten gestoppt. Gespeicherte Vorschau prüfen."); break; }
        previous = result; previousPending = result.pending_count; previousRequests = started;
        const id = uuid();
        next = { id, path: base + "/previews/" + encodeURIComponent(result.id) + "/continue", label: "Ausstehende Preisabschnitte abrufen", body: { request_id: id, preview_sha256: result.preview_sha256, confirm_external_request: true, retry_open: false } };
      }
      if (current()) {
        try { await refreshRecent(); } catch { if (current()) setNotice("Vorschau gespeichert. Die Liste gespeicherter Vorschauen konnte nicht aktualisiert werden."); }
      }
    } finally { if (mounted.current) setPollingId(""); }
  });
  const checkStatus = () => command("Abrufstatus prüfen", async () => {
    const version = serial.current;
    const result = await readApi<CollectionStatus>(base + "/previews/" + recoveryId + "/status");
    if (!mounted.current || version !== serial.current) return;
    setProgress(result); setExternal(false);
    if (result.status === "ready") {
      const saved = await readApi<Preview>(base + "/previews/" + recoveryId);
      if (mounted.current && version === serial.current) acceptPreview(saved);
    }
  });
  const continueCollection = (retryOpen: boolean) => {
    if (!preview || !external || !observedPreview || budgetExhausted) return;
    const id = uuid();
    void collect({ id, path: base + "/previews/" + preview.id + "/continue", label: retryOpen ? "Offene Abrufe erneut versuchen" : "Nächsten Preisabschnitt abrufen", body: { request_id: id, preview_sha256: preview.preview_sha256, confirm_external_request: true, retry_open: retryOpen } });
  };
  return <section className="wsPage wsPriceWorkspace" aria-label="EUR-Preise ermitteln" aria-busy={!!busy}>
    <h2>EUR-Preise ermitteln</h2>
    <p>Historische Bewertung und heutiger Bestandswert sind getrennt. Fehlende Kurse bleiben offen, nicht 0 €.</p>
    <div className="wsFilters"><fieldset disabled={!!busy || !!recoveryId} className="wsFilterInputs"><legend>Historischer Preisbedarf</legend>
      <label>Jahr<select value={year} onChange={(e) => set({ year: e.target.value })}><option value="all">Alle Jahre</option>{Array.from({ length: new Date().getFullYear() - 2008 }, (_, i) => String(2009 + i)).reverse().map((value) => <option key={value}>{value}</option>)}</select></label>
      <label>Asset<input value={asset} maxLength={100} placeholder="Alle Assets" onChange={(e) => set({ asset: e.target.value.toUpperCase() })} /></label>
      <label>Preisumfang<select value={scope} onChange={(e) => setScope(e.target.value as HistoricalPriceQuery["scope"])}><option value="all_observed">Alle erkannten Token</option><option value="tax_required">Nur steuerlich benötigte Preise</option></select></label>
      <label>Historischer Preisanbieter<select value={provider} onChange={(e) => setProvider(e.target.value as HistoricalPriceQuery["provider"])}><option value="defillama">DefiLlama + historischer USD/EUR-Kurs</option><option value="coingecko">CoinGecko – EUR direkt</option></select></label>
      <label>HTTP-Anfragen pro Abschnitt<input type="number" min="1" max={validTotalLimit ? Math.min(50, Number(totalLimit)) : 50} value={limit} onChange={(e) => setLimit(e.target.value)} /></label>
      <label>Gesamtes HTTP-Budget<input type="number" min="1" max="1000" value={totalLimit} onChange={(e) => {
        const value = e.target.value; setTotalLimit(value);
        if (requestBudget(Number(value)) != null && Number(limit) > Number(value)) setLimit(value);
      }} /></label>
      <label className="checkboxLabel"><input type="checkbox" checked={autoContinue} onChange={(e) => { setAutoContinue(e.target.checked); setExternal(false); }} /> Ausstehende Abschnitte automatisch fortsetzen</label>
      <HelpTip label="Historische Preisquellen">CoinGecko liefert eine UTC-Tagesreferenz, sofern der Zugang die angeforderte Historie erlaubt. DefiLlama prüft passende naheliegende Zeitpunkte vor dem ersten betroffenen Ereignis des UTC-Tags und gegebenenfalls eine nachgewiesene native SOL-Referenz. Die Umrechnung nutzt einen historischen USD/EUR-Referenzkurs. Wochenenden können den vorherigen Geschäftstag verwenden, höchstens sieben Tage zurück. Kein Ausführungskurs und keine steuerliche Freigabe. Alternative Suchversuche, Wiederholungen und Wechselkursabfragen zählen zum gesamten HTTP-Budget.</HelpTip>
      <button type="button" disabled={!validLimit} onClick={() => void loadPlan()}><RefreshCw size={16} /> Preisbedarf planen</button>
    </fieldset></div>
    {busy && <p role="status"><LoaderCircle size={16} className="spin" /> {busy} läuft. Anbieterwartezeiten und lokale Vorschau können dauern.</p>}
    {error && <p role="alert" className="wsWarning">{error}</p>}{notice && <p role="status">{notice}</p>}
    {recoveryId && <section className="wsPriceRecovery" aria-label="Abrufstatus">
      <h3>{busy && pollingId ? `Preisabschnitt ${collectionRun?.section ?? 1} läuft` : "Abrufstatus offen"}</h3>
      <p>Vorgang <code>{recoveryId}</code></p>
      {busy && collectionRun && <p role="status">Aktueller Abschnitt: {collectionRun.section} · HTTP-Anfragen in diesem Abschnitt: {sectionRequests ?? "noch nicht ausgewiesen"}{collectionRun.previousRequests != null && <> · Gesamt-HTTP: {totalRequests ?? collectionRun.previousRequests}{collectionRun.budget != null && <> / {collectionRun.budget}</>}{totalRequests == null && " zuletzt bestätigt"}</>}</p>}
      {progress && <p role="status">{({ running: "Abruf läuft", ready: "Vorschau gespeichert", interrupted: "Abruf unterbrochen", not_found: "Noch kein gespeicherter Vorgang gefunden" })[progress.status]} · {progress.rows_processed} / {progress.total_rows} Zeilen · {sectionRequests ?? "Nicht ausgewiesen"} HTTP-Anfragen im Abschnitt{progress.phase && <> · {phaseLabel(progress.phase)}</>}</p>}
      {pollingStopped && busy && <p>Automatische Statusprüfung beendet. Die ursprüngliche Anfrage bleibt aktiv.</p>}
      {!busy && <>
        <p>Die Statusprüfung liest nur den bestehenden Vorgang. Sie startet keine externen Preisabfragen.</p>
        <button type="button" onClick={() => void checkStatus()}><RefreshCw size={16} /> Abrufstatus prüfen</button>
        {operation.current && progress?.status === "not_found" && <>
          <label className="checkboxLabel"><input type="checkbox" checked={external} onChange={(e) => setExternal(e.target.checked)} /> Dieselbe Anfrage erneut senden und mögliche weitere externe Preis- und Wechselkursabfragen ausdrücklich bestätigen.{collectionRun?.budget != null && <> Das gesamte HTTP-Budget bleibt bei {collectionRun.budget} Anfragen einschließlich bisheriger Abschnitte.{autoContinue && " Ausstehende Abschnitte dürfen unter dieser Einwilligung automatisch fortgesetzt werden; keine automatischen Fehler-Retries."}</>} Dieselbe Vorgangs-ID bleibt erhalten. Kein automatischer Import und keine automatische Übernahme von Preisen oder Neuberechnung.</label>
          <button type="button" disabled={!external} onClick={() => { if (operation.current) void collect(operation.current); }}><RefreshCw size={16} /> Dieselbe Anfrage erneut senden</button>
        </>}
        {progress?.status === "interrupted" && <p className="wsInlineWarning">Dieser unterbrochene Vorgang kann nicht mit derselben ID fortgesetzt werden. Vorhandene Originalbelege bleiben erhalten. Eine neue Planung und erneute ausdrückliche Zustimmung sind für weitere externe Abrufe erforderlich; es wird kein Abrufbudget automatisch zurückgesetzt.</p>}
        {progress && ["interrupted", "not_found"].includes(progress.status) && <>
          {!operation.current && <p>Nach einem Neuladen ist nur die Vorgangs-ID gespeichert, nicht die Anfrage mit ihren Finanzfiltern. Gespeicherte Vorschauen bleiben separat verfügbar.</p>}
          <button type="button" onClick={() => {
            if (operation.current && !window.confirm("Diesen Vorgang zurückstellen und eine neue Planung vorbereiten? Gespeicherte Vorschauen und Belege bleiben erhalten. Es wird jetzt kein neuer externer Abruf gestartet.")) return;
            operation.current = undefined; setRecoveryId(""); setProgress(undefined); setExternal(false); setPlan(undefined); setPreview(undefined); setError(""); rememberRequest("");
          }}>Neue Planung vorbereiten</button>
        </>}
      </>}
    </section>}
    <SourceCoverage types={preview?.source_event_types || plan?.source_event_types} />
    {plan && !preview && <>
      <p role="status">{plan.requirements_count} fehlende Asset-Tagespreise für {plan.events_count} Ereignisse; {plan.fetchable_count} mit zugeordneter Preisquelle. Höchstens {limit} HTTP-Anfragen pro Abschnitt, insgesamt höchstens {totalLimit}.</p>
      <p>{plan.source_events_count ?? plan.events_count} Quellereignisse · {plan.inventory_count ?? "Unbekannt viele"} Asset-Tageszeilen im Inventar. {eventTypeText(plan.source_event_types)}</p>
      <YearOverview summaries={plan.year_summary} selectedYear={year} />
      {!plan.requirements_count && <p>Kein offener Preisbedarf in den bereits importierten Ereignissen dieses Filters. Noch nicht freigegebene Historienvorschauen werden nicht mitgezählt. Das ist keine Vollständigkeits- oder Abgabefreigabe.</p>}
      <PriceRows rows={plan.rows} />
      <nav className="wsPager" aria-label="Planseiten">
        <span>{plan.rows_total ? `${plan.row_offset + 1}–${Math.min(plan.row_offset + plan.rows.length, plan.rows_total)} von ${plan.rows_total}` : "Keine Zeilen"} · Seite {planPage}</span>
        <button type="button" title="Vorherige Planseite" aria-label="Vorherige Planseite" disabled={!!busy || !!recoveryId || planPage === 1} onClick={() => void loadPlan(planPage - 1)}><ChevronLeft size={16} /></button>
        <button type="button" title="Nächste Planseite" aria-label="Nächste Planseite" disabled={!!busy || !!recoveryId || plan.next_offset == null} onClick={() => void loadPlan(Math.floor(plan.next_offset! / 25) + 1)}><ChevronRight size={16} /></button>
      </nav>
      <label className="checkboxLabel"><input type="checkbox" checked={external} disabled={!!busy || !!recoveryId} onChange={(e) => setExternal(e.target.checked)} /> Externe Preis- und gegebenenfalls Wechselkursabfragen einschließlich alternativer Suchversuche ausdrücklich bis zum gesamten Budget von {totalLimit} HTTP-Anfragen erlauben, höchstens {limit} je Abschnitt. {autoContinue ? "Ausstehende Abschnitte werden unter dieser Einwilligung automatisch fortgesetzt; fehlgeschlagene Abrufe nicht automatisch wiederholt." : "Nur einen Abschnitt starten; weitere Abschnitte benötigen eine erneute Bestätigung."} Anbieterlimits und mögliche Tarifkosten beachten. Kein automatischer Import und keine Übernahme von Preisen oder Neuberechnung in die produktiven Daten.</label>
      <button type="button" className="wsPrimary" disabled={!!busy || !!recoveryId || !external || !plan.fetchable_count || !validLimit} onClick={() => {
        const id = uuid();
        void collect({ id, path: base + "/previews", label: "Kurse abrufen und Vorschau berechnen", body: { ...query, request_id: id, plan_sha256: plan.plan_sha256, confirm_external_request: true } });
      }}><Download size={16} /> Kurse abrufen und Vorschau berechnen</button>
    </>}
    {preview && <>
      <h3>{preview.applied ? "Preisübernahme abgeschlossen" : "Gespeicherte Preisvorschau"}</h3>
      <p>Gespeicherter Umfang: {preview.query?.year == null ? "Alle Jahre" : preview.query.year} · {preview.query?.scope === "all_observed" ? "Alle erkannten Token" : "Steuerlicher Preisbedarf"} · {preview.query?.assets?.join(", ") || "Alle Assets"}</p>
      <p>{preview.prices_count} {preview.prices_count === 1 ? "belegter EUR-Preis" : "belegte EUR-Preise"} · Gesamt-HTTP: {preview.requests_started}{savedBudget != null && <> / {savedBudget}</>} gestartet{preview.section_requests_started != null && <> · Letzter Abschnitt: {preview.section_requests_started} HTTP-Anfragen</>} · {timestamp(preview.created_at)}</p>
      <p>{preview.total_rows != null ? `${preview.total_rows} Zeilen insgesamt` : `${preview.rows.length} Zeilen in dieser gespeicherten Vorschau`} · {preview.pending_count != null ? `${pendingCount} noch nicht abgerufen` : "Ausstehende Abschnitte nicht ausgewiesen"} · {preview.open_count != null ? openCount : preview.rows.filter((row) => rowStatus(row) === "open").length} offene / fehlgeschlagene Abrufe. {preview.collection_complete === true ? "Sammlung abgeschlossen; offene und blockierte Zeilen bleiben gesondert zu prüfen." : preview.collection_complete === false ? "Sammlung noch nicht abgeschlossen." : "Sammlungsstand für diese ältere Vorschau nicht hinterlegt."} Keine steuerliche Jahresfreigabe.</p>
      {preview.parent_preview_id && <p className="wsMuted">Zusammengeführte Vorschau einschließlich aller zuvor belegten Preise.</p>}
      <YearOverview summaries={preview.year_summary} selectedYear={preview.query?.year?.toString() || "all"} />
      <PreviewRows key={preview.id} preview={preview} />
      <div className="wsActionFooter" aria-label="Preisberichte herunterladen">{([ ["zip", "Jahres-CSV und Belege als ZIP"], ["json", "Preisvorschau und Quellen als JSON"], ["md", "Preisbericht als Markdown"] ] as const).map(([extension, label]) => <a className="wsButton" key={extension} href={API_BASE + base + "/previews/" + encodeURIComponent(preview.id) + "/report." + extension} download><Download size={16} /> {label}</a>)}</div>
      {(preview.remaining_requirements != null || preview.review_issues_open != null) && <p>Noch {preview.remaining_requirements ?? "unbekannt viele"} benötigte Preispositionen; {preview.review_issues_open ?? "unbekannt viele"} fachliche Hinweise – nicht alles Preisfehler. <a href="#review">Fachliche Hinweise prüfen</a>. Auch 0 Preispositionen bedeuten keine Vollständigkeits- oder Jahresfreigabe.</p>}
      <details className="wsTechnical"><summary>Belege und Berechnungsänderungen</summary>
        <p>Vorschau-Fingerabdruck (SHA-256): <code>{preview.preview_sha256}</code></p>
        <h4>Bewertung vorher / nachher</h4>
        <pre>{JSON.stringify({ vorher: preview.before_valuation_summary ?? "Nicht hinterlegt", nachher: preview.after_valuation_summary ?? "Nicht hinterlegt" }, null, 2)}</pre>
        <h4>Unveränderter Quellstand</h4>
        <p>{preview.canonical_events_unchanged === true ? "Backend-Nachweis: Canonical Events sind unverändert." : preview.canonical_events_unchanged === false ? "Der Backend-Nachweis unveränderter Canonical Events ist fehlgeschlagen." : "Für diese Vorschau ist kein Nachweis unveränderter Canonical Events hinterlegt."}</p>
        <p>Eingefrorener Quellstand (SHA-256): <code>{preview.frozen_source_sha256 || "Nicht hinterlegt"}</code></p>
        <h4>Berechnung und Originalbelege</h4>
        <pre>{JSON.stringify({ before: preview.before_summary, after: preview.after_summary, changes: preview.tax_line_deltas, evidence: preview.rows.map((row) => ({ asset: row.asset, date: row.price_date, hashes: row.evidence_sha256, source: row.source })) }, null, 2)}</pre>
      </details>
      {!preview.applied && observedPreview && (pendingCount > 0 || openCount > 0) && <fieldset disabled={!!busy || !!recoveryId}><legend>Historische Preise abschnittsweise sammeln</legend>
        <p>Höchstens {preview.query?.max_requests ?? limit} HTTP-Anfragen je weiterem Abschnitt.{savedBudget != null ? <> Gesamtes HTTP-Budget: {savedBudget}; davon bereits {preview.requests_started} gestartet.</> : <> Für diese ältere Vorschau ist kein Gesamtbudget hinterlegt; keine automatische Fortsetzung.</>} Bereits belegte Preise bleiben in der gemeinsamen Vorschau erhalten.</p>
        {budgetExhausted && <p className="wsInlineWarning">Gesamtes HTTP-Budget erreicht. Keine weiteren Abschnitte oder Fehler-Retries in diesem Lauf.</p>}
        <label className="checkboxLabel"><input type="checkbox" checked={external} disabled={budgetExhausted} onChange={(e) => setExternal(e.target.checked)} /> Weitere externe Preis- und gegebenenfalls Wechselkursabfragen ausdrücklich erlauben.{savedBudget != null && <> Insgesamt höchstens {savedBudget} HTTP-Anfragen einschließlich bisheriger Abschnitte.</>} {autoContinue && preview.query?.strategy === "automatic" && savedBudget != null ? "Ausstehende Abschnitte werden unter dieser Einwilligung automatisch bis zum Gesamtbudget fortgesetzt, auch nach einem bewusst gestarteten Fehler-Retry." : "Nur diesen Abschnitt starten."} Nur „Offene Abrufe erneut versuchen“ wiederholt fehlgeschlagene Abrufe. Anbieterlimits und mögliche Tarifkosten beachten. Kein automatischer Import und keine automatische Übernahme von Preisen oder Neuberechnung.</label>
        {pendingCount > 0 && <button type="button" className="wsPrimary" disabled={!external || budgetExhausted} onClick={() => continueCollection(false)}><Download size={16} /> Nächsten Preisabschnitt abrufen</button>}
        {openCount > 0 && <button type="button" disabled={!external || budgetExhausted} onClick={() => continueCollection(true)}><RefreshCw size={16} /> Offene Abrufe erneut versuchen</button>}
      </fieldset>}
      {!preview.applied && applyBlocked && <p className="wsWarning">Vor der gemeinsamen Übernahme müssen die ausstehenden Abschnitte gesammelt werden. Blockierte oder fehlgeschlagene Preise bleiben offen, nicht 0 €.</p>}
      {!preview.applied && preview.status === "ready" && <fieldset disabled={!!busy || !!recoveryId || applyBlocked}><legend>Diese Vorschau übernehmen</legend>
        <label>Freigebende Person<input value={actor} maxLength={100} onChange={(e) => setActor(e.target.value)} /></label>
        <label className="checkboxLabel"><input type="checkbox" checked={prices} onChange={(e) => setPrices(e.target.checked)} /> Die ausgewiesenen EUR-Preise mit ihren Belegen speichern.</label>
        <label className="checkboxLabel"><input type="checkbox" checked={recalculate} onChange={(e) => setRecalculate(e.target.checked)} /> Die gezeigte Neuberechnung ausdrücklich übernehmen. Bestehende Jahres- und Referenzsnapshots bleiben erhalten; dies ist keine fachliche Jahresfreigabe.</label>
        <button type="button" className="wsPrimary" disabled={!prices || !recalculate || !actor.trim()} onClick={() => void command("Preise übernehmen", async () => {
          await readApi(base + "/previews/" + preview.id + "/apply", undefined, { preview_sha256: preview.preview_sha256, actor: actor.trim(), confirm_prices: true, confirm_recalculation: true });
          window.dispatchEvent(new Event("steuerreport:refresh")); setPreview({ ...preview, applied: true }); setNotice("Preisübernahme und Neuberechnung abgeschlossen. Offene Hinweise und Steuerjahr erneut prüfen."); await refreshRecent();
        })}><Check size={16} /> Preise und Neuberechnung übernehmen</button>
      </fieldset>}
      <button type="button" disabled={!!busy || !!recoveryId} onClick={() => { setPreview(undefined); setPlan(undefined); setExternal(false); setPrices(false); setRecalculate(false); rememberRequest(""); }}>Weiteren Preisabschnitt planen</button>
    </>}
    <details className="wsTechnical"><summary>Gespeicherte Preisvorschauen</summary><button type="button" disabled={!!busy} onClick={() => void command("Vorschauen aktualisieren", refreshRecent)}><RefreshCw size={16} /> Liste aktualisieren</button>{recent.length ? recent.map((item) => <div key={item.id}><button type="button" disabled={!!busy || (!!recoveryId && item.id !== recoveryId)} onClick={() => void loadPreview(item.id)}>{timestamp(item.created_at)} · {item.prices_count} Preise · {item.applied ? "übernommen" : "Vorschau"}</button></div>) : <p>Noch keine gespeicherte Preisvorschau.</p>}</details>
    <details className="wsTechnical"><summary>Preisquellen zuordnen</summary><p>Exakte Anbieter-ID verwenden. Bei Solana-Token den Mint prüfen; gleiche Symbole beweisen keine Tokenidentität. Eine Zuordnung ist keine Eigentums- oder Spamfreigabe.</p>
      <label>Vorhandene Preiszuordnung<select disabled={!!busy || !!recoveryId} value={mappings[mappingAsset] ? mappingAsset : ""} onChange={(e) => { const asset = e.target.value; setMappingAsset(asset); setCoinId(mappings[asset]?.coingecko_id || ""); setMintId(mappings[asset]?.defillama_id || ""); setOriginalMint(mappings[asset]?.solana_mint || ""); setMappingNetwork(mappings[asset]?.network || ""); setMappingContract(mappings[asset]?.contract_address || ""); setMappingDecimals(mappings[asset]?.decimals?.toString() ?? ""); }}><option value="">Neue Zuordnung</option>{Object.keys(mappings).sort().map((asset) => <option key={asset}>{asset}</option>)}</select></label>
      <form onSubmit={(e) => { e.preventDefault(); void command("Preiszuordnung speichern", async () => {
        await fetchMapping({ asset: mappingAsset.trim(), coingecko_id: coinId.trim() || null, defillama_id: mintId.trim() || null, solana_mint: originalMint.trim() || null, network: mappingNetwork.trim() || null, contract_address: mappingContract.trim() || null, decimals: mappingDecimals === "" ? null : Number(mappingDecimals) });
        setMappings(await readApi<typeof mappings>(base + "/mappings")); setPlan(undefined); setPreview(undefined); setExternal(false); setPrices(false); setRecalculate(false); rememberRequest(""); setNotice("Preiszuordnung gespeichert. Preisbedarf erneut planen.");
      }); }}><fieldset disabled={!!busy || !!recoveryId}><legend>Eigene Preiszuordnung</legend>
        <label>Asset-Kennung<input required maxLength={100} pattern="[A-Za-z0-9_:./-]+" value={mappingAsset} onChange={(e) => setMappingAsset(e.target.value)} /></label>
        <label>CoinGecko-ID<input pattern="[a-z0-9-]+" value={coinId} onChange={(e) => setCoinId(e.target.value)} placeholder="zum Beispiel solana" /></label>
        <label>Originale Solana-Mint-Adresse<input pattern="[1-9A-HJ-NP-Za-km-z]{32,44}" value={originalMint} onChange={(e) => setOriginalMint(e.target.value)} /></label>
        <label>Netzwerk<input pattern="[a-z0-9][a-z0-9:_-]{0,60}" value={mappingNetwork} onChange={(e) => setMappingNetwork(e.target.value)} /></label>
        <label>Contractadresse<input maxLength={150} value={mappingContract} onChange={(e) => setMappingContract(e.target.value)} /></label>
        <label>Token-Dezimalstellen<input type="number" min={0} max={255} step={1} value={mappingDecimals} onChange={(e) => setMappingDecimals(e.target.value)} /></label>
        <HelpTip label="Mint-Bindung der Preiszuordnung">Die originale Mint-Adresse bleibt mit ihrer Groß-/Kleinschreibung gespeichert. Bei einer CoinGecko-Zuordnung bindet sie die Anbieter-ID an den beobachteten Solana-Token; ein gleiches Symbol allein genügt nicht.</HelpTip>
        <label>DefiLlama-ID<input pattern="[A-Za-z0-9_-]+:[A-Za-z0-9_-]+" value={mintId} onChange={(e) => setMintId(e.target.value)} placeholder="solana:exakterMint" /></label>
        <button type="submit" disabled={!mappingAsset.trim() || (!coinId.trim() && !mintId.trim())}><Save size={16} /> Preiszuordnung speichern</button>
      </fieldset></form>
    </details>
    <section><h3>Heutige Portfolio-Marktpreise</h3><p>Nur für bereits importierte positive Ledger-Bestände. Keine rückwirkende Bewertung vergangener Ereignisse.</p><button type="button" disabled={!!busy || !!recoveryId || !validLimit} onClick={() => onCurrentPrices(limit, true, asset)}>Aktuelle Preise planen</button><button type="button" disabled={!!busy || !!recoveryId || !validLimit} onClick={() => { if (window.confirm("Aktuelle Preise extern abrufen, im Preis-Ledger speichern und die bestehende Pipeline neu berechnen? Keine Jahresfreigabe. Anbieterlimits und mögliche Tarifkosten beachten.")) onCurrentPrices(limit, false, asset); }}><Download size={16} /> Aktuelle Preise abrufen</button></section>
    <p>Fehlende Historie oder nicht unterstützte Token: Preisbelege als CSV im Expertenmodus importieren. Keine geschätzten Preise eintragen.</p>
  </section>;
}

async function fetchMapping(body: unknown) {
  const response = await fetch(API_BASE + base + "/mappings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error("mapping_failed");
}
function PriceRows({ rows, previewId }: { rows: Row[]; previewId?: string }) {
  const identityLabels: Record<string, string> = { original_mint: "Mint aus Originaldaten", native_sol_reference: "Native SOL-Referenz", configured_mapping: "Konfigurierte Preiszuordnung" };
  return <div className="wsTableScroll"><table className="wsPriceRows">
    <caption>Historische EUR-Preisbedarfe und Belege</caption>
    <thead><tr><th>Asset / Identität</th><th>Datum (UTC) / Jahre</th><th>Ereignisse</th><th>EUR je Token</th><th>Preiszeit / FX-Tag</th><th>Status</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.asset + ":" + row.price_date}>
      <td>{row.asset}<small>{row.resolved_provider_id || row.provider_id || "Keine Preisquelle"}</small>
        {row.asset === "SOL" && row.resolved_provider_id === "coingecko:solana" && row.resolved_provider_id !== row.provider_id && row.price_eur != null && <small>Belegte native SOL-Preisreferenz als Alternative zur ursprünglich geplanten Quelle.</small>}
        {row.identity_basis && <small>Identitätsbasis: {identityLabels[row.identity_basis] || row.identity_basis}</small>}
        {row.mint && <small>Mint: {row.mint}</small>}
        {!!row.mints?.length && (!row.mint || row.mints.length > 1) && <details><summary>Erkannte Mint-Adressen ({row.mints.length})</summary>{row.mints.map((mint) => <small key={mint}>{mint}</small>)}</details>}
      </td>
      <td>{row.price_date}{!!row.years?.length && <small>Jahre: {row.years.join(", ")}</small>}</td>
      <td>{row.event_count}<small>{(Array.isArray(row.event_types) ? row.event_types : []).map((type) => eventTypes[type] || type).join(" · ")}</small>
        {!!Object.keys(row.event_year_counts || {}).length && <small>Ereignisse je Jahr: {Object.entries(row.event_year_counts!).map(([year, count]) => `${year}: ${count}`).join(" · ")}</small>}
      </td>
      <td>{row.price_eur == null ? "Noch nicht verfügbar" : <ExactQuantity value={row.price_eur} />}</td>
      <td>{row.priced_at ? timestamp(row.priced_at) : "Nicht belegt"}{row.fx_date && <small>USD/EUR: {row.fx_date}</small>}</td>
      <td><span className={"wsBadge " + (rowStatus(row) === "blocked" ? "danger" : ["open", "pending"].includes(rowStatus(row)) ? "warning" : "")}>{rowStatuses[rowStatus(row)] || "Status unbekannt"}</span>
        {rowStatus(row) === "pending" && row.lookup_stage === "fallback" ? <small>Alternative Zeitpunkte oder eine nachgewiesene native SOL-Referenz sind noch ausstehend.</small> : row.reason && <small>{reasons[row.reason] || "Preisnachweis noch offen"}</small>}
        {(!!row.lookup_attempts?.length || (row.resolved_provider_id && row.resolved_provider_id !== row.provider_id)) && <details><summary>Technische Abrufversuche ({row.lookup_attempts?.length ?? 0})</summary>
          <small>Geplante Quelle: {row.provider_id || "Nicht hinterlegt"}</small>
          {row.resolved_provider_id && <small>Aufgelöste Quelle: {row.resolved_provider_id}</small>}
          {row.lookup_stage && <small>Abrufstufe: {row.lookup_stage}</small>}
          {row.source && <small>Preisbeleg: <code>{row.source}</code></small>}
          {row.lookup_attempts?.map((attempt, index) => <div key={index}>
            <small>Versuch {index + 1}: {attempt.provider_id || "Quelle nicht hinterlegt"} · Suche: {attempt.search ?? "Nicht hinterlegt"} · Status: {attempt.status || "Nicht hinterlegt"}</small>
            {attempt.reason && <small>{reasons[attempt.reason] || attempt.reason}</small>}
            {(Array.isArray(attempt.evidence_sha256) ? attempt.evidence_sha256 : attempt.evidence_sha256 ? [attempt.evidence_sha256] : []).map((sha) => <small key={sha}>{previewId ? <a href={API_BASE + base + "/previews/" + encodeURIComponent(previewId) + "/evidence/" + encodeURIComponent(sha)} download>Originalantwort: <code>{sha}</code></a> : <code>{sha}</code>}</small>)}
          </div>)}
        </details>}
        {previewId && !!row.evidence_sha256?.length && <details><summary>Originalbelege</summary>{row.evidence_sha256.map((sha, i) => <p key={sha}><a href={API_BASE + base + "/previews/" + encodeURIComponent(previewId) + "/evidence/" + encodeURIComponent(sha)} download>Originalantwort {i + 1}</a></p>)}</details>}
      </td>
    </tr>)}{!rows.length && <tr><td colSpan={6}>Keine Preiszeilen für diese Auswahl. Keine Aussage zur Vollständigkeit der Historie.</td></tr>}</tbody>
  </table></div>;
}

function SourceCoverage({ types }: { types?: Record<string, number> }) {
  const present = Object.entries(types || {}).filter(([, count]) => count > 0);
  return present.length > 0 && present.every(([type]) => ["transfer", "fee"].includes(type)) ? <p className="wsInlineWarning">In der importierten Datenbasis sind nur Transfers und/oder Gebühren enthalten. Handels-, Reward-, Mining-, Staking- und andere Einkommensereignisse sind hier nicht nachgewiesen. Auch vollständig belegte Preise ersetzen keine fehlenden Ereignisklassen.</p> : null;
}

function YearOverview({ summaries, selectedYear }: { summaries?: YearSummary[]; selectedYear: string }) {
  const rows = summaries || [];
  return <section className="wsPriceYears" aria-label="Historische Jahresübersicht">
    <h3>Jahresübersicht</h3>
    {(!rows.length || (selectedYear !== "all" && !rows.some((row) => String(row.year) === selectedYear))) && <p className="wsInlineWarning">Für {selectedYear === "all" ? "diese Auswahl" : selectedYear} liegen keine Jahresdaten vor. Fehlende Daten bedeuten nicht vollständig bewertete oder freigegebene Jahre.</p>}
    {!!rows.length && <div className="wsTableScroll"><table><caption>Importierte Ereignisse und Preisabdeckung je Jahr</caption><thead><tr><th>Jahr</th><th>Ereignisse</th><th>Token</th><th>Preisbedarf</th><th>Abgedeckt</th><th>Abrufbar</th><th>Blockiert</th><th>Offene Abrufe</th></tr></thead><tbody>{rows.map((row) => <tr key={row.year}><th scope="row">{row.year}{row.events_count === 0 && <small>Keine Ereignisdaten</small>}</th><td>{row.events_count}</td><td>{row.tokens_count}</td><td>{row.requirements_count}</td><td>{row.covered_count}</td><td>{row.fetchable_count}</td><td>{row.blocked_count}</td><td>{row.open_count ?? "Nicht ausgewiesen"}</td></tr>)}</tbody></table></div>}
  </section>;
}

function PreviewRows({ preview }: { preview: Preview }) {
  const [year, setYear] = useState("all"), [status, setStatus] = useState("all"), [page, setPage] = useState(1);
  const yearsFor = (row: Row) => row.years?.length ? row.years.map(String) : [row.price_date.slice(0, 4)];
  const years = [...new Set([...(preview.year_summary || []).map((row) => String(row.year)), ...preview.rows.flatMap(yearsFor)])].sort().reverse();
  const filtered = preview.rows.filter((row) => (year === "all" || yearsFor(row).includes(year)) && (status === "all" || rowStatus(row) === status));
  const pages = Math.max(1, Math.ceil(filtered.length / 25)), currentPage = Math.min(page, pages);
  const start = (currentPage - 1) * 25;
  return <div className="wsPricePreviewRows">
    <div className="wsFilterInputs">
      <label>Vorschau-Jahr<select value={year} onChange={(e) => { setYear(e.target.value); setPage(1); }}><option value="all">Alle Jahre</option>{years.map((value) => <option key={value}>{value}</option>)}</select></label>
      <label>Vorschau-Status<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="all">Alle Status</option>{Object.entries(rowStatuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    </div>
    <PriceRows rows={filtered.slice(start, start + 25)} previewId={preview.id} />
    <nav className="wsPager" aria-label="Vorschauseiten">
      <span>{filtered.length ? `${start + 1}–${Math.min(start + 25, filtered.length)} von ${filtered.length}` : "Keine Zeilen"} · Seite {currentPage} / {pages}</span>
      <button type="button" title="Vorherige Vorschauseite" aria-label="Vorherige Vorschauseite" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={16} /></button>
      <button type="button" title="Nächste Vorschauseite" aria-label="Nächste Vorschauseite" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}><ChevronRight size={16} /></button>
    </nav>
  </div>;
}
