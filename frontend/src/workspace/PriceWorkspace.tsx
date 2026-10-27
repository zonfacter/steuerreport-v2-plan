import { useEffect, useRef, useState } from "react";
import { Check, Download, LoaderCircle, RefreshCw, Save } from "lucide-react";
import { HelpTip } from "../Help";
import { API_BASE } from "../api-base";
import { ApiReadError, readApi, timestamp } from "./resource";
import { ExactQuantity } from "./Ui";
import { useViewState } from "./view-state";

const base = "/api/v1/prices/historical";
type Row = { asset: string; price_date: string; event_count: number; provider_id?: string; status: string; reason?: string; price_eur?: string; priced_at?: string; fx_date?: string; source?: string; evidence_sha256?: string[] };
type Plan = { plan_sha256: string; requirements_count: number; fetchable_count: number; events_count: number; max_requests: number; rows: Row[]; rows_truncated: boolean; time_basis: string };
type Preview = { id: string; preview_sha256: string; prices_count: number; requests_started: number; created_at: string; rows: Row[]; status: string; applied: boolean; remaining_requirements?: number; review_issues_open?: number; before_summary?: unknown; after_summary?: unknown; tax_line_deltas?: unknown[] };
const reasons: Record<string, string> = {
  asset_not_configured: "Preisquelle zuordnen", token_risk_spam_review: "Token zunächst prüfen – Spamverdacht",
  future_date: "Heutiger oder zukünftiger Tag: historischen Tagesabschluss abwarten",
  historical_price_timestamp_mismatch: "Kein zeitlich passender Kurs geliefert",
  historical_price_fx_date_invalid: "Wechselkursdatum unzulässig oder zu alt",
  historical_price_value_invalid: "Kein gültiger positiver Preis geliefert",
  historical_price_identity_mismatch: "Anbieter-ID stimmt nicht überein",
  historical_price_http_401: "Preiszugang fehlt oder ist ungültig", historical_price_http_403: "Anbieterzugang oder Historie nicht freigeschaltet",
  historical_price_http_404: "Anbieter hat keinen Datensatz gefunden", historical_price_http_429: "Anbieterlimit erreicht – später erneut planen",
  request_budget_or_limiter_unavailable: "Abrufbudget erreicht oder Abrufsteuerung nicht verfügbar",
  historical_price_provider_unavailable: "Preisantwort fehlt oder ist unvollständig",
  historical_price_plan_stale: "Datenbasis geändert. Preisbedarf erneut planen.",
  historical_price_preview_stale: "Vorschau ist veraltet. Eine neue Planung und Vorschau sind erforderlich.",
  historical_price_not_found: "Vorschau nicht gefunden oder noch nicht vollständig gespeichert.",
  historical_price_evidence_changed: "Belegprüfung fehlgeschlagen. Keine Übernahme möglich.",
  historical_price_operation_running: "Dieser Vorgang läuft bereits. Gespeicherte Vorschauen später aktualisieren.",
  historical_price_demo_read_only: "Testumgebung: externe Abrufe und Übernahmen sind gesperrt."
};
function message(error: unknown) { return error instanceof ApiReadError ? reasons[error.code || ""] || "Vorgang nicht abgeschlossen. Status prüfen und erneut versuchen." : "Vorgang nicht abgeschlossen. Gespeicherte Daten bleiben erhalten."; }
function uuid() {
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((n) => n.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function PriceWorkspace({ onCurrentPrices }: { onCurrentPrices: (requests: string, dryRun: boolean, assets: string) => void }) {
  const { view, set } = useViewState("portfolio");
  const [provider, setProvider] = useState("defillama"), [limit, setLimit] = useState("10");
  const [plan, setPlan] = useState<Plan>(), [preview, setPreview] = useState<Preview>();
  const [recent, setRecent] = useState<Preview[]>([]), [busy, setBusy] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [external, setExternal] = useState(false), [prices, setPrices] = useState(false), [recalculate, setRecalculate] = useState(false), [actor, setActor] = useState("");
  const [mappingAsset, setMappingAsset] = useState(""), [coinId, setCoinId] = useState(""), [mintId, setMintId] = useState("");
  const [mappings, setMappings] = useState<Record<string, { coingecko_id?: string; defillama_id?: string }>>({});
  const active = useRef(false), serial = useRef(0), requestId = useRef("");
  const key = JSON.stringify([view.year, view.asset, provider, limit]);
  const query = { year: view.year === "all" ? null : Number(view.year), assets: view.asset ? [view.asset] : [], provider, max_requests: Number(limit) };
  const refreshRecent = async () => setRecent(await readApi<Preview[]>(base + "/previews"));
  useEffect(() => { ++serial.current; setPlan(undefined); setPreview(undefined); setExternal(false); setPrices(false); setRecalculate(false); requestId.current = ""; }, [key]);
  useEffect(() => { const controller = new AbortController(); void readApi<Preview[]>(base + "/previews", controller.signal).then(setRecent).catch((e) => { if (!controller.signal.aborted) setError(message(e)); }); return () => controller.abort(); }, []);
  useEffect(() => { const controller = new AbortController(); void readApi<typeof mappings>(base + "/mappings", controller.signal).then(setMappings).catch((e) => { if (!controller.signal.aborted) setError(message(e)); }); return () => controller.abort(); }, []);
  const command = async (name: string, fn: () => Promise<void>) => {
    if (active.current) return; active.current = true; setBusy(name); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError(message(e)); } finally { active.current = false; setBusy(""); }
  };
  const loadPreview = (id: string) => command("Vorschau laden", async () => { setPreview(await readApi<Preview>(base + "/previews/" + encodeURIComponent(id))); setPrices(false); setRecalculate(false); });
  return <section className="wsPage wsPriceWorkspace" aria-label="EUR-Preise ermitteln" aria-busy={!!busy}>
    <h2>EUR-Preise ermitteln</h2>
    <p>Historische Bewertung und heutiger Bestandswert sind getrennt. Fehlende Kurse bleiben offen, nicht 0 €.</p>
    <div className="wsFilters"><fieldset disabled={!!busy} className="wsFilterInputs"><legend>Historischer Preisbedarf</legend>
      <label>Jahr<select value={view.year} onChange={(e) => set({ year: e.target.value })}><option value="all">Alle Jahre</option>{Array.from({ length: new Date().getFullYear() - 2008 }, (_, i) => String(2009 + i)).reverse().map((year) => <option key={year}>{year}</option>)}</select></label>
      <label>Asset<input value={view.asset} maxLength={100} placeholder="Alle Assets" onChange={(e) => set({ asset: e.target.value.toUpperCase() })} /></label>
      <label>Historischer Preisanbieter<select value={provider} onChange={(e) => setProvider(e.target.value)}><option value="defillama">DefiLlama + historischer USD/EUR-Kurs</option><option value="coingecko">CoinGecko – EUR direkt</option></select></label>
      <label>Maximale HTTP-Anfragen<input type="number" min="1" max="50" value={limit} onChange={(e) => setLimit(e.target.value)} /></label>
      <HelpTip label="Historische Preisquellen">CoinGecko liefert eine UTC-Tagesreferenz, sofern der Zugang die angeforderte Historie erlaubt. DefiLlama liefert einen belegten Kurs vor dem ersten betroffenen Ereignis des UTC-Tags; die Umrechnung nutzt einen historischen USD/EUR-Referenzkurs. Wochenenden können den vorherigen Geschäftstag verwenden, höchstens sieben Tage zurück. Kein Ausführungskurs und keine steuerliche Freigabe. Wiederholungen und Wechselkursabfragen zählen zum HTTP-Budget.</HelpTip>
      <button type="button" disabled={!Number.isInteger(Number(limit)) || Number(limit) < 1 || Number(limit) > 50} onClick={() => void command("Preisbedarf planen", async () => {
        const version = ++serial.current; const result = await readApi<Plan>(base + "/plan", undefined, query);
        if (version !== serial.current) return; setPlan(result); setPreview(undefined); requestId.current = uuid(); setExternal(false);
      })}><RefreshCw size={16} /> Preisbedarf planen</button>
    </fieldset></div>
    {busy && <p role="status"><LoaderCircle size={16} className="spin" /> {busy} läuft. Anbieterwartezeiten und lokale Vorschau können dauern.</p>}
    {error && <p role="alert" className="wsWarning">{error}</p>}{notice && <p role="status">{notice}</p>}
    {plan && !preview && <>
      <p role="status">{plan.requirements_count} fehlende Asset-Tagespreise für {plan.events_count} Ereignisse; {plan.fetchable_count} mit zugeordneter Preisquelle. Höchstens {limit} HTTP-Anfragen in diesem Abschnitt.</p>
      {!plan.requirements_count && <p>Kein offener Preisbedarf in den bereits importierten Ereignissen dieses Filters. Noch nicht freigegebene Historienvorschauen werden nicht mitgezählt. Das ist keine Vollständigkeits- oder Abgabefreigabe.</p>}
      <PriceRows rows={plan.rows} />
      {plan.rows_truncated && <p>Erste 200 Preisbedarfe. Nach Übernahme erneut planen, um weitere Abschnitte zu laden.</p>}
      <label className="checkboxLabel"><input type="checkbox" checked={external} disabled={!!busy} onChange={(e) => setExternal(e.target.checked)} /> Externe Preis- und gegebenenfalls Wechselkursabfragen ausdrücklich starten. Anbieterlimits und mögliche Tarifkosten beachten. Noch keine Übernahme in die produktive Berechnung.</label>
      <button type="button" className="wsPrimary" disabled={!!busy || !external || !plan.fetchable_count} onClick={() => void command("Kurse abrufen und Vorschau berechnen", async () => {
        const version = serial.current;
        const result = await readApi<Preview>(base + "/previews", undefined, { ...query, request_id: requestId.current, plan_sha256: plan.plan_sha256, confirm_external_request: true });
        if (version !== serial.current) return; setPreview(result); setPrices(false); setRecalculate(false); await refreshRecent();
      })}><Download size={16} /> Kurse abrufen und Vorschau berechnen</button>
    </>}
    {preview && <>
      <h3>{preview.applied ? "Preisübernahme abgeschlossen" : "Gespeicherte Preisvorschau"}</h3>
      <p>{preview.prices_count} {preview.prices_count === 1 ? "belegter EUR-Preis" : "belegte EUR-Preise"} · {preview.requests_started} {preview.requests_started === 1 ? "gestartete HTTP-Anfrage" : "gestartete HTTP-Anfragen"} · {timestamp(preview.created_at)}</p>
      <PriceRows rows={preview.rows} previewId={preview.id} />
      <a href={API_BASE + base + "/previews/" + preview.id} download>Preisvorschau und Quellen als JSON</a>
      {preview.remaining_requirements != null && <p>In der isolierten Berechnung verbleiben {preview.remaining_requirements} Preisbedarfe und {preview.review_issues_open ?? "noch unbekannte"} offene Hinweise. Keine Jahresfreigabe.</p>}
      <details className="wsTechnical"><summary>Belege und Berechnungsänderungen</summary><code>{preview.preview_sha256}</code><pre>{JSON.stringify({ before: preview.before_summary, after: preview.after_summary, changes: preview.tax_line_deltas, evidence: preview.rows.map((row) => ({ asset: row.asset, date: row.price_date, hashes: row.evidence_sha256, source: row.source })) }, null, 2)}</pre></details>
      {!preview.applied && preview.status === "ready" && <fieldset disabled={!!busy}><legend>Diese Vorschau übernehmen</legend>
        <label>Freigebende Person<input value={actor} maxLength={100} onChange={(e) => setActor(e.target.value)} /></label>
        <label className="checkboxLabel"><input type="checkbox" checked={prices} onChange={(e) => setPrices(e.target.checked)} /> Die ausgewiesenen EUR-Preise mit ihren Belegen speichern.</label>
        <label className="checkboxLabel"><input type="checkbox" checked={recalculate} onChange={(e) => setRecalculate(e.target.checked)} /> Die gezeigte Neuberechnung ausdrücklich übernehmen. Bestehende Jahres- und Referenzsnapshots bleiben erhalten; dies ist keine fachliche Jahresfreigabe.</label>
        <button type="button" className="wsPrimary" disabled={!prices || !recalculate || !actor.trim()} onClick={() => void command("Preise übernehmen", async () => {
          await readApi(base + "/previews/" + preview.id + "/apply", undefined, { preview_sha256: preview.preview_sha256, actor: actor.trim(), confirm_prices: true, confirm_recalculation: true });
          setPreview({ ...preview, applied: true }); setNotice("Preisübernahme und Neuberechnung abgeschlossen. Offene Hinweise und Steuerjahr erneut prüfen."); window.dispatchEvent(new Event("steuerreport:refresh")); await refreshRecent();
        })}><Check size={16} /> Preise und Neuberechnung übernehmen</button>
      </fieldset>}
      <button type="button" disabled={!!busy} onClick={() => { setPreview(undefined); setPlan(undefined); setExternal(false); }}>Weiteren Preisabschnitt planen</button>
    </>}
    <details className="wsTechnical"><summary>Gespeicherte Preisvorschauen</summary><button type="button" disabled={!!busy} onClick={() => void command("Vorschauen aktualisieren", refreshRecent)}><RefreshCw size={16} /> Liste aktualisieren</button>{recent.length ? recent.map((item) => <div key={item.id}><button type="button" disabled={!!busy} onClick={() => void loadPreview(item.id)}>{timestamp(item.created_at)} · {item.prices_count} Preise · {item.applied ? "übernommen" : "Vorschau"}</button></div>) : <p>Noch keine gespeicherte Preisvorschau.</p>}</details>
    <details className="wsTechnical"><summary>Preisquellen zuordnen</summary><p>Exakte Anbieter-ID verwenden. Bei Solana-Token den Mint prüfen; gleiche Symbole beweisen keine Tokenidentität. Eine Zuordnung ist keine Eigentums- oder Spamfreigabe.</p>
      <label>Vorhandene Preiszuordnung<select disabled={!!busy} value={mappings[mappingAsset] ? mappingAsset : ""} onChange={(e) => { const asset = e.target.value; setMappingAsset(asset); setCoinId(mappings[asset]?.coingecko_id || ""); setMintId(mappings[asset]?.defillama_id || ""); }}><option value="">Neue Zuordnung</option>{Object.keys(mappings).sort().map((asset) => <option key={asset}>{asset}</option>)}</select></label>
      <form onSubmit={(e) => { e.preventDefault(); void command("Preiszuordnung speichern", async () => {
        await fetchMapping({ asset: mappingAsset.toUpperCase().trim(), coingecko_id: coinId.trim() || null, defillama_id: mintId.trim() || null });
        setMappings(await readApi<typeof mappings>(base + "/mappings")); setPlan(undefined); setPreview(undefined); setNotice("Preiszuordnung gespeichert. Preisbedarf erneut planen.");
      }); }}><fieldset disabled={!!busy}><legend>Eigene Preiszuordnung</legend>
        <label>Asset-Kennung<input required maxLength={100} pattern="[A-Za-z0-9_:./-]+" value={mappingAsset} onChange={(e) => setMappingAsset(e.target.value)} /></label>
        <label>CoinGecko-ID<input pattern="[a-z0-9-]+" value={coinId} onChange={(e) => setCoinId(e.target.value)} placeholder="zum Beispiel solana" /></label>
        <label>DefiLlama-ID<input pattern="[A-Za-z0-9_-]+:[A-Za-z0-9_-]+" value={mintId} onChange={(e) => setMintId(e.target.value)} placeholder="solana:exakterMint" /></label>
        <button type="submit" disabled={!mappingAsset.trim() || (!coinId.trim() && !mintId.trim())}><Save size={16} /> Preiszuordnung speichern</button>
      </fieldset></form>
    </details>
    <section><h3>Heutige Portfolio-Marktpreise</h3><p>Nur für bereits importierte positive Ledger-Bestände. Keine rückwirkende Bewertung vergangener Ereignisse.</p><button type="button" disabled={!!busy} onClick={() => onCurrentPrices(limit, true, view.asset)}>Aktuelle Preise planen</button><button type="button" disabled={!!busy} onClick={() => { if (window.confirm("Aktuelle Preise extern abrufen, im Preis-Ledger speichern und die bestehende Pipeline neu berechnen? Keine Jahresfreigabe. Anbieterlimits und mögliche Tarifkosten beachten.")) onCurrentPrices(limit, false, view.asset); }}><Download size={16} /> Aktuelle Preise abrufen</button></section>
    <p>Fehlende Historie oder nicht unterstützte Token: Preisbelege als CSV im Expertenmodus importieren. Keine geschätzten Preise eintragen.</p>
  </section>;
}

async function fetchMapping(body: unknown) {
  const response = await fetch(API_BASE + base + "/mappings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error("mapping_failed");
}
function PriceRows({ rows, previewId }: { rows: Row[]; previewId?: string }) {
  return <div className="wsTableScroll"><table><caption>Historische EUR-Preisbedarfe und Belege</caption><thead><tr><th>Asset</th><th>Datum (UTC)</th><th>Ereignisse</th><th>EUR je Token</th><th>Preiszeit / FX-Tag</th><th>Status</th></tr></thead><tbody>{rows.map((row) => <tr key={row.asset + row.price_date}><td>{row.asset}<small>{row.provider_id || "Keine Preisquelle"}</small></td><td>{row.price_date}</td><td>{row.event_count}</td><td>{row.price_eur == null ? "Noch nicht verfügbar" : <ExactQuantity value={row.price_eur} />}</td><td>{row.priced_at ? timestamp(row.priced_at) : "Nicht belegt"}{row.fx_date && <small>USD/EUR: {row.fx_date}</small>}</td><td>{row.status === "fetched" ? "Belegt; Übernahme separat" : row.reason ? reasons[row.reason] || "Preisnachweis noch offen" : "Geplant"}{previewId && !!row.evidence_sha256?.length && <details><summary>Originalbelege</summary>{row.evidence_sha256.map((sha, i) => <p key={sha}><a href={API_BASE + base + "/previews/" + previewId + "/evidence/" + sha} download>Originalantwort {i + 1}</a></p>)}</details>}</td></tr>)}</tbody></table></div>;
}
