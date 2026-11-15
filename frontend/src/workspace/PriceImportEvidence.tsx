import { useEffect, useRef, useState } from "react";
import { Download, FileSearch, LoaderCircle } from "lucide-react";
import { API_BASE } from "../api-base";
import { ExactQuantity } from "./Ui";
import { ApiReadError, canonicalDecimal, compactQuantity, readApi, timestamp } from "./resource";

export type PreparedPriceBinding = { price_id: string; price_fingerprint: string; asset: string; price_eur: string; stored_reference_at: string };
type Original = { sha256: string; byte_length: number; filename?: string | null };
type Evidence = { status: string; integrity_scope: string; preview_id: string; price_id: string; price_fingerprint: string; asset: string; price_eur: string; stored_reference_at: string; strict_eligible: boolean; admission_status: string; originals: Original[] };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const sha = /^[a-f0-9]{64}$/;
const instant = (value: unknown) => typeof value === "string" && /(?:Z|\+00:00)$/.test(value)
  && Number.isFinite(Date.parse(value)) ? value.replace(/\+00:00$/, "Z") : null;
const errors: Record<string, string> = {
  historical_price_binding_missing: "Älteres Vorschauformat ohne konkrete Preis-ID-Bindung. Der Archivstand bleibt unverändert.",
  historical_price_binding_invalid: "Preiszeile und Importbeleg stimmen nicht mehr überein.",
  historical_price_binding_ambiguous: "Die Originalzuordnung ist nicht eindeutig.",
  historical_price_not_applied: "Die Preisvorschau wurde noch nicht ausdrücklich übernommen.",
  historical_price_apply_decision_invalid: "Der gespeicherte Übernahmenachweis passt nicht zu dieser Vorschau.",
  historical_price_evidence_changed: "Die Originalbelege konnten nicht unverändert bestätigt werden.",
  historical_price_reader_limit_exceeded: "Die Beleg-Lesegrenze ist erreicht. Jahresumfang oder Originalpaket administrativ prüfen.",
  historical_price_not_found: "Ein benötigter Originalbeleg ist nicht mehr verfügbar.",
  historical_price_point_not_found: "Diese Preis-ID ist im aktuellen Datenbestand nicht vorhanden.",
  historical_price_store_not_initialized: "Die Anwendungsdatenbank ist noch nicht initialisiert.",
};

export function PriceImportEvidence({ previewId, version, bindings }: { previewId: string; version?: number; bindings?: PreparedPriceBinding[] }) {
  const rows = Array.isArray(bindings) ? bindings.filter((row) => row && uuid.test(row.price_id) && sha.test(row.price_fingerprint)
    && typeof row.asset === "string" && canonicalDecimal(row.price_eur) !== null && instant(row.stored_reference_at) !== null) : [];
  const supported = version === 1 && uuid.test(previewId) && rows.length > 0 && rows.length === bindings?.length
    && new Set(rows.map((row) => row.price_id)).size === rows.length;
  const [selected, setSelected] = useState("");
  const [status, setStatus] = useState<"initial" | "loading" | "ready" | "error">("initial");
  const [result, setResult] = useState<Evidence>();
  const [error, setError] = useState("");
  const controller = useRef<AbortController>();
  const serial = useRef(0);
  const key = JSON.stringify([previewId, version, bindings]);
  useEffect(() => {
    controller.current?.abort(); ++serial.current; setSelected(""); setStatus("initial"); setResult(undefined); setError("");
    return () => { controller.current?.abort(); ++serial.current; };
  }, [key]);
  const change = (id: string) => {
    controller.current?.abort(); ++serial.current; setSelected(id); setStatus("initial"); setResult(undefined); setError("");
  };
  const load = async () => {
    if (!supported || !rows.some((row) => row.price_id === selected) || status === "loading") return;
    const request = new AbortController(); controller.current?.abort(); controller.current = request;
    const sequence = ++serial.current;
    setStatus("loading"); setResult(undefined); setError("");
    try {
      const data = await readApi<Evidence>(`/api/v1/prices/historical/previews/${previewId}/prices/${selected}/evidence`, request.signal);
      if (request.signal.aborted || sequence !== serial.current) return;
      const binding = rows.find((row) => row.price_id === selected)!;
      if (!data || data.preview_id !== previewId || data.price_id !== selected || data.price_fingerprint !== binding.price_fingerprint
        || data.asset !== binding.asset || canonicalDecimal(data.price_eur) !== canonicalDecimal(binding.price_eur)
        || instant(data.stored_reference_at) !== instant(binding.stored_reference_at)
        || data.status !== "verified_import_binding" || data.integrity_scope !== "selected_price_only"
        || data.strict_eligible !== false || data.admission_status !== "not_reviewed"
        || !Array.isArray(data.originals) || !data.originals.length || data.originals.some((ref) => !ref || !sha.test(ref.sha256)
          || !Number.isSafeInteger(ref.byte_length) || ref.byte_length <= 0 || ref.byte_length > 2 * 1024 * 1024)
        || new Set(data.originals.map((ref) => ref.sha256)).size !== data.originals.length) throw new Error("invalid_evidence");
      setResult(data); setStatus("ready");
    } catch (failure) {
      if (!request.signal.aborted && sequence === serial.current) {
        setError(failure instanceof ApiReadError ? errors[failure.code || ""] || "Belegprüfung nicht verfügbar. Erneut prüfen." : "Die Belegantwort konnte nicht eindeutig bestätigt werden.");
        setStatus("error");
      }
    }
  };
  return <details className="wsTechnical">
    <summary>Originalzuordnung der übernommenen Preise</summary>
    {!supported ? <p>Für diesen Archivstand fehlt eine unterstützte konkrete Preis-ID-Bindung. Es wurde keine neue Zuordnung ergänzt.</p> : <>
      <label>Übernommene Preiszeile<select value={selected} onChange={(event) => change(event.target.value)}>
        <option value="">Preiszeile auswählen</option>
        {rows.map((row) => <option key={row.price_id} value={row.price_id}>{row.asset} · {compactQuantity(row.price_eur)} EUR · {timestamp(row.stored_reference_at)}</option>)}
      </select></label>
      <button type="button" disabled={!selected || status === "loading"} onClick={() => void load()}><FileSearch size={16} /> Importbelege prüfen</button>
      {status === "loading" && <p role="status"><LoaderCircle size={16} className="spin" /> Importbelegprüfung läuft.</p>}
      {status === "error" && <p role="alert" className="wsInlineWarning">{error}</p>}
      {status === "ready" && result && <div role="group" aria-label="Originalbindung der Preiszeile">
        <p role="status">Importbindung dieser Preis-ID bestätigt. Keine Preiszeit-, Methoden- oder Jahresfreigabe.</p>
        <p>{result.asset}: <ExactQuantity value={result.price_eur} /> EUR · gespeicherte Referenzzeit: {timestamp(result.stored_reference_at)}</p>
        <p>Beobachtungs- und Veröffentlichungszeiten: nicht geprüft.</p>
        <ul className="wsPriceImportOriginals">{result.originals.map((ref) => <li key={ref.sha256}><a className="wsButton" download href={`${API_BASE}/api/v1/prices/historical/previews/${previewId}/prices/${selected}/evidence/${ref.sha256}`}>
          <Download size={16} /> <span>{ref.filename || `Original ${ref.sha256.slice(0, 12)}`}</span>
        </a><small>SHA-256: <code>{ref.sha256}</code> · {ref.byte_length} Byte</small></li>)}</ul>
      </div>}
    </>}
  </details>;
}
