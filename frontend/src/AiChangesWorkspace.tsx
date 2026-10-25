import { Fragment, useEffect, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Download, Pencil, Play, RefreshCw, RotateCcw, Save, Trash2, X } from "lucide-react";
import { API_BASE } from "./api-base";

type Kind = "event" | "price";
type Query = { kind: Kind; year: number; asset: string; source: string; offset: number; limit: number };
type Row = { kind: Kind; target_id: string; revision: string; values: Record<string, string | null>; provenance: Record<string, string | number | null> };
type Context = { context_sha256: string; total: number; rows: Row[] };
type Change = { kind: Kind; target_id: string; before_sha256: string; patch: Record<string, string | null>; reason: string; evidence_ref: string };
type Draft = { summary: string; changes: Change[] };
type Preview = { preview_sha256: string; selected_indices: number[]; before_summary: Record<string, unknown>; after_summary: Record<string, unknown>; tax_line_deltas: unknown[]; reconciliation_status: string; pipeline: { allow_export: boolean; review_issues_open: number; tax_lines: number } };
type ChangeSet = { change_set_id: string; status: string; draft: Draft; before: Row[]; origin: string; model: string | null; created_at: string; preview: Preview | null; approval: Record<string, unknown> | null; parent_id: string | null };
const FIELDS: Record<Kind, string[]> = { event: ["event_type", "event_time", "asset", "quantity", "quote_asset", "quote_quantity", "fee_asset", "fee_quantity", "account", "wallet"], price: ["price_eur", "confidence"] };
const ERRORS: Record<string, string> = {
  ai_change_storage_insufficient: "Zu wenig freier Speicher fuer eine sichere Berechnungskopie.",
  ai_change_calculation_failed: "Neuberechnung fehlgeschlagen. Es wurden keine Fachdaten geaendert.",
  ai_correction_target_missing: "Eine gespeicherte Korrektur verweist auf eine fehlende Datenzeile. Quellenabgleich erforderlich.",
  ai_correction_replay_conflict: "Eine gespeicherte Korrektur widerspricht dem aktuellen Quellstand. Manuelle Pruefung erforderlich.",
  ai_correction_target_protected: "Diese Daten tragen eine freigegebene Korrektur. Vor dem Entfernen zuerst deren Ruecknahme pruefen.",
  ai_request_invalid: "Eingaben und Pflichtfelder pruefen.", ai_change_not_found: "Vorschlag nicht gefunden.",
  ai_change_stale: "Daten oder Methoden wurden geaendert. Daten neu laden und Vorschlag erneut pruefen.",
  ai_change_context_stale: "Datenauswahl ist veraltet. Daten erneut laden.", ai_config_revision_conflict: "KI-Konfiguration wurde geaendert. KI-Einstellungen neu laden.",
  ai_change_state_conflict: "Vorschlag wurde zwischenzeitlich bearbeitet oder bereits abgeschlossen.",
  ai_change_preview_required: "Eine aktuelle, passende Vorschau ist erforderlich.",
  ai_change_prepared_mismatch: "Vorbereiteter Datenstand stimmt nicht mehr ueberein. Neue Vorschau erforderlich.",
  ai_change_preview_missing: "Vorbereiteter Datenstand fehlt. Neue Vorschau erforderlich.",
  ai_change_field_not_allowed: "Dieses Feld darf nicht ueber die KI geaendert werden.",
  ai_change_value_invalid: "Feldwert oder zusammengehoerige Felder ungueltig.",
  ai_change_decimal_invalid: "Zahl ungueltig oder ausserhalb der unterstuetzten Genauigkeit.",
  ai_change_timezone_required: "Zeitangaben benoetigen UTC oder einen ausdruecklichen Zeitzonenoffset.",
  ai_change_no_difference: "Mindestens eine echte Aenderung je Position ist erforderlich.",
  ai_change_selection_invalid: "Auswahl ist ungueltig oder nicht mehr im freigegebenen Datenkontext.",
  ai_change_target_missing: "Betroffene Datenzeile fehlt.", ai_change_duplicate_target: "Jede Datenzeile darf nur einmal vorkommen.",
  ai_change_context_too_large: "Datenkontext zu gross. Weniger Zeilen auswaehlen.",
  ai_change_invalid_model_output: "Das Modell lieferte keinen gueltigen Aenderungsvorschlag. Es wurde nichts uebernommen.",
  ai_change_model_truncated: "Modellantwort unvollstaendig. Antwortlimit erhoehen oder weniger Zeilen auswaehlen.",
  ai_change_derived_price_readonly: "Abgeleitete Preise nicht direkt aendern; zugrunde liegendes Ereignis korrigieren.",
  ai_change_generation_running: "Dieser KI-Auftrag laeuft bereits. Verlauf spaeter aktualisieren.",
  ai_change_generation_failed: "Dieser KI-Auftrag ist fehlgeschlagen. Keine automatische Wiederholung.",
  ai_task_external_not_confirmed: "Cloud-Versand wurde nicht freigegeben.", external_ai_disabled: "Cloud-Zugriffe sind deaktiviert.",
  local_ai_disabled: "Lokale KI ist deaktiviert.", ai_auth_failed: "KI-Anbieter lehnt den API-Key ab.",
  ai_credit_required: "KI-Anbieter verlangt Guthaben.", ai_rate_limited: "Anfragelimit des KI-Anbieters erreicht.",
  ai_timeout: "Zeitlimit erreicht. Vor erneutem Auftrag Verlauf aktualisieren.", ai_connection_failed: "KI-Anbieter nicht erreichbar.",
  reconciliation_failed: "Einzelpositionen und Summen stimmen nicht ueberein. Keine Uebernahme.",
};

function eur(value: unknown): string {
  const raw = String(value ?? "0");
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(raw);
  if (!match) return raw;
  const fraction = match[3] || "";
  const cents = BigInt(match[2]) * 100n + BigInt((fraction + "00").slice(0, 2)) + (fraction.length > 2 && fraction[2] >= "5" ? 1n : 0n);
  return `${match[1] && cents ? "-" : ""}${(cents / 100n).toLocaleString("de-DE")},${String(cents % 100n).padStart(2, "0")} EUR`;
}

function EffectSummary({ value }: { value: Record<string, unknown> }) {
  const tax = value.tax as Record<string, Record<string, string | number>>;
  const derivatives = value.derivatives as Record<string, Record<string, string | number>>;
  return <><table className="aiEffectTable"><tbody>
    {Object.entries(tax).map(([year, totals]) => <Fragment key={year}><tr><th colSpan={2}>{year} / {totals.lines} Steuerzeilen</th></tr>
      <tr><th>Anschaffungskosten</th><td>{eur(totals.acquisition_cost_eur)}</td></tr><tr><th>Verauesserungserloese</th><td>{eur(totals.disposal_proceeds_eur)}</td></tr>
      <tr><th>Gewinn/Verlust</th><td><strong>{eur(totals.gain_loss_eur)}</strong></td></tr></Fragment>)}
    {Object.entries(derivatives).map(([year, totals]) => <tr key={year}><th>{year} / Derivate</th><td>{eur(totals.pnl_eur)}</td></tr>)}
    <tr><th>Fehlende FIFO-Zuordnung</th><td>{String(value.unmatched_disposals)}</td></tr>
  </tbody></table><details><summary>Exakte Summen</summary><pre>{JSON.stringify(value, null, 2)}</pre></details></>;
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1/ai${path}`, { method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const value = await response.json();
  if (!response.ok || value.status === "error") throw new Error(ERRORS[value.detail] || "Aenderungsauftrag fehlgeschlagen. Verlauf pruefen.");
  return value.data as T;
}

export function AiChangesWorkspace({ providerRevision, connectionAllowed, cloud }: { providerRevision: string; connectionAllowed: boolean; cloud: boolean }) {
  const [query, setQuery] = useState<Query>({ kind: "event", year: 2025, asset: "", source: "", offset: 0, limit: 20 });
  const [context, setContext] = useState<Context | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [instruction, setInstruction] = useState("");
  const [external, setExternal] = useState(false);
  const [history, setHistory] = useState<ChangeSet[]>([]);
  const [active, setActive] = useState<ChangeSet | null>(null);
  const [indices, setIndices] = useState<number[]>([]);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [actor, setActor] = useState("");
  const [rationale, setRationale] = useState("");
  const [checked, setChecked] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const gate = useRef(false);
  useEffect(() => { let live = true; void api<ChangeSet[]>("/changes").then((rows) => { if (live) setHistory(rows); }).catch(() => { if (live) setError("Aenderungsverlauf konnte nicht geladen werden."); }); return () => { live = false; }; }, []);
  useEffect(() => { setExternal(false); }, [providerRevision]);
  const choose = (item: ChangeSet) => { setActive(item); setIndices(item.preview?.selected_indices || item.draft.changes.map((_, index) => index)); setEditing(null); setChecked(false); setConfirmed(false); };
  async function act(action: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true; setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Aenderungsauftrag fehlgeschlagen."); }
    finally { gate.current = false; setBusy(false); }
  }
  async function refresh() { setHistory(await api<ChangeSet[]>("/changes")); }
  async function load(next = query) { const value = await api<Context>("/data-context", next); setQuery(next); setContext(value); setSelected([]); setExternal(false); }
  function queryField(patch: Partial<Query>) { setQuery({ ...query, ...patch, offset: 0 }); setContext(null); setSelected([]); setExternal(false); }
  const rows = context?.rows.filter((row) => selected.includes(row.target_id)) || [];
  const editable = !!active && ["proposed", "previewed"].includes(active.status);
  const previewMatches = !!active?.preview && JSON.stringify([...indices].sort((a, b) => a - b)) === JSON.stringify(active.preview.selected_indices);
  function editChange(index: number, patch: Partial<Change>) { if (editing) setEditing({ ...editing, changes: editing.changes.map((change, at) => at === index ? { ...change, ...patch } : change) }); }
  function manual() {
    setActive(null); setChecked(false); setConfirmed(false);
    setEditing({ summary: "Manuelle Datenkorrektur", changes: rows.map((row) => ({ kind: row.kind, target_id: row.target_id, before_sha256: row.revision,
      patch: { [row.kind === "event" ? "event_type" : "price_eur"]: row.values[row.kind === "event" ? "event_type" : "price_eur"] }, reason: "", evidence_ref: row.values.raw_object_id ? "raw:" + row.values.raw_object_id : "" })) });
  }

  return <section className="aiChanges" aria-label="KI-Datenkorrekturen">
    <h3>Datenkorrekturen</h3>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">Auftrag wird verarbeitet.</p>}
    <form onSubmit={(event) => { event.preventDefault(); void act(() => load()); }}>
      <fieldset disabled={busy}><legend>Datenauswahl</legend><div className="formGrid">
        <label>Datenart<select aria-label="Korrektur-Datenart" value={query.kind} onChange={(event) => queryField({ kind: event.target.value as Kind })}><option value="event">Transaktionen</option><option value="price">Preise</option></select></label>
        <label>Jahr<input aria-label="Korrektur-Jahr" type="number" min={2000} max={2100} value={query.year} onChange={(event) => queryField({ year: Number(event.target.value) })} /></label>
        <label>Asset<input aria-label="Korrektur-Asset" value={query.asset} onChange={(event) => queryField({ asset: event.target.value })} /></label>
        <label>Quelle<input aria-label="Korrektur-Quelle" value={query.source} onChange={(event) => queryField({ source: event.target.value })} /></label>
      </div></fieldset><div className="buttonRow"><button type="submit" disabled={busy}><RefreshCw size={16} /> Daten laden</button>
      {context && <><span>{context.total} Treffer / {selected.length} ausgewaehlt</span><button type="button" title="Vorherige Seite" aria-label="Vorherige Datenseite" disabled={busy || !query.offset} onClick={() => void act(() => load({ ...query, offset: Math.max(0, query.offset - query.limit) }))}><ChevronLeft size={16} /></button>
      <button type="button" title="Naechste Seite" aria-label="Naechste Datenseite" disabled={busy || query.offset + query.limit >= context.total} onClick={() => void act(() => load({ ...query, offset: query.offset + query.limit }))}><ChevronRight size={16} /></button></>}
      </div>
    </form>
    {context && <>
      <div className="aiChangesTable"><table><thead><tr><th><input type="checkbox" aria-label="Alle angezeigten Zeilen auswaehlen" checked={!!context.rows.length && selected.length === context.rows.length} disabled={busy} onChange={(event) => { setSelected(event.target.checked ? context.rows.map((row) => row.target_id) : []); setExternal(false); }} /></th><th>Zeit / Asset</th><th>Menge / Preis</th><th>Quelle / Beleg</th></tr></thead>
        <tbody>{context.rows.map((row) => <tr key={row.target_id}><td><input type="checkbox" aria-label={`Datenzeile ${row.target_id} auswaehlen`} checked={selected.includes(row.target_id)} disabled={busy} onChange={(event) => { setSelected(event.target.checked ? [...selected, row.target_id] : selected.filter((id) => id !== row.target_id)); setExternal(false); }} /></td>
          <td>{row.values.event_time || row.values.priced_at}<br /><strong>{row.values.asset}</strong><br />{row.values.event_type}</td><td>{row.values.quantity || row.values.price_eur}{row.kind === "price" ? " EUR" : ""}</td><td>{row.values.source}<br />{row.provenance.filename}<details><summary>Datensatz</summary><pre>{JSON.stringify(row, null, 2)}</pre></details></td></tr>)}</tbody></table></div>
      {!context.rows.length && <p role="status">Keine passenden Datenzeilen.</p>}
      <form onSubmit={(event) => { event.preventDefault(); if (context) void act(async () => {
        const item = await api<ChangeSet>("/changes/generate", { request_id: crypto.randomUUID().replaceAll("-", ""), query, selected_ids: selected, context_sha256: context.context_sha256,
          instruction, confirm_external: cloud && external, provider_revision: providerRevision }); choose(item); setExternal(false); await refresh(); setNotice("KI-Vorschlaege erstellt.");
      }); }}>
        <label>Korrekturauftrag<textarea aria-label="KI-Korrekturauftrag" rows={4} maxLength={4000} value={instruction} disabled={busy} onChange={(event) => { setInstruction(event.target.value); setExternal(false); }} /></label>
        <details><summary>Freizugebender Datenkontext ({rows.length})</summary><pre>{JSON.stringify(rows, null, 2)}</pre></details>
        {cloud && <label className="checkboxLabel"><input type="checkbox" checked={external} disabled={busy} onChange={(event) => setExternal(event.target.checked)} /> Auftrag und ausgewaehlte Daten an den KI-Anbieter senden</label>}
        <div className="buttonRow"><button type="submit" disabled={busy || !connectionAllowed || !selected.length || selected.length > 25 || instruction.trim().length < 10 || (cloud && !external)}><Play size={16} /> KI-Vorschlaege erstellen</button>
          <button type="button" disabled={busy || !selected.length || selected.length > 25} onClick={manual}><Pencil size={16} /> Manuell vorbereiten</button></div>
      </form>
    </>}
    <div className="panelToolbar"><h3>Aenderungsverlauf</h3><button type="button" title="Aenderungsverlauf aktualisieren" aria-label="Aenderungsverlauf aktualisieren" disabled={busy} onClick={() => void act(refresh)}><RefreshCw size={16} /></button></div>
    <label>Vorschlag<select aria-label="Aenderungsvorschlag" value={active?.change_set_id || ""} disabled={busy} onChange={(event) => { const id = event.target.value; if (id) void act(async () => choose(await api<ChangeSet>(`/changes/${encodeURIComponent(id)}`))); else setActive(null); }}>
      <option value="">Vorschlag auswaehlen</option>{history.map((item) => <option key={item.change_set_id} value={item.change_set_id}>{new Date(item.created_at).toLocaleString("de-DE")} / {item.status} / {item.draft.summary}</option>)}
    </select></label>
    {active && <>
      <div className="panelToolbar"><strong>{active.draft.summary}</strong><span>{({ proposed: "Vorgeschlagen", previewed: "Vorschau bereit", applied: "Uebernommen", rejected: "Abgelehnt" } as Record<string, string>)[active.status]}</span></div>
      <small>{active.model || active.origin} / {active.change_set_id}</small>
      <div className="aiChangesTable"><table><thead><tr><th>Auswahl</th><th>Feld / Vorher</th><th>Vorschlag</th><th>Grund / Beleg</th></tr></thead><tbody>{active.draft.changes.map((change, index) => {
        const before = active.before[index];
        return <tr key={change.target_id}><td><input type="checkbox" aria-label={`Aenderung ${index + 1} auswaehlen`} checked={indices.includes(index)} disabled={busy || !editable} onChange={(event) => { setIndices(event.target.checked ? [...indices, index] : indices.filter((value) => value !== index)); setChecked(false); setConfirmed(false); }} /><br /><small>{change.target_id}</small></td>
          <td>{Object.keys(change.patch).map((field) => <div key={field}><strong>{field}</strong><br />{before?.values[field] ?? "null"}</div>)}</td><td>{Object.entries(change.patch).map(([field, value]) => <div key={field}><strong>{field}</strong><br />{value ?? "null"}</div>)}</td><td>{change.reason}<br /><code>{change.evidence_ref}</code></td></tr>;
      })}</tbody></table></div>
      <div className="buttonRow"><a href={`${API_BASE}/api/v1/ai/changes/${encodeURIComponent(active.change_set_id)}/audit.json`} download><Download size={16} /> Audit-JSON</a>
        {editable && <><button type="button" disabled={busy} onClick={() => setEditing(structuredClone(active.draft))}><Pencil size={16} /> Vorschlag bearbeiten</button>
          <button type="button" disabled={busy || !indices.length || !!editing} onClick={() => void act(async () => { choose(await api<ChangeSet>(`/changes/${active.change_set_id}/preview`, { selected_indices: indices })); await refresh(); })}><Check size={16} /> Vorschau berechnen</button>
          <button type="button" disabled={busy} onClick={() => { if (window.confirm("Diesen Vorschlag ablehnen?")) void act(async () => { choose(await api<ChangeSet>(`/changes/${active.change_set_id}/reject`, {})); await refresh(); }); }}><X size={16} /> Ablehnen</button></>}
      </div>
      {active.preview && <><h3>Berechnete Auswirkungen</h3><span role="status">{previewMatches ? "Vorschau passend zur Auswahl" : "Vorschau veraltet"} / {active.preview.reconciliation_status} / {active.preview.pipeline.review_issues_open} offene Pruefpunkte / Export {active.preview.pipeline.allow_export ? "freigegeben" : "blockiert"}</span>
        <div className="aiChangesEffects"><div><strong>Vorher</strong><EffectSummary value={active.preview.before_summary} /></div><div><strong>Nachher</strong><EffectSummary value={active.preview.after_summary} /></div></div>
        <details><summary>Steuerzeilen-Aenderungen ({active.preview.tax_line_deltas.length})</summary><pre>{JSON.stringify(active.preview.tax_line_deltas, null, 2)}</pre></details>
      </>}
    </>}
    {editing && <form onSubmit={(event) => { event.preventDefault(); void act(async () => { const path = active ? `/changes/${active.change_set_id}/revise` : "/changes"; choose(await api<ChangeSet>(path, editing)); await refresh(); }); }}>
      <h3>Vorschlag bearbeiten</h3><label>Zusammenfassung<input aria-label="Korrektur-Zusammenfassung" required minLength={3} maxLength={2000} value={editing.summary} onChange={(event) => setEditing({ ...editing, summary: event.target.value })} /></label>
      {editing.changes.map((change, index) => <fieldset key={change.target_id} disabled={busy}><legend>Position {index + 1}: {change.target_id}</legend>
        {Object.entries(change.patch).map(([field, value]) => <div className="aiPatchField" key={field}><label>{field}<input aria-label={`Position ${index + 1} ${field}`} value={value ?? ""} disabled={value === null} onChange={(event) => editChange(index, { patch: { ...change.patch, [field]: event.target.value } })} /></label>
          <label className="checkboxLabel"><input type="checkbox" checked={value === null} onChange={(event) => editChange(index, { patch: { ...change.patch, [field]: event.target.checked ? null : "" } })} /> null</label>
          <button type="button" title="Feld entfernen" aria-label={`Position ${index + 1} Feld ${field} entfernen`} onClick={() => editChange(index, { patch: Object.fromEntries(Object.entries(change.patch).filter(([name]) => name !== field)) })}><Trash2 size={16} /></button></div>)}
        <label>Weiteres Feld<select aria-label={`Position ${index + 1} Feld hinzufuegen`} value="" onChange={(event) => { const field = event.target.value; if (field) editChange(index, { patch: { ...change.patch, [field]: "" } }); }}><option value="">Feld hinzufuegen</option>{FIELDS[change.kind].filter((field) => !(field in change.patch)).map((field) => <option key={field} value={field}>{field}</option>)}</select></label>
        <label>Begruendung<textarea aria-label={`Position ${index + 1} Begruendung`} required minLength={10} maxLength={2000} value={change.reason} onChange={(event) => editChange(index, { reason: event.target.value })} /></label>
        <label>Belegstelle<input aria-label={`Position ${index + 1} Belegstelle`} required minLength={3} maxLength={1000} value={change.evidence_ref} onChange={(event) => editChange(index, { evidence_ref: event.target.value })} /></label>
      </fieldset>)}
      <div className="buttonRow"><button type="submit" disabled={busy}><Save size={16} /> Neue Vorschlagsrevision speichern</button><button type="button" disabled={busy} title="Bearbeitung verwerfen" aria-label="Bearbeitung verwerfen" onClick={() => setEditing(null)}><X size={16} /></button></div>
    </form>}
    {active && (editable || active.status === "applied") && <form onSubmit={(event) => { event.preventDefault(); if (editable && active.preview) void act(async () => {
      choose(await api<ChangeSet>(`/changes/${active.change_set_id}/apply`, { preview_sha256: active.preview!.preview_sha256, actor, rationale, confirm: confirmed, evidence_checked: checked })); await refresh(); setNotice("Datenbank und Auswertungen aktualisiert.");
    }); }}><h3>{active.status === "applied" ? "Ruecknahme" : "Menschliche Freigabe"}</h3>
      {editable && <label>Freigebende Person<input aria-label="Freigebende Person" required minLength={2} maxLength={128} value={actor} disabled={busy} onChange={(event) => setActor(event.target.value)} /></label>}
      <label>Pruefvermerk<textarea aria-label="Korrektur-Pruefvermerk" required minLength={10} maxLength={2000} value={rationale} disabled={busy} onChange={(event) => setRationale(event.target.value)} /></label>
      {editable ? <><label className="checkboxLabel"><input type="checkbox" checked={checked} disabled={busy} onChange={(event) => setChecked(event.target.checked)} /> Originalbelege und Auswirkungen selbst geprueft</label>
        <label className="checkboxLabel"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} /> Ausgewaehlte Aenderungen verbindlich in die Datenbank uebernehmen</label>
        <button type="submit" className="primaryButton" disabled={busy || !previewMatches || !checked || !confirmed || actor.trim().length < 2 || rationale.trim().length < 10 || !!editing}><Check size={16} /> Freigegebene Aenderungen uebernehmen</button></>
        : <button type="button" disabled={busy || rationale.trim().length < 10} onClick={() => void act(async () => { choose(await api<ChangeSet>(`/changes/${active.change_set_id}/revert`, { reason: rationale })); await refresh(); })}><RotateCcw size={16} /> Ruecknahme vorbereiten</button>}
    </form>}
  </section>;
}
