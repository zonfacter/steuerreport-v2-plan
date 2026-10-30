import { useEffect, useRef, useState } from "react";
import { Check, LoaderCircle, RefreshCw, Upload } from "lucide-react";
import { ApiReadError, readApi } from "./resource";

type Facts = {
  event_time_utc: string; event_type: string; asset: string; quantity: string;
  quote_asset?: string | null; quote_quantity?: string | null;
  fee_asset?: string | null; fee_quantity?: string | null;
};
type Candidate = {
  csv_row_number: number; csv_provider_record_id?: string | null; symbol?: string | null;
  api_record_identity?: string | null; csv_financial_sha256?: string | null; api_financial_sha256?: string | null;
  csv_financial_facts?: Facts | null; api_financial_facts?: Facts | null;
  decision_id?: string | null; decision_state: "none" | "active" | "revoked";
  status: "matchable" | "missing_stable_id" | "symbol_missing" | "api_record_missing" | "csv_id_ambiguous" | "api_id_ambiguous" | "financial_digest_conflict" | "financial_shape_unsupported" | "already_decided" | "match_revoked";
};
type Preview = { connection_id: string; file_sha256: string; source_batch_id?: string | null; preview_sha256: string; candidates: Candidate[] };
type Props = {
  base: string; jobId: string; jobStatus: "ready" | "succeeded"; sourceLabel: string;
  actor: string; setActor: (value: string) => void;
};

const statusLabels: Record<Candidate["status"], string> = {
  matchable: "Exakte Übereinstimmung zur manuellen Prüfung",
  missing_stable_id: "Stabile Trade-ID fehlt oder ist mehrdeutig",
  symbol_missing: "Handelspaar fehlt oder ist mehrdeutig",
  api_record_missing: "Kein passender API-Fill mit dieser ID",
  csv_id_ambiguous: "Trade-ID und Handelspaar kommen mehrfach in der CSV vor",
  api_id_ambiguous: "Trade-ID und Handelspaar kommen mehrfach in der API-Historie vor",
  financial_digest_conflict: "Finanzdaten weichen ab; kein Abgleich möglich",
  financial_shape_unsupported: "Finanzform nicht sicher vergleichbar",
  already_decided: "Bereits ausdrücklich abgeglichen",
  match_revoked: "Abgleich widerrufen; erneute Übernahme bleibt gesperrt",
};

function encodeFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Die CSV-Datei konnte nicht gelesen werden."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.readAsDataURL(file);
  });
}

function errorText(error: unknown) {
  const code = error instanceof ApiReadError ? error.code : undefined;
  const known: Record<string, string> = {
    history_match_api_evidence_not_persisted: "Der API-Auftrag ist noch nicht importiert und diese CSV-Datei ist noch nicht als Rohbeleg gebunden. Importiere die CSV zuerst oder schließe den API-Historienimport ab und prüfe erneut.",
    history_match_both_sources_already_imported: "CSV und API-Historie wurden bereits importiert. Der Abgleich ändert keine gespeicherten Ereignisse; prüfe die betroffene Historie über den bestehenden Korrekturablauf.",
    history_match_revoke_after_import: "Der Abgleich ist bereits in einen abgeschlossenen Import eingeflossen. Ein Widerruf würde die gespeicherten Ereignisse nicht zurücksetzen; eine gesonderte Korrekturprüfung ist erforderlich.",
    history_match_preview_stale: "Die Belege haben sich seit der Vorschau geändert. Erzeuge eine neue Vorschau und prüfe sie erneut.",
    history_match_already_decided: "Dieses Paar wurde bereits entschieden. Lade die Vorschau neu.",
    history_match_not_exact: "Die Zeile erfüllt die exakten Abgleichbedingungen nicht. Es wurde nichts zugeordnet.",
    history_match_already_revoked: "Dieser Abgleich wurde bereits widerrufen.",
    history_match_revoked_review_required: "Der Abgleich wurde widerrufen. Eine erneute Übernahme ist gesperrt und benötigt eine gesonderte Prüfung.",
  };
  if (code && known[code]) return known[code];
  return error instanceof Error ? error.message : "Abgleich fehlgeschlagen. Belege prüfen und erneut versuchen.";
}

export function BinanceSpotMatchReview({ base, jobId, jobStatus, sourceLabel, actor, setActor }: Props) {
  const [file, setFile] = useState<File>();
  const [encoded, setEncoded] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [rationale, setRationale] = useState("");
  const [armed, setArmed] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const activeRequest = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => () => activeRequest.current?.abort(), []);

  const selectFile = (selected?: File) => {
    generation.current += 1;
    activeRequest.current?.abort();
    setFile(undefined); setEncoded(""); setPreview(undefined); setRationale(""); setArmed(""); setNotice(""); setError("");
    if (!selected) return;
    if (!/\.csv$/i.test(selected.name) || selected.size === 0 || selected.size > 25 * 1024 * 1024) {
      setError("Eine einzelne, nicht leere CSV-Datei bis 25 MiB auswählen."); return;
    }
    setFile(selected);
  };

  const upload = async (knownContent?: string) => {
    if (!file) throw new Error("Zuerst eine CSV-Datei auswählen.");
    const content = knownContent || encoded || await encodeFile(file);
    if (!content) throw new Error("Die CSV-Datei enthält keine lesbaren Daten.");
    if (!encoded) setEncoded(content);
    return { filename: file.name, content_base64: content };
  };

  const loadPreview = async (controller: AbortController, token: number, knownContent?: string) => {
    const source = await upload(knownContent);
    const value = await readApi<Preview>(`${base}/jobs/${encodeURIComponent(jobId)}/binance-spot-matches/preview`, controller.signal, source);
    if (!controller.signal.aborted && generation.current === token) setPreview(value);
    return value;
  };

  const previewFile = async () => {
    if (!file || busy) return;
    const token = generation.current;
    const controller = new AbortController(); activeRequest.current?.abort(); activeRequest.current = controller;
    setBusy("preview"); setError(""); setNotice(""); setPreview(undefined); setArmed("");
    try { await loadPreview(controller, token); }
    catch (caught) { if (!controller.signal.aborted && generation.current === token) setError(errorText(caught)); }
    finally { if (generation.current === token) setBusy(""); }
  };

  const submitDecision = async (candidate: Candidate, revoke = false) => {
    if (!file || !preview || !encoded || busy || !actor.trim() || rationale.trim().length < 8) return;
    const confirmationKey = `${revoke ? "revoke" : "match"}:${candidate.csv_row_number}`;
    if (armed !== confirmationKey) return;
    if (!revoke && candidate.status !== "matchable") return;
    if (revoke && (!candidate.decision_id || candidate.decision_state !== "active"
      || (jobStatus === "succeeded" && !!preview.source_batch_id))) return;
    const token = generation.current;
    const controller = new AbortController(); activeRequest.current?.abort(); activeRequest.current = controller;
    setBusy(`${revoke ? "revoke" : "match"}:${candidate.csv_row_number}`); setError(""); setNotice("");
    try {
      const source = { filename: file.name, content_base64: encoded };
      if (revoke) {
        await readApi(`${base}/spot-matches/${encodeURIComponent(candidate.decision_id!)}/revoke`, controller.signal,
          { actor: actor.trim(), rationale: rationale.trim() });
        setNotice(`Abgleich für CSV-Zeile ${candidate.csv_row_number} widerrufen. Das ändert keine bereits gespeicherten Finanzereignisse.`);
      } else {
        if (!candidate.api_record_identity) throw new Error("Die API-Belegidentität fehlt; keine Zuordnung angelegt.");
        await readApi(`${base}/jobs/${encodeURIComponent(jobId)}/binance-spot-matches`, controller.signal, {
          ...source, preview_sha256: preview.preview_sha256, csv_row_number: candidate.csv_row_number,
          api_record_identity: candidate.api_record_identity, actor: actor.trim(), rationale: rationale.trim(), confirm_match: true,
        });
        setNotice(`Explizite Prüfentscheidung für CSV-Zeile ${candidate.csv_row_number} gespeichert. Es wurde kein Import automatisch gestartet.`);
      }
      setArmed("");
      await loadPreview(controller, token, encoded);
    } catch (caught) {
      if (!controller.signal.aborted && generation.current === token) setError(errorText(caught));
    } finally { if (generation.current === token) setBusy(""); }
  };

  const canDecide = jobStatus === "ready" ? Boolean(preview?.source_batch_id) : !preview?.source_batch_id;
  const matchedCount = preview?.candidates.filter((candidate) => candidate.decision_state === "active").length ?? 0;

  return <section className="hiMatch" aria-label="Binance-Spot-CSV/API-Abgleich">
    <div className="hiMatchHeading"><h3>Binance-Spot-CSV/API-Abgleich</h3><span>Manuelle Einzelentscheidung</span></div>
    <p>Verglichen werden nur stabile Trade-ID, Handelspaar und die angezeigten Finanzwerte einschließlich Zeit, Gegenwert und Gebühr. Ähnlichkeit bei Datum oder Betrag reicht nicht. Kein automatisches Zusammenführen.</p>
    {jobStatus === "ready"
      ? <p className="wsMuted">Die API-Historie ist noch nicht importiert. Für eine Entscheidung muss die CSV bereits mit derselben Verbindung als Rohbeleg vorliegen. Ist sie es noch nicht, importiere sie zuerst und lade danach die Vorschau erneut.</p>
      : <p className="wsMuted">Die API-Historie ist bereits importiert. Nach dem Abgleich muss die CSV separat über den geführten Dateiimport mit derselben Verbindung geprüft und importiert werden.</p>}
    <label>Binance-Spot-CSV<input type="file" accept=".csv,text/csv" disabled={!!busy} onChange={(event) => { selectFile(event.target.files?.[0]); event.currentTarget.value = ""; }} /></label>
    {file && <p className="wsMuted">{file.name} · {(file.size / 1024).toLocaleString("de-DE", { maximumFractionDigits: 1 })} KiB · bleibt unverändert im Browser, bis du die Vorschau ausdrücklich startest.</p>}
    <div className="hiActions"><button type="button" disabled={!file || !!busy} onClick={() => void previewFile()}>{busy === "preview" ? <LoaderCircle size={16} className="spin" /> : <RefreshCw size={16} />} Vorschau vergleichen</button></div>
    {error && <p className="wsResource error" role="alert">{error}</p>}
    {notice && <p className="wsResource" role="status">{notice}</p>}
    {preview && <>
      <p className="wsMuted">Datei-SHA-256: <code>{preview.file_sha256}</code> · Verbindung: {sourceLabel} · {preview.candidates.length} CSV-Datenzeilen geprüft</p>
      {preview.source_batch_id && <p className="wsMuted">Vorhandener CSV-Rohbeleg: <code>{preview.source_batch_id}</code></p>}
      {!canDecide && <p className="wsInlineWarning" role="status">Die Voraussetzungen für eine neue Zuordnung sind noch nicht erfüllt. {jobStatus === "ready" ? "CSV-Rohbeleg zuerst über den geführten Import an dieselbe Verbindung binden." : "Die Datei ist bereits importiert; eine neue Match-Entscheidung würde vorhandene Ereignisse nicht korrigieren."}</p>}
      {!!preview.candidates.length && <>
        <label>Prüfende Person (wird protokolliert, derzeit nicht serverseitig authentifiziert)<input autoComplete="off" maxLength={120} value={actor} onChange={(event) => { setActor(event.target.value); setArmed(""); }} /></label>
        <label>Begründung für die folgende Einzelentscheidung<textarea rows={3} maxLength={2000} value={rationale} onChange={(event) => { setRationale(event.target.value); setArmed(""); }} /><small>Mindestens 8 Zeichen; konkret die geprüften Originalbelege beschreiben.</small></label>
      </>}
      <div className="hiMatchList">{preview.candidates.map((candidate) => {
        const action = candidate.status === "already_decided" ? "revoke" : "match";
        const actionKey = `${action}:${candidate.csv_row_number}`;
        const canRevoke = candidate.status === "already_decided" && candidate.decision_state === "active"
          && (jobStatus === "ready" || (jobStatus === "succeeded" && !preview.source_batch_id));
        const enabled = action === "match" ? candidate.status === "matchable" && canDecide : canRevoke;
        return <article key={`${candidate.csv_row_number}:${candidate.api_record_identity || "none"}`} className="hiMatchRow">
          <div className="hiJobHeading"><strong>CSV-Zeile {candidate.csv_row_number} · {candidate.symbol || "Handelspaar fehlt"} · Trade-ID {candidate.csv_provider_record_id || "fehlt"}</strong><span>{statusLabels[candidate.status]}</span></div>
          {(candidate.csv_financial_facts || candidate.api_financial_facts) && <div className="hiMatchFacts">
            <FinancialFacts title="CSV-Beleg" facts={candidate.csv_financial_facts} />
            <FinancialFacts title="API-Fill" facts={candidate.api_financial_facts} />
          </div>}
          {candidate.csv_financial_sha256 && candidate.api_financial_sha256 && <details><summary>Finanz-Digests</summary><p>CSV: <code>{candidate.csv_financial_sha256}</code></p><p>API: <code>{candidate.api_financial_sha256}</code></p></details>}
          {candidate.decision_id && <p className="wsMuted">Entscheidungs-ID: <code>{candidate.decision_id}</code></p>}
          {enabled && <>
            <label className="hiCheck"><input type="checkbox" checked={armed === actionKey} disabled={!!busy || !actor.trim() || rationale.trim().length < 8} onChange={(event) => setArmed(event.target.checked ? actionKey : "")} />
              <span>{action === "match" ? `Ich habe CSV-Zeile ${candidate.csv_row_number} und den angezeigten API-Fill anhand der Originalbelege geprüft; ich bestätige ausschließlich diese Zuordnung.` : `Ich bestätige den Widerruf für CSV-Zeile ${candidate.csv_row_number}.`}</span></label>
            <button type="button" className={action === "match" ? "wsPrimary" : ""} disabled={!!busy || armed !== actionKey || !actor.trim() || rationale.trim().length < 8} onClick={() => void submitDecision(candidate, action === "revoke")}>
              {busy === `${action}:${candidate.csv_row_number}` ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}
              {action === "match" ? "Diese Zeile ausdrücklich abgleichen" : "Abgleich widerrufen"}
            </button>
          </>}
          {candidate.status === "already_decided" && jobStatus === "succeeded" && <p className="wsInlineWarning">{preview.source_batch_id
            ? "API-Historie und CSV sind bereits gespeichert. Ein Widerruf macht den erfolgten Import nicht rückgängig; dafür ist eine gesonderte Prüfung und Korrektur nötig."
            : "Die API-Historie ist bereits importiert, die CSV aber noch nicht. Ein Widerruf ändert die API-Ereignisse nicht; ein CSV-Import mit diesem Überschneidungsfall bleibt bis zur gesonderten Prüfung gesperrt."}</p>}
          {candidate.status === "match_revoked" && <p className="wsInlineWarning">Der Widerruf bleibt append-only gespeichert. Dieser Kandidat kann über diesen Ablauf nicht erneut aktiviert werden.</p>}
        </article>;
      })}</div>
      {matchedCount > 0 && jobStatus === "succeeded" && <div className="hiActions"><a className="wsButton" href="#import" onClick={() => {
        try {
          window.sessionStorage.setItem("steuerreport:import-source-once", "binance");
          window.sessionStorage.setItem("steuerreport:import-connection-once", preview.connection_id);
        } catch { /* The import page remains usable with manual source selection. */ }
      }}><Upload size={16} /> CSV mit gleicher Verbindung importieren</a></div>}
      {matchedCount > 0 && jobStatus === "ready" && <p className="wsMuted">Die Match-Entscheidung ist gespeichert. Sie verändert den Prüfstand. Berechne im ausgewählten Auftrag zuerst die Vorschau erneut aus den gespeicherten Originalbelegen (kein erneuter Anbieterabruf); prüfe danach den neuen Vorschauhash und bestätige Import und Neuberechnung ausdrücklich. Der abgeglichene API-Fill wird dabei als bereits durch die CSV belegte Buchung behandelt.</p>}
    </>}
  </section>;
}

function FinancialFacts({ title, facts }: { title: string; facts?: Facts | null }) {
  if (!facts) return <section><strong>{title}</strong><p className="wsMuted">Finanzform nicht verfügbar.</p></section>;
  const direction = facts.event_type === "trade" ? facts.quantity.startsWith("-") ? "Verkauf / Abgang" : "Kauf / Zugang" : facts.event_type;
  return <section><strong>{title}</strong><dl>
    <div><dt>Zeitpunkt UTC</dt><dd>{facts.event_time_utc}</dd></div>
    <div><dt>Richtung</dt><dd>{direction}</dd></div>
    <div><dt>Menge</dt><dd>{facts.quantity} {facts.asset}</dd></div>
    <div><dt>Gegenwert</dt><dd>{facts.quote_quantity == null ? "Nicht ausgewiesen" : `${facts.quote_quantity} ${facts.quote_asset || "?"}`}</dd></div>
    <div><dt>Gebühr</dt><dd>{facts.fee_quantity == null ? "Nicht ausgewiesen" : `${facts.fee_quantity} ${facts.fee_asset || "?"}`}</dd></div>
  </dl></section>;
}
