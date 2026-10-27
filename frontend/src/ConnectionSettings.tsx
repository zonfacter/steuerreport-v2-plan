import { useEffect, useId, useRef, useState } from "react";
import { Pencil, Plus, RefreshCw, Save, ShieldCheck, Square, Trash2, X } from "lucide-react";
import { API_BASE } from "./api-base";
import { HelpTip } from "./Help";
import { useResource, readApi, timestamp } from "./workspace/resource";
import "./connection-settings.css";
import "./request-limit-settings.css";

export function useAdminEnvironment() {
  const resource = useResource<{ synthetic_preview: boolean; read_only: boolean }>(
    "admin-environment", (signal) => readApi("/api/v1/workspace/environment", signal)
  );
  return { ...resource, locked: resource.status !== "ready" || resource.data?.read_only !== false || resource.data?.synthetic_preview === true };
}

export function AdminEnvironmentState({ environment }: { environment: ReturnType<typeof useAdminEnvironment> }) {
  if (environment.status === "error") return <p role="alert" className="adminMessage error">Der Betriebsmodus konnte nicht geprüft werden. Änderungen bleiben gesperrt. <button type="button" className="ghostButton" onClick={environment.reload}>Erneut prüfen</button></p>;
  if (environment.status !== "ready") return <p role="status" className="adminMessage">Betriebsmodus wird geprüft. Änderungen sind noch gesperrt.</p>;
  if (environment.data?.synthetic_preview) return <p role="note" className="adminMessage">Demo-/Testmodus mit synthetischen Daten. Speichern, Entfernen, Verbindungstests und externe Abrufe sind hier deaktiviert.</p>;
  if (environment.data?.read_only) return <p role="note" className="adminMessage">Diese Installation ist schreibgeschützt. Einstellungen und externe Aktionen sind gesperrt.</p>;
  return null;
}

type Credentials = { status: "missing" | "incomplete" | "configured" | "unavailable" | "invalid"; has_api_key: boolean; has_api_secret: boolean; has_passphrase: boolean; encrypted: boolean; updated_at: string | null };
type Connection = { id: string; provider: string; label: string; account: string; subaccount: string; origin: string; budget_group: string; credentials: Credentials; last_test_at: string | null; last_sync_at: string | null; last_error_code: string | null; tax_source_activated: false };
type LegacyConnection = Pick<Connection, "id" | "provider" | "label" | "origin" | "budget_group" | "credentials">;
type Connections = { connections: Connection[]; legacy_connections: LegacyConnection[]; vault_ready: boolean; automatic_migration: false };
type ConnectionJob = { id: string; connection_id: string; provider: string; action: "test" | "sync"; status: "queued" | "running" | "succeeded" | "failed" | "cancelled"; created_at: string; updated_at: string; deadline_at: string; error_code: string | null; cancel_requested: boolean; slot_reserved?: boolean; snapshot_count: number; effect: string };
type Jobs = { jobs: ConnectionJob[]; max_active: number; max_retained: number };
const PROVIDERS: Record<string, string> = { binance: "Binance", bitget: "Bitget", coinbase: "Coinbase", pionex: "Pionex" };
const CREDENTIAL_LABELS: Record<Credentials["status"], string> = { missing: "Zugangsdaten fehlen", incomplete: "Zugangsdaten unvollständig", configured: "Zugangsdaten hinterlegt · noch kein Verbindungsnachweis", unavailable: "Zugangsdaten derzeit nicht entschlüsselbar", invalid: "Zugangsdaten ungültig" };
const JOB_LABELS: Record<ConnectionJob["status"], string> = { queued: "Eingeplant · wartet auf Ausführung / Kontingent", running: "Läuft · mögliche Budgetwartezeit siehe Abrufsteuerung", succeeded: "Erfolgreich beendet", failed: "Fehlgeschlagen", cancelled: "Abgebrochen" };
const GROUP_PATTERN = /^(provider|ip|project|account|endpoint|budget):[a-z0-9][a-z0-9_.:-]{0,63}$/;
const CONNECTION_GROUP_PATTERN = /^(ip:global|budget:[a-z0-9_-]{1,48})$/;
function errorLabel(code?: string | null) {
  const known: Record<string, string> = {
    external_http_unavailable: "Der zentrale Abrufkoordinator ist nicht verfügbar. Administration prüfen lassen; es wurde kein unkontrollierter Ersatzabruf gestartet.",
    secret_vault_key_unavailable: "Der Vault-Schlüssel ist nicht verfügbar. Sichere Schlüsselbereitstellung administrativ prüfen.",
    encrypted_secret_vault_required: "Der verschlüsselte Vault ist nicht bereit. Zuerst die sichere Speicherung einrichten.",
    secret_vault_key_required: "Ein verschlüsselter Vault mit verfügbarem Schlüssel ist erforderlich. Sichere Persistenz unter Installation administrativ einrichten.",
    connection_credentials_incomplete: "Die Zugangsdaten sind unvollständig. Benötigten API-Key, Secret und gegebenenfalls Passphrase ergänzen.",
    connection_credentials_unavailable: "Die Zugangsdaten sind nicht entschlüsselbar. Vault-Schlüssel und persistente Schlüsseldatei administrativ prüfen.",
    connection_credentials_invalid: "Die Zugangsdaten sind ungültig. Den Lesezugang im Anbieterportal prüfen und hier ausdrücklich ersetzen.",
    connection_payload_invalid: "Die Verbindungsangaben sind ungültig. Kontoname, unterstützten Anbieter und Budgetgruppe prüfen.",
    connection_provider_mismatch: "Der Anbieter einer bestehenden Verbindung darf nicht ausgetauscht werden. Dafür eine getrennte Verbindung anlegen.",
    connection_job_queue_full: "Die lokale Auftragswarteschlange ist voll. Bestehende Aufträge abwarten oder ausdrücklich abbrechen.",
    connection_effect_confirmation_required: "Die konkrete Wirkung des externen Abrufs muss ausdrücklich bestätigt werden.",
    connection_job_deadline_exceeded: "Die Auftragsfrist wurde erreicht. Abrufumfang und lokale Budgetwartezeiten prüfen.",
    connection_job_interrupted: "Der Auftrag wurde unterbrochen. Lokalen Auftragsstatus und Koordinator prüfen, bevor ein neuer Abruf gestartet wird.",
    connection_worker_unavailable: "Die lokale Auftragsverarbeitung ist nicht verfügbar. Administration prüfen lassen.",
    cex_authentication_failed: "Der Anbieter hat den Zugang abgewiesen. Key, Berechtigungen, IP-Freigabe und gegebenenfalls Passphrase im Anbieterportal prüfen.",
    cex_request_timeout: "Der Anbieteraufruf hat sein Zeitlimit erreicht. Lokale Wartezeiten und Auftragsfrist prüfen.",
    connection_provider_request_failed: "Der Anbieterabruf ist fehlgeschlagen. Anbieterstatus, Lesezugang und lokale Budgetsteuerung prüfen.",
    connection_demo_read_only: "Die Demo-/Testumgebung sperrt schreibende und externe Aktionen.",
    connection_service_unavailable: "Die Verbindungsverwaltung ist derzeit nicht verfügbar. Administration prüfen lassen.",
    connection_limiter_unavailable: "Der Abrufkoordinator ist ausgefallen. Neue Requests bleiben gesperrt; Koordinator und persistentes Zustandsverzeichnis administrativ prüfen.",
    connection_request_cancelled: "Der Abruf wurde abgebrochen. Bereits gespeicherte Ergebnisse bleiben dem Auftrag zugeordnet.",
    connection_budget_capacity_exceeded: "Der Request passt nicht in das lokale Budget. Endpunktkosten und Kostenbudget prüfen, statt den Abruf unlimitiert zu wiederholen.",
    connection_retry_not_allowed: "Eine automatische Wiederholung ist für diesen Aufruf nicht zulässig. Ursache und sichere Wiederholbarkeit prüfen.",
    authentication_failed: "Der Anbieter hat den Zugang abgewiesen. Key, Berechtigungen und gegebenenfalls Passphrase im Anbieterportal prüfen.",
    rate_limited: "Der Anbieter begrenzt den Abruf. Wartezeit und wirksames Budget unter Abrufsteuerung prüfen.",
    cancelled: "Der Auftrag wurde abgebrochen.", deadline_exceeded: "Die Auftragsfrist wurde erreicht. Abrufumfang und lokale Wartezeiten prüfen.",
    connection_not_found: "Diese Verbindung wurde nicht gefunden. Die Verbindungsliste neu laden.",
    connection_job_already_active: "Für diese Verbindung läuft bereits ein Auftrag. Den vorhandenen Auftrag beobachten.",
    request_limits_revision_conflict: "Das Limitprofil wurde inzwischen geändert. Neu laden und Änderungen erneut prüfen."
  };
  return code && known[code] ? known[code] : "Die Aktion konnte nicht abgeschlossen werden. Zugang, Berechtigungen und lokale Abrufsteuerung prüfen; es wurde kein Erfolg bestätigt.";
}
async function adminRequest<T>(path: string, method: string, body?: unknown): Promise<T> {
  let response: Response;
  try { response = await fetch(API_BASE + "/api/v1/admin/" + path, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) }); }
  catch { throw new Error("Das Backend ist nicht erreichbar. Es wurde kein Erfolg bestätigt."); }
  const result = await response.json().catch(() => null);
  if (!response.ok || result?.status === "error") {
    if (response.status === 409 && result?.detail === "request_limits_active_leases_conflict") throw new Error("Aktive Abrufe oder Reservierungen zuerst beenden; Konfiguration danach erneut speichern. Es wurde nichts geändert und kein automatischer Neustart ausgelöst.");
    if (response.status === 409) throw new Error(result?.detail === "request_limits_preset_conflict" ? "Das Startprofil kollidiert mit abweichenden vorhandenen Profilen oder Tarifgrenzen. Es wurde nichts angewendet. Vorschau neu laden und die betroffenen Profile einzeln prüfen." : "Die Einstellungen oder Aufträge haben sich geändert. Neu laden und den aktuellen Stand prüfen. Ungespeicherte Eingaben bleiben bis zum Neuladen erhalten.");
    if (response.status === 422) throw new Error("Die Angaben sind ungültig. Pflichtfelder, Budgetgruppen und Zahlenbereiche prüfen; Zugangsdaten werden nicht in Fehlermeldungen wiedergegeben.");
    throw new Error(errorLabel(typeof result?.detail === "string" ? result.detail : result?.errors?.[0]?.code ?? result?.error?.code));
  }
  return result.data as T;
}
function activeJob(job: ConnectionJob) { return job.status === "queued" || job.status === "running" || job.slot_reserved === true; }

export function ConnectionSettings() {
  const environment = useAdminEnvironment();
  const connections = useResource<Connections>("admin-connections", (signal) => readApi("/api/v1/admin/connections", signal));
  const jobs = useResource<Jobs>("admin-connection-jobs", (signal) => readApi("/api/v1/admin/connections/jobs", signal));
  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const [provider, setProvider] = useState("binance");
  const [label, setLabel] = useState("");
  const [account, setAccount] = useState("");
  const [subaccount, setSubaccount] = useState("");
  const [budgetGroup, setBudgetGroup] = useState("ip:global");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [validation, setValidation] = useState<Record<string, string>>({});
  const formRef = useRef<HTMLHeadingElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const polls = useRef(0);
  const id = useId();
  const locked = environment.locked || busy || connections.status !== "ready";
  const vaultReady = connections.data?.vault_ready === true;
  const list = connections.data?.connections ?? [];
  const runningJobs = jobs.data?.jobs.filter(activeJob) ?? [];
  useEffect(() => {
    if (!runningJobs.length || environment.locked || jobs.status !== "ready" || polls.current >= 100) return;
    const timer = window.setTimeout(() => { polls.current += 1; jobs.reload(); connections.reload(); }, 3000);
    return () => window.clearTimeout(timer);
  }, [jobs.data, jobs.status, environment.locked, runningJobs.length, jobs.reload, connections.reload]);
  useEffect(() => { if (editing) formRef.current?.focus(); }, [editing]);
  const changed = editing === "new" ? !!(label || account || subaccount || apiKey || apiSecret || passphrase || budgetGroup !== "ip:global") : !!editing && (label !== editing.label || account !== editing.account || subaccount !== editing.subaccount || budgetGroup !== editing.budget_group || !!apiKey || !!apiSecret || !!passphrase);
  function close(force = false) {
    if (!force && changed && !window.confirm("Ungespeicherte Verbindungsänderungen verwerfen?")) return;
    setEditing(null); setApiKey(""); setApiSecret(""); setPassphrase(""); setValidation({});
    triggerRef.current?.focus();
  }
  function open(connection: Connection | "new", trigger: HTMLButtonElement) {
    if (changed && !window.confirm("Ungespeicherte Verbindungsänderungen verwerfen?")) return;
    triggerRef.current = trigger; setEditing(connection); setError(""); setNotice(""); setValidation({});
    setProvider(connection === "new" ? "binance" : connection.provider); setLabel(connection === "new" ? "" : connection.label);
    setAccount(connection === "new" ? "" : connection.account); setSubaccount(connection === "new" ? "" : connection.subaccount);
    setBudgetGroup(connection === "new" ? "ip:global" : connection.budget_group); setApiKey(""); setApiSecret(""); setPassphrase("");
  }
  async function act(action: () => Promise<void>) {
    if (locked) return;
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Die Aktion konnte nicht abgeschlossen werden."); }
    finally { setBusy(false); }
  }
  function start(connection: Connection, action: "test" | "sync") {
    if (locked || runningJobs.some((job) => job.connection_id === connection.id)) return;
    const effect = action === "test" ? "Ein lesender Verbindungstest sendet jetzt Anfragen an den Anbieter. Er importiert keine vollständige Historie und aktiviert keine Steuerquelle." : "Die Bestandsabfrage sendet jetzt Anfragen an den Anbieter und speichert einen aktuellen Bestands-Snapshot. Sie importiert keine vollständige Historie und verändert keine historischen Transaktionen.";
    if (!window.confirm(`${effect} Anbieterentgelt und gemeinsame Abruflimits können gelten. Für „${connection.label}“ starten?`)) return;
    void act(async () => {
      const job = await adminRequest<ConnectionJob>(`connections/${connection.id}/${action}`, "POST", { confirm_external_request: true, confirm_balance_snapshot: action === "sync", deadline_seconds: 120 });
      polls.current = 0; jobs.reload(); connections.reload();
      setNotice(`${action === "test" ? "Verbindungstest" : "Bestandsabfrage"} angenommen. ${JOB_LABELS[job.status]}. Ein angenommener Auftrag ist noch kein erfolgreicher Abruf.`);
    });
  }
  return <section className="installationSettings connectionSettings" aria-label="Eigene Verbindungen">
    <div className="panelToolbar"><div className="pageTitle"><h2>Eigene Verbindungen</h2><HelpTip label="Eigene Börsenkonten getrennt einrichten">Jedes Konto und Unterkonto erhält eine eigene stabile Verbindung. Gemeinsame Anbieter- und IP-Limits bleiben zusätzlich wirksam. Speichern startet keinen Test, Abruf oder Import.</HelpTip></div>
      <div className="adminRowActions"><button className="ghostButton" type="button" title="Verbindungen und lokale Aufträge neu laden" aria-label="Verbindungen und lokale Aufträge neu laden" disabled={busy} onClick={() => { polls.current = 0; connections.reload(); jobs.reload(); }}><RefreshCw size={16} /></button>
        <button type="button" className="primaryButton" disabled={locked} onClick={(event) => open("new", event.currentTarget)}><Plus size={16} /> Verbindung hinzufügen</button></div></div>
    <p className="adminSectionIntro">Mehrere Konten je Börse, jeweils mit eigenem Namen und geschützten Zugangsdaten. Nur Leserechte verwenden; keine Handels- oder Auszahlungsrechte erforderlich.</p>
    <AdminEnvironmentState environment={environment} />
    {error && <p className="adminMessage error" role="alert">{error}</p>}
    {notice && <p className="adminMessage" role="status">{notice}</p>}
    {connections.status === "loading" && <p role="status">Verbindungen werden geladen.{connections.data ? " Der vorherige Stand bleibt sichtbar." : ""}</p>}
    {connections.status === "error" && <p className="adminMessage error" role="alert">Verbindungen konnten nicht geladen werden. <button type="button" className="ghostButton" onClick={connections.reload}>Erneut laden</button></p>}
    {connections.data && !vaultReady && <p role="note" className="adminMessage">{environment.data?.synthetic_preview ? "In dieser Demo ist die Secretspeicherung absichtlich deaktiviert. Keine produktiven Zugangsdaten eingeben." : "Der verschlüsselte Secret-Vault ist nicht bereit. Zugangsdaten können nicht gespeichert werden. Die Administration findet den Lösungsweg unter Installation."}</p>}
    {connections.status === "ready" && !list.length && <p>Noch keine eigene Verbindung angelegt. Bestehende Dateiquellen und Wallet-Zuordnungen bleiben unverändert.</p>}
    <div className="adminConnectionList">{list.map((connection) => {
      const hasActiveJob = runningJobs.some((job) => job.connection_id === connection.id);
      const actionDisabled = locked || jobs.status !== "ready" || hasActiveJob || connection.credentials.status !== "configured" || !vaultReady;
      return <article className="adminConnectionRow" key={connection.id} aria-label={connection.label}>
        <div><h3>{connection.label}</h3><p>{PROVIDERS[connection.provider] ?? connection.provider} · {connection.account || "Kontoname nicht angegeben"}{connection.subaccount ? ` / Unterkonto ${connection.subaccount}` : ""}</p>
          <p>{CREDENTIAL_LABELS[connection.credentials.status]}</p><small className="adminInlineHelp">Herkunft: {connection.origin === "manual" ? "manuell eingerichtet" : connection.origin === "import" ? "importiert" : "API"} · Zugangsdaten geändert: {timestamp(connection.credentials.updated_at)}</small></div>
        <div><p>Erfolgreicher Test: {connection.last_test_at ? timestamp(connection.last_test_at) : "noch nicht bestätigt"}</p><p>Letzter Bestandsabruf: {connection.last_sync_at ? timestamp(connection.last_sync_at) : "noch nicht erfolgreich"}</p>
          <p>Budgetgruppe: <code>{connection.budget_group}</code></p><small className="adminInlineHelp">Zusätzlich gelten Anbieterprofil und gemeinsames IP-Budget.</small>
          {connection.last_error_code && <p className="adminDanger">{errorLabel(connection.last_error_code)}</p>}</div>
        <div className="adminRowActions"><button type="button" className="ghostButton" disabled={locked || hasActiveJob} onClick={(event) => open(connection, event.currentTarget)} aria-label={`${connection.label} bearbeiten`} title="Name, Konto und Zugangsdaten bearbeiten"><Pencil size={16} /></button>
          <button type="button" className="ghostButton" disabled={actionDisabled} onClick={() => start(connection, "test")} title="Expliziter externer Lesetest; keine vollständige Historie"><ShieldCheck size={16} /> Verbindung testen</button>
          <button type="button" className="ghostButton" disabled={actionDisabled} onClick={() => start(connection, "sync")} title="Externen aktuellen Bestand abrufen und als Snapshot speichern; kein Historienimport"><RefreshCw size={16} /> Bestand abrufen</button></div>
      </article>;
    })}</div>
    <p className="adminInlineHelp">Verbindungstest, Bestandsabfrage und vollständiger Historienimport sind verschiedene Vorgänge. Die Verbindung aktiviert keine fachliche Steuerquelle. Eigentums- und Quellenzuordnung erfolgen weiterhin unter Quellen &amp; Wallets.</p>
    {editing && <form className="adminForm" onSubmit={(event) => {
      event.preventDefault(); if (locked) return;
      const errors: Record<string, string> = {};
      if (!label.trim()) errors.label = "Bitte einen eindeutigen Anzeigenamen eingeben.";
      if (!CONNECTION_GROUP_PATTERN.test(budgetGroup)) errors.group = "Eine geheimnisfreie Budgetgruppen-ID wie ip:global oder budget:boersen verwenden.";
      if (Object.keys(errors).length) { setValidation(errors); return; }
      void act(async () => {
        const secrets = { ...(apiKey.trim() ? { api_key: apiKey } : {}), ...(apiSecret.trim() ? { api_secret: apiSecret } : {}), ...(passphrase.trim() ? { passphrase } : {}) };
        const payload = { label: label.trim(), account: account.trim(), subaccount: subaccount.trim(), budget_group: budgetGroup, ...secrets, ...(editing === "new" ? { provider, origin: "manual" } : {}) };
        await adminRequest<Connection>(editing === "new" ? "connections" : `connections/${editing.id}`, editing === "new" ? "POST" : "PUT", payload);
        setApiKey(""); setApiSecret(""); setPassphrase(""); close(true); connections.reload(); setNotice("Verbindung gespeichert. Kein externer Test, Abruf oder Import wurde gestartet.");
      });
    }}>
      <h3 className="adminSubheading" ref={formRef} tabIndex={-1}>{editing === "new" ? "Neue Verbindung" : "Verbindung bearbeiten"}</h3>
      <div className="formGrid"><div className="adminFormField"><label htmlFor={`${id}-provider`}>Anbieter</label><select id={`${id}-provider`} value={provider} disabled={locked || editing !== "new"} onChange={(event) => { setProvider(event.target.value); setApiKey(""); setApiSecret(""); setPassphrase(""); }}>{Object.entries(PROVIDERS).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></div>
        <label>Anzeigename <input value={label} maxLength={120} disabled={locked} autoComplete="off" aria-invalid={!!validation.label} aria-describedby={validation.label ? `${id}-label-error` : undefined} onChange={(event) => setLabel(event.target.value)} />{validation.label && <small className="adminFieldError" id={`${id}-label-error`}>{validation.label}</small>}</label>
        <label>Konto (optional)<input value={account} maxLength={120} disabled={locked} autoComplete="off" onChange={(event) => setAccount(event.target.value)} /></label>
        <label>Unterkonto (optional)<input value={subaccount} maxLength={120} disabled={locked} autoComplete="off" onChange={(event) => setSubaccount(event.target.value)} /></label></div>
      <label htmlFor={`${id}-group`}>Gemeinsame Budgetgruppe</label><input id={`${id}-group`} value={budgetGroup} disabled={locked} maxLength={80} autoComplete="off" spellCheck={false} aria-invalid={!!validation.group} aria-describedby={`${id}-group-help${validation.group ? ` ${id}-group-error` : ""}`} onChange={(event) => setBudgetGroup(event.target.value)} />
      <small className="adminInlineHelp" id={`${id}-group-help`}>Öffentliche lokale Kennung, niemals API-Key oder Kontogeheimnis: ip:global oder budget:boersen. Alle Verbindungen teilen weiterhin ip:global und das jeweilige Anbieterbudget. Gruppenprofile werden unter Abrufsteuerung eingerichtet.</small>
      {validation.group && <small className="adminFieldError" id={`${id}-group-error`}>{validation.group}</small>}
      <fieldset disabled={locked || !vaultReady}><legend>Zugangsdaten verschlüsselt hinterlegen</legend>
        <p id={`${id}-secret-help`} className="adminInlineHelp">Leere Felder behalten vorhandene Werte. Es werden keine gespeicherten Secrets zurückgeladen. Entfernen ist eine eigene, bestätigte Aktion. Keine Seed-Phrase und keine Wallet-Private-Keys eingeben.</p>
        <div className="formGrid"><label>API-Key<input type="password" value={apiKey} maxLength={4096} autoComplete="new-password" spellCheck={false} aria-describedby={`${id}-secret-help`} onChange={(event) => setApiKey(event.target.value)} /></label>
          <label>API-Secret<input type="password" value={apiSecret} maxLength={4096} autoComplete="new-password" spellCheck={false} aria-describedby={`${id}-secret-help${provider === "coinbase" ? ` ${id}-coinbase-help` : ""}`} onChange={(event) => setApiSecret(event.target.value)} onPaste={(event) => {
            if (provider !== "coinbase") return;
            const pasted = event.clipboardData.getData("text");
            if (!/[\r\n]/.test(pasted)) return;
            event.preventDefault();
            const input = event.currentTarget;
            setApiSecret((previous) => (previous.slice(0, input.selectionStart ?? 0) + pasted.replace(/\r\n|\r|\n/g, "\\n") + previous.slice(input.selectionEnd ?? previous.length)).slice(0, 4096));
          }} /></label>
          <label>Passphrase{provider === "bitget" ? " (für Bitget erforderlich)" : " (falls vom Anbieter benötigt)"}<input type="password" value={passphrase} maxLength={4096} autoComplete="new-password" spellCheck={false} aria-describedby={`${id}-secret-help`} onChange={(event) => setPassphrase(event.target.value)} /></label></div>
      </fieldset>
      {provider === "coinbase" && <p className="adminInlineHelp" id={`${id}-coinbase-help`}>Coinbase erwartet das ECDSA-API-Secret des CDP-Lesezugangs, nicht den Private Key einer Wallet. Beim Einfügen bleiben PEM-Zeilenumbrüche als maskiertes \\n erhalten; gespeicherte Secrets werden nicht angezeigt.</p>}
      <div className="adminFormActions"><button type="submit" className="primaryButton" disabled={locked || !changed}><Save size={16} /> Verbindung speichern</button>
        <button type="button" className="ghostButton" disabled={busy} onClick={() => close()}><X size={16} /> Abbrechen</button>
        {editing !== "new" && <button type="button" className="ghostButton adminDanger" disabled={locked || !vaultReady || editing.credentials.status === "missing"} onClick={() => {
          if (!window.confirm("Alle gespeicherten Zugangsdaten dieser Verbindung entfernen? Die Verbindung und vorhandene Finanzdaten bleiben erhalten.")) return;
          void act(async () => { await adminRequest(`connections/${editing.id}/credentials`, "DELETE"); close(true); connections.reload(); setNotice("Zugangsdaten entfernt. Verbindung und vorhandene Quelldaten bleiben erhalten."); });
        }}><Trash2 size={16} /> Zugangsdaten entfernen</button>}
      </div>
    </form>}
    {!!connections.data?.legacy_connections.length && <details className="installationSection"><summary>Vorhandene ältere Anbieterzugänge ({connections.data.legacy_connections.length})</summary>
      <p className="adminInlineHelp">Nur lesende Anzeige. Es wurde nichts automatisch migriert oder einem neuen Konto zugeordnet. Eine neue Verbindung ausdrücklich mit dem richtigen Konto einrichten; historische Belege bleiben unverändert.</p>
      {connections.data.legacy_connections.map((connection) => <p key={connection.id}>{connection.label} · {PROVIDERS[connection.provider] ?? connection.provider} · {CREDENTIAL_LABELS[connection.credentials.status]}</p>)}
    </details>}
    <details className="installationSection" open={runningJobs.length > 0}><summary>Verbindungsaufträge{runningJobs.length ? ` · ${runningJobs.length} aktiv` : ""}</summary>
      {jobs.status === "loading" && <p role="status">Lokaler Auftragsstatus wird geladen.</p>}
      {jobs.status === "error" && <p role="alert" className="adminMessage error">Auftragsstatus konnte nicht gelesen werden. <button className="ghostButton" type="button" onClick={jobs.reload}>Status erneut laden</button></p>}
      {jobs.status === "ready" && !jobs.data?.jobs.length && <p>Noch keine Verbindungsaufträge vorhanden.</p>}
      {jobs.data?.jobs.map((job) => <div className="adminConnectionRow" key={job.id}>
        <div><strong>{list.find((connection) => connection.id === job.connection_id)?.label ?? PROVIDERS[job.provider] ?? "Verbindung"}</strong><p>{job.action === "test" ? "Verbindungstest" : "Bestandsabfrage"} · {JOB_LABELS[job.status]}</p>{job.slot_reserved && job.status === "failed" && <p>Das Zeitlimit oder ein Fehler hat den Auftrag beendet; ein Aufruf wird noch beendet. Der Ausführungsplatz bleibt reserviert. Kein neuer Auftrag startet parallel.</p>}{job.cancel_requested && <p>Abbruch angefordert. Bereits laufende Requests können noch enden.</p>}</div>
        <div><p>Aktualisiert: {timestamp(job.updated_at)}</p><p>Auftragsfrist: {timestamp(job.deadline_at)}</p>{job.error_code && <p className="adminDanger">{errorLabel(job.error_code)}</p>}{job.status === "succeeded" && job.action === "sync" && <p>{job.snapshot_count} Bestandspositionen gespeichert · kein Historienimport</p>}</div>
        {activeJob(job) && <button type="button" className="ghostButton" disabled={locked || job.cancel_requested} onClick={() => void act(async () => { await adminRequest(`connections/jobs/${job.id}/cancel`, "POST"); jobs.reload(); setNotice("Abbruch angefordert. Der endgültige Auftragsstatus wird separat angezeigt."); })}><Square size={16} /> Auftrag abbrechen</button>}
      </div>)}
      {polls.current >= 100 && <p role="status">Automatische Statusabfrage pausiert. Den lokalen Auftragsstatus bei Bedarf neu laden.</p>}
      <p className="adminInlineHelp">Warteschlange und Budgetpause sind lokale Zustände. Konkrete Wartegründe und nächster möglicher Request-Start stehen unter Abrufsteuerung. Ein laufender Auftrag ist kein erfolgreicher Verbindungsnachweis.</p>
    </details>
  </section>;
}

type LimitProfile = {
  origin: "local_conservative"; manufacturer_limit_verified: false; cost_unit: "local_units";
  requests_per_second: number; requests_per_10_seconds?: number | null; requests_per_minute: number; weighted_cost_per_minute: number | null;
  burst: number; max_concurrency: number; timeout_seconds: number; max_retries: number;
  backoff_base_seconds: number; backoff_max_seconds: number; jitter_ratio: number; job_deadline_seconds: number;
};
type ProviderCeiling = { requests_per_second: number | null; requests_per_10_seconds?: number | null; requests_per_minute: number | null; weighted_cost_per_minute: number | null; source_url: string; checked_date: string; scope: "provider" | "ip" | "account" | "api_key" | "project" | "endpoint_group" | "combination"; plan: string; declared_by_operator: true; independently_verified: false };
type LimitConfig = { schema_version: 1; revision: number; default_profile: LimitProfile; group_profiles: Record<string, LimitProfile>; provider_groups: Record<string, string[]>; endpoint_profiles?: Record<string, Record<string, LimitProfile>>; endpoint_costs?: Record<string, Record<string, number>>; provider_ceilings?: Record<string, ProviderCeiling>; scheduler_enabled: false };
type ProviderObservation = { last_observed_at: number; last_rate_limit_at: number | null; used_weight_1m: number | null; remaining_requests: number | null; reset_at: number | null };
type LimitStatus = { schema_version: 1; config_revision: number; observed_at: number; clock_rollback: boolean; manufacturer_telemetry_available: boolean; provider_observations?: Record<string, ProviderObservation>; coordination_scope: string; concurrency_recovery: string; groups: Array<{ group: string; provider?: string | null; endpoint?: string | null; profile: LimitProfile; requests_last_second: number; requests_last_10_seconds?: number | null; requests_last_minute: number; cost_last_minute: number; in_flight: number; queued: number; paused_until: number | null; next_start_at: number | null; blocking_reasons: string[] }> };
type ProviderReferences = { checked_at: string; providers: Array<{ provider: string; source_url: string; scope: string; limitation: string }> };
type LimitPreset = { id: string; label: string; source_url: string; checked_date: string; description: string; profile: LimitProfile; endpoint_profiles?: Record<string, Record<string, LimitProfile>>; affected_groups: string[]; conflicts: string[]; current_revision: number };
type ProfileNumber = Exclude<keyof LimitProfile, "origin" | "manufacturer_limit_verified" | "cost_unit">;
type LimitField = { key: ProfileNumber; label: string; help: string; min: number; max: number; step: string; optional?: boolean };
const LIMIT_FIELDS: LimitField[] = [
  { key: "requests_per_second", label: "Requests pro Sekunde", help: "Rollierendes Sekundenfenster. Gilt zusätzlich zum Minutenfenster, nicht stattdessen.", min: 1, max: 10000, step: "1" },
  { key: "requests_per_10_seconds", label: "Requests pro 10 Sekunden", help: "Optionales, eigenständiges rollierendes 10-Sekunden-Fenster. Leer: keine zusätzliche lokale 10-Sekunden-Grenze. Sekunden- und Minutenlimits bleiben aktiv.", min: 1, max: 100000, step: "1", optional: true },
  { key: "requests_per_minute", label: "Requests pro Minute", help: "Eigenständiges rollierendes 60-Sekunden-Fenster. Wird nicht aus dem Sekundenwert berechnet.", min: 1, max: 100000, step: "1" },
  { key: "weighted_cost_per_minute", label: "Lokales Kostenbudget pro Minute", help: "Optionale zusätzliche Grenze in lokalen Kosteneinheiten. Leer: keine zusätzliche lokale Kostengrenze; die Requestgrenzen bleiben aktiv. Keine Zusage über CU, Credits oder Herstellergewichte.", min: 1, max: 100000000, step: "1", optional: true },
  { key: "burst", label: "Burst (zusätzliche Startgrenze)", help: "Token-Bucket-Kapazität; Auffüllung mit Requests pro Sekunde. Darf keines der rollierenden Requestfenster überschreiten und hebt diese nicht auf.", min: 1, max: 10000, step: "1" },
  { key: "max_concurrency", label: "Maximal parallele Requests", help: "Gleichzeitig laufende HTTP-Aufrufe. Unabhängig von der Anzahl gestarteter Requests pro Zeitfenster.", min: 1, max: 1000, step: "1" },
  { key: "timeout_seconds", label: "Timeout je Request (Sekunden)", help: "Zeitlimit des einzelnen HTTP-Aufrufs; darf die Gesamtdeadline nicht überschreiten.", min: 0.001, max: 3600, step: "any" },
  { key: "max_retries", label: "Maximale Wiederholungen", help: "Zusätzliche Versuche bei dafür geeigneten Fehlern. 0 bedeutet keine Wiederholung. Jeder Versuch verbraucht erneut Budget.", min: 0, max: 10, step: "1" },
  { key: "backoff_base_seconds", label: "Anfängliche Retry-Wartezeit (Sekunden)", help: "Ausgangswert der wachsenden Wartezeit. Ein Anbieter-Wartehinweis kann zusätzlich verzögern.", min: 0.001, max: 300, step: "any" },
  { key: "backoff_max_seconds", label: "Maximale Retry-Basiswartezeit (Sekunden)", help: "Obergrenze der lokalen Backoff-Basis; zusätzlich können Zufallsstreuung oder Anbieter-Wartehinweise gelten.", min: 0.001, max: 3600, step: "any" },
  { key: "jitter_ratio", label: "Zufallsstreuung (Anteil 0–1)", help: "Zusätzliche Streuung von Retry-Wartezeiten, z. B. 0,2 für bis zu 20 Prozent. 0 deaktiviert nur die Streuung.", min: 0, max: 1, step: "any" },
  { key: "job_deadline_seconds", label: "Gesamtdeadline je Auftrag (Sekunden)", help: "Begrenzt einschließlich Budgetwartezeit und Wiederholungen. Einzelne Aktionen können kürzere Fristen verwenden.", min: 0.001, max: 86400, step: "any" }
];
function profileValues(profile: LimitProfile): Record<ProfileNumber, string> {
  return Object.fromEntries(LIMIT_FIELDS.map(({ key }) => [key, profile[key] == null ? "" : String(profile[key])])) as Record<ProfileNumber, string>;
}
function limitValue(value: number | null | undefined) {
  return value === null ? "Keine zusätzliche Grenze" : value === undefined ? "Nicht gemeldet" : new Intl.NumberFormat("de-DE", { maximumFractionDigits: 6 }).format(value);
}
function epochTime(value: number | null) { return value === null ? "Nicht gemeldet" : timestamp(new Date(value * 1000).toISOString()); }
const BLOCK_REASONS: Record<string, string> = { requests_per_second: "Sekundenbudget", rolling_second: "Sekundenbudget", requests_per_10_seconds: "10-Sekunden-Budget", rolling_10_seconds: "10-Sekunden-Budget", requests_per_minute: "Minutenbudget", rolling_minute: "Minutenbudget", weighted_cost_per_minute: "Lokales Kostenbudget", burst: "Burst-Grenze", max_concurrency: "Parallelitätsgrenze", provider_pause: "Wartehinweis des Anbieters", clock_rollback: "Systemzeit zurückgestellt" };
const REQUEST_PROVIDERS: Record<string, string> = { ...PROVIDERS, solana_rpc: "Solana Public RPC", alchemy: "Alchemy", helius: "Helius", solscan: "Solscan", jupiter: "Jupiter", coingecko: "CoinGecko", cryptocompare: "CryptoCompare", ecb: "EZB", fx: "Wechselkurse", ai_local: "KI lokal", ai_cloud: "KI Cloud", ai_openrouter: "OpenRouter", other: "Sonstige" };
const RPC_LIMIT_PROVIDERS: Record<string, string> = { alchemy: "Alchemy", helius: "Helius", solana_custom_rpc: "Eigener Solana-RPC", solana_rpc: "Solana Public RPC" };
function hasInheritedProfile(target: string) {
  return target === "ip:global" || (target.startsWith("provider:") && Object.hasOwn(RPC_LIMIT_PROVIDERS, target.slice(9)));
}
function endpointSelection(target: string): { provider: string; endpoint: string } | null {
  if (!target.startsWith("endpoint-profile:")) return null;
  const [provider, ...endpoint] = target.slice("endpoint-profile:".length).split(":");
  return { provider, endpoint: endpoint.join(":") };
}
function selectedProfile(config: LimitConfig, target: string, provider: string, endpoint: string): LimitProfile | undefined {
  const selection = target === "new-endpoint" ? { provider, endpoint } : endpointSelection(target);
  if (selection) return config.endpoint_profiles?.[selection.provider]?.[selection.endpoint] ?? (target === "new-endpoint" ? config.group_profiles[`provider:${selection.provider}`] ?? config.default_profile : undefined);
  return target === "default" || target === "new" ? config.default_profile : config.group_profiles[target] ?? (hasInheritedProfile(target) ? config.default_profile : undefined);
}
function documentationUrl(value: string): string | undefined {
  try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password ? url.href : undefined; } catch { return undefined; }
}

export function RequestLimitSettings() {
  const environment = useAdminEnvironment();
  const config = useResource<LimitConfig>("admin-request-limits", (signal) => readApi("/api/v1/admin/request-limits", signal));
  const status = useResource<LimitStatus>("admin-request-limits-status", (signal) => readApi("/api/v1/admin/request-limits/status", signal));
  const references = useResource<ProviderReferences>("admin-provider-references", (signal) => readApi("/api/v1/admin/provider-references", signal));
  const endpoints = useResource<{ http?: { id: string; path: string }[]; rpc?: { id: string; method: string }[] }>("admin-request-endpoints", (signal) => readApi("/api/v1/admin/request-limits/endpoints", signal));
  const presets = useResource<{ presets: LimitPreset[]; current_revision: number }>("admin-request-presets", (signal) => readApi("/api/v1/admin/request-limits/presets", signal));
  const [presetConfirmed, setPresetConfirmed] = useState(false);
  const [target, setTarget] = useState("default");
  const [newGroup, setNewGroup] = useState("");
  const [endpointProvider, setEndpointProvider] = useState("solana_rpc");
  const [endpointName, setEndpointName] = useState("rpc_gettransaction");
  const [draft, setDraft] = useState<Record<ProfileNumber, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [validation, setValidation] = useState<Record<string, string>>({});
  const [costProvider, setCostProvider] = useState("binance");
  const [costEndpoint, setCostEndpoint] = useState("default");
  const [costValue, setCostValue] = useState("1");
  const [costError, setCostError] = useState("");
  const [ceilingDraft, setCeilingDraft] = useState({ provider: "binance", requests_per_second: "", requests_per_10_seconds: "", requests_per_minute: "", weighted_cost_per_minute: "", source_url: "", checked_date: "", scope: "provider" as ProviderCeiling["scope"], plan: "", confirmed: false, revision: null as number | null });
  const [ceilingError, setCeilingError] = useState("");
  const id = useId();
  const dirtyRef = useRef(false);
  const draftRevision = useRef<number | null>(null);
  const writePending = useRef(false);
  const selection = target === "new-endpoint" ? { provider: endpointProvider, endpoint: endpointName } : endpointSelection(target);
  const base = config.data && selectedProfile(config.data, target, endpointProvider, endpointName);
  const profileNeedsCreation = !!config.data && hasInheritedProfile(target) && !config.data.group_profiles[target];
  const dirty = !!(draft && base && LIMIT_FIELDS.some(({ key }) => draft[key] !== profileValues(base)[key])) || (target === "new" && !!newGroup) || target === "new-endpoint";
  dirtyRef.current = dirty;
  useEffect(() => { if (config.data && !dirtyRef.current) { const profile = selectedProfile(config.data, target, endpointProvider, endpointName); if (profile) { draftRevision.current = config.data.revision; setDraft(profileValues(profile)); } } }, [config.data, target, endpointProvider, endpointName]);
  useEffect(() => { setPresetConfirmed(false); }, [presets.data, config.data?.revision]);
  useEffect(() => { setCeilingDraft((previous) => previous.confirmed ? { ...previous, confirmed: false } : previous); }, [config.data?.revision]);
  const locked = busy || environment.locked || config.status !== "ready";
  const group = target === "new" ? newGroup : target;
  const providerCeiling = target.startsWith("provider:") ? config.data?.provider_ceilings?.[target.slice("provider:".length)] : undefined;
  const effectiveGroup = providerCeiling ? `budget:ceiling:${target.slice("provider:".length)}` : group;
  const observed = status.data?.groups.find((item) => selection ? item.provider === selection.provider && item.endpoint === selection.endpoint : item.group === effectiveGroup);
  const statusCurrent = status.status === "ready" && status.data?.config_revision === config.data?.revision;
  const draftConflict = draft !== null && dirty && draftRevision.current !== config.data?.revision;
  const ceilingConflict = ceilingDraft.revision !== null && ceilingDraft.revision !== config.data?.revision;
  const providerNames = Array.from(new Set([...Object.keys(REQUEST_PROVIDERS), ...Object.keys(config.data?.provider_ceilings ?? {}), ...Object.keys(config.data?.endpoint_profiles ?? {}), ...Object.keys(config.data?.endpoint_costs ?? {}), ...Object.keys(config.data?.provider_groups ?? {}), ...Object.keys(config.data?.group_profiles ?? {}).filter((key) => key.startsWith("provider:")).map((key) => key.slice(9)), ...(references.data?.providers ?? []).map((item) => item.provider)])).sort();
  const endpointNames = new Map<string, string>([["default", "Standard / sonstige Endpunkte"], ...(endpoints.data?.http ?? []).map((item): [string, string] => [item.id, `${item.id} · ${item.path}`]), ...(endpoints.data?.rpc ?? []).map((item): [string, string] => [item.id, item.method])]);
  const solanaPreset = presets.data?.presets.find((preset) => preset.id === "solana_public_free");
  const presetCurrent = presets.status === "ready" && presets.data?.current_revision === config.data?.revision && solanaPreset?.current_revision === config.data?.revision;
  function beginWrite() {
    if (writePending.current) return false;
    writePending.current = true;
    setBusy(true); setError(""); setNotice("");
    return true;
  }
  function finishWrite() { writePending.current = false; setBusy(false); }
  function chooseProfile(value: string) {
    if (writePending.current || !config.data) return;
    if (dirty && !window.confirm("Ungespeicherte Limitänderungen verwerfen?")) return;
    setTarget(value); setNewGroup(""); setValidation({}); setNotice("");
    draftRevision.current = config.data.revision;
    const profile = selectedProfile(config.data, value, endpointProvider, endpointName);
    setDraft(profile ? profileValues(profile) : null);
  }
  function updateCeilingDraft(values: Partial<typeof ceilingDraft>) {
    setCeilingDraft((previous) => ({ ...previous, ...values, confirmed: false, revision: previous.revision ?? config.data?.revision ?? null }));
  }
  function editCeiling(provider: string) {
    if (locked || writePending.current || !config.data) return;
    const ceiling = config.data.provider_ceilings?.[provider];
    setCeilingDraft({ provider, requests_per_second: ceiling?.requests_per_second == null ? "" : String(ceiling.requests_per_second), requests_per_10_seconds: ceiling?.requests_per_10_seconds == null ? "" : String(ceiling.requests_per_10_seconds), requests_per_minute: ceiling?.requests_per_minute == null ? "" : String(ceiling.requests_per_minute), weighted_cost_per_minute: ceiling?.weighted_cost_per_minute == null ? "" : String(ceiling.weighted_cost_per_minute), source_url: ceiling?.source_url ?? "", checked_date: ceiling?.checked_date ?? "", scope: ceiling?.scope ?? "provider", plan: ceiling?.plan ?? "", confirmed: false, revision: config.data.revision });
    setCeilingError("");
  }
  function refresh() {
    if (writePending.current) return;
    if (dirty && !window.confirm("Ungespeicherte Limitänderungen verwerfen?")) return;
    dirtyRef.current = false; draftRevision.current = null; setDraft(null); if (target === "new-endpoint" || target === "new") setTarget("default"); setNewGroup(""); setValidation({}); setError(""); setNotice(""); setPresetConfirmed(false); setCeilingDraft((previous) => ({ ...previous, confirmed: false })); config.reload(); status.reload(); presets.reload();
  }
  return <section className="installationSettings connectionSettings requestLimitSettings" aria-label="Abrufsteuerung">
    <div className="panelToolbar"><div className="pageTitle"><h2>Abrufsteuerung</h2><HelpTip label="Gemeinsame serverseitige Abrufbudgets">Alle gleichzeitig geltenden Budgetgruppen begrenzen den Start eines Requests gemeinsam. Sekunden-, 10-Sekunden- und Minutenfenster, Burst und Parallelität haben unterschiedliche Aufgaben. Ein zweites Konto erhöht kein geteiltes Anbieter- oder IP-Budget.</HelpTip></div>
      <button type="button" className="ghostButton" title="Gespeicherte Limits und lokale Auslastung neu lesen" aria-label="Gespeicherte Limits und lokale Auslastung neu lesen" disabled={busy} onClick={refresh}><RefreshCw size={16} /></button></div>
    <p className="adminSectionIntro">Lokale Betreiberlimits und gemessene Auslastung. Herstellerobergrenzen sind nicht bestätigt; lokale Einstellungen können Anbietergrenzen niemals erhöhen. KI hat einen getrennten Providerbereich.</p>
    <AdminEnvironmentState environment={environment} />
    {error && <p role="alert" className="adminMessage error">{error}</p>}
    {notice && <p role="status" className="adminMessage">{notice}</p>}
    {config.status === "loading" && <p role="status">Gespeicherte Limitprofile werden geladen.{config.data ? " Der vorherige Stand bleibt sichtbar." : ""}</p>}
    {config.status === "error" && <p role="alert" className="adminMessage error">Limitprofile konnten nicht gelesen werden. Änderungen bleiben gesperrt. <button className="ghostButton" type="button" onClick={config.reload}>Erneut laden</button></p>}
    {config.data && <>
      <details className="installationSection"><summary>Solana Public RPC - Free</summary>
        <p>Der gesamte Flaschenhals zählt: Anbieterprofil und gemeinsames <code>ip:global</code>-Budget gelten gleichzeitig. Ein höherer Anbieterwert allein hebt ein engeres IP-Budget nicht auf.</p>
        <p className="adminInlineHelp">Konservativer Startwert: 3 Requests/s, 180/min und 30/10 Sekunden, Burst 1, parallel 1. Drei Historien-RPC-Endpunkte erhalten 4/s, 240/min und 40/10 Sekunden, ebenfalls Burst 1 und parallel 1; das gemeinsame Gesamtbudget bleibt strenger. Keine Zusage einer erreichbaren Abrufrate.</p>
        <p className="adminInlineHelp">Dokumentierte Public-RPC-Grenzen: 100 Requests/10 Sekunden insgesamt, 40/10 Sekunden je Methode und 40 neue Verbindungen/10 Sekunden. Deshalb konservativ 3/s. 100 MB/30 Sekunden werden nicht als Bytebudget durchgesetzt. Weiterer Verkehr hinter derselben NAT/IP wird nicht koordiniert.</p>
        {presets.status === "loading" && <p role="status">Serverseitige Preset-Vorschau wird geladen. Kein Anbieter wird angefragt.</p>}
        {presets.status === "error" && <p role="alert" className="adminMessage error">Die Preset-Vorschau ist nicht verfügbar. Es wurde nichts angewendet. <button className="ghostButton" type="button" disabled={busy} onClick={presets.reload}>Vorschau neu laden</button></p>}
        {presets.status === "ready" && !solanaPreset && <p>Der Server bietet dieses Startprofil nicht an.</p>}
        {solanaPreset && <>
          <p><strong>Solana Public RPC - Free</strong> · Quellenstand {solanaPreset.checked_date}</p><p>{solanaPreset.description}</p>
          {documentationUrl(solanaPreset.source_url) && <a href={documentationUrl(solanaPreset.source_url)} target="_blank" rel="noreferrer noopener">Solana-Referenz öffnen</a>}
          <p className="adminInlineHelp">Betroffene gemeinsame Gruppen: {solanaPreset.affected_groups.filter((groupName) => !groupName.startsWith("budget:endpoint:")).join(", ")}. Startkonfiguration, keine Herstellerverifikation. Alle Zahlen bleiben über die Profile editierbar.</p>
          <div className="adminLimitTableWrap" role="region" aria-label="Vorgeschlagene Solana-Profile" tabIndex={0}><table className="adminLimitTable"><thead><tr><th scope="col">Profil</th><th scope="col">Requests: 1 s / 10 s / 60 s</th><th scope="col">Burst / parallel</th></tr></thead><tbody>
            <tr><th scope="row">Anbieter und gemeinsame IP</th><td>{solanaPreset.profile.requests_per_second} / {solanaPreset.profile.requests_per_10_seconds ?? "Keine zusätzliche Grenze"} / {solanaPreset.profile.requests_per_minute}</td><td>{solanaPreset.profile.burst} / {solanaPreset.profile.max_concurrency}</td></tr>
            {Object.entries(solanaPreset.endpoint_profiles ?? {}).flatMap(([providerName, profiles]) => Object.entries(profiles).map(([endpoint, profile]) => <tr key={`${providerName}:${endpoint}`}><th scope="row">{REQUEST_PROVIDERS[providerName] ?? providerName} · {endpointNames.get(endpoint) ?? endpoint}</th><td>{profile.requests_per_second} / {profile.requests_per_10_seconds ?? "Keine zusätzliche Grenze"} / {profile.requests_per_minute}</td><td>{profile.burst} / {profile.max_concurrency}</td></tr>))}
          </tbody></table></div>
          {!!solanaPreset.conflicts.length && <p role="alert" className="adminMessage error">Abweichende vorhandene Profile: {solanaPreset.conflicts.join(", ")}. Das Preset überschreibt diese nicht. Die betroffenen Profile einzeln prüfen und bearbeiten.</p>}
          {!presetCurrent && <p role="status">Die Vorschau passt nicht zur aktuellen Konfigurationsrevision. Vor dem Anwenden neu laden.</p>}
          <form className="adminForm" onSubmit={(event) => {
            event.preventDefault(); if (locked || dirty || !presetConfirmed || !presetCurrent || solanaPreset.conflicts.length || !config.data) return;
            if (!beginWrite()) return;
            void adminRequest<LimitConfig>("request-limits/presets/solana_public_free", "POST", { expected_revision: config.data.revision, confirmation: true }).then(() => {
              setPresetConfirmed(false); setDraft(null); config.reload(); status.reload(); presets.reload(); setNotice("Solana-Startprofil serverseitig gespeichert. Kein externer Abruf, Sync oder Historienimport gestartet. Die Profile bleiben einzeln editierbar.");
            }).catch((caught) => { setPresetConfirmed(false); setError(caught instanceof Error ? caught.message : "Das Startprofil konnte nicht angewendet werden."); presets.reload(); }).finally(finishWrite);
          }}>
            <label className="adminCheckbox"><input type="checkbox" checked={presetConfirmed} disabled={locked || dirty || !presetCurrent || !!solanaPreset.conflicts.length} onChange={(event) => setPresetConfirmed(event.target.checked)} />Ich möchte das Startprofil ausdrücklich auf die genannten gemeinsamen und Endpunktbudgets anwenden. Dies startet keinen Abruf.</label>
            {dirty && <p className="adminInlineHelp">Zuerst Änderungen am Betreiberprofil speichern oder verwerfen.</p>}
            <div><button type="submit" className="primaryButton" disabled={locked || dirty || !presetConfirmed || !presetCurrent || !!solanaPreset.conflicts.length}><Save size={16} /> Solana-Startprofil anwenden</button></div>
          </form>
        </>}
      </details>
      <label htmlFor={`${id}-profile`}>Limitprofil</label><select id={`${id}-profile`} value={target} disabled={busy} onChange={(event) => chooseProfile(event.target.value)}><option value="default">Lokales Standardprofil (für nicht separat konfigurierte Gruppen)</option>
        <optgroup label="Solana-Datenanbieter">{Object.entries(RPC_LIMIT_PROVIDERS).map(([provider, label]) => <option value={`provider:${provider}`} key={provider}>{label} · eigenes Anbieterlimit</option>)}</optgroup>
        <optgroup label="Gemeinsame Budgetgruppen"><option value="ip:global">Gemeinsame IP · alle Börsen und RPC-Anbieter</option>{Object.keys(config.data.group_profiles).filter((value) => !hasInheritedProfile(value)).sort().map((value) => <option value={value} key={value}>{value}</option>)}</optgroup>
        <optgroup label="Endpunktprofile">{Object.entries(config.data.endpoint_profiles ?? {}).flatMap(([providerName, profiles]) => Object.keys(profiles).sort().map((endpoint) => <option key={`${providerName}:${endpoint}`} value={`endpoint-profile:${providerName}:${endpoint}`}>{REQUEST_PROVIDERS[providerName] ?? providerName} · {endpointNames.get(endpoint) ?? endpoint}</option>))}</optgroup>
        <option value="new">Zusätzliches Budgetgruppenprofil</option><option value="new-endpoint">Endpunktprofil hinzufügen / bearbeiten</option></select>
      {profileNeedsCreation && <p role="status">Für dieses Budget ist noch kein eigenes Profil gespeichert. Angezeigt wird das geerbte Standardprofil. Erst „Limitprofil speichern“ legt das eigene Profil an; die Auswahl allein ändert nichts.</p>}
      {target === "provider:alchemy" && <p className="adminInlineHelp"><strong>Alchemy: Einheit des Tarifs prüfen.</strong> CU/s (Compute Units pro Sekunde) sind keine Requests/s. „500 CU/s“ nicht als 500 Requests/s eintragen. Dieses Formular steuert Requestgrenzen und lokale Kosten pro Minute, keinen CU/s-Durchsatz. <a href="https://www.alchemy.com/docs/reference/throughput" target="_blank" rel="noreferrer noopener">Alchemy-Durchsatz und Einheiten</a></p>}
      {target === "provider:helius" && <p className="adminInlineHelp">Helius unterscheidet RPC-Requests/s von DAS-/Enhanced-API-Limits. Nur die für den verwendeten RPC und eigenen Tarif belegten Werte eintragen. <a href="https://www.helius.dev/docs/billing/rate-limits" target="_blank" rel="noreferrer noopener">Helius-Limits prüfen</a></p>}
      {target.startsWith("provider:") && hasInheritedProfile(target) && <div className="adminInlineHelp"><p>Dieses Anbieterprofil ist kein Durchsatzversprechen. Sekunden-, 10-Sekunden-, Minuten-, Burst- und Methodenlimits gelten zusätzlich. Der Historienabruf verarbeitet Details weiterhin sequenziell.</p><p>Gemeinsames IP-Profil: {config.data.group_profiles["ip:global"] ? "eigenes Profil" : "geerbtes Standardprofil"} · {limitValue((config.data.group_profiles["ip:global"] ?? config.data.default_profile).requests_per_second)} Requests/s · {limitValue((config.data.group_profiles["ip:global"] ?? config.data.default_profile).requests_per_minute)} Requests/min. Ein niedrigeres gemeinsames Budget begrenzt auch Alchemy und Helius.</p><button type="button" className="ghostButton" disabled={busy} onClick={() => chooseProfile("ip:global")}><Pencil size={16} /> Gemeinsames IP-Limit bearbeiten</button></div>}
      {target === "new-endpoint" && <div className="adminForm"><div className="formGrid">
        <label>Anbieter des Endpunktprofils<select value={endpointProvider} disabled={locked} onChange={(event) => {
          if (draft && base && LIMIT_FIELDS.some(({ key }) => draft[key] !== profileValues(base)[key]) && !window.confirm("Ungespeicherte Limitänderungen verwerfen?")) return;
          draftRevision.current = config.data!.revision; setEndpointProvider(event.target.value); setDraft(profileValues(selectedProfile(config.data!, "new-endpoint", event.target.value, endpointName)!)); setValidation({});
        }}>{providerNames.map((providerName) => <option key={providerName} value={providerName}>{REQUEST_PROVIDERS[providerName] ?? providerName}</option>)}</select></label>
        <label>Endpunkt des Limitprofils<select value={endpointName} disabled={locked || endpoints.status !== "ready"} onChange={(event) => {
          if (draft && base && LIMIT_FIELDS.some(({ key }) => draft[key] !== profileValues(base)[key]) && !window.confirm("Ungespeicherte Limitänderungen verwerfen?")) return;
          draftRevision.current = config.data!.revision; setEndpointName(event.target.value); setDraft(profileValues(selectedProfile(config.data!, "new-endpoint", endpointProvider, event.target.value)!)); setValidation({});
        }}>{!endpointNames.has(endpointName) && <option value={endpointName}>{endpointName}</option>}{Array.from(endpointNames, ([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
      </div><p className="adminInlineHelp">{config.data.endpoint_profiles?.[endpointProvider]?.[endpointName] ? "Vorhandenes Endpunktprofil bearbeiten." : "Neues vollständiges Profil auf Basis des Anbieter- oder Standardprofils."} Automatisch an passende Requests gebunden; gemeinsame Anbieter- und IP-Budgets gelten zusätzlich. Keine URL und keinen API-Key eingeben.</p></div>}
      {endpoints.status === "error" && <p role="alert" className="adminMessage error">Der Endpunktkatalog konnte nicht geladen werden. Neue Endpunktzuordnungen bleiben gesperrt. <button type="button" className="ghostButton" disabled={busy} onClick={endpoints.reload}>Katalog erneut laden</button></p>}
      {target === "new" && <div className="adminFormField"><label htmlFor={`${id}-new-group`}>Neue Budgetgruppen-ID</label><input id={`${id}-new-group`} type="text" value={newGroup} maxLength={80} disabled={locked} autoComplete="off" spellCheck={false} aria-describedby={`${id}-new-group-help`} aria-invalid={!!validation.group} onChange={(event) => setNewGroup(event.target.value)} /><small id={`${id}-new-group-help`} className="adminInlineHelp">Geheimnisfreie Kennung, z. B. provider:binance, ip:global oder budget:boersen. Ein Gruppenprofil ist erst für zugeordnete Verbindungen bzw. Anbieter wirksam. Keine API-Keys eingeben.</small>{validation.group && <small className="adminFieldError">{validation.group}</small>}</div>}
      <p className="adminInlineHelp">{target === "default" ? "Das Standardprofil ersetzt keine Herstellergrenze. Jede aktive Budgetgruppe erbt es, sofern kein eigenes Profil hinterlegt ist." : selection ? `Endpunktprofil für ${selection.provider} / ${selection.endpoint}. Alle passenden Requests teilen dieses Budget; weitere IP-/Anbietergruppen können strenger begrenzen.` : "Dieses Profil begrenzt die gesamte Budgetgruppe gemeinsam, nicht jedes Konto einzeln. Weitere IP-/Anbietergruppen können strenger begrenzen."}</p>
      <div className="adminLimitTableWrap" role="region" aria-label="Hersteller, Betreiber und wirksame Limits" tabIndex={0}><table className="adminLimitTable"><caption>Gespeicherter Stand · Revision {config.data.revision}. Wirksame Werte gelten für diese Budgetgruppe einschließlich einer hinterlegten Betreiberdeklaration. Weitere gemeinsame Budgets können zusätzlich strenger begrenzen.</caption><thead><tr><th scope="col">Parameter</th><th scope="col">Herstellergrenze (Betreiberdeklaration)</th><th scope="col">Betreiberwert (gespeichert)</th><th scope="col">Wirksames Gruppenlimit</th></tr></thead><tbody>
        {LIMIT_FIELDS.filter(({ key }) => ["requests_per_second", "requests_per_10_seconds", "requests_per_minute", "weighted_cost_per_minute", "burst", "max_concurrency", "timeout_seconds", "max_retries", "job_deadline_seconds"].includes(key)).map(({ key, label: fieldLabel }) => {
          const cap = providerCeiling && (key === "requests_per_second" || key === "requests_per_10_seconds" || key === "requests_per_minute" || key === "weighted_cost_per_minute") ? providerCeiling[key] : null;
          return <tr key={key}><th scope="row">{fieldLabel}</th><td>{cap == null ? "Unbekannt / nicht bestätigt" : `${limitValue(cap)} · vom Betreiber deklariert, nicht unabhängig verifiziert`}</td><td>{limitValue(key === "requests_per_10_seconds" ? base?.[key] ?? null : base?.[key])}</td><td>{!statusCurrent ? status.status === "error" ? "Koordinatorstatus nicht verfügbar" : "Aktueller Koordinatorstatus wird geprüft" : target === "default" || target === "new" ? "Je zugeordneter Budgetgruppe" : limitValue(observed?.profile[key])}</td></tr>;
        })}
      </tbody></table></div>
      {providerCeiling && <p className="adminInlineHelp">Betreiberdeklaration für Plan {providerCeiling.plan} · Prüfung durch den Betreiber: {providerCeiling.checked_date}. Geltungsbereich: {providerCeiling.scope}. Die Software hat diese Grenze nicht unabhängig verifiziert.</p>}
      <details className="installationSection" open={target === "new" || target === "new-endpoint" || profileNeedsCreation ? true : undefined}><summary>Lokales Betreiberprofil bearbeiten</summary><form className="adminForm" onSubmit={(event) => {
        event.preventDefault(); if (locked || !draft || !base || !config.data) return;
        if (draftConflict) { setError("Die Konfiguration wurde während der Bearbeitung geändert. Ihre Eingaben bleiben erhalten. Neu laden und den aktuellen Stand prüfen, bevor Sie erneut speichern."); return; }
        const errors: Record<string, string> = {};
        const values: Partial<Record<ProfileNumber, number | null>> = {};
        for (const field of LIMIT_FIELDS) {
          const raw = draft[field.key].trim();
          if (field.optional && !raw) { values[field.key] = null; continue; }
          const value = Number(raw);
          if (!raw || !Number.isFinite(value) || value < field.min || value > field.max || (field.step === "1" && !Number.isInteger(value))) errors[field.key] = `Wert zwischen ${field.min} und ${field.max}${field.step === "1" ? " als ganze Zahl" : ""} erforderlich.`;
          else values[field.key] = value;
        }
        if (Number(values.burst) > Math.min(Number(values.requests_per_second), values.requests_per_10_seconds == null ? Infinity : Number(values.requests_per_10_seconds), Number(values.requests_per_minute))) errors.burst = "Burst darf die Sekunden-, 10-Sekunden- und Minutengrenze nicht überschreiten.";
        if (Number(values.backoff_base_seconds) > Number(values.backoff_max_seconds)) errors.backoff_base_seconds = "Die anfängliche Wartezeit darf die maximale Basiswartezeit nicht überschreiten.";
        if (Number(values.timeout_seconds) > Number(values.job_deadline_seconds)) errors.timeout_seconds = "Der Request-Timeout darf die Gesamtdeadline nicht überschreiten.";
        if (target === "new" && (!GROUP_PATTERN.test(newGroup) || newGroup.startsWith("budget:ceiling:") || newGroup.startsWith("budget:endpoint:") || !!config.data.group_profiles[newGroup])) errors.group = "Eine gültige, neue Budgetgruppen-ID angeben. budget:ceiling: und budget:endpoint: sind reserviert; vorhandene Gruppen im Profilmenü auswählen.";
        if (selection && (endpoints.status !== "ready" || !endpointNames.has(selection.endpoint) || !providerNames.includes(selection.provider))) errors.endpoint = "Anbieter und unterstützten Endpunkt aus dem geladenen Katalog wählen.";
        setValidation(errors); if (Object.keys(errors).length) return;
        const profile = { ...base, ...values } as LimitProfile;
        const nextConfig = { ...config.data, ...(selection ? { endpoint_profiles: { ...config.data.endpoint_profiles, [selection.provider]: { ...config.data.endpoint_profiles?.[selection.provider], [selection.endpoint]: profile } } } : target === "default" ? { default_profile: profile } : { group_profiles: { ...config.data.group_profiles, [group]: profile } }) };
        if (!beginWrite()) return;
        void adminRequest<LimitConfig>("request-limits", "PUT", { config: nextConfig, expected_revision: config.data.revision }).then(() => {
          dirtyRef.current = false; setDraft(profileValues(profile)); setTarget(selection ? `endpoint-profile:${selection.provider}:${selection.endpoint}` : target === "new" ? group : target); setNewGroup(""); config.reload(); status.reload(); presets.reload(); setNotice("Lokales Limitprofil gespeichert. Kein externer Abruf und kein Zeitplan gestartet. Bestehende Budgetbelegung wurde nicht durch die Oberfläche zurückgesetzt.");
        }).catch((caught) => setError(caught instanceof Error ? caught.message : "Das Limitprofil konnte nicht gespeichert werden.")).finally(finishWrite);
      }}>
        <fieldset disabled={locked || !draft}><legend>Lokales Betreiberprofil bearbeiten</legend>
          <div className="formGrid">{LIMIT_FIELDS.map((field) => <div className="adminFormField" key={field.key}><span className="adminFieldLabel"><label htmlFor={`${id}-${field.key}`}>{field.label}</label><HelpTip label={field.label}>{field.help}</HelpTip></span>
            <input id={`${id}-${field.key}`} type="number" min={field.min} max={field.max} step={field.step} value={draft?.[field.key] ?? ""} inputMode={field.step === "1" ? "numeric" : "decimal"} aria-invalid={!!validation[field.key]} aria-describedby={`${id}-${field.key}-help${validation[field.key] ? ` ${id}-${field.key}-error` : ""}`} onChange={(event) => setDraft((previous) => previous ? { ...previous, [field.key]: event.target.value } : previous)} />
            <small className="adminInlineHelp" id={`${id}-${field.key}-help`}>{field.help}</small>{validation[field.key] && <small className="adminFieldError" id={`${id}-${field.key}-error`}>{validation[field.key]}</small>}
          </div>)}</div>
        </fieldset>
        <label>Automatisches Sync-Intervall (Sekunden)<input type="number" value={0} disabled aria-describedby={`${id}-sync-help`} /></label><small className="adminInlineHelp" id={`${id}-sync-help`}>0 = deaktiviert. Es gibt derzeit keinen aktivierten periodischen Sync-Scheduler. Speichern eines Profils plant keine Abrufe.</small>
        {validation.endpoint && <p role="alert" className="adminFieldError">{validation.endpoint}</p>}
        {draftConflict && <p role="alert" className="adminMessage error">Die Konfiguration wurde während der Bearbeitung geändert. Ihre Eingaben bleiben erhalten. Neu laden und den aktuellen Stand prüfen; der alte Entwurf wird nicht mit einer neueren Revision gespeichert.</p>}
        <div><button type="submit" className="primaryButton" disabled={locked || draftConflict || !draft || (selection !== null && endpoints.status !== "ready") || (!dirty && target !== "new" && !profileNeedsCreation)}><Save size={16} /> Limitprofil speichern</button></div>
      </form></details>
      <details className="installationSection"><summary>Gemeinsame Gruppen und Geltungsbereich</summary>
        <p>Börsen-/RPC-Connectoren verwenden das gemeinsame IP-Budget <code>ip:global</code> und ihr Anbieterbudget <code>provider:anbieter</code>. Zusätzliche Gruppen begrenzen gemeinsam. API-Key- oder IP-Wechsel zur Umgehung sind kein Einrichtungsablauf.</p>
        <p>KI-Verbindungen verwenden einen eigenen Providerbereich und die getrennte Budgetgruppe <code>ip:ai</code>. Tokenlimits der KI sind keine Requests-/Sekundenlimits.</p>
        {!!Object.keys(config.data.provider_groups).length && <ul>{Object.entries(config.data.provider_groups).map(([providerName, groups]) => <li key={providerName}>{providerName}: {groups.join(", ") || "keine zusätzlichen Gruppen"}</li>)}</ul>}
        <p className="adminInlineHelp">Lokale Kosteneinheiten sind keine bestätigten Anbieter-Credits. Ein Tages-/Abrechnungsbudget wird hier nicht angeboten, solange dessen technische Durchsetzung und Herstellersemantik nicht verfügbar sind.</p>
      </details>
      <details className="installationSection"><summary>Herstellergrenzen aus eigenem Tarif deklarieren</summary>
        <p className="adminInlineHelp">Optionale, vom Betreiber aus dem eigenen Tarif übertragene Obergrenzen. Nicht unabhängig verifiziert. Ohne Deklaration bleiben Herstellergrenzen unbekannt; lokale Schutzlimits bleiben aktiv. Der Server begrenzt zusätzlich auf den kleineren passenden Wert. Rollierende Sekunden-/10-Sekunden-/Minutenwerte ersetzen keine anders definierten Anbieterfenster.</p>
        {Object.entries(config.data.provider_ceilings ?? {}).map(([providerName, ceiling]) => <div className="adminStorageCheck" key={providerName}><strong>{REQUEST_PROVIDERS[providerName] ?? providerName} · {ceiling.plan}</strong><p>Betreiberdeklaration vom {ceiling.checked_date} · nicht unabhängig verifiziert</p><div className="adminRowActions"><button type="button" className="ghostButton" disabled={locked} onClick={() => editCeiling(providerName)}><Pencil size={16} /> Deklaration bearbeiten</button>{documentationUrl(ceiling.source_url) && <a href={documentationUrl(ceiling.source_url)} rel="noreferrer noopener" target="_blank">Hinterlegte Referenz öffnen</a>}</div></div>)}
        <form className="adminForm" onSubmit={(event) => {
          event.preventDefault(); if (locked || !config.data || dirty || !ceilingDraft.confirmed) return;
          if (ceilingDraft.revision === null || ceilingConflict) { setCeilingError("Die Tarifdeklaration stammt aus einem älteren Konfigurationsstand. Aktuellen Stand ausdrücklich laden und erneut prüfen; Ihre Eingaben wurden nicht gespeichert."); return; }
          const values: Record<string, number | null> = {};
          let invalid = false;
          for (const [key, maximum] of [["requests_per_second", 10000], ["requests_per_10_seconds", 100000], ["requests_per_minute", 100000], ["weighted_cost_per_minute", 100000000]] as const) {
            const raw = ceilingDraft[key].trim(); const value = Number(raw);
            if (!raw) values[key] = null;
            else if (!Number.isInteger(value) || value < 1 || value > maximum) invalid = true;
            else values[key] = value;
          }
          let validUrl = false;
          try { const url = new URL(ceilingDraft.source_url); validUrl = url.protocol === "https:" && !!url.hostname.includes(".") && !url.username && !url.password && !url.search && !url.hash && !url.port && !url.hostname.includes(":") && !/^\d+(?:\.\d+){3}$/.test(url.hostname) && !url.hostname.endsWith(".local") && !url.hostname.endsWith(".internal") && /^[\x21-\x7e]+$/.test(ceilingDraft.source_url); } catch { /* Invalid URLs are rejected before sending. */ }
          if (invalid || Object.values(values).every((value) => value === null) || !/^[a-z][a-z0-9_-]{0,47}$/.test(ceilingDraft.provider) || !/^[a-zA-Z0-9][a-zA-Z0-9 ._:+-]{0,79}$/.test(ceilingDraft.plan) || !/^\d{4}-\d{2}-\d{2}$/.test(ceilingDraft.checked_date) || !validUrl) {
            setCeilingError("Mindestens eine positive Grenze, gültige Anbieterkennung, Tarifname, Prüfdatum und öffentliche HTTPS-Referenz ohne Zugangsdaten, IP-Adresse oder Query-Parameter angeben."); return;
          }
          const ceiling = { ...config.data.provider_ceilings?.[ceilingDraft.provider], ...values, source_url: ceilingDraft.source_url, checked_date: ceilingDraft.checked_date, scope: ceilingDraft.scope, plan: ceilingDraft.plan, declared_by_operator: true, independently_verified: false };
          const nextConfig = { ...config.data, provider_ceilings: { ...config.data.provider_ceilings, [ceilingDraft.provider]: ceiling } };
          if (!beginWrite()) return;
          setCeilingError("");
          void adminRequest<LimitConfig>("request-limits", "PUT", { config: nextConfig, expected_revision: ceilingDraft.revision }).then(() => { setCeilingDraft((previous) => ({ ...previous, confirmed: false })); config.reload(); status.reload(); presets.reload(); setNotice("Tarifgrenze als Betreiberdeklaration gespeichert, nicht unabhängig verifiziert. Die Referenz wurde nicht aufgerufen; kein Abruf wurde gestartet."); }).catch((caught) => setError(caught instanceof Error ? caught.message : "Die Betreiberdeklaration konnte nicht gespeichert werden.")).finally(finishWrite);
        }}>
          <fieldset disabled={locked || dirty || ceilingConflict}><legend>Eigene Tarifdeklaration</legend><div className="formGrid">
            <label>Anbieterkennung für Tarifgrenze<select value={ceilingDraft.provider} onChange={(event) => updateCeilingDraft({ provider: event.target.value })}>{providerNames.map((providerName) => <option key={providerName} value={providerName}>{REQUEST_PROVIDERS[providerName] ?? providerName}</option>)}</select></label>
            <label>Nicht vertraulicher Tarifname<input value={ceilingDraft.plan} maxLength={80} autoComplete="off" onChange={(event) => updateCeilingDraft({ plan: event.target.value })} /></label>
            <label>Tarifgrenze Requests pro Sekunde<input type="number" min={1} max={10000} step={1} value={ceilingDraft.requests_per_second} onChange={(event) => updateCeilingDraft({ requests_per_second: event.target.value })} /></label>
            <label>Tarifgrenze Requests pro 10 Sekunden<input type="number" min={1} max={100000} step={1} value={ceilingDraft.requests_per_10_seconds} onChange={(event) => updateCeilingDraft({ requests_per_10_seconds: event.target.value })} /></label>
            <label>Tarifgrenze Requests pro Minute<input type="number" min={1} max={100000} step={1} value={ceilingDraft.requests_per_minute} onChange={(event) => updateCeilingDraft({ requests_per_minute: event.target.value })} /></label>
            <label>Tarifgrenze gewichtete Kosten pro Minute<input type="number" min={1} max={100000000} step={1} value={ceilingDraft.weighted_cost_per_minute} onChange={(event) => updateCeilingDraft({ weighted_cost_per_minute: event.target.value })} /></label>
            <div className="adminFormField"><label htmlFor={`${id}-ceiling-scope`}>Geltungsbereich der Tarifgrenze</label><select id={`${id}-ceiling-scope`} value={ceilingDraft.scope} onChange={(event) => updateCeilingDraft({ scope: event.target.value as ProviderCeiling["scope"] })}>{Object.entries({ provider: "Anbieter", ip: "IP-Adresse", account: "Anbieterkonto", api_key: "API-Key", project: "Projekt", endpoint_group: "Endpunktgruppe", combination: "Kombination" }).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></div>
            <label>Öffentliche Referenz zur Tarifgrenze<input type="url" value={ceilingDraft.source_url} maxLength={1024} autoComplete="off" onChange={(event) => updateCeilingDraft({ source_url: event.target.value })} /></label>
            <label>Prüfdatum der Tarifdeklaration<input type="date" value={ceilingDraft.checked_date} onChange={(event) => updateCeilingDraft({ checked_date: event.target.value })} /></label>
          </div><p className="adminInlineHelp">Leere Grenzfelder bedeuten unbekannt, nicht unbegrenzt. Ein Kostenwert darf nur bei passender, geprüfter Einheit und Zeitfenstersemantik übertragen werden. Keine vertraulichen Vertragsnotizen oder Secrets eingeben.</p>
          <label className="adminCheckbox"><input type="checkbox" checked={ceilingDraft.confirmed} onChange={(event) => { if (!ceilingConflict) setCeilingDraft({ ...ceilingDraft, confirmed: event.target.checked, revision: ceilingDraft.revision ?? config.data!.revision }); }} />Ich habe diese Angaben aus meinem Tarif geprüft. Sie sind eine Betreiberdeklaration, keine unabhängige Verifikation durch die Software.</label></fieldset>
          {dirty && <p className="adminInlineHelp">Zuerst Änderungen am Betreiberprofil speichern oder verwerfen.</p>}{ceilingError && <p className="adminFieldError" role="alert">{ceilingError}</p>}
          {ceilingConflict && <p role="alert" className="adminMessage error">Die Konfiguration wurde seit Beginn dieses Tarifentwurfs geändert. Die alten Eingaben bleiben sichtbar, sind aber nicht mehr bestätigt und können nicht gespeichert werden. Aktuellen Stand ausdrücklich laden und erneut prüfen.</p>}
          <div className="adminFormActions"><button className="primaryButton" type="submit" disabled={locked || dirty || ceilingConflict || !ceilingDraft.confirmed}><Save size={16} /> Tarifdeklaration speichern</button>
            <button className="ghostButton" type="button" disabled={locked} onClick={() => editCeiling(ceilingDraft.provider)}><RefreshCw size={16} /> Tarifentwurf verwerfen und aktuellen Stand laden</button></div>
        </form>
      </details>
      <details className="installationSection"><summary>Lokale Endpunktkosten</summary>
        <p className="adminInlineHelp">Lokale Gewichtung für das zusätzliche Kostenbudget. Keine bestätigten Herstellergewichte oder Compute Units. Nur öffentliche technische Kennungen verwenden, niemals vollständige URLs, Wallet-Adressen oder API-Keys.</p>
        <div className="adminLimitTableWrap" role="region" aria-label="Gespeicherte lokale Endpunktkosten" tabIndex={0}><table className="adminLimitTable"><thead><tr><th scope="col">Anbieterkennung</th><th scope="col">Endpunktkennung</th><th scope="col">Lokale Einheiten je Versuch</th><th scope="col">Aktion</th></tr></thead><tbody>
          {Object.entries(config.data.endpoint_costs ?? {}).flatMap(([providerName, costs]) => Object.entries(costs).map(([endpoint, cost]) => <tr key={`${providerName}:${endpoint}`}><th scope="row">{providerName}</th><td>{endpoint}</td><td>{cost}</td><td><button type="button" className="ghostButton" aria-label={`Lokale Kosten für ${providerName} ${endpoint} bearbeiten`} title="Vorhandenen lokalen Kostenwert ins Formular übernehmen" disabled={locked} onClick={() => { setCostProvider(providerName); setCostEndpoint(endpoint); setCostValue(String(cost)); setCostError(""); document.getElementById(`${id}-cost-value`)?.focus(); }}><Pencil size={16} /></button></td></tr>))}
        </tbody></table></div>
        {!Object.keys(config.data.endpoint_costs ?? {}).length && <p>Keine eigenen Endpunktgewichte gespeichert. Ohne spezielle Zuordnung verwendet der Connector den lokalen Standardwert; dies ist keine Herstellerkostenangabe.</p>}
        <form className="adminForm" onSubmit={(event) => {
          event.preventDefault(); if (locked || !config.data || dirty) return;
          const cost = Number(costValue);
          const supported = new Set(["default", ...(endpoints.data?.http ?? []).map((item) => item.id), ...(endpoints.data?.rpc ?? []).map((item) => item.id)]);
          if (endpoints.status !== "ready" || !Array.isArray(endpoints.data?.http) || !supported.has(costEndpoint)) { setCostError("Unterstützte Endpunktkennung aus der Liste wählen. Der Katalog muss erfolgreich geladen sein."); return; }
          if (!/^[a-z][a-z0-9_-]{0,47}$/.test(costProvider) || !/^[a-zA-Z][a-zA-Z0-9_.:-]{0,63}$/.test(costEndpoint) || !Number.isInteger(cost) || cost < 1 || cost > 100000000) { setCostError("Gültige Anbieter-/Endpunktkennung und ganze lokale Kosten zwischen 1 und 100000000 angeben."); return; }
          if (!beginWrite()) return;
          setCostError("");
          const nextConfig = { ...config.data, endpoint_costs: { ...config.data.endpoint_costs, [costProvider]: { ...config.data.endpoint_costs?.[costProvider], [costEndpoint]: cost } } };
          void adminRequest<LimitConfig>("request-limits", "PUT", { config: nextConfig, expected_revision: config.data.revision }).then(() => { config.reload(); status.reload(); presets.reload(); setNotice("Lokaler Endpunktkostenwert gespeichert. Keine Herstellerquote geändert und kein Request gestartet."); }).catch((caught) => setError(caught instanceof Error ? caught.message : "Endpunktkosten konnten nicht gespeichert werden.")).finally(finishWrite);
        }}>
          <fieldset disabled={locked || dirty}><legend>Lokalen Kostenwert hinterlegen</legend><div className="formGrid">
            <label>Anbieterkennung<select value={costProvider} onChange={(event) => setCostProvider(event.target.value)} aria-describedby={`${id}-cost-help`}>{providerNames.map((providerName) => <option key={providerName} value={providerName}>{REQUEST_PROVIDERS[providerName] ?? providerName}</option>)}</select></label>
            <label>Endpunktkennung<select value={costEndpoint} disabled={endpoints.status !== "ready"} onChange={(event) => setCostEndpoint(event.target.value)} aria-describedby={`${id}-cost-help`}>{!endpointNames.has(costEndpoint) && <option value={costEndpoint}>{costEndpoint}</option>}{Array.from(endpointNames, ([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
            <label htmlFor={`${id}-cost-value`}>Lokale Einheiten je Requestversuch<input id={`${id}-cost-value`} type="number" min={1} max={100000000} step={1} value={costValue} onChange={(event) => setCostValue(event.target.value)} aria-describedby={`${id}-cost-help`} /></label>
          </div></fieldset>
          <small id={`${id}-cost-help`} className="adminInlineHelp">Beispiele aus dem vorhandenen Connector: binance / account, bitget / spot_assets, pionex / balances, coinbase / accounts. Solana-RPC verwendet rpc_ plus kleingeschriebenen Methodennamen; default ist der Rückfallwert eines Anbieters. Ein frei erfundener Name trifft keinen Request-Pfad.</small>
          {dirty && <p className="adminInlineHelp">Zuerst Änderungen am Betreiberprofil speichern oder verwerfen, bevor Endpunktkosten bearbeitet werden.</p>}
          {costError && <p role="alert" className="adminFieldError">{costError}</p>}
          <div><button className="primaryButton" type="submit" disabled={locked || dirty || endpoints.status !== "ready"}><Save size={16} /> Endpunktkosten speichern</button></div>
        </form>
      </details>
    </>}
    <div className="installationSection"><h3>Lokale Auslastung und Wartezeiten</h3>
      <p className="adminInlineHelp">Lokale Messwerte, keine vom Anbieter gemeldete Restquote. Diese Ansicht liest nur den Koordinatorstatus und startet keine externen Requests.</p>
      {status.status === "loading" && <p role="status">Lokaler Abrufstatus wird geladen.{status.data ? " Der vorherige Stand bleibt sichtbar." : ""}</p>}
      {status.status === "error" && <p role="alert" className="adminMessage error">Der Abrufkoordinator konnte nicht gelesen werden. Keine Aussage über freie Kontingente möglich. <button type="button" className="ghostButton" onClick={status.reload}>Status erneut lesen</button></p>}
      {status.data?.clock_rollback && <p role="alert" className="adminMessage error">Die Systemzeit wurde zurückgestellt. Der Koordinator meldet einen gesonderten Wartezustand; Serverzeit administrativ prüfen.</p>}
      {status.status === "ready" && !status.data?.groups.length && <p>Noch keine aktive Budgetgruppe gemessen. Das ist weder eine freie Restquote noch ein Nachweis unbegrenzter Abrufe.</p>}
      {status.data && <>
        <p className="adminInlineHelp">Messzeitpunkt: {epochTime(status.data.observed_at)} · Konfigurationsrevision {status.data.config_revision}</p>
        <div className="adminLimitTableWrap" role="region" aria-label="Lokale Budgetauslastung" tabIndex={0}><table className="adminLimitTable"><thead><tr><th scope="col">Budgetgruppe</th><th scope="col">Starts: 1 s / 10 s / 60 s</th><th scope="col">Lokale Kosten: 60 s</th><th scope="col">Laufend / wartend</th><th scope="col">Wartehinweis</th><th scope="col">Nächster Start laut Koordinator</th></tr></thead><tbody>{status.data.groups.map((item) => <tr key={item.group}>
          <th scope="row">{item.provider && item.endpoint ? <>{REQUEST_PROVIDERS[item.provider] ?? item.provider} · {endpointNames.get(item.endpoint) ?? item.endpoint}</> : item.group.startsWith("budget:endpoint:") ? "Endpunktbudget (Zuordnung nicht gemeldet)" : <code>{item.group}</code>}</th><td>{item.requests_last_second} / {item.requests_last_10_seconds ?? "Nicht gemeldet"} / {item.requests_last_minute}</td><td>{item.cost_last_minute}</td><td>{item.in_flight} / {item.queued}</td>
          <td>{item.paused_until ? `Anbieterpause bis ${epochTime(item.paused_until)}` : "Keine Anbieterpause gemeldet"}{item.blocking_reasons.length > 0 && <div>{item.blocking_reasons.map((reason) => BLOCK_REASONS[reason] ?? "Lokale Budgetbedingung").join(", ")}</div>}</td><td>{epochTime(item.next_start_at)}</td>
        </tr>)}</tbody></table></div>
        <details className="installationSection"><summary>Tatsächlich gemeldete Anbieterwerte</summary>
          <p className="adminInlineHelp">Nur vom Adapter gelesene Header. Keine Schätzung aus lokalen Starts und kein zugesagtes Tarifbudget. Fehlender Wert bedeutet unbekannt, nicht null.</p>
          {!Object.keys(status.data.provider_observations ?? {}).length ? <p>Noch keine Anbieter-Headerwerte gemeldet.</p> : <div className="adminLimitTableWrap" role="region" aria-label="Vom Anbieter gemeldete Kontingentwerte" tabIndex={0}><table className="adminLimitTable"><thead><tr><th scope="col">Anbieter</th><th scope="col">Gemeldet am</th><th scope="col">Letzte Limitantwort</th><th scope="col">Genutztes 1-Minuten-Gewicht</th><th scope="col">Gemeldete verbleibende Requests</th><th scope="col">Gemeldete Rücksetzung</th></tr></thead><tbody>{Object.entries(status.data.provider_observations ?? {}).map(([providerName, observation]) => <tr key={providerName}><th scope="row">{PROVIDERS[providerName] ?? providerName}</th><td>{epochTime(observation.last_observed_at)}</td><td>{epochTime(observation.last_rate_limit_at)}</td><td>{observation.used_weight_1m ?? "Nicht gemeldet"}</td><td>{observation.remaining_requests ?? "Nicht gemeldet"}</td><td>{epochTime(observation.reset_at)}</td></tr>)}</tbody></table></div>}
        </details>
        <details className="installationSection"><summary>Technischer Umfang der Messung</summary><p>Koordination: gemeinsames host-lokales Dateisystem mit atomarer Sperre. Mehrere Hosts benötigen einen dafür geeigneten gemeinsamen Koordinator; diese Anzeige bestätigt keine hostübergreifende Durchsetzung.</p><p>Ungeklärte laufende Reservierungen werden nicht automatisch als frei gezählt. Nach einem Ausfall kann eine administrative Prüfung erforderlich sein. Alle alten Worker und HTTP-Aufrufe müssen nachweislich beendet sein, bevor eine administrative Wiederherstellung unter exklusivem Zugriff geprüft wird. Kein automatischer Reset.</p></details>
      </>}
    </div>
    <details className="installationSection"><summary>Anbieterunterlagen und Prüfgrenzen</summary>
      {references.status === "loading" && <p role="status">Hinterlegte Quellenangaben werden geladen. Es wird kein Anbieter angefragt.</p>}
      {references.status === "error" && <p role="alert" className="adminMessage error">Die hinterlegten Quellenangaben konnten nicht geladen werden. Herstellerobergrenzen bleiben unbestätigt. <button className="ghostButton" type="button" onClick={references.reload}>Quellenangaben neu lesen</button></p>}
      {references.data && <><p>Dokumentationsprüfung: <time dateTime={references.data.checked_at}>{references.data.checked_at}</time>. Tarif, Projekt und Endpunkt können zusätzliche Grenzen haben. Dies ist kein Nachweis einer für Ihr Konto gültigen Quote.</p>
        {references.data.providers.map((reference, index) => <div className="adminStorageCheck" key={`${reference.provider}-${index}`}><strong>{PROVIDERS[reference.provider] ?? reference.provider}</strong><p>{reference.scope}</p><p className="adminInlineHelp">{reference.limitation}</p>{documentationUrl(reference.source_url) && <a href={documentationUrl(reference.source_url)} rel="noreferrer noopener" target="_blank">Offizielle Dokumentation öffnen</a>}</div>)}
      </>}
    </details>
  </section>;
}
