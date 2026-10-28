import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { AlertTriangle, ArrowUpCircle, Check, Copy, Download, ExternalLink, RefreshCw, Save } from "lucide-react";
import { API_BASE } from "./api-base";
import { timestamp } from "./workspace/resource";
import "./VersionUpdates.css";

type Channel = "stable" | "stable_rc";
export type UpdateRelease = {
  release_id: number; tag: string; version: string; channel: "stable" | "rc";
  github_prerelease: boolean; published_at: string | null; url: string; body: string;
  source_commit: string | null; image_reference: string | null; image_digest: string | null;
  open_checks: string[]; snapshot_digest: string;
};
export type UpdatesStatus = {
  installed_version: string | null;
  status: "disabled" | "not_checked" | "checking" | "up_to_date" | "update_available" | "unavailable";
  settings: { channel: Channel; automatic: boolean };
  checked_at: string | null; last_success_at: string | null; retry_at: string | null;
  stale: boolean; incomplete: boolean; message: string; releases: UpdateRelease[];
  latest: UpdateRelease | null; check_allowed: boolean; settings_writable: boolean;
};
type Handoff = { handoff_schema_version: 1; installed_version: string | null; target: UpdateRelease; text: string; created_at: string };
type StoreState = { data: UpdatesStatus | null; loading: boolean; checking: boolean; error: string };

const SIX_HOURS = 6 * 60 * 60 * 1000;
let state: StoreState = { data: null, loading: false, checking: false, error: "" };
const listeners = new Set<() => void>();
let readPending: Promise<void> | undefined;
let checkPending: Promise<void> | undefined;
let settingsPending = false;
let automaticTimer: ReturnType<typeof setTimeout> | undefined;
let nextAutomaticAt = 0;
let checkingReads = 0;
let serial = 0;

async function api<T>(path: string, method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1/updates${path}`, {
    method, signal, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  let result;
  try { result = await response.json(); } catch { throw new Error(`Ungültige Serverantwort (HTTP ${response.status}). Kein Erfolg bestätigt.`); }
  if (!response.ok || result.status === "error" || result.data == null) {
    if (path === "/handoff" && response.status === 409) throw new Error("Release-Snapshot geändert (HTTP 409). Neu prüfen und das Ziel erneut auswählen. Kein anderer Auftrag wurde erzeugt.");
    throw new Error(`Anfrage nicht bestätigt (HTTP ${response.status}). Gespeicherter Stand bleibt unverändert.`);
  }
  return result.data as T;
}

function publish(changes: Partial<StoreState>) {
  state = { ...state, ...changes };
  listeners.forEach((listener) => listener());
  scheduleAutomatic();
}

function scheduleAutomatic() {
  clearTimeout(automaticTimer);
  const data = state.data;
  if (!listeners.size || settingsPending || state.loading || state.checking || !data?.check_allowed) return;
  if (data.status === "checking") {
    if (checkingReads < 5) automaticTimer = setTimeout(() => { ++checkingReads; void loadStatus(); }, 2000);
    return;
  }
  checkingReads = 0;
  if (!data.settings.automatic) return;
  const retry = data.retry_at ? Date.parse(data.retry_at) : 0;
  const delay = Math.max(0, nextAutomaticAt - Date.now(), (Number.isFinite(retry) ? retry : 0) - Date.now());
  automaticTimer = setTimeout(() => { void checkUpdates("automatic"); }, Math.min(delay, 2147483647));
}

async function loadStatus(): Promise<void> {
  if (readPending) return readPending;
  if (checkPending) return checkPending;
  const revision = ++serial;
  const controller = new AbortController();
  publish({ loading: true });
  readPending = api<UpdatesStatus>("", "GET", undefined, controller.signal).then((data) => {
    if (revision === serial && !controller.signal.aborted) publish({ data, error: "" });
  }).catch((error) => {
    if (!controller.signal.aborted && revision === serial) publish({ error: error instanceof Error ? error.message : "Prüfstatus nicht erreichbar." });
  }).finally(() => {
    readPending = undefined;
    if (revision === serial) publish({ loading: false });
  });
  return readPending;
}

async function checkUpdates(mode: "manual" | "automatic"): Promise<void> {
  if (checkPending) return checkPending;
  const data = state.data;
  if (settingsPending || !data?.check_allowed || (mode === "automatic" && (!data.settings.automatic || Date.now() < nextAutomaticAt))) return;
  nextAutomaticAt = Date.now() + SIX_HOURS;
  checkingReads = 0;
  const revision = ++serial;
  publish({ checking: true, loading: false, error: "" });
  checkPending = api<UpdatesStatus>("/check", "POST", { mode }).then((result) => {
    if (revision === serial) publish({ data: result });
  }).catch((error) => {
    if (revision === serial) publish({ error: error instanceof Error ? error.message : "Prüfung derzeit nicht möglich." });
  }).finally(() => {
    checkPending = undefined;
    if (revision === serial) publish({ checking: false });
  });
  return checkPending;
}

const refresh = () => { void loadStatus(); };
function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) { window.addEventListener("steuerreport:refresh", refresh); void loadStatus(); }
  return () => {
    listeners.delete(listener);
    if (!listeners.size) { clearTimeout(automaticTimer); window.removeEventListener("steuerreport:refresh", refresh); }
  };
}
const getState = () => state;
function useUpdates() { return useSyncExternalStore(subscribe, getState, getState); }

function resultLabel(data: UpdatesStatus | null, error: string, checking: boolean) {
  if (checking || data?.status === "checking") return "Prüfung läuft";
  if (error || data?.status === "unavailable") return "Prüfung derzeit nicht möglich";
  if (!data) return "Prüfstatus wird geladen";
  if (data.stale) return "Letzter Prüfstand veraltet";
  if (data.incomplete) return "Prüfung unvollständig";
  if (data.status === "update_available") return data.latest?.channel === "rc" ? "Neue RC-Version verfügbar" : "Neue Version verfügbar";
  if (data.status === "up_to_date") return "Keine neuere Version gefunden";
  if (data.status === "disabled") return "Versionsprüfung gesperrt";
  return "Noch nicht geprüft";
}

export function UpdateIndicator({ onNavigate }: { onNavigate: () => void }) {
  const { data, error, checking } = useUpdates();
  const available = data?.status === "update_available" && !!data.latest;
  const label = resultLabel(data, error, checking);
  return <button type="button" className="updateIndicator" onClick={onNavigate} title={`Version & Updates: ${label}`} aria-label={`Version & Updates öffnen. Installiert: ${data?.installed_version ?? "unbekannt"}. ${label}`}>
    {available ? <ArrowUpCircle size={16} /> : <RefreshCw size={15} />}
    <span>{data?.installed_version ?? "Version unbekannt"}</span>
    {available && <span className="updateIndicatorHint">{data.latest?.tag}</span>}
    {(error || data?.stale || data?.incomplete) && <AlertTriangle size={14} aria-label="Prüfstand offen" />}
  </button>;
}

function releaseKey(release: UpdateRelease) { return `${release.release_id}:${release.snapshot_digest}`; }
function releaseUrl(value: string) {
  try { const url = new URL(value); return url.protocol === "https:" && url.hostname === "github.com" && !url.username && !url.password ? url.href : null; } catch { return null; }
}
function download(handoff: Handoff, format: "txt" | "json") {
  const blob = new Blob([format === "txt" ? handoff.text : JSON.stringify(handoff, null, 2)], { type: format === "txt" ? "text/plain;charset=utf-8" : "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = `steuerreport-update-${handoff.target.tag.replace(/[^a-zA-Z0-9._-]/g, "_")}.${format}`;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function VersionUpdates() {
  const { data, error, loading, checking } = useUpdates();
  const id = useId();
  const [channel, setChannel] = useState<Channel>("stable");
  const [automatic, setAutomatic] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [selected, setSelected] = useState<UpdateRelease | null>(null);
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "fallback">("idle");
  const manualText = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (data && !dirty) { setChannel(data.settings.channel); setAutomatic(data.settings.automatic); }
    if (!selected && data?.latest) setSelected(data.latest);
  }, [data, dirty, selected]);
  useEffect(() => { if (copyState === "fallback") { manualText.current?.focus(); manualText.current?.select(); } }, [copyState]);

  const releases = data?.releases ?? [];
  const selectedCurrent = !!selected && releases.some((release) => releaseKey(release) === releaseKey(selected));
  const locked = busy || checking || loading || !data?.settings_writable;
  async function saveSettings() {
    if (!data || locked || !dirty) return;
    setBusy(true); setActionError(""); setNotice(""); settingsPending = true; clearTimeout(automaticTimer);
    try {
      const result = await api<UpdatesStatus>("/settings", "PUT", { channel, automatic });
      ++serial; publish({ data: result, error: "", loading: false });
      setDirty(false); setNotice("Update-Einstellungen gespeichert.");
    } catch (caught) { setActionError(caught instanceof Error ? caught.message : "Speichern nicht bestätigt."); }
    finally { settingsPending = false; setBusy(false); scheduleAutomatic(); }
  }
  async function copyHandoff() {
    if (!selected || busy) return;
    setBusy(true); setActionError(""); setNotice(""); setCopyState("idle");
    try {
      let bound = handoff;
      if (!bound) {
        bound = await api<Handoff>("/handoff", "POST", { release_id: selected.release_id, snapshot_digest: selected.snapshot_digest });
        if (bound.handoff_schema_version !== 1 || bound.target.release_id !== selected.release_id || bound.target.snapshot_digest !== selected.snapshot_digest || !bound.text) {
          throw new Error("Die Antwort passt nicht zum ausgewählten Release-Snapshot. Kein Auftrag übernommen.");
        }
        setHandoff(bound);
      }
      try {
        if (!navigator.clipboard?.writeText) throw new Error("clipboard_unavailable");
        await navigator.clipboard.writeText(bound.text); setCopyState("copied");
      } catch { setCopyState("fallback"); }
    } catch (caught) { setActionError(caught instanceof Error ? caught.message : "Auftrag konnte nicht geladen werden."); }
    finally { setBusy(false); }
  }

  return <section className="versionUpdates" aria-label="Version & Updates" id="version-updates">
    <div className="panelToolbar"><h2>Version &amp; Updates</h2><button type="button" className="ghostButton" title="Gespeicherten Update-Status neu laden" aria-label="Gespeicherten Update-Status neu laden" disabled={loading || checking || busy} onClick={refresh}><RefreshCw size={16} /></button></div>
    <dl className="updatesFacts">
      <div><dt>Installierte Backend-Version</dt><dd>{data?.installed_version ?? "Unbekannt"}</dd></div>
      <div><dt>Prüfergebnis</dt><dd role="status">{resultLabel(data, error, checking)}</dd></div>
      <div><dt>Letzte erfolgreiche Prüfung</dt><dd>{timestamp(data?.last_success_at)}</dd></div>
      <div><dt>Letzter Prüfversuch</dt><dd>{timestamp(data?.checked_at)}</dd></div>
    </dl>
    {error && <p className="adminMessage error" role="alert">{error}</p>}
    {data?.message && <p className="adminInlineHelp">{data.message}</p>}
    {data?.stale && <p className="adminMessage" role="status">Der letzte erfolgreiche Stand ist veraltet und kein Nachweis für Aktualität.</p>}
    {data?.incomplete && <p className="adminMessage" role="status">Nicht alle Releases wurden bewertet. Kein vollständiger Aktualitätsnachweis.</p>}
    {data?.retry_at && <p>Erneute Prüfung frühestens: {timestamp(data.retry_at)}</p>}
    {data && !data.check_allowed && <p className="adminMessage" role="status">Versionsprüfungen sind in dieser Umgebung gesperrt. Es wird kein Abruf gestartet.</p>}
    {actionError && <p className="adminMessage error" role="alert">{actionError}</p>}
    {notice && <p className="adminMessage" role="status">{notice}</p>}
    <form className="updatesSettings" onSubmit={(event) => { event.preventDefault(); void saveSettings(); }}>
      <label htmlFor={`${id}-channel`}>Release-Kanal</label>
      <select id={`${id}-channel`} value={channel} disabled={locked} onChange={(event) => { setChannel(event.target.value as Channel); setDirty(true); setNotice(""); }}>
        <option value="stable">Stabile Versionen</option><option value="stable_rc">Stabile Versionen + RC</option>
      </select>
      <label className="updatesAutomatic"><input type="checkbox" checked={automatic} disabled={locked} onChange={(event) => { setAutomatic(event.target.checked); setDirty(true); setNotice(""); }} />Automatisch auf neue Versionen prüfen</label>
      <div className="updatesActions">
        <button type="submit" className="primaryButton" disabled={locked || !dirty}><Save size={16} /> Einstellungen speichern</button>
        <button type="button" className="ghostButton" disabled={!data?.check_allowed || checking || loading || busy || data.status === "checking"} onClick={() => { void checkUpdates("manual"); }}><RefreshCw size={16} /> Jetzt prüfen</button>
      </div>
    </form>
    {!!releases.length && <div className="updatesRelease">
      <label htmlFor={`${id}-release`}>Veröffentlichtes Zielrelease</label>
      <select id={`${id}-release`} value={selected ? releaseKey(selected) : ""} disabled={busy} onChange={(event) => {
        const release = releases.find((item) => releaseKey(item) === event.target.value);
        if (release) { setSelected(release); setHandoff(null); setCopyState("idle"); setActionError(""); }
      }}>
        {!selected && <option value="">Release auswählen</option>}
        {selected && !selectedCurrent && <option value={releaseKey(selected)}>Bisher ausgewählt: {selected.tag} (nicht im aktuellen Prüfstand)</option>}
        {releases.map((release) => <option key={releaseKey(release)} value={releaseKey(release)}>{release.tag} · {release.channel === "rc" ? "RC" : "Stabil"}</option>)}
      </select>
    </div>}
    {selected && <div className="updatesReleaseDetails" aria-label="Release-Details">
      <h3>{selected.tag} <span className="statusPill">{selected.channel === "rc" ? "RC" : "Stabil"}</span></h3>
      <dl className="updatesFacts">
        <div><dt>Veröffentlicht</dt><dd>{timestamp(selected.published_at)}</dd></div>
        <div><dt>GitHub-Prerelease-Flag</dt><dd>{selected.github_prerelease ? "Ja" : "Nein"}</dd></div>
        <div><dt>Verifizierter Quellcommit</dt><dd><code>{selected.source_commit ?? "Unbekannt / nicht verifiziert"}</code></dd></div>
        <div><dt>Image-Referenz</dt><dd><code>{selected.image_reference ?? "Nicht bestätigt"}</code></dd></div>
        <div><dt>Verifizierter Image-Digest</dt><dd><code>{selected.image_digest ?? "Unbekannt / nicht verifiziert"}</code></dd></div>
      </dl>
      {releaseUrl(selected.url) && <a href={releaseUrl(selected.url)!} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} /> Release auf GitHub</a>}
      <h4>Offene Installationsprüfungen</h4>
      {selected.open_checks.length ? <ul>{selected.open_checks.map((check, index) => <li key={index}>{check}</li>)}</ul> : <p>Keine offenen Prüfpunkte gemeldet. Keine Installationsfreigabe durch diese Anzeige.</p>}
      <h4>Versionshinweise</h4><pre className="updatesReleaseNotes">{selected.body || "Keine Versionshinweise veröffentlicht."}</pre>
      {!selectedCurrent && <p role="alert">Dieser Snapshot gehört nicht mehr zum aktuellen Prüfstand. Einen neuen Auftrag erst nach ausdrücklicher Zielauswahl anfordern. Ein bereits geladener Auftrag bleibt unverändert.</p>}
      <div className="updatesActions">
        <button type="button" className="primaryButton" disabled={busy || (!handoff && !selectedCurrent)} onClick={() => { void copyHandoff(); }}><Copy size={16} /> Updateauftrag für KI kopieren</button>
        <button type="button" className="ghostButton" disabled={!handoff || busy} onClick={() => { if (handoff) download(handoff, "txt"); }}><Download size={16} /> TXT herunterladen</button>
        <button type="button" className="ghostButton" disabled={!handoff || busy} onClick={() => { if (handoff) download(handoff, "json"); }}><Download size={16} /> JSON herunterladen</button>
      </div>
    </div>}
    {handoff && <div className="updatesHandoff">
      <h3>Geladener Auftrag: {handoff.target.tag}</h3>
      {copyState === "copied" && <p role="status"><Check size={16} /> Auftrag in die Zwischenablage kopiert.</p>}
      {copyState === "fallback" && <p role="alert">Zwischenablage nicht verfügbar oder nicht freigegeben. Nicht kopiert. Den vollständigen Auftrag hier manuell auswählen und kopieren.</p>}
      <label htmlFor={`${id}-handoff`}>Vollständiger Updateauftrag</label><textarea id={`${id}-handoff`} ref={manualText} readOnly rows={10} value={handoff.text} spellCheck={false} />
    </div>}
  </section>;
}
