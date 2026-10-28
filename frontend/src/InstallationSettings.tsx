import { useEffect, useState } from "react";
import { RefreshCw, Save, Trash2 } from "lucide-react";
import { API_BASE } from "./api-base";
import { HelpTip } from "./Help";
import { AdminEnvironmentState, useAdminEnvironment } from "./ConnectionSettings";
import { VersionUpdates } from "./VersionUpdates";

type Field = {
  key: string; label: string; group: string; kind: "account" | "path" | "url" | "text";
  value: string; source: string; editable: boolean;
};
type Settings = {
  fields: Field[]; revision: string; restart_required: boolean;
  profile_writable: boolean; encrypted_secrets_available: boolean; providers: Record<string, boolean>;
  profile_issue?: string | null; server_time_utc?: string; demo_mode?: boolean;
  storage_checks?: Array<{ code: string; status: "ready" | "blocked"; label: string; detail: string; action: string }>;
};
type ConfigDocument = { filename: string; content: string; revision: string };
const CONFIGS = [
  "source_registry.json", "solana_v1_ownership_scope.json", "solana_service_swap_tax_mappings.json",
  "pionex_hnt_reconciliation.json", "fairspot_hnt_staking_reconciliation.json", "solana_staking_position_reconciliations.json",
  "token_conversion_mappings.json"
];
const HIDDEN_FIELDS = ["v1_fx_db_file", "v1_connector_base_url", "local_llm_base", "local_llm_model"];
const PROFILE_ISSUES: Record<string, string> = {
  profile_disabled: "Kein privates Profil konfiguriert.",
  profile_symlink: "Das Profil ist eine symbolische Verknüpfung; eine reguläre private Profildatei verwenden.",
  profile_inside_software: "Das Profil liegt im Softwareverzeichnis statt im privaten Datenvolume.",
  profile_permission_denied: "Der Dienstbenutzer hat keine ausreichenden Schreibrechte auf die Profildatei oder ihr Verzeichnis.",
  profile_readonly_filesystem: "Das Dateisystem des privaten Profils ist schreibgeschützt eingebunden.",
  profile_not_regular_file: "Der konfigurierte Profilpfad ist keine reguläre Datei.",
  profile_storage_unavailable: "Der Speicherort des privaten Profils ist derzeit nicht zugänglich."
};

async function request<T>(path: string, method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1/admin/installation${path}`, {
    signal, method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok || result.status === "error") {
    const errors: Record<string, string> = {
      profile_revision_conflict: "Die Konfiguration wurde zwischenzeitlich geändert. Vor erneutem Speichern neu laden.",
      config_revision_conflict: "Die Datei wurde zwischenzeitlich geändert. Vor erneutem Speichern neu laden.",
      config_json_or_schema_invalid: "JSON oder Konfigurationsschema ist ungültig.",
      encrypted_secret_vault_required: "Ein verschlüsselter Secret-Vault ist erforderlich. Die Administration muss den Schlüssel sicher bereitstellen.",
      profile_url_invalid_or_contains_credentials: "Die Dienstadresse muss eine HTTP(S)-URL ohne Zugangsdaten, Query-Parameter oder Fragment sein.",
      profile_location_not_writable: "Das private Profil muss außerhalb des Softwareverzeichnisses liegen und für den Dienstbenutzer beschreibbar sein.",
      profile_unreadable: "Das private Profil ist nicht lesbar. Dateipfad und Leserechte des Dienstbenutzers administrativ prüfen.",
      profile_invalid: "Das private Profil ist kein gültiges Einstellungsdokument. Eine gesicherte Profilkopie administrativ prüfen.",
      profile_write_failed: "Das Profil konnte nicht gespeichert werden. Verzeichnis, freien Speicher und Schreibrechte des Dienstbenutzers prüfen.",
      config_write_failed: "Die Belegkonfiguration konnte nicht gespeichert werden. Privates Konfigurationsverzeichnis administrativ prüfen."
    };
    throw new Error(errors[typeof result.detail === "string" ? result.detail : ""] || "Die Einstellungen konnten nicht verarbeitet werden. Es wurde kein Erfolg bestätigt.");
  }
  return result.data as T;
}

export function InstallationSettings() {
  const environment = useAdminEnvironment();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filename, setFilename] = useState(CONFIGS[0]);
  const [document, setDocument] = useState<ConfigDocument | null>(null);
  const [content, setContent] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [documentLoading, setDocumentLoading] = useState(false);
  const [documentError, setDocumentError] = useState("");
  const [documentAttempt, setDocumentAttempt] = useState(0);

  async function load(preserveDraft = false) {
    const result = await request<Settings>("");
    setSettings(result);
    if (!preserveDraft) setValues(Object.fromEntries(result.fields.map((field) => [field.key, field.value])));
  }
  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Die Einstellungen konnten nicht geladen werden.");
    } finally { setBusy(false); }
  }
  useEffect(() => { const controller = new AbortController();
    setBusy(true);
    void request<Settings>("", "GET", undefined, controller.signal).then((result) => {
      setSettings(result); setValues(Object.fromEntries(result.fields.map((field) => [field.key, field.value])));
    }).catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Die Einstellungen konnten nicht geladen werden."); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!advancedOpen) return;
    const controller = new AbortController();
    setDocument(null); setContent(""); setDocumentError(""); setDocumentLoading(true);
    void request<ConfigDocument>(`/configs/${filename}`, "GET", undefined, controller.signal).then((result) => {
      if (!controller.signal.aborted) { setDocument(result); setContent(result.content); }
    }).catch(() => { if (!controller.signal.aborted) setDocumentError("Die Konfigurationsdatei konnte nicht geladen werden."); })
      .finally(() => { if (!controller.signal.aborted) setDocumentLoading(false); });
    return () => controller.abort();
  }, [filename, advancedOpen, documentAttempt]);

  const visibleFields = settings?.fields.filter((field) => !HIDDEN_FIELDS.includes(field.key) && field.key !== "solana_rpc_url") ?? [];
  const dirty = visibleFields.some((field) => field.editable && values[field.key] !== field.value);
  const demo = environment.data?.synthetic_preview === true || settings?.demo_mode === true;
  const locked = environment.locked || demo || busy || !settings?.profile_writable;
  const primaryFields = visibleFields.filter((field) => field.kind === "path");
  const otherFields = visibleFields.filter((field) => field.kind !== "path");
  const renderFields = (fields: Field[]) => [...new Set(fields.map((field) => field.group))].map((group) => <fieldset key={group} disabled={locked}>
    <legend>{group}</legend>
    <div className="formGrid">{fields.filter((field) => field.group === group).map((field) => <label key={field.key}>
      {field.label}{!field.editable && <small>Durch die Serverumgebung verwaltet</small>}
      <input type={field.kind === "url" ? "url" : "text"} value={values[field.key] ?? ""} disabled={!field.editable}
        autoComplete="off" spellCheck={false} maxLength={2048} onChange={(event) => setValues((previous) => ({ ...previous, [field.key]: event.target.value }))} />
    </label>)}</div>
  </fieldset>);
  return <section className="installationSettings" aria-label="Installation">
    <div className="panelToolbar">
      <div className="pageTitle"><h2>Installation</h2><HelpTip label="Private Installationseinstellungen">Profil, Daten und Belege gehören in private, dauerhaft eingebundene Verzeichnisse außerhalb des Softwareverzeichnisses. Speichern startet weder einen externen Abruf noch eine Neuberechnung.</HelpTip></div>
      <button type="button" className="ghostButton" title="Installationseinstellungen neu laden" aria-label="Installationseinstellungen neu laden" disabled={busy}
        onClick={() => { if (!dirty || window.confirm("Ungespeicherte Profiländerungen verwerfen?")) void act(load); }}><RefreshCw size={16} /></button>
    </div>
    <p className="adminSectionIntro">Privates Profil, Speicherfähigkeit und Dateizuordnungen. Datenanbieter, eigene Verbindungen und KI werden getrennt eingerichtet.</p>
    <AdminEnvironmentState environment={environment} />
    {error && <p role="alert" className="adminMessage error">{error}</p>}
    {notice && <p role="status" className="adminMessage">{notice}</p>}
    {!settings && !error && <p role="status">Installationseinstellungen werden geladen.</p>}
    {settings && <dl className="adminCheckList">
      <div><dt>Privates Profil</dt><dd>{demo ? "Demo: Änderungen gesperrt" : settings.profile_writable ? "Vom Backend als beschreibbar gemeldet" : "Administrative Prüfung erforderlich"}</dd></div>
      <div><dt>Verschlüsselter Secret-Vault</dt><dd>{demo ? "Demo: Secretspeicherung deaktiviert" : settings.encrypted_secrets_available ? "Verfügbar" : "Nicht verfügbar"}</dd><small>Kein Speichern von Zugangsdaten ohne Verschlüsselung.</small></div>
      <div><dt>Konfigurationsstand</dt><dd>{settings.restart_required ? "Neustart erforderlich" : "Kein Neustart gemeldet"}</dd><small>Kein Nachweis für vollständige Imports oder Anbieterzugriffe.</small></div>
    </dl>}
    {settings?.server_time_utc && <p className="adminInlineHelp">Serverzeit bei der Prüfung: <time dateTime={settings.server_time_utc}>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "long", timeZone: "UTC" }).format(new Date(settings.server_time_utc))}</time> · UTC</p>}
    {!demo && !!settings?.storage_checks?.length && <div className="adminStorageChecks" aria-label="Prüfung der privaten Speicherung">{settings.storage_checks.map((check) => <div className="adminStorageCheck" key={check.code}>
      <strong>{check.label} · {check.status === "ready" ? "Bereit" : "Administrative Klärung erforderlich"}</strong><p>{PROFILE_ISSUES[check.detail] ?? check.detail}</p>{check.status === "blocked" && <p className="adminInlineHelp">Nächster Schritt: {check.action}</p>}
    </div>)}</div>}
    {settings && !demo && !settings.profile_writable && !settings.storage_checks?.length && <div className="adminMessage error" role="alert">
      Das private Profil liegt am falschen Ort oder ist nicht beschreibbar. Die Administration muss <code>STEUERREPORT_PRIVATE_PROFILE</code> außerhalb des Softwareverzeichnisses konfigurieren und gezielt die Eigentümer-/Schreibrechte des Dienstbenutzers prüfen. Keine allgemeinen Schreibrechte vergeben.
    </div>}
    {settings && !demo && !settings.encrypted_secrets_available && <details className="installationSection"><summary>Verschlüsselte Speicherung administrativ vorbereiten</summary><p>Den Vault-Schlüssel über <code>STEUERREPORT_V2_SECRET_VAULT_KEY_FILE</code> sicher für den Dienst bereitstellen. Schlüsseldatei und private Daten dauerhaft und getrennt vom Image einbinden; Zugriff auf den Dienstbenutzer begrenzen. Schlüssel nicht in Quellcode, Profiltext, URL oder Chat eintragen. Es gibt keinen Klartext-Ersatz.</p></details>}
    {settings?.restart_required && !demo && <p role="status" className="adminMessage">Gespeicherte Konto-/Dateizuordnungen erfordern einen API- oder Container-Neustart. Bestehende Auswertungen wurden nicht neu berechnet.</p>}
    <form onSubmit={(event) => {
      event.preventDefault(); if (!settings || locked) return;
      void act(async () => {
        const changed = Object.fromEntries(visibleFields.filter((field) => field.editable && values[field.key] !== field.value).map((field) => [field.key, values[field.key] ?? ""]));
        const result = await request<Settings>("", "PUT", { revision: settings.revision, values: changed });
        setSettings(result); setValues(Object.fromEntries(result.fields.map((field) => [field.key, field.value]))); setNotice("Privates Profil gespeichert. Es wurde kein Abruf gestartet.");
      });
    }}>
      {renderFields(primaryFields)}
      <details className="installationSection"><summary>Bestehende Wallet-, Gegenpartei- und Abgleichzuordnungen</summary>
        <p className="adminInlineHelp">Bestehende Profilzuordnungen bleiben erhalten. Ein Eintrag ist weder ein Eigentumsnachweis noch die fachliche Aktivierung einer Steuerquelle.</p>{renderFields(otherFields)}
      </details>
      <button type="submit" className="primaryButton" disabled={locked || !dirty}><Save size={16} /> Profil speichern</button>
    </form>
    <details className="installationSection" onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}><summary>Erweiterte Quellen- und Belegkonfiguration</summary>
      <p className="adminInlineHelp">Nur geprüfte Quellen-/Belegzuordnungen bearbeiten. Keine API-Keys oder sonstigen Secrets in JSON ablegen. Eine Änderung übernimmt keine fachliche Review-Entscheidung.</p>
      {documentLoading && <p role="status">Belegkonfiguration wird geladen.</p>}
      {documentError && <p role="alert" className="adminMessage error">{documentError} <button className="ghostButton" type="button" onClick={() => setDocumentAttempt((value) => value + 1)}>Erneut laden</button></p>}
      <form onSubmit={(event) => { event.preventDefault(); if (!document || environment.locked || demo || busy) return; void act(async () => {
        const result = await request<ConfigDocument>(`/configs/${filename}`, "PUT", { revision: document.revision, content });
        setDocument(result); await load(true); setNotice("Private Belegkonfiguration gespeichert. Keine Berechnung wurde gestartet.");
      }); }}>
          <label htmlFor="admin-installation-document">Konfigurationsdatei</label><select id="admin-installation-document" value={filename} disabled={busy} onChange={(event) => {
          if (!document || content === document.content || window.confirm("Ungespeicherte Dateiänderungen verwerfen?")) setFilename(event.target.value);
        }}>{CONFIGS.map((file) => <option key={file} value={file}>{file}</option>)}</select>
        <label>JSON-Belegkonfiguration<textarea rows={12} value={content} autoComplete="off" spellCheck={false} disabled={busy || !document || environment.locked || demo}
          onChange={(event) => setContent(event.target.value)} /></label>
        <button type="submit" className="primaryButton" disabled={busy || environment.locked || demo || !document || content === document.content}><Save size={16} /> Belegdatei speichern</button>
      </form>
    </details>
    <VersionUpdates />
  </section>;
}

export function DataProviderSettings() {
  const environment = useAdminEnvironment();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [provider, setProvider] = useState("solscan");
  const [secret, setSecret] = useState("");
  const [rpc, setRpc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function load(preserveDraft = false) {
    const result = await request<Settings>(""); setSettings(result);
    if (!preserveDraft) setRpc(result.fields.find((field) => field.key === "solana_rpc_url")?.value ?? "");
  }
  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (caught) { setError(caught instanceof Error ? caught.message : "Die Anbieter-Einstellung konnte nicht verarbeitet werden."); }
    finally { setBusy(false); }
  }
  useEffect(() => { void act(load); }, []);
  const rpcField = settings?.fields.find((field) => field.key === "solana_rpc_url");
  const modeLocked = environment.locked || settings?.demo_mode === true;
  const secretLocked = busy || modeLocked || !settings?.encrypted_secrets_available;
  return <section className="installationSettings" aria-label="Datenanbieter">
    <div className="panelToolbar"><div className="pageTitle"><h2>Datenanbieter</h2><HelpTip label="Datenanbieter und Kontoverbindungen">RPC und Blockchain-Dienste liefern technische Daten. Börsenkonten werden unter Eigene Verbindungen eingerichtet. Ein gespeicherter Key bestätigt noch keinen erfolgreichen Anbieterzugriff.</HelpTip></div>
      <button type="button" className="ghostButton" aria-label="Datenanbieter neu laden" title="Datenanbieter neu laden" disabled={busy} onClick={() => void act(() => load(true))}><RefreshCw size={16} /></button></div>
    <p className="adminSectionIntro">RPC und Zugangsdaten für Blockchain-Dienste. Speichern und Anbieterauswahl lösen keine externen Requests aus.</p>
    <AdminEnvironmentState environment={environment} />
    {error && <p role="alert" className="adminMessage error">{error}</p>}
    {notice && <p role="status" className="adminMessage">{notice}</p>}
    {!settings && !error && <p role="status">Datenanbieter werden geladen.</p>}
    {settings && <>
      <form className="adminForm" onSubmit={(event) => { event.preventDefault(); if (!rpcField?.editable || modeLocked || !settings.profile_writable || busy) return;
        void act(async () => { const result = await request<Settings>("", "PUT", { revision: settings.revision, values: { solana_rpc_url: rpc } }); setSettings(result); setRpc(result.fields.find((field) => field.key === "solana_rpc_url")?.value ?? ""); setNotice("RPC-Adresse gespeichert. Kein Verbindungstest und kein Abruf gestartet."); });
      }}>
        <label>Solana-RPC-Endpunkt<input type="url" autoComplete="off" value={rpc} disabled={busy || modeLocked || !settings.profile_writable || !rpcField?.editable} onChange={(event) => setRpc(event.target.value)} aria-describedby="admin-rpc-help" /></label>
        <small id="admin-rpc-help" className="adminInlineHelp">Nur Dienstadresse ohne eingebetteten API-Key, Passwort oder Query-Parameter. Durch die Serverumgebung verwaltete Adressen sind hier nicht änderbar.</small>
        <div><button type="submit" className="primaryButton" disabled={busy || modeLocked || !settings.profile_writable || !rpcField?.editable || rpc === rpcField.value}><Save size={16} /> RPC-Adresse speichern</button></div>
      </form>
      <form className="adminForm installationSection" onSubmit={(event) => {
        event.preventDefault(); if (secretLocked || !secret.trim()) return;
        void act(async () => { await request(`/providers/${provider}`, "PUT", { api_key: secret }); setSecret(""); await load(true); setNotice("API-Key verschlüsselt gespeichert. Der Anbieterzugang wurde nicht getestet."); });
      }}>
        {!settings.encrypted_secrets_available && <p role="status" className="adminMessage">{environment.data?.synthetic_preview || settings.demo_mode ? "In dieser Demo ist die Secretspeicherung absichtlich deaktiviert. Keine produktiven Zugangsdaten eingeben." : "Secret-Vault nicht verfügbar. Die Administration muss die verschlüsselte Speicherung unter Installation vorbereiten."}</p>}
        <div className="formGrid"><div className="adminFormField"><label htmlFor="admin-data-provider">Datenanbieter</label><select id="admin-data-provider" value={provider} disabled={busy} onChange={(event) => { setProvider(event.target.value); setSecret(""); }}>
          <option value="solscan">Solscan</option><option value="alchemy">Alchemy</option><option value="jupiter">Jupiter</option><option value="helius">Helius</option>
        </select></div><label>Neuer API-Key<input type="password" autoComplete="new-password" value={secret} disabled={secretLocked} onChange={(event) => setSecret(event.target.value)} aria-describedby="admin-provider-key-help" /></label></div>
        <p id="admin-provider-key-help" className="adminInlineHelp">API-Key {settings.providers[provider] ? "vorhanden" : "fehlt"} · Zugang nicht durch diese Anzeige geprüft. Leer lassen behält den gespeicherten Key unverändert.</p>
        {(provider === "alchemy" || provider === "helius") && <p className="adminInlineHelp">Abruflimits getrennt unter <strong>Abrufsteuerung → Limitprofil → {provider === "alchemy" ? "Alchemy" : "Helius"} · eigenes Anbieterlimit</strong> einstellen. Das Speichern des Keys erhöht keine Quote.{provider === "alchemy" ? " CU/s aus dem Alchemy-Tarif nicht als Requests/s übernehmen." : " RPC- und DAS-/Enhanced-API-Limits unterscheiden."}</p>}
        <div className="adminFormActions"><button type="submit" className="primaryButton" disabled={secretLocked || !secret.trim()}><Save size={16} /> API-Key speichern</button>
          <button type="button" className="ghostButton adminDanger" disabled={secretLocked || !settings.providers[provider]} onClick={() => {
            if (!window.confirm("Den gespeicherten API-Key dieses Datenanbieters entfernen? Ein leerer Eingabewert allein löscht nichts.")) return;
            void act(async () => { await request(`/providers/${provider}`, "DELETE"); setSecret(""); await load(true); setNotice("API-Key entfernt. Bestehende Quelldaten bleiben erhalten."); });
          }}><Trash2 size={16} /> API-Key entfernen</button></div>
      </form>
      <p className="adminInlineHelp">Abruflimits gelten unabhängig vom gespeicherten Key. Wirksame Profile und lokale Auslastung stehen im Bereich Abrufsteuerung. Ein Anbieterwechsel erhöht kein gemeinsames Budget.</p>
    </>}
  </section>;
}
