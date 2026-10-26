import { useEffect, useRef, useState } from "react";
import { BookOpen, Bot, Check, Download, LoaderCircle, Play, RefreshCw, Save, Trash2 } from "lucide-react";
import { API_BASE } from "./api-base";
import { AiChangesWorkspace } from "./AiChangesWorkspace";
import { AiAgentProfiles, loadAgents, type Agents } from "./AiAgentProfiles";
import { HelpTip } from "./Help";

type Config = { provider: "local" | "openrouter" | "cloud"; base_url: string; model: string; max_tokens: number; probe_max_tokens: number; timeout_seconds: number; token_parameter: "max_tokens" | "max_completion_tokens"; thinking: "server_default" | "llamacpp_off" | "ollama_off" };
type Settings = { config: Config; revision: string; local_enabled: boolean; external_enabled: boolean; api_key_present: boolean; api_key_readable: boolean; encrypted_secrets_available: boolean; configured: boolean; source: string };
type Task = { task_id: string; task_type: string; prompt: string; status: string; result_json?: string; allow_external: boolean; created_at: string };
type Model = { id: string; name: string; is_free?: boolean | null; prompt_price_usd_per_token?: string | null; completion_price_usd_per_token?: string | null; request_price_usd?: string | null; context_length?: number | null };
type Probe = { model: string; answer: string; truncated: boolean };

const ERRORS: Record<string, string> = {
  ai_agent_revision_conflict: "Agentenprofil wurde geaendert. Profile neu laden und Auftrag erneut pruefen.",
  ai_agent_unavailable: "Agentenrolle fehlt oder ist deaktiviert.", ai_agents_config_invalid: "Agentenprofile sind ungueltig. Einrichtung pruefen.",
  ai_request_invalid: "Bitte Feldwerte und Zahlenbereiche pruefen.",
  ai_url_invalid: "HTTP(S)-API-Adresse ohne Zugangsdaten, Query oder Fragment erforderlich.",
  ai_cloud_https_required: "Cloud-Endpunkte benoetigen HTTPS.",
  ai_openrouter_url_invalid: "OpenRouter verwendet https://openrouter.ai/api/v1.",
  ai_local_thinking_only: "Lokale Thinking-Optionen sind bei Cloud-Anbietern nicht verfuegbar.",
  ai_model_invalid: "Modell-ID ist ungueltig.", ai_key_invalid: "API-Key enthaelt ungueltige Zeichen.",
  ai_key_action_conflict: "API-Key entweder ersetzen oder entfernen, nicht beides.",
  ai_key_endpoint_changed: "Beim Anbieter- oder Adresswechsel API-Key neu eingeben oder explizit entfernen.",
  ai_encrypted_vault_required: "Der verschluesselte Secret-Vault ist nicht verfuegbar.",
  ai_key_unreadable_or_wrong_endpoint: "API-Key nicht entschluesselbar oder fuer eine andere Dienstadresse gespeichert. Bitte neu hinterlegen.",
  ai_config_revision_conflict: "Einstellungen wurden zwischenzeitlich geaendert. Bitte neu laden.",
  external_ai_disabled: "Cloud-Zugriffe sind nicht freigegeben.", local_ai_disabled: "Lokale KI ist deaktiviert.",
  ai_not_configured: "API-Adresse und Modell muessen zuerst gespeichert werden.",
  ai_api_key_missing: "Fuer den Cloud-Anbieter fehlt ein API-Key.",
  ai_local_endpoint_not_private: "Dieser Endpunkt ist nicht lokal. Fuer oeffentliche Dienste einen Cloud-Anbieter waehlen.",
  ai_connection_failed: "Der Server erreicht den KI-Endpunkt nicht. Adresse, DNS, Port und Docker-Netz pruefen.",
  ai_timeout: "Zeitlimit beim KI-Anbieter erreicht. Vor einem neuen Auftrag den Aufgabenverlauf pruefen.",
  ai_auth_failed: "API-Key wurde abgelehnt (401).", ai_access_denied: "Zugriff vom Anbieter verweigert (403).",
  ai_credit_required: "Guthaben oder Abrechnung beim Anbieter pruefen (402).",
  ai_endpoint_or_model_missing: "API-Pfad oder Modell nicht gefunden (404).",
  ai_rate_limited: "Anfragelimit erreicht (429). Spaeter erneut pruefen.",
  ai_provider_http_error: "Der Anbieter hat die Anfrage abgelehnt. Modell und Einstellungen pruefen.",
  ai_provider_response_error: "Der Anbieter meldet einen Fehler in seiner Antwort.",
  ai_invalid_response: "Die Antwort entspricht nicht dem erwarteten Chat-API-Format.",
  ai_response_too_large: "Die Antwort des Anbieters ist zu gross.",
  ai_empty_answer: "Das Modell hat keine sichtbare Textantwort geliefert. Antwort-/Testlimit oder Thinking-Einstellung pruefen.",
  ai_prompt_invalid: "Aufgabentext muss 1 bis 32000 Zeichen enthalten.",
  ai_task_not_found: "Aufgabe wurde nicht gefunden.", ai_task_not_queued: "Aufgabe laeuft bereits oder ist abgeschlossen. Verlauf aktualisieren.",
  ai_task_running: "Eine laufende Aufgabe kann nicht entfernt werden.",
  ai_task_external_not_confirmed: "Fuer diese Aufgabe fehlt die ausdrueckliche Cloud-Freigabe.",
  ai_execution_failed: "Die Ausfuehrung ist fehlgeschlagen. Keine automatische Wiederholung.",
  ai_saved_config_invalid: "Gespeicherte KI-Konfiguration ist ungueltig. Administrator-Pruefung erforderlich.",
};

async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 265000);
  try {
    const response = await fetch(`${API_BASE}/api/v1/ai${path}`, { method, signal: controller.signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    const value = await response.json();
    if (!response.ok || value.status === "error") throw new Error(ERRORS[value.detail] || "KI-Anfrage konnte nicht verarbeitet werden.");
    return value.data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("Zeitlimit erreicht. Aufgabenverlauf vor erneutem Ausfuehren aktualisieren.");
    throw error;
  } finally { window.clearTimeout(timer); }
}

function resultOf(task: Task): { answer?: string; error?: string; model?: string; resolved_model?: string; truncated?: boolean; agent?: { name?: string } } {
  try { return JSON.parse(task.result_json || "{}"); } catch { return {}; }
}

function tokenPrice(value?: string | null): string {
  if (value == null || !Number.isFinite(Number(value) * 1000000)) return "unbekannt";
  return (Number(value) * 1000000).toLocaleString("de-DE", { maximumSignificantDigits: 6 }) + " USD / Mio. Token";
}

export function AiWorkspace({ configurationOnly = false }: { configurationOnly?: boolean }) {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [localEnabled, setLocalEnabled] = useState(true);
  const [externalEnabled, setExternalEnabled] = useState(false);
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [models, setModels] = useState<Model[]>([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [prompt, setPrompt] = useState("");
  const [taskType, setTaskType] = useState("review");
  const [workMode, setWorkMode] = useState("text");
  const [agents, setAgents] = useState<Agents | null>(null);
  const [agentId, setAgentId] = useState("coordinator");
  const [agentsDirty, setAgentsDirty] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const gate = useRef(false);

  const setSettings = (value: Settings) => { setSaved(value); setConfig(value.config); setLocalEnabled(value.local_enabled); setExternalEnabled(value.external_enabled); setKey(""); setClearKey(false); setProbe(null); setConfirmed(false); };
  useEffect(() => {
    let active = true;
    void Promise.all([api<Settings>("/provider"), configurationOnly ? Promise.resolve([]) : api<Task[]>("/tasks")])
      .then(([settings, rows]) => { if (active) { setSettings(settings); setTasks(rows); } })
      .catch(() => { if (active) setError("KI-Einstellungen konnten nicht geladen werden."); });
    return () => { active = false; };
  }, [configurationOnly]);
  useEffect(() => { setFreeOnly(config?.provider === "openrouter"); setModelSearch(""); }, [config?.provider]);
  useEffect(() => { void loadAgents().then(setAgents).catch(() => setError("Agentenprofile konnten nicht geladen werden.")); }, []);
  useEffect(() => {
    if (!tasks.some((task) => task.status === "running")) return;
    const timer = window.setInterval(() => { void api<Task[]>("/tasks").then(setTasks).catch(() => {}); }, 3000);
    return () => window.clearInterval(timer);
  }, [tasks]);

  const dirty = !!saved && (JSON.stringify(config) !== JSON.stringify(saved.config) || localEnabled !== saved.local_enabled || externalEnabled !== saved.external_enabled || !!key || clearKey);
  const cloud = config?.provider !== "local";
  const connectionAllowed = !!saved && !dirty && (cloud ? saved.external_enabled && saved.api_key_readable : saved.local_enabled) && !!config?.base_url;
  const isOpenRouter = config?.provider === "openrouter";
  const query = modelSearch.trim().toLocaleLowerCase();
  const filteredModels = models.filter((model) => (!isOpenRouter || !freeOnly || model.is_free === true) && (!query || `${model.name} ${model.id}`.toLocaleLowerCase().includes(query)));
  const selectedModel = models.find((model) => model.id === config?.model);
  const selectedOutsideFilter = !!config?.model && !filteredModels.some((model) => model.id === config.model);
  const clearCatalog = () => { setModels([]); setCatalogLoaded(false); setModelSearch(""); };
  const selectModel = (model: string) => { if (config) setConfig({ ...config, model }); setProbe(null); setConfirmed(false); };
  async function act(action: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true; setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (caught) { setError(caught instanceof Error ? caught.message : "KI-Anfrage fehlgeschlagen."); }
    finally { gate.current = false; setBusy(false); }
  }
  async function execute(task: Task, confirmExternal: boolean) {
    const result = await api<Task>(`/tasks/${encodeURIComponent(task.task_id)}/execute`, "POST", { confirm_external: confirmExternal, provider_revision: saved?.revision });
    setTasks(await api<Task[]>("/tasks"));
    setConfirmed(false);
    if (result.status === "failed") setError(ERRORS[resultOf(result).error || ""] || "KI-Aufgabe fehlgeschlagen.");
  }

  return <section className="aiWorkspace" aria-label={configurationOnly ? "KI-Einrichtung" : "KI-Assistent"}>
    <div className="panelToolbar"><h2>{configurationOnly ? "KI-Einrichtung" : "KI-Assistent"}</h2><div className="buttonRow">
      <HelpTip label="KI-Aufgaben und Datenschutz">Textaufgaben erhalten den eingegebenen Text, nicht automatisch die gesamte Datenbank. Datenkorrekturen verwenden ausgewaehlte Zeilen und benoetigen Vorschau und menschliche Freigabe. Cloud-Inhalte werden nicht automatisch anonymisiert.</HelpTip>
      <a href="/ki-einsatzleitfaden.html" target="_blank" rel="noreferrer"><BookOpen size={16} /> Leitfaden</a>
      <button type="button" className="ghostButton" title="KI-Einstellungen neu laden" aria-label="KI-Einstellungen neu laden" disabled={busy}
        onClick={() => { if (!dirty || window.confirm("Ungespeicherte KI-Einstellungen verwerfen?")) void act(async () => { setSettings(await api<Settings>("/provider")); clearCatalog(); }); }}><RefreshCw size={16} /></button>
    </div></div>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!config && !error && <p role="status">KI-Einstellungen werden geladen.</p>}
    {config && saved && <>
      <details className="aiConnectionSettings" key={saved.configured ? "configured" : "setup"} open={configurationOnly || !saved.configured ? true : undefined}>
      <summary>Verbindung und Modelle{saved.configured ? `: ${config.provider === "openrouter" ? "OpenRouter" : config.provider === "local" ? "Lokal" : "Cloud"} / ${saved.config.model}` : ": Einrichtung erforderlich"}</summary>
      <form onSubmit={(event) => { event.preventDefault(); void act(async () => {
        const value = await api<Settings>("/provider", "PUT", { ...config, revision: saved.revision, local_enabled: localEnabled, external_enabled: externalEnabled, api_key: key || null, clear_api_key: clearKey });
        setSettings(value); setNotice("KI-Einstellungen gespeichert.");
      }); }}>
        <fieldset disabled={busy}><legend>Verbindung <HelpTip label="Verbindung einrichten">Zuerst Anbieter, Adresse, Zugriff und bei Bedarf API-Key speichern. Danach Modelle laden, ein Modell waehlen und erneut speichern. Verbindung testen sendet eine kurze Anfrage und kann Kosten ausloesen.</HelpTip></legend><div className="formGrid">
          <label>Anbieter<select aria-label="KI-Anbieter" value={config.provider} onChange={(event) => {
            const provider = event.target.value as Config["provider"];
            setConfig({ ...config, provider, base_url: provider === "openrouter" ? "https://openrouter.ai/api/v1" : "", model: "", thinking: "server_default", token_parameter: "max_tokens" });
            clearCatalog(); setProbe(null); setConfirmed(false);
          }}><option value="local">Lokaler OpenAI-kompatibler Server</option><option value="openrouter">OpenRouter (Cloud)</option><option value="cloud">Andere OpenAI-kompatible Cloud-API</option></select></label>
          <label>API-Basisadresse<input aria-label="KI-API-Basisadresse" type="url" autoComplete="off" spellCheck={false} value={config.base_url} readOnly={config.provider === "openrouter"} maxLength={2048} onChange={(event) => { setConfig({ ...config, base_url: event.target.value }); clearCatalog(); setProbe(null); }} /></label>
          <label>Modell<select aria-label="KI-Modellauswahl" title={selectedModel?.name || config.model} value={config.model} disabled={!catalogLoaded} onChange={(event) => selectModel(event.target.value)}>
            <option value="">{catalogLoaded ? filteredModels.length ? "Modell auswaehlen" : "Keine Treffer" : "Keine Modellliste geladen"}</option>
            {selectedOutsideFilter && <option value={config.model}>{selectedModel?.name || config.model} (ausgewaehlt, ausserhalb Filter){selectedModel?.is_free === false ? " - Kostenpflichtig" : ""}</option>}
            {filteredModels.map((model) => <option key={model.id} value={model.id}>{model.is_free === true ? "Free - " : ""}{model.name} ({model.id})</option>)}
          </select></label>
          <label>API-Key {saved.api_key_present ? saved.api_key_readable ? "(gespeichert)" : "(nicht lesbar)" : "(nicht gespeichert)"}<input aria-label="KI-API-Key" type="password" autoComplete="new-password" value={key} maxLength={8192} disabled={!saved.encrypted_secrets_available} onChange={(event) => setKey(event.target.value)} /></label>
        </div>
        <div className="aiModelCatalog"><div className="formGrid"><label>Modellsuche<input type="search" aria-label="KI-Modellsuche" value={modelSearch} disabled={!catalogLoaded} onChange={(event) => setModelSearch(event.target.value)} /></label>
          <label>Modell-ID<input aria-label="KI-Modell-ID" autoComplete="off" spellCheck={false} maxLength={256} value={config.model} onChange={(event) => selectModel(event.target.value)} /></label></div>
          {isOpenRouter && <label className="checkboxLabel"><input type="checkbox" checked={freeOnly} onChange={(event) => setFreeOnly(event.target.checked)} /> Nur Free-Modelle</label>}
          {catalogLoaded && <span role="status">{filteredModels.length} von {models.length} Textmodellen{isOpenRouter ? ` / ${models.filter((model) => model.is_free === true).length} Free` : ""}</span>}
          {config.model && isOpenRouter && <div className="aiModelFacts" aria-label="Ausgewaehltes Modell"><strong>{selectedModel?.is_free === true ? "Free" : selectedModel?.is_free === false ? "Kostenpflichtig" : "Preis unbekannt"}</strong>
            <span>Eingabe: {tokenPrice(selectedModel?.prompt_price_usd_per_token)}</span><span>Ausgabe: {tokenPrice(selectedModel?.completion_price_usd_per_token)}</span>
            {selectedModel?.request_price_usd != null && Number(selectedModel.request_price_usd) > 0 && <span>{Number(selectedModel.request_price_usd).toLocaleString("de-DE", { maximumSignificantDigits: 6 })} USD / Anfrage</span>}
            {selectedModel?.context_length != null && <span>Kontext: {selectedModel.context_length.toLocaleString("de-DE")} Token</span>}</div>}
        </div>
        {saved.api_key_present && <label className="checkboxLabel"><input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} /> Gespeicherten KI-API-Key entfernen</label>}
        <div className="aiChecks"><label className="checkboxLabel"><input type="checkbox" checked={localEnabled} onChange={(event) => setLocalEnabled(event.target.checked)} /> Lokale KI aktivieren</label>
          <label className="checkboxLabel"><input type="checkbox" checked={externalEnabled} onChange={(event) => setExternalEnabled(event.target.checked)} /> Cloud-Zugriffe erlauben</label></div>
        {!saved.encrypted_secrets_available && <p role="status">Verschluesselter Secret-Vault nicht verfuegbar.</p>}
        <details><summary>Modellparameter</summary><HelpTip label="Token und Zeitlimit">Token begrenzen die Antwortlaenge. Ein zu kleines Limit kann Antworten abschneiden. Das Zeitlimit begrenzt die Wartezeit; nach einem Abbruch zuerst den Aufgabenverlauf pruefen, bevor erneut eine Anfrage gesendet wird.</HelpTip><div className="formGrid">
          <label>Antwortlimit (Token)<input type="number" aria-label="KI-Antwortlimit" min={16} max={16384} value={config.max_tokens} onChange={(event) => setConfig({ ...config, max_tokens: Number(event.target.value) })} /></label>
          <label>Testlimit (Token)<input type="number" min={16} max={2048} value={config.probe_max_tokens} onChange={(event) => setConfig({ ...config, probe_max_tokens: Number(event.target.value) })} /></label>
          <label>Zeitlimit (Sekunden)<input type="number" min={5} max={240} value={config.timeout_seconds} onChange={(event) => setConfig({ ...config, timeout_seconds: Number(event.target.value) })} /></label>
          {config.provider !== "openrouter" && <label>Token-Parameter<select value={config.token_parameter} onChange={(event) => setConfig({ ...config, token_parameter: event.target.value as Config["token_parameter"] })}><option value="max_tokens">max_tokens</option><option value="max_completion_tokens">max_completion_tokens</option></select></label>}
          {!cloud && <label>Thinking-Steuerung<select value={config.thinking} onChange={(event) => setConfig({ ...config, thinking: event.target.value as Config["thinking"] })}><option value="server_default">Serverstandard</option><option value="llamacpp_off">llama.cpp: Thinking aus</option><option value="ollama_off">Ollama: Thinking aus</option></select></label>}
        </div></details></fieldset>
        <div className="buttonRow"><button type="submit" className="primaryButton" disabled={busy || !dirty}><Save size={16} /> KI-Einstellungen speichern</button>
          <button type="button" disabled={busy || !connectionAllowed} onClick={() => void act(async () => { const rows = await api<Model[]>("/provider/models", "POST"); setModels(rows); setCatalogLoaded(true); setNotice(`${rows.length} Textmodelle geladen${isOpenRouter ? `, davon ${rows.filter((model) => model.is_free === true).length} Free` : ""}.`); })}><Download size={16} /> Modelle laden</button>
          <button type="button" disabled={busy || !connectionAllowed || !saved.configured} onClick={() => void act(async () => { setProbe(null); setProbe(await api<Probe>("/provider/test", "POST")); })}>{busy ? <LoaderCircle size={16} /> : <Check size={16} />} Verbindung testen</button></div>
      </form>
      {probe && <div role="status" className="aiProbe"><strong>Verbindung erfolgreich: {probe.model}</strong><p>{probe.answer}</p>{probe.truncated && <span>Testantwort am Tokenlimit beendet.</span>}</div>}
      </details>
      {agents && <><label>Fachagent<select aria-label="KI-Fachagent" value={agentId} disabled={busy} onChange={(event) => { setAgentId(event.target.value); setConfirmed(false); }}>
        {agents.profiles.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.name}{agent.enabled ? "" : " (deaktiviert)"}</option>)}
      </select></label><HelpTip label="Fachagent und Modell">Ein Fachagent ist ein Aufgabenprofil, kein zusaetzlich trainiertes Modell. Ohne eigene Modell-ID erbt er das Modell der aktiven Verbindung. Keine automatische Team-Ausfuehrung und kein automatischer Wechsel auf kostenpflichtige Modelle.</HelpTip><AiAgentProfiles value={agents} activeId={agentId} provider={config.provider} models={filteredModels} onSaved={(value) => { setAgents(value); setConfirmed(false); }} onDirty={setAgentsDirty} /></>}
      {!configurationOnly && <>
        <div className="buttonRow" role="tablist" aria-label="KI-Arbeitsmodus">
          <button type="button" role="tab" aria-selected={workMode === "text"} onClick={() => setWorkMode("text")}><Bot size={16} /> Textaufgaben</button>
          <button type="button" role="tab" aria-selected={workMode === "changes"} onClick={() => setWorkMode("changes")}><Check size={16} /> Datenkorrekturen</button>
        </div>
        {workMode === "changes" ? <AiChangesWorkspace providerRevision={saved.revision} connectionAllowed={connectionAllowed && saved.configured && !agentsDirty && !!agents?.profiles.find((agent) => agent.agent_id === agentId)?.enabled} cloud={cloud} agentId={agentId} agentRevision={agents?.revision} /> : <>
        <form className="aiTaskComposer" onSubmit={(event) => { event.preventDefault(); void act(async () => {
          const task = await api<Task>("/tasks", "POST", { task_type: taskType, prompt, allow_external: cloud && confirmed, agent_id: agentId, agent_revision: agents?.revision });
          setTasks(await api<Task[]>("/tasks")); await execute(task, cloud && confirmed);
        }); }}>
          <h3>Neue Aufgabe</h3><label>Aufgabentyp<select value={taskType} disabled={busy} onChange={(event) => setTaskType(event.target.value)}><option value="review">Review</option><option value="risk_scan">Risikopruefung</option><option value="import_mapping">Importzuordnung</option><option value="documentation">Dokumentation</option></select></label>
          <label>Aufgabentext<textarea aria-label="KI-Aufgabentext" rows={6} maxLength={32000} value={prompt} disabled={busy} onChange={(event) => { setPrompt(event.target.value); setConfirmed(false); }} /></label>
          {cloud && <label className="checkboxLabel"><input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} /> Diesen Text an {config.provider === "openrouter" ? "OpenRouter" : "den Cloud-Anbieter"} senden</label>}
          <p className="actionRequirement" role="status">{busy ? "Auftrag wird verarbeitet." : dirty ? "Geaenderte Verbindungseinstellungen zuerst speichern." : !connectionAllowed || !saved.configured ? "Aktivierte Verbindung und Modell zuerst speichern." : agentsDirty ? "Geaenderte Agentenprofile zuerst speichern." : !agents?.profiles.find((agent) => agent.agent_id === agentId)?.enabled ? "Einen aktivierten Fachagenten waehlen." : !prompt.trim() ? "Aufgabentext eingeben." : cloud && !confirmed ? "Vor dem Senden die Cloud-Freigabe bestaetigen." : "Aufgabe bereit zur Ausfuehrung."}</p>
          <button type="submit" className="primaryButton" disabled={busy || !connectionAllowed || !saved.configured || agentsDirty || !agents?.profiles.find((agent) => agent.agent_id === agentId)?.enabled || !prompt.trim() || (cloud && !confirmed)}>{busy ? <LoaderCircle size={16} /> : <Play size={16} />} Aufgabe ausfuehren</button>
        </form>
        <div className="panelToolbar"><h3>Aufgabenverlauf</h3><button type="button" title="Aufgabenverlauf aktualisieren" aria-label="Aufgabenverlauf aktualisieren" disabled={busy} onClick={() => void act(async () => setTasks(await api<Task[]>("/tasks")))}><RefreshCw size={16} /></button></div>
        {!tasks.length && <p>Keine KI-Aufgaben vorhanden.</p>}
        <div className="aiTaskList">{tasks.map((task) => {
          const result = resultOf(task);
          return <article className="aiTask" key={task.task_id}>
            <div className="panelToolbar"><strong><Bot size={16} /> {result.agent?.name || task.task_type}</strong><span>{({ queued: "Wartend", running: "Laeuft", done: "Abgeschlossen", failed: "Fehlgeschlagen" } as Record<string, string>)[task.status] || task.status}</span><div className="buttonRow">
              {task.status === "queued" && <button type="button" disabled={busy || !connectionAllowed || !saved.configured || (cloud && !task.allow_external)} onClick={() => { if (!cloud || window.confirm("Den gespeicherten Aufgabentext jetzt an den Cloud-Anbieter senden?")) void act(async () => execute(task, cloud)); }} title="Gespeicherte Aufgabe ausfuehren"><Play size={16} /></button>}
              <button type="button" title="KI-Aufgabe entfernen" aria-label="KI-Aufgabe entfernen" disabled={busy || task.status === "running"} onClick={() => { if (window.confirm("Diese KI-Aufgabe samt Ergebnis entfernen?")) void act(async () => { await api(`/tasks/${encodeURIComponent(task.task_id)}`, "DELETE"); setTasks(await api<Task[]>("/tasks")); }); }}><Trash2 size={16} /></button>
            </div></div>
            <small>{new Date(task.created_at).toLocaleString("de-DE")}{result.model ? ` / ${result.resolved_model || result.model}` : ""}</small>
            <details><summary>Aufgabentext</summary><pre>{task.prompt}</pre></details>
            {result.error && <p role="status" className="error">{ERRORS[result.error] || "KI-Aufgabe fehlgeschlagen."}</p>}
            {result.answer && <pre className="aiAnswer">{result.answer}</pre>}
            {result.truncated && <p role="status">Antwort am Tokenlimit beendet; unvollstaendig.</p>}
          </article>;
        })}</div>
        </>}
      </>}
    </>}
  </section>;
}
