import { BookOpen, RefreshCw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { API_BASE } from "./api-base";

export type Agent = { agent_id: string; name: string; instructions: string; enabled: boolean; models: Record<"local" | "openrouter" | "cloud", string> };
export type Agents = { revision: string; profiles: Agent[]; knowledge: Record<string, unknown>; knowledge_sha256: string };
export async function loadAgents(): Promise<Agents> {
  const response = await fetch(`${API_BASE}/api/v1/ai/agents`);
  if (!response.ok) throw new Error("Agentenprofile konnten nicht geladen werden.");
  return (await response.json()).data;
}

export function AiAgentProfiles({ value, activeId, provider, models, onSaved, onDirty }: { value: Agents; activeId: string; provider: "local" | "openrouter" | "cloud"; models: { id: string; name: string; is_free?: boolean | null }[]; onSaved: (value: Agents) => void; onDirty: (dirty: boolean) => void }) {
  const [draft, setDraft] = useState(value.profiles);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { setDraft(value.profiles); }, [value]);
  useEffect(() => { onDirty(JSON.stringify(draft) !== JSON.stringify(value.profiles)); }, [draft, value, onDirty]);
  const profile = draft.find((item) => item.agent_id === activeId);
  if (!profile) return null;
  function edit(patch: Partial<Agent>) { setDraft(draft.map((item) => item.agent_id === activeId ? { ...item, ...patch } : item)); setNotice(""); }
  async function save() {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${API_BASE}/api/v1/ai/agents`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision: value.revision, profiles: draft }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail === "ai_agent_revision_conflict" ? "Agentenprofile wurden geaendert. Neu laden und erneut pruefen." : "Agentenprofil ungueltig. Namen, Modell-IDs und Aufgabenbeschreibung pruefen; mindestens eine Rolle muss aktiv bleiben.");
      onSaved(data.data); setNotice("Agentenprofile gespeichert.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Agentenprofile konnten nicht gespeichert werden."); }
    finally { setBusy(false); }
  }
  return <details className="aiAgentProfiles"><summary>Agentenprofile einrichten</summary>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="aiAgentEditor"><fieldset disabled={busy}><legend>{profile.name}</legend>
      <div className="formGrid"><label>Agentenname<input aria-label="Agentenname" value={profile.name} minLength={3} maxLength={100} onChange={(event) => edit({ name: event.target.value })} /></label>
        <label>Agentenmodell<select aria-label="Agentenmodellauswahl" value={profile.models[provider]} onChange={(event) => edit({ models: { ...profile.models, [provider]: event.target.value } })}>
          <option value="">Standardmodell der Verbindung</option>{profile.models[provider] && !models.some((model) => model.id === profile.models[provider]) && <option value={profile.models[provider]}>{profile.models[provider]} (gespeichert)</option>}
          {models.map((model) => <option key={model.id} value={model.id}>{model.name} ({model.id})</option>)}
        </select></label></div>
      <label>Aufgabenbeschreibung<textarea aria-label="Agenten-Aufgabenbeschreibung" rows={6} minLength={20} maxLength={6000} value={profile.instructions} onChange={(event) => edit({ instructions: event.target.value })} /></label>
      {profile.models[provider] && <span role="status">{provider === "local" ? "Lokales Agentenmodell" : models.find((model) => model.id === profile.models[provider])?.is_free === true ? "Free" : models.find((model) => model.id === profile.models[provider])?.is_free === false ? "Kostenpflichtig" : "Preis unbekannt"} / {profile.models[provider]}</span>}
      <label className="checkboxLabel"><input type="checkbox" checked={profile.enabled} onChange={(event) => edit({ enabled: event.target.checked })} /> Agent aktiviert</label>
      <details><summary>Modell-IDs je Anbieter</summary><div className="formGrid">{(["local", "openrouter", "cloud"] as const).map((key) => <label key={key}>{({ local: "Lokales Modell", openrouter: "OpenRouter-Modell", cloud: "Anderes Cloud-Modell" })[key]}<input aria-label={`Agentenmodell ${key}`} value={profile.models[key]} maxLength={256} onChange={(event) => edit({ models: { ...profile.models, [key]: event.target.value } })} /></label>)}</div></details>
    </fieldset><div className="buttonRow"><button type="button" disabled={busy || JSON.stringify(draft) === JSON.stringify(value.profiles)} onClick={() => void save()}><Save size={16} /> Agentenprofile speichern</button>
      <button type="button" title="Agentenprofile neu laden" aria-label="Agentenprofile neu laden" disabled={busy} onClick={() => { if (JSON.stringify(draft) === JSON.stringify(value.profiles) || window.confirm("Ungespeicherte Agentenaenderungen verwerfen?")) void loadAgents().then(onSaved).catch(() => setError("Agentenprofile konnten nicht geladen werden.")); }}><RefreshCw size={16} /></button></div>
      <details><summary><BookOpen size={16} /> Anwendungswissen / {value.knowledge_sha256.slice(0, 12)}</summary><pre>{JSON.stringify(value.knowledge, null, 2)}</pre></details>
    </div>
  </details>;
}
