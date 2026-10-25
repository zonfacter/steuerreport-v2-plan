import { useEffect, useState } from "react";
import { RefreshCw, Save, Trash2 } from "lucide-react";
import { API_BASE } from "./api-base";

type Field = {
  key: string; label: string; group: string; kind: "account" | "path" | "url" | "text";
  value: string; source: string; editable: boolean;
};
type Settings = {
  fields: Field[]; revision: string; restart_required: boolean;
  profile_writable: boolean; encrypted_secrets_available: boolean; providers: Record<string, boolean>;
};
type ConfigDocument = { filename: string; content: string; revision: string };

const CONFIGS = [
  "source_registry.json", "solana_v1_ownership_scope.json", "solana_service_swap_tax_mappings.json",
  "pionex_hnt_reconciliation.json", "fairspot_hnt_staking_reconciliation.json", "solana_staking_position_reconciliations.json"
];

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1/admin/installation${path}`, {
    method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const result = await response.json();
  if (!response.ok || result.status === "error") {
    const errors: Record<string, string> = {
      profile_revision_conflict: "Konfiguration wurde zwischenzeitlich geaendert. Bitte neu laden.",
      config_revision_conflict: "Datei wurde zwischenzeitlich geaendert. Bitte neu laden.",
      config_json_or_schema_invalid: "JSON oder Quellenregister-Schema ist ungueltig.",
      encrypted_secret_vault_required: "Verschluesselten Secret-Vault zuerst einrichten.",
      profile_url_invalid_or_contains_credentials: "Dienstadresse muss eine HTTP(S)-URL ohne Zugangsdaten oder Query-Parameter sein."
    };
    throw new Error(errors[result.detail] || "Einstellungen konnten nicht verarbeitet werden.");
  }
  return result.data as T;
}

export function InstallationSettings() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [provider, setProvider] = useState("solscan");
  const [secret, setSecret] = useState("");
  const [filename, setFilename] = useState(CONFIGS[0]);
  const [document, setDocument] = useState<ConfigDocument | null>(null);
  const [content, setContent] = useState("");

  async function load(preserveDraft = false) {
    const result = await request<Settings>("");
    setSettings(result);
    if (!preserveDraft) setValues(Object.fromEntries(result.fields.map((field) => [field.key, field.value])));
  }
  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Einstellungen konnten nicht geladen werden.");
    } finally { setBusy(false); }
  }
  useEffect(() => { void act(load); }, []);
  useEffect(() => {
    let active = true;
    setDocument(null); setContent("");
    void request<ConfigDocument>(`/configs/${filename}`).then((result) => {
      if (active) { setDocument(result); setContent(result.content); }
    }).catch(() => { if (active) setError("Konfigurationsdatei konnte nicht geladen werden."); });
    return () => { active = false; };
  }, [filename]);

  const dirty = settings?.fields.some((field) => field.editable && values[field.key] !== field.value) ?? false;
  const visibleFields = settings?.fields.filter((field) => !["v1_fx_db_file", "v1_connector_base_url"].includes(field.key)) ?? [];
  const groups = [...new Set(visibleFields.map((field) => field.group))];
  return (
    <section className="installationSettings" aria-label="Installation und Konten">
      <div className="panelToolbar">
        <h2>Installation und Konten</h2>
        <button type="button" className="ghostButton" title="Einstellungen neu laden" aria-label="Einstellungen neu laden" disabled={busy}
          onClick={() => { if (!dirty || window.confirm("Ungespeicherte Aenderungen verwerfen?")) void act(load); }}><RefreshCw size={16} /></button>
      </div>
      {error && <p role="alert" className="installationMessage error">{error}</p>}
      {notice && <p role="status" className="installationMessage">{notice}</p>}
      {!settings && !error && <p role="status">Einstellungen werden geladen.</p>}
      {settings?.restart_required && <p role="status" className="installationMessage">Gespeichert. API beziehungsweise Container neu starten, damit Konto- und Dateizuordnungen aktiv werden. Bestehende Auswertungen wurden nicht neu berechnet.</p>}
      {settings && !settings.profile_writable && <p role="alert">Das private Profil ist schreibgeschuetzt oder liegt im Softwareverzeichnis.</p>}
      <form onSubmit={(event) => {
        event.preventDefault();
        if (!settings) return;
        void act(async () => {
          const changed = Object.fromEntries(settings.fields.filter((field) => field.editable && values[field.key] !== field.value).map((field) => [field.key, values[field.key] ?? ""]));
          const result = await request<Settings>("", "PUT", { revision: settings.revision, values: changed });
          setSettings(result); setValues(Object.fromEntries(result.fields.map((field) => [field.key, field.value]))); setNotice("Private Konfiguration gespeichert.");
        });
      }}>
        {groups.map((group) => <fieldset key={group} disabled={busy || !settings?.profile_writable}>
          <legend>{group}</legend>
          <div className="formGrid">{visibleFields.filter((field) => field.group === group).map((field) => <label key={field.key}>
            {field.label}{!field.editable && <small>Durch Umgebung verwaltet</small>}
            <input type={field.kind === "url" ? "url" : "text"} value={values[field.key] ?? ""} disabled={!field.editable}
              autoComplete="off" spellCheck={false} maxLength={2048} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })} />
          </label>)}</div>
        </fieldset>)}
        <button type="submit" className="primaryButton" disabled={busy || !dirty || !settings?.profile_writable}><Save size={16} /> Konfiguration speichern</button>
      </form>
      {settings && <form className="installationSection" onSubmit={(event) => {
        event.preventDefault(); void act(async () => {
          await request(`/providers/${provider}`, "PUT", { api_key: secret }); setSecret(""); await load(true); setNotice("API-Key verschluesselt gespeichert.");
        });
      }}>
        <h3>Provider-Zugangsdaten</h3>
        {!settings.encrypted_secrets_available && <p role="status">Verschluesselter Secret-Vault noch nicht eingerichtet.</p>}
        <div className="formGrid"><label>Provider<select value={provider} disabled={busy} onChange={(event) => { setProvider(event.target.value); setSecret(""); }}>
          <option value="solscan">Solscan</option><option value="alchemy">Alchemy</option><option value="jupiter">Jupiter</option><option value="helius">Helius</option>
        </select></label><label>API-Key {settings.providers[provider] ? "(vorhanden)" : "(fehlt)"}
          <input type="password" autoComplete="new-password" value={secret} disabled={busy} onChange={(event) => setSecret(event.target.value)} /></label></div>
        <div className="installationActions"><button type="submit" className="primaryButton" disabled={busy || !secret.trim() || !settings.encrypted_secrets_available}><Save size={16} /> API-Key speichern</button>
          <button type="button" className="ghostButton" title="API-Key entfernen" aria-label="API-Key entfernen" disabled={busy || !settings.providers[provider]}
            onClick={() => { if (window.confirm("Gespeicherten API-Key entfernen?")) void act(async () => { await request(`/providers/${provider}`, "DELETE"); await load(true); setNotice("API-Key entfernt."); }); }}><Trash2 size={16} /></button></div>
      </form>}
      <details className="installationSection"><summary>Erweiterte Quellen- und Belegkonfiguration</summary>
        <form onSubmit={(event) => { event.preventDefault(); if (!document) return; void act(async () => {
          const result = await request<ConfigDocument>(`/configs/${filename}`, "PUT", { revision: document.revision, content });
          setDocument(result); await load(true); setNotice("Private Belegkonfiguration gespeichert; keine Pipeline ausgefuehrt.");
        }); }}>
          <label>Konfigurationsdatei<select value={filename} disabled={busy} onChange={(event) => {
            if (!document || content === document.content || window.confirm("Ungespeicherte Dateiaenderungen verwerfen?")) setFilename(event.target.value);
          }}>{CONFIGS.map((file) => <option key={file} value={file}>{file}</option>)}</select></label>
          <label>JSON<textarea rows={12} value={content} autoComplete="off" spellCheck={false} disabled={busy || !document}
            onChange={(event) => setContent(event.target.value)} /></label>
          <button type="submit" className="primaryButton" disabled={busy || !document || content === document.content}><Save size={16} /> Datei speichern</button>
        </form>
      </details>
    </section>
  );
}
