import { useState, type FormEvent } from "react";
import { Plus, Save, X } from "lucide-react";

type Query = {
  year: number | null;
  assets: string[];
  provider: "defillama" | "coingecko";
  max_requests: number;
  max_total_requests: number | null;
  strategy: "standard" | "automatic";
  scope: "tax_required" | "all_observed";
};
type Target = {
  asset: string;
  price_date: string;
  status: string;
  identity_basis?: string;
  mint?: string | null;
  mints?: string[];
};
type FxQuote = { date: string; pair: "USD/EUR" | "EUR/USD"; rate: string };

const isoDateTime = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function originalFile(file: File, sourceName: string, sourceReference: string, observedAt: string) {
  if (!file.size || file.size > 2 * 1024 * 1024) throw new Error("Belegdateien müssen zwischen 1 Byte und 2 MiB groß sein.");
  if (!isoDateTime.test(observedAt) || Number.isNaN(Date.parse(observedAt))) {
    throw new Error("Der Erfassungszeitpunkt benötigt einen vollständigen Zeitstempel mit Zeitzone.");
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return {
    filename: file.name,
    media_type: file.type || "application/octet-stream",
    source_name: sourceName,
    source_reference: sourceReference || null,
    source_observed_at: observedAt,
    content_base64: btoa(binary),
  };
}

export function ManualHistoricalPriceEvidence({
  target,
  query,
  planSha256,
  busy,
  onSubmit,
  onClose,
}: {
  target: Target;
  query: Query;
  planSha256: string;
  busy: boolean;
  onSubmit: (body: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}) {
  const [currency, setCurrency] = useState<"EUR" | "USD">("EUR");
  const [priceValue, setPriceValue] = useState("");
  const [pricedAt, setPricedAt] = useState("");
  const [priceSource, setPriceSource] = useState("");
  const [priceReference, setPriceReference] = useState("");
  const [priceObservedAt, setPriceObservedAt] = useState("");
  const [priceFile, setPriceFile] = useState<File>();
  const [fxSource, setFxSource] = useState("");
  const [fxReference, setFxReference] = useState("");
  const [fxObservedAt, setFxObservedAt] = useState("");
  const [fxFile, setFxFile] = useState<File>();
  const [quotes, setQuotes] = useState<FxQuote[]>([{ date: "", pair: "USD/EUR", rate: "" }]);
  const [formError, setFormError] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError("");
    if (!priceFile) {
      setFormError("Bitte den unveränderten Originalbeleg für den Tokenpreis auswählen.");
      return;
    }
    try {
      const priceEvidence = await originalFile(priceFile, priceSource, priceReference, priceObservedAt);
      const fxEvidence = currency === "USD" && fxFile
        ? await originalFile(fxFile, fxSource, fxReference, fxObservedAt)
        : null;
      const fxObservations = currency === "USD" && fxFile && fxSource
        ? quotes.filter((quote) => quote.date && quote.rate).map((quote) => ({
          date: quote.date,
          base: quote.pair === "USD/EUR" ? "USD" : "EUR",
          quote: quote.pair === "USD/EUR" ? "EUR" : "USD",
          rate: quote.rate,
          source: fxSource,
        }))
        : [];
      await onSubmit({
        request_id: uuid(),
        query,
        plan_sha256: planSha256,
        asset: target.asset,
        price_date: target.price_date,
        price_value: priceValue,
        price_currency: currency,
        price_unit: "currency_per_asset",
        priced_at: pricedAt,
        price_evidence: priceEvidence,
        fx_evidence: fxEvidence,
        fx_observations: fxObservations,
      });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Der Beleg konnte nicht gelesen werden.");
    }
  };

  return <section className="wsManualPrice" aria-label="Manuellen historischen Preis belegen">
    <header>
      <div>
        <h3>Manuellen Preisbeleg prüfen</h3>
        <p>{target.asset} · {target.price_date} UTC · Identität: {target.mint || target.identity_basis || "nicht ausgewiesen"}</p>
      </div>
      <button type="button" title="Formular schließen" aria-label="Formular schließen" disabled={busy} onClick={onClose}><X size={16} /></button>
    </header>
    <p>Nur für diese offene Planzeile. Preis je 1 {target.asset}; der Kurszeitpunkt muss am selben UTC-Tag und nicht nach dem ersten Ereignis liegen. Die Eingabe erzeugt zunächst nur eine isolierte Vorschau, keinen Anbieterabruf und keine Preisänderung in der Datenbank.</p>
    <form onSubmit={(event) => void submit(event)}>
      <fieldset disabled={busy}>
        <legend>Tokenpreis</legend>
        <label>Belegter Wert<input required type="text" inputMode="decimal" value={priceValue} onChange={(event) => setPriceValue(event.target.value)} placeholder="z. B. 12.3456" /></label>
        <label>Währung<select value={currency} onChange={(event) => setCurrency(event.target.value as "EUR" | "USD")}><option value="EUR">EUR direkt belegt</option><option value="USD">USD mit FX-Beleg</option></select></label>
        <label>Preiszeitpunkt mit Zeitzone<input required type="text" value={pricedAt} onChange={(event) => setPricedAt(event.target.value)} placeholder="2024-06-02T11:30:00+00:00" /></label>
        <label>Quelle des Preisbelegs<input required maxLength={200} value={priceSource} onChange={(event) => setPriceSource(event.target.value)} /></label>
        <label>Fundstelle, URL oder Seite<input maxLength={500} value={priceReference} onChange={(event) => setPriceReference(event.target.value)} /></label>
        <label>Beleg erfasst am, mit Zeitzone<input required type="text" value={priceObservedAt} onChange={(event) => setPriceObservedAt(event.target.value)} placeholder="2024-06-02T12:30:00+00:00" /></label>
        <label>Unveränderte Preisbelegdatei<input required type="file" onChange={(event) => setPriceFile(event.target.files?.[0])} /></label>
      </fieldset>
      {currency === "USD" && <fieldset disabled={busy}>
        <legend>Historischer USD/EUR- oder EUR/USD-Beleg</legend>
        <p>Es gilt die vorhandene Referenzregel: jüngster belegter Kurs am oder vor dem Preisdatum, höchstens sieben Kalendertage alt. Zukunfts-, veraltete, fehlende und widersprüchliche Kurse blockieren die Vorschau.</p>
        <label>Quelle des FX-Belegs<input maxLength={200} value={fxSource} onChange={(event) => setFxSource(event.target.value)} /></label>
        <label>Fundstelle, URL oder Seite<input maxLength={500} value={fxReference} onChange={(event) => setFxReference(event.target.value)} /></label>
        <label>FX-Beleg erfasst am, mit Zeitzone<input type="text" value={fxObservedAt} onChange={(event) => setFxObservedAt(event.target.value)} placeholder="2024-06-02T12:30:00+00:00" /></label>
        <label>Unveränderte FX-Belegdatei<input type="file" onChange={(event) => setFxFile(event.target.files?.[0])} /></label>
        <div className="wsManualFxRows">
          {quotes.map((quote, index) => <fieldset key={index}>
            <legend>FX-Beobachtung {index + 1}</legend>
            <label>Referenztag<input type="date" value={quote.date} onChange={(event) => setQuotes((current) => current.map((item, i) => i === index ? { ...item, date: event.target.value } : item))} /></label>
            <label>Quotierung<select value={quote.pair} onChange={(event) => setQuotes((current) => current.map((item, i) => i === index ? { ...item, pair: event.target.value as FxQuote["pair"] } : item))}><option value="USD/EUR">EUR je USD</option><option value="EUR/USD">USD je EUR</option></select></label>
            <label>Originalkurs<input type="text" inputMode="decimal" value={quote.rate} onChange={(event) => setQuotes((current) => current.map((item, i) => i === index ? { ...item, rate: event.target.value } : item))} /></label>
            {quotes.length > 1 && <button type="button" aria-label={`FX-Beobachtung ${index + 1} entfernen`} title="FX-Beobachtung entfernen" onClick={() => setQuotes((current) => current.filter((_, i) => i !== index))}><X size={16} /> Entfernen</button>}
          </fieldset>)}
          <button type="button" onClick={() => setQuotes((current) => [...current, { date: "", pair: "USD/EUR", rate: "" }])}><Plus size={16} /> FX-Beobachtung ergänzen</button>
        </div>
      </fieldset>}
      {formError && <p role="alert" className="wsWarning">{formError}</p>}
      <div className="wsActionFooter">
        <button type="submit" className="wsPrimary" disabled={busy || !priceValue || !pricedAt || !priceSource || !priceObservedAt || !priceFile}><Save size={16} /> Vorschau erstellen</button>
        <button type="button" disabled={busy} onClick={onClose}>Abbrechen</button>
      </div>
    </form>
  </section>;
}
