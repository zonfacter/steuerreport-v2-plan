import { type ReactNode, useEffect, useRef, useState } from "react";
import { ArrowRight, ClipboardCheck, Download, FolderInput, Plus, RefreshCw, Save, ShieldCheck, Upload, Wallet } from "lucide-react";
import { API_BASE } from "../api-base";
import { HelpTip } from "../Help";
import { ActivityWorkspace } from "./Transactions";
import { navigateView, useViewState } from "./view-state";
import { compareAmounts, money, readApi, timestamp, useDebounced, useResource } from "./resource";
import { ActionConfirm, Badge, DetailPanel, Empty, label, ListTools, Pager, ResourceNotice, RowMenu, TabPanel, Tabs } from "./Ui";
import type { Source, SourceDetail, SourceList } from "./types";

const success = new Set(["refreshed", "empty_response", "success", "ok"]);
const fileProviders = new Set(["manual-csv", "binance", "bitget", "pionex", "coinbase", "helium", "solana_rpc"]);
const failed = (source: Source) => !!source.last_attempt && !success.has(source.last_attempt.status);
export function SourceWorkspace({ technical, onTechnical }: { technical: ReactNode; onTechnical: (enabled: boolean) => void }) {
  const { view, set, search, setSearch, reset } = useViewState("sources");
  const query = useDebounced(search);
  const resource = useResource<SourceList>("workspace-sources", (signal) => readApi("/api/v1/workspace/sources", signal));
  const [adding, setAdding] = useState(false), [sync, setSync] = useState<Source | null>(null);
  useEffect(() => { onTechnical(view.tab === "expert"); }, [view.tab, onTechnical]);
  const all = resource.data?.sources || [];
  const rows = all.filter((source) => (!query || source.label.toLocaleLowerCase("de").includes(query.toLocaleLowerCase("de"))) && (!view.status || (
    view.status === "configured" ? ["configured", "registered", "imported", "not_required"].includes(source.connection_status)
      : view.status === "setup" ? ["missing", "not_configured", "ownership_verified_pending_registry"].includes(source.connection_status)
      : view.status === "failed" ? failed(source)
      : view.status === "stale" ? source.freshness === "stale"
      : view.status === "reconciliation" ? source.issues_count > 0 || !!source.warning : true
  ))).sort((a, b) => view.sort === "value" ? compareAmounts(b.value_eur, a.value_eur) || a.label.localeCompare(b.label, "de") : view.sort === "issues" ? b.issues_count - a.issues_count || a.label.localeCompare(b.label, "de") : a.label.localeCompare(b.label, "de"));
  const pages = Math.max(1, Math.ceil(rows.length / view.size));
  const page = Math.min(view.page, pages);
  useEffect(() => { if (resource.status === "ready" && page !== view.page) set({ page }, true); }, [page, view.page, resource.status]);
  const filtered = !!search || !!view.status;
  const open = (source: Source, detailTab = "overview") => set({ detail: source.ref, detailTab, detailPage: 1 });
  return <section className="wsPage" aria-label="Eigene Quellen">
    <div className="wsPageActions"><button type="button" className="wsPrimary" onClick={() => setAdding(true)}><Plus size={17} /> Quelle hinzufügen</button><a className="wsButton" href="#import"><Upload size={16} /> Dateien importieren</a></div>
    <ResourceNotice resource={resource} label="Eigene Quellen" />
    {resource.data && <div className="wsSummaryLine"><span>{all.length} eigene Quellen</span><span>{resource.data.events_count} kanonische Ereignisse</span><span>{all.filter(failed).length} fehlgeschlagene letzte Abrufe</span><HelpTip label="Getrennte Quellenzustände">Einrichtung, letzter erfolgreicher Bestand, jüngster Abrufversuch und fachlicher Abgleich sind getrennte Zustände. Eine Dateiquelle benötigt nicht zwangsläufig einen API-Zugang. Ein bestätigter Nullbestand ist etwas anderes als ein fehlender Vergleichsbestand.</HelpTip></div>}
    <Tabs name="Quellenbereich" active={view.tab} items={[{ id: "list", label: "Eigene Quellen" }, { id: "expert", label: "Expertenmodus" }]} onChange={(tab) => set({ tab })} />
    <TabPanel name="Quellenbereich" active={view.tab}>{view.tab === "expert" ? <div className="wsTechnical"><EarnPreview />{technical}</div> : <>
      <ListTools search={search} onSearch={setSearch} chips={view.status ? [{ label: statusLabel(view.status), remove: () => set({ status: "" }) }] : []} onReset={reset}>
        <label>Status<select aria-label="Quellenstatus" value={view.status} onChange={(event) => set({ status: event.target.value })}><option value="">Alle Zustände</option>{["configured", "setup", "failed", "stale", "reconciliation"].map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}</select></label>
        <label>Sortierung<select aria-label="Quellen sortieren" value={view.sort} onChange={(event) => set({ sort: event.target.value })}><option value="name">Name A–Z</option><option value="value">Höchster bekannter Wert zuerst</option><option value="issues">Offene Hinweise zuerst</option></select></label>
      </ListTools>
      {resource.status === "ready" && !all.length ? <Empty title="Noch keine eigene Quelle eingerichtet">Füge eine verwendete Börse oder Wallet hinzu oder importiere deren Originaldateien. Ein leerer Anbieter-Katalog ist kein geprüftes Portfolio.</Empty>
        : resource.data && !rows.length ? <Empty title="Keine passenden Quellen" filtered={filtered} onReset={reset} />
          : <div className="wsSourceList" aria-label="Quellenliste">{rows.slice((page - 1) * view.size, page * view.size).map((source) => <article key={source.ref} className="wsSourceRow">
            <div className="wsSourceIdentity"><Wallet size={22} aria-hidden="true" /><div><button type="button" className="wsTextButton" onClick={() => open(source)}>{source.label}</button><small>{label(source.source_type, "Importierte Quelle")} · {source.events_count} Ereignisse</small><Badge>{label(source.connection_status)}</Badge></div></div>
            <div className="wsSourceDates"><small>Letzter erfolgreicher Abruf</small><span>{timestamp(source.last_success_at)}</span>{failed(source) && <span className="wsWarning">Neuer Versuch fehlgeschlagen · {timestamp(source.last_attempt?.attempted_at)}</span>}{source.freshness === "stale" && <Badge tone="warning">Datenstand veraltet</Badge>}</div>
            <div className="wsSourceValue"><strong>{money(source.value_eur)}</strong><small>{label(source.value_basis, "Bewertungsbasis prüfen")}</small><span>{source.issues_count} fachliche Hinweise{source.warning ? " · Abgleich prüfen" : ""}</span></div>
            <div className="wsSourceActions"><button type="button" disabled={resource.stale} onClick={() => source.issues_count || source.warning ? open(source, "issues") : source.can_sync ? setSync(source) : open(source, source.events_count ? "overview" : "settings")}>
              {source.issues_count || source.warning ? <ClipboardCheck size={16} /> : source.can_sync ? <RefreshCw size={16} /> : <ArrowRight size={16} />}
              {source.issues_count || source.warning ? "Hinweise prüfen" : source.can_sync ? "Synchronisieren" : source.events_count ? "Details" : "Einrichten"}</button>
              <RowMenu><button type="button" onClick={() => open(source, "transactions")}>Transaktionen öffnen</button><button type="button" onClick={() => open(source, "settings")}>Einstellungen und Belege</button><a href="#import">Dateien importieren</a></RowMenu>
            </div>
          </article>)}</div>}
      {resource.data && <Pager total={rows.length} page={page} pages={pages} size={view.size} onPage={(page) => set({ page })} onSize={(size) => set({ size })} />}
    </>}</TabPanel>
    {adding && <AddSource onClose={() => setAdding(false)} onSaved={() => resource.reload()} />}
    {view.detail && !sync && <SourcePanel sourceRef={view.detail} tab={view.detailTab} setTab={(detailTab) => set({ detailTab })} onClose={() => set({ detail: "", detailTab: "overview", detailPage: 1 })} onSync={setSync} />}
    {sync && <ActionConfirm title={`${sync.label} synchronisieren`} effect="Diese Aktion fragt den externen Anbieter ab und speichert neue Bestands-Snapshots, Abrufprotokolle und gegebenenfalls Solana-Preise. Sie importiert in diesem bestehenden Abrufpfad keine Transaktionshistorie und berechnet keine Steuerjahre neu. Anbieterlimits und mögliche API-Kosten beachten." command={async () => {
      const result = await readApi<{ connector_results: { status: string; message: string }[] }>(`/api/v1/workspace/sources/${sync.ref}/sync`, undefined, {});
      const failedRows = result.connector_results.filter((row) => !success.has(row.status));
      if (failedRows.length) throw new Error("Abruf nicht erfolgreich. Der vorherige erfolgreiche Datenstand bleibt erhalten. Hinweise zur Quelle prüfen.");
      return "Abruf abgeschlossen. Gespeicherten Datenstand und Abgleich prüfen.";
    }} onDone={() => { resource.reload(); window.dispatchEvent(new Event("steuerreport:refresh")); }} onClose={() => setSync(null)} />}
  </section>;
}

function statusLabel(status: string) { return ({ configured: "Eingerichtet / importiert", setup: "Einrichtung erforderlich", failed: "Abruf fehlgeschlagen", stale: "Daten veraltet", reconciliation: "Abgleich offen" } as Record<string, string>)[status] || "Alle Zustände"; }

function EarnPreview() {
  const [open, setOpen] = useState(false), [data, setData] = useState<unknown>();
  return <details><summary>Binance Earn: ausdrücklicher externer Vorschauabruf</summary><p>Dieser vorhandene GET-Endpunkt fragt den Anbieter ab. Er läuft nicht beim Öffnen dieser Ansicht. Zeitraum ab 01.01.2025, höchstens zwei Seiten / 500 Datensätze; kein Historienimport oder fachliche Freigabe.</p><button type="button" onClick={() => setOpen(true)}><RefreshCw size={16} /> Externen Earn-Abruf prüfen</button>{data !== undefined && <pre>{JSON.stringify(data, null, 2)}</pre>}{open && <ActionConfirm title="Externen Earn-Abruf bestätigen" effect="Fragt Binance mit vorhandenen Leserechten ab. Anbieterlimits und mögliche Kosten beachten. Kein Import und keine automatische Klassifizierung." command={async () => { setData(await readApi("/api/v1/sources/binance/earn-history-api-preview?since=2025-01-01&max_pages=2&max_records=500")); return "Vorschau empfangen. Datensätze und Anbietergrenzen prüfen."; }} onDone={() => {}} onClose={() => setOpen(false)} />}</details>;
}

function SourcePanel({ sourceRef, tab, setTab, onClose, onSync }: { sourceRef: string; tab: string; setTab: (tab: string) => void; onClose: () => void; onSync: (source: Source) => void }) {
  const resource = useResource<SourceDetail>("source-detail:" + sourceRef, (signal) => readApi(`/api/v1/workspace/sources/${sourceRef}`, signal));
  const detail = resource.data?.source.ref === sourceRef ? resource.data : undefined;
  const active = ["overview", "holdings", "transactions", "issues", "settings"].includes(tab) ? tab : "overview";
  return <DetailPanel title={detail?.source.label || "Quellendetail"} onClose={onClose}>
    <ResourceNotice resource={resource} label="Quellendetail" />
    {detail && <><Tabs name="Quellendetail" active={active} onChange={setTab} items={[{ id: "overview", label: "Übersicht" }, { id: "holdings", label: "Bestände" }, { id: "transactions", label: "Transaktionen" }, { id: "issues", label: "Hinweise / Abgleich" }, { id: "settings", label: "Einstellungen" }]} /><TabPanel name="Quellendetail" active={active}>
      {active === "overview" && <><dl className="wsFacts"><div><dt>Bestandswert</dt><dd>{money(detail.source.value_eur)}</dd></div><div><dt>Bewertungsbasis</dt><dd>{label(detail.source.value_basis)}</dd></div><div><dt>Letzter erfolgreicher Abruf</dt><dd>{timestamp(detail.source.last_success_at)}</dd></div><div><dt>Letzter Versuch</dt><dd>{detail.source.last_attempt ? `${label(detail.source.last_attempt.status, "Abrufstatus in technischen Details prüfen")} · ${timestamp(detail.source.last_attempt.attempted_at)}` : "Noch kein Abrufversuch"}</dd></div><div><dt>Eigentumsprüfung</dt><dd>{label(detail.source.ownership_status)}</dd></div></dl><div className="wsActionFooter">{detail.source.can_sync && <button type="button" disabled={resource.stale} onClick={() => onSync(detail.source)}><RefreshCw size={16} /> Quelle synchronisieren</button>}<button type="button" onClick={() => setTab("transactions")}><ArrowRight size={16} /> Transaktionen prüfen</button></div></>}
      {active === "holdings" && <>{detail.valuation?.assets.length ? <div className="wsTableScroll"><table><thead><tr><th>Asset</th><th>Menge</th><th>Wert / Basis</th></tr></thead><tbody>{detail.valuation.assets.map((row) => <tr key={row.asset}><td>{row.asset}</td><td>{row.quantity}</td><td>{row.price_status === "missing" ? "Preis fehlt" : money(row.value_eur)}<small>{label(detail.source.value_basis)}</small></td></tr>)}</tbody></table></div> : <Empty title={detail.source.last_success_at && compareAmounts(detail.source.value_eur, "0") === 0 ? "Bestand mit 0,00 EUR bestätigt" : "Keine bewertbaren Bestände verfügbar"}>Fehlende Bestands- oder Preisdaten sind kein bestätigter Nullbestand.</Empty>}</>}
      {active === "transactions" && <ActivityWorkspace embeddedSource={sourceRef} />}
      {active === "issues" && <><div className="wsInlineWarning"><strong>{detail.source.issues_count} Hinweise im Quellenabgleich</strong><p>{detail.source.warning || (detail.source.issues_count ? "Abweichungen anhand von Bestand, Preisen und Originalbelegen klären." : "Kein Quellenhinweis gemeldet. Dies ersetzt keine Jahresfreigabe oder Vollständigkeitsprüfung.")}</p></div><dl className="wsFacts"><div><dt>Letzter erfolgreicher Datenstand</dt><dd>{timestamp(detail.source.last_success_at)}</dd></div><div><dt>Letzter Versuch</dt><dd>{detail.source.last_attempt ? label(detail.source.last_attempt.status, "Abrufproblem prüfen") : "Noch kein Abruf"}</dd></div></dl><a className="wsButton" href="#review"><ClipboardCheck size={16} /> Fachliche Aufgaben öffnen</a><details className="wsTechnical"><summary>Technischer Quellenabgleich</summary><pre>{JSON.stringify(detail.valuation?.reconciliation || detail.source, null, 2)}</pre></details></>}
      {active === "settings" && <><p>Eigentumsnachweis, Speicherung von Zugangsdaten und steuerliche Quellenaktivierung sind getrennte Schritte.</p><div className="wsActionFooter"><a className="wsButton" href="#admin"><Save size={16} /> Einrichtung öffnen</a><a className="wsButton" href="#import"><Upload size={16} /> Originaldateien importieren</a></div><details className="wsTechnical"><summary>Eigentum, Abdeckung und Belegpfade</summary><pre>{JSON.stringify(detail.evidence, null, 2)}</pre></details><details className="wsTechnical"><summary>Kontenzuordnung und Bewertungsmethode</summary><pre>{JSON.stringify({ accounts: detail.valuation?.full_accounts, evidence: detail.valuation?.evidence_refs, methodology: detail.valuation?.methodology }, null, 2)}</pre></details></>}
    </TabPanel></>}
  </DetailPanel>;
}

type Catalog = { security: { connector_writes_enabled: boolean; auth_mode: string; vault: { configured: boolean } }; connectors: { connector_id: string; label: string; category: string; availability: string; connection_status: string; limitation: string | null }[] };
function AddSource({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const catalog = useResource<Catalog>("add-source-catalog", (signal) => readApi("/api/v1/connectors/catalog", signal));
  const profiles = useResource<{ source: string; label: string }[]>("add-source-profiles", (signal) => readApi("/api/v1/import/profiles", signal));
  const [provider, setProvider] = useState(""), [mode, setMode] = useState("api"), [step, setStep] = useState(1);
  const [key, setKey] = useState(""), [secret, setSecret] = useState(""), [passphrase, setPassphrase] = useState("");
  const [address, setAddress] = useState(""), [token, setToken] = useState(""), [signature, setSignature] = useState("");
  const [challenge, setChallenge] = useState<{ challenge_id: string; message: string } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [result, setResult] = useState("");
  const gate = useRef(false);
  const dirty = !result && !!(key || secret || passphrase || address || token || signature);
  const cex = ["binance", "bitget", "pionex", "coinbase"].includes(provider);
  const fileSource = fileProviders.has(provider) ? profiles.data?.find((row) => row.source === provider)?.source : undefined;
  const connector = catalog.data?.connectors.find((row) => row.connector_id === provider);
  const availability = !!fileSource || ["available", "server_admin_only", "evidence_only"].includes(connector?.availability || "");
  const valid = mode === "file" ? !!fileSource : mode === "wallet" ? /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(address) : cex && !!key.trim() && !!secret.trim() && (provider !== "bitget" || !!passphrase.trim());
  const ready = valid && (mode !== "api" || !!catalog.data?.security.vault.configured) && (mode !== "wallet" || !!challenge && !!signature.trim() && !!catalog.data?.security.connector_writes_enabled);
  async function action(callback: () => Promise<void>) { if (gate.current) return; gate.current = true; setBusy(true); setError(""); try { await callback(); } catch { setError("Angaben konnten nicht verarbeitet werden. Eingaben bleiben erhalten; vorhandene Berechtigungen und Verbindung prüfen."); } finally { gate.current = false; setBusy(false); } }
  async function walletRequest<T>(path: string, body: unknown): Promise<T> {
    const response = await fetch(API_BASE + path, { method: "POST", headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) }, body: JSON.stringify(body) });
    const envelope = await response.json(); if (!response.ok || envelope.status === "error") throw new Error("wallet_request_failed"); return envelope.data;
  }
  return <DetailPanel title="Quelle hinzufügen" onClose={() => { if (!busy) onClose(); }} dirty={dirty}>
    <ol className="wsWizardSteps" aria-label="Einrichtungsschritte">{["Anbieter", "Angaben", "Zusammenfassung"].map((text, index) => <li key={text} aria-current={step === index + 1 ? "step" : undefined}>{index + 1}. {text}</li>)}</ol>
    <ResourceNotice resource={catalog} label="Anbieterkatalog" /><ResourceNotice resource={profiles} label="Importprofile" />
    {error && <p role="alert" className="error">{error}</p>}{result && <p role="status">{result}</p>}
    {!result && <form className="wsForm" onSubmit={(event) => { event.preventDefault(); if (step < 3) { if (step === 1 && provider && availability && (cex || fileSource || provider === "solana-wallet") || step === 2 && ready) setStep(step + 1); return; } if (!ready) return;
      if (mode === "file") { window.sessionStorage.setItem("steuerreport:import-source-once", fileSource!); onClose(); navigateView("import", {}); return; }
      void action(async () => {
        if (mode === "api") {
          const saved = await readApi<{ status: string }>("/api/v1/admin/cex-credentials", undefined, { connector_id: provider, api_key: key, api_secret: secret, passphrase: passphrase || null });
          setResult(saved.status === "ok" ? "Zugangsdaten im Secret-Store gespeichert. Noch keine Anbieterabfrage, kein Historienimport und keine steuerliche Quellenfreigabe ausgeführt." : "Zugangsdaten gespeichert; ihre Nutzbarkeit ist noch zu prüfen. Es wurde keine Verbindung als erfolgreich bestätigt.");
        } else {
          const verified = await walletRequest<{ status: string }>("/api/v1/connectors/wallet/verifications", { challenge_id: challenge?.challenge_id, signature });
          setResult(verified.status === "registered" ? "Eigentumsprüfung erfolgreich; die bestehende Quellenregistrierung wurde gefunden. Noch keine Historie importiert." : "Eigentumsprüfung erfolgreich. Steuerliche Aktivierung in der Quellenregistrierung bleibt offen; keine Historie importiert.");
        }
        setKey(""); setSecret(""); setPassphrase(""); setToken(""); setSignature(""); onSaved();
      });
    }}>
      {step === 1 && <><label>Anbieter<select aria-label="Anbieter für neue Quelle" required value={provider} onChange={(event) => {
        if (dirty && !window.confirm("Ungespeicherte Angaben für den bisherigen Anbieter verwerfen?")) return;
        const next = event.target.value;
        setProvider(next); setKey(""); setSecret(""); setPassphrase(""); setAddress(""); setToken(""); setChallenge(null); setSignature("");
        setMode(next === "solana-wallet" ? "wallet" : ["binance", "bitget", "pionex", "coinbase"].includes(next) ? "api" : "file");
      }}><option value="">Anbieter wählen</option>{profiles.data?.filter((row) => fileProviders.has(row.source) && !catalog.data?.connectors.some((item) => item.connector_id === row.source)).map((row) => <option key={row.source} value={row.source}>{row.label}</option>)}{catalog.data?.connectors.map((row) => <option key={row.connector_id} value={row.connector_id} disabled={!["available", "server_admin_only", "evidence_only"].includes(row.availability)}>{row.label}{["planned", "partner_access_required"].includes(row.availability) ? ` — ${label(row.availability)}` : ""}</option>)}</select></label>{connector?.limitation && <p>{connector.limitation}</p>}{provider && <label>Eingabeart<select aria-label="Eingabeart" value={mode} onChange={(event) => setMode(event.target.value)}>{cex && <option value="api">API-Zugangsdaten</option>}{fileSource && <option value="file">CSV / Excel</option>}{provider === "solana-wallet" && <option value="wallet">Wallet-Adresse und Signaturnachweis</option>}</select></label>}{provider && !cex && !fileSource && provider !== "solana-wallet" && <p>Dieser Dienst wird im vorhandenen Einrichtungsbereich konfiguriert und ist keine eigenständige Transaktionsquelle.</p>}</>}
      {step === 2 && <>{mode === "api" ? <><label>API-Key<input aria-label="API-Key der neuen Quelle" type="password" required autoComplete="new-password" maxLength={8192} value={key} onChange={(event) => setKey(event.target.value)} /></label><label>API-Secret<input aria-label="API-Secret der neuen Quelle" type="password" required autoComplete="new-password" maxLength={8192} value={secret} onChange={(event) => setSecret(event.target.value)} /></label>{provider === "bitget" && <label>Passphrase<input aria-label="API-Passphrase der neuen Quelle" type="password" required autoComplete="new-password" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} /></label>}{!catalog.data?.security.vault.configured && <p role="alert">Verschlüsselungsschlüssel fehlt. Zuerst die Einrichtung prüfen; hier werden ohne eingerichteten Vault keine Zugangsdaten gespeichert.</p>}<p>Nur vorhandene Leseberechtigungen verwenden. Pflichtfeldprüfung ist kein erfolgreicher Anbieter-Verbindungstest.</p></>
        : mode === "file" ? <><p>Der vorhandene Importassistent prüft Originaldatei, Spalten, Dubletten und Vorschau. Erst dessen ausdrückliche Importfreigabe schreibt Transaktionen.</p><a href="/importformate.html" target="_blank" rel="noreferrer"><Download size={16} /> Formate und Pflichtspalten</a></>
          : <><label>Solana-Wallet-Adresse<input aria-label="Neue Wallet-Adresse" value={address} autoComplete="off" spellCheck={false} required aria-invalid={!!address && !valid} aria-describedby="wallet-address-error" onChange={(event) => { setAddress(event.target.value); setChallenge(null); setSignature(""); }} /></label><p id="wallet-address-error">{address && !valid ? "Eine Solana-Adresse mit 32–44 Base58-Zeichen ist erforderlich; die endgültige Validierung erfolgt im bestehenden Backend." : "Keine Seed-Phrase und keinen privaten Schlüssel eingeben."}</p>{!catalog.data?.security.connector_writes_enabled ? <p role="status">Die vorhandene Connector-Schreibfreigabe ist nicht aktiv. Sie wird hier nicht erweitert. Einrichtung prüfen.</p> : <>{catalog.data.security.auth_mode === "setup_token" && <label>Lokaler Connector-Setup-Token<input aria-label="Connector-Setup-Token" type="password" autoComplete="new-password" value={token} onChange={(event) => setToken(event.target.value)} /></label>}<button type="button" disabled={busy || !valid} onClick={() => void action(async () => setChallenge(await walletRequest("/api/v1/connectors/wallet/challenges", { wallet_address: address, wallet_provider: "other" })))}><ShieldCheck size={16} /> Nachricht für Eigentumsnachweis anfordern</button>{challenge && <><pre>{challenge.message}</pre><p>Genau diese Nachricht mit einem geeigneten Wallet-Signer signieren. Nur die öffentliche Base58-Signatur einfügen; keine Signierberechtigung für Transaktionen erteilen.</p><label>Base58-Signatur<input aria-label="Öffentliche Wallet-Signatur" value={signature} autoComplete="off" onChange={(event) => setSignature(event.target.value)} /></label></>}</>}</>}
      </>}
      {step === 3 && <>{connector?.connection_status === "configured" && mode === "api" && <p className="wsInlineWarning">Diese Quelle ist bereits eingerichtet. Speichern ersetzt ihre vorhandenen Zugangsdaten.</p>}<dl className="wsFacts"><div><dt>Anbieter</dt><dd>{connector?.label || "Eigene Datei"}</dd></div><div><dt>Eingabeart</dt><dd>{mode === "api" ? "API-Zugang" : mode === "file" ? "Dateiimport" : "Eigentumsnachweis"}</dd></div><div><dt>Prüfung</dt><dd>{mode === "api" ? "Pflichtfelder vorhanden; Verbindung noch nicht geprüft" : mode === "file" ? "Dateiprüfung und Freigabe erfolgen im Importassistenten" : "Signatur wird vom bestehenden Backend geprüft"}</dd></div></dl><p>{mode === "api" ? "Speichert Zugangsdaten verschlüsselt. Kein Abruf und keine automatische Steueraktivierung." : mode === "wallet" ? "Speichert nur den bestehenden Signaturnachweis. Eigentum ist nicht gleich steuerliche Quellenaktivierung." : "Öffnet den Importassistenten. Noch kein Import."}</p></>}
      <div className="wsActionFooter">{step > 1 && <button type="button" disabled={busy} onClick={() => setStep(step - 1)}>Zurück</button>}<button type="submit" className="wsPrimary" disabled={busy || step === 1 && (!provider || !availability || (!cex && !fileSource && provider !== "solana-wallet")) || step > 1 && !ready}>{step < 3 ? <ArrowRight size={16} /> : mode === "file" ? <FolderInput size={16} /> : <Save size={16} />}{busy ? "Wird verarbeitet" : step < 3 ? "Weiter" : mode === "api" ? "Zugangsdaten speichern" : mode === "file" ? "Importassistent öffnen" : "Signatur prüfen und speichern"}</button></div>
    </form>}
    {result && <button type="button" onClick={onClose}>Fertig</button>}
  </DetailPanel>;
}
