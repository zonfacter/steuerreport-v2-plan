import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { API_BASE } from "../api-base";

const key = "steuerreport:current-price-request";
const eventName = "steuerreport:current-price-request-changed";
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
function remembered() {
  try { const value = sessionStorage.getItem(key); return value && uuid.test(value) ? value : ""; } catch { return ""; }
}
export function rememberCurrentPriceRequest(id: string) {
  try { sessionStorage.setItem(key, id); } catch { /* Storage is optional; the event still carries the ID. */ }
  window.dispatchEvent(new CustomEvent(eventName, { detail: id }));
}
type Status = { status: "recorded" | "unknown_or_running" | "not_found"; explanation: string;
  warnings?: { message: string }[];
  result?: { pipeline_status: string; imported_prices: number; failed: number; skipped: number; stored_price_ids: string[] } | null };
export function CurrentPriceRequestStatus() {
  const [id, setId] = useState(remembered);
  const [result, setResult] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  function change(value: string) {
    request.current?.abort(); setBusy(false); setResult(null); setError(null); setId(value);
  }
  useEffect(() => {
    const update = (event: Event) => change(String((event as CustomEvent).detail));
    window.addEventListener(eventName, update);
    return () => { request.current?.abort(); window.removeEventListener(eventName, update); };
  }, []);
  async function check() {
    if (!uuid.test(id) || busy) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(null); setResult(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/prices/backfill/current-portfolio/status`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: id }), signal: controller.signal,
      });
      if (!response.ok) throw new Error("status_unknown");
      const body = await response.json();
      if (!body.data || !["recorded", "unknown_or_running", "not_found"].includes(body.data.status)) throw new Error("status_unknown");
      if (!controller.signal.aborted) setResult({ ...body.data, warnings: body.warnings ?? [] });
    } catch {
      if (!controller.signal.aborted) setError("Auftragsstatus nicht sicher lesbar. Vor einem neuen Abruf den Preisbestand prüfen.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return <section aria-label="Portfolio-Preisauftrag prüfen">
    <h3>Portfolio-Preisauftrag prüfen</h3>
    <label>Auftragskennung<input value={id} onChange={(event) => change(event.target.value.trim())} autoComplete="off" spellCheck={false} /></label>
    <button className="statusButton" type="button" disabled={busy || !uuid.test(id)} onClick={() => void check()} title="Liest nur den gespeicherten Auftrag; kein Anbieterabruf und keine Neuberechnung"><RefreshCw size={16} /> {busy ? "Status wird gelesen" : "Auftragsstatus lesen"}</button>
    <div aria-live="polite">
      {error && <p className="wsInlineWarning">{error}</p>}
      {result && <><p>{result.explanation}</p>{result.result && <p>Damals gespeichert: {result.result.imported_prices} Preise. Fehlgeschlagen: {result.result.failed}. Übersprungen: {result.result.skipped}. {result.result.pipeline_status === "completed" ? "Pipeline damals abgeschlossen." : result.result.pipeline_status === "failed" ? "Pipeline fehlgeschlagen; Folgen unbekannt oder teilweise." : "Pipeline nicht gestartet."}</p>}{result.warnings?.map((warning, index) => <p className="wsInlineWarning" key={index}>{warning.message}</p>)}</>}
    </div>
  </section>;
}
