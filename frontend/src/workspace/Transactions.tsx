import { type ReactNode, useEffect, useRef, useState } from "react";
import { ArrowRight, Download, LoaderCircle } from "lucide-react";
import { API_BASE } from "../api-base";
import { HelpTip } from "../Help";
import { navigateView, useViewState } from "./view-state";
import { readApi, timestamp, useDebounced, useResource } from "./resource";
import { Badge, DetailPanel, Empty, ExactQuantity, label, ListTools, Pager, ResourceNotice, TabPanel, Tabs } from "./Ui";
import { ReviewReturn } from "./ReviewContext";
import type { ActivityDetail, ActivityPage, SourceList } from "./types";

const TYPES = ["trade", "transfer", "fee", "reward", "income", "staking", "mining", "derivative", "unknown"];
const DATA_TABS = [{ id: "transactions", label: "Transaktionen" }, { id: "ledger", label: "Ledger" }, { id: "flows", label: "Geldflüsse" }, { id: "transfers", label: "Transferkandidaten" }];
export function ActivityWorkspace({ embeddedSource, flows, transfers }: { embeddedSource?: string; flows?: ReactNode; transfers?: ReactNode }) {
  const { view, set, search: parentSearch, setSearch: setParentSearch, reset } = useViewState(embeddedSource ? "sources" : "flows");
  const [innerSearch, setInnerSearch] = useState("");
  const search = embeddedSource ? innerSearch : parentSearch;
  const setSearch = embeddedSource ? (value: string) => { setInnerSearch(value); set({ detailPage: 1 }); } : setParentSearch;
  const debounced = useDebounced(search);
  const tab = embeddedSource ? "transactions" : view.tab;
  const sources = useResource<SourceList>(embeddedSource ? null : "activity-sources", (signal) => readApi("/api/v1/workspace/sources", signal));
  const assets = useResource<{ assets: string[]; truncated: boolean }>(embeddedSource ? null : "activity-assets", (signal) => readApi("/api/v1/activity/assets", signal));
  const query = { mode: tab === "ledger" ? "ledger" : "events", year: view.year === "all" ? null : Number(view.year), source_ref: embeddedSource || view.source || null, account_ref: embeddedSource ? null : view.account || null,
    asset: embeddedSource ? null : view.asset || null, event_type: embeddedSource ? null : view.type || null, hint: !embeddedSource && ["present", "none"].includes(view.status) ? view.status : "all",
    start: embeddedSource ? null : view.start || null, end: embeddedSource ? null : view.end || null, search: debounced, sort: !embeddedSource && view.sort === "oldest" ? "oldest" : "newest",
    page: embeddedSource ? view.detailPage : view.page, page_size: view.size };
  const queryKey = JSON.stringify(query);
  const list = useResource<ActivityPage>(["transactions", "ledger"].includes(tab) ? "activity:" + queryKey : null, (signal) => readApi("/api/v1/activity/query", signal, query));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const filterKey = JSON.stringify({ ...query, page: 1, sort: "newest", page_size: 25 });
  useEffect(() => { setSelected(new Set()); }, [filterKey]);
  useEffect(() => {
    if (list.status === "ready" && list.key === "activity:" + queryKey && list.data && list.data.page !== query.page) set(embeddedSource ? { detailPage: list.data.page } : { page: list.data.page }, true);
  }, [list.status, list.data?.page, query.page, queryKey, list.key]);
  const pending = list.stale || search !== debounced || list.status === "loading";
  const filtered = !!search || !!(!embeddedSource && (view.asset || view.source || view.account || view.type || view.status || view.start || view.end));
  const clear = embeddedSource ? () => { setInnerSearch(""); set({ detailPage: 1 }); } : reset;
  const open = (id: string) => embeddedSource ? navigateView("flows", { tab: "transactions", source: embeddedSource, detail: id, detailTab: "overview", page: 1 }) : set({ detail: id, detailTab: "overview" });
  const chips = !embeddedSource ? [
    ...(view.account ? [{ label: "Konto: " + (list.data?.account_label || "gespeicherter Kontofilter"), remove: () => set({ account: "" }) }] : []),
    ...(view.source ? [{ label: sources.data?.sources.find((source) => source.ref === view.source)?.label || "Quellenfilter", remove: () => set({ source: "" }) }] : []),
    ...(view.asset ? [{ label: view.asset, remove: () => set({ asset: "" }) }] : []),
    ...(view.type ? [{ label: label(view.type), remove: () => set({ type: "" }) }] : []),
    ...(view.status ? [{ label: view.status === "present" ? "Mit Datenhinweis" : "Ohne Datenhinweis", remove: () => set({ status: "" }) }] : []),
    ...(view.start || view.end ? [{ label: "Datumsbereich", remove: () => set({ start: "", end: "" }) }] : [])
  ] : [];
  return <section className="wsPage" aria-label={embeddedSource ? "Transaktionen der Quelle" : "Transaktionsarbeitsbereich"}>
    {!embeddedSource && <ReviewReturn task={view.task} />}
    {!embeddedSource && <Tabs name="Transaktionsansicht" active={tab} items={DATA_TABS} onChange={(tab) => set({ tab, page: 1, detail: "" })} />}<TabPanel name={embeddedSource ? undefined : "Transaktionsansicht"} active={tab}>
    {tab === "flows" ? flows : tab === "transfers" ? transfers : <>
      <div className="wsPageActions"><span>{tab === "ledger" ? "Einzelne berechnete Buchungsbewegungen und Gebühren" : "Kanonische Ereignisse aus importierten Quellen"}</span><HelpTip label="Transaktionen und Ledger">Ein kanonisches Ereignis kann mehrere Ledger-Bewegungen auslösen, etwa Kauf, Gegenwert und Gebühr. Unterschiedliche Zeilenanzahlen sind deshalb nicht automatisch Datenverlust. Keine Transferkandidaten werden hier automatisch anerkannt.</HelpTip>{!embeddedSource && <button type="button" disabled={!list.data || pending || list.status === "error"} onClick={() => setExporting(true)}><Download size={17} /> Exportieren</button>}</div>
      <ListTools search={search} onSearch={setSearch} chips={chips} onReset={clear}>
        {!embeddedSource && <><label>Quelle<select aria-label="Transaktionsquelle" value={view.source} onChange={(event) => set({ source: event.target.value })}><option value="">Alle Quellen</option>{view.source && !sources.data?.sources.some((source) => source.ref === view.source) && <option value={view.source}>Quelle aus URL prüfen</option>}{sources.data?.sources.map((source) => <option key={source.ref} value={source.ref}>{source.label}</option>)}</select></label>
          <label>Asset<select aria-label="Transaktionsasset" value={view.asset} onChange={(event) => set({ asset: event.target.value })}><option value="">Alle Assets</option>{view.asset && !assets.data?.assets.includes(view.asset) && <option value={view.asset}>{view.asset} (URL-Filter)</option>}{assets.data?.assets.map((asset) => <option key={asset}>{asset}</option>)}</select></label>
          <label>Typ<select aria-label="Transaktionstyp" value={view.type} onChange={(event) => set({ type: event.target.value })}><option value="">Alle Typen</option>{TYPES.map((type) => <option value={type} key={type}>{label(type)}</option>)}</select></label>
          <label>Datenhinweis<select aria-label="Transaktionshinweis" value={view.status} onChange={(event) => set({ status: event.target.value })}><option value="">Alle</option><option value="present">Mit Datenhinweis</option><option value="none">Ohne Datenhinweis</option></select></label>
          <label>Von (Berlin)<input aria-label="Transaktionen ab Datum" type="date" value={view.start} onChange={(event) => set({ start: event.target.value })} /></label><label>Bis (Berlin)<input aria-label="Transaktionen bis Datum" type="date" value={view.end} onChange={(event) => set({ end: event.target.value })} /></label></>}
        <label>Steuerjahr<select aria-label="Transaktionsjahr" value={view.year} onChange={(event) => set(embeddedSource ? { year: event.target.value, page: view.page, detailPage: 1 } : { year: event.target.value })}><option value="all">Gesamte Historie</option>{Array.from({ length: 12 }, (_, index) => String(2020 + index)).map((year) => <option key={year}>{year}</option>)}{!(Number(view.year) >= 2020 && Number(view.year) <= 2031) && view.year !== "all" && <option>{view.year}</option>}</select></label>
        {!embeddedSource && <label>Sortierung<select aria-label="Transaktionen sortieren" value={view.sort} onChange={(event) => set({ sort: event.target.value })}><option value="newest">Neueste zuerst</option><option value="oldest">Älteste zuerst</option></select></label>}
      </ListTools>
      <ResourceNotice resource={list} label={tab === "ledger" ? "Ledger-Bewegungen" : "Transaktionen"} />
      {!embeddedSource && <><ResourceNotice resource={sources} label="Quellenfilter" /><ResourceNotice resource={assets} label="Assetfilter" /></>}
      {search !== debounced && <p role="status" className="wsMuted">Suche wird aktualisiert; bisherige Treffer bleiben vorläufig sichtbar.</p>}
      {list.data && <><div className="wsSummaryLine"><span>{list.data.total} {tab === "ledger" ? list.data.total === 1 ? "Ledger-Bewegung" : "Ledger-Bewegungen" : list.data.total === 1 ? "Ereignis" : "Ereignisse"}</span>{!embeddedSource && <span>{selected.size} ausgewählt</span>}<HelpTip label="Umfang der Datenhinweise">Unbekannter Ereignistyp, fehlender Rohbeleg oder nicht zugeordneter FIFO-Abgang. Diese zeilenbezogenen Hinweise sind keine vollständige Review-Prüfung und keine Jahresfreigabe.</HelpTip></div>
        {!list.data.rows.length ? <Empty title={filtered ? "Keine passenden Transaktionen" : tab === "ledger" ? "Noch keine berechneten Ledger-Bewegungen" : "Noch keine Transaktionshistorie"} filtered={filtered} onReset={clear}>{!filtered && <a href="#import">Originaldateien importieren</a>}</Empty> : <div className="wsTableScroll" tabIndex={0} role="region" aria-label="Transaktionstabelle, horizontal scrollbar"><table className="wsActivityTable"><thead><tr>{!embeddedSource && <th><input type="checkbox" aria-label="Angezeigte Zeilen auswählen" disabled={pending} checked={list.data.rows.every((row) => selected.has(row.row_id))} onChange={(event) => setSelected((previous) => { const next = new Set(previous); list.data?.rows.forEach((row) => event.target.checked ? next.size < 1000 && next.add(row.row_id) : next.delete(row.row_id)); return next; })} /></th>}<th>Datum · Europe/Berlin</th><th>Typ</th><th>{tab === "ledger" ? "Bewegung" : "Asset / Menge"}</th><th>{tab === "ledger" ? "Konto" : "Gegenwert / Gebühr"}</th><th>Quelle / Status</th><th>Details</th></tr></thead><tbody>{list.data.rows.map((row) => <tr key={row.row_id}>
          {!embeddedSource && <td><input type="checkbox" aria-label={`Zeile ${row.row_id} auswählen`} checked={selected.has(row.row_id)} disabled={pending || !selected.has(row.row_id) && selected.size >= 1000} onChange={(event) => setSelected((previous) => { const next = new Set(previous); if (event.target.checked) next.add(row.row_id); else next.delete(row.row_id); return next; })} /></td>}
          <td>{timestamp(row.event.event_time)}</td><td>{label(row.event.event_type)}</td><td><strong>{tab === "ledger" ? row.ledger_asset : row.event.asset}</strong><br /><ExactQuantity value={tab === "ledger" ? row.ledger_quantity : row.event.quantity} /><small>{/^[-+]?0(?:\.0+)?$/.test((tab === "ledger" ? row.ledger_quantity : row.event.quantity) || "") ? "Keine Mengenänderung" : (tab === "ledger" ? row.ledger_quantity : row.event.quantity)?.startsWith("-") ? "Abgang" : "Zugang"}</small></td><td>{tab === "ledger" ? row.ledger_account : <>{row.event.quote_asset ? <><ExactQuantity value={row.event.quote_quantity} /> {row.event.quote_asset}</> : "Kein Gegenwert hinterlegt"}<small>Gebühr: {row.event.fee_asset ? <><ExactQuantity value={row.event.fee_quantity} /> {row.event.fee_asset}</> : "Nicht separat ausgewiesen"}</small></>}</td><td>{row.event.source}<div className="wsBadges">{row.has_hint && <Badge tone="warning">Datenhinweis</Badge>}{row.corrected && <Badge>Freigegebene Korrektur</Badge>}</div></td><td><button type="button" title="Ereignisdetails öffnen" aria-label={`Details zu Ereignis ${row.event.event_id}`} disabled={pending} onClick={() => open(row.event.event_id)}><ArrowRight size={16} /></button></td>
        </tr>)}</tbody></table></div>}
        <Pager total={list.data.total} page={list.data.page} pages={list.data.pages} size={list.data.page_size} onPage={(page) => set(embeddedSource ? { detailPage: page } : { page })} onSize={embeddedSource ? undefined : (size) => set({ size })} disabled={pending} />
      </>}
      {embeddedSource && <button type="button" onClick={() => navigateView("flows", { tab: "transactions", source: embeddedSource, detail: "", page: 1 })}><ArrowRight size={16} /> Alle Transaktionen dieser Quelle öffnen</button>}
      {!embeddedSource && view.detail && <EventPanel id={view.detail} tab={view.detailTab} onTab={(detailTab) => set({ detailTab })} onClose={() => set({ detail: "", detailTab: "overview" })} />}
      {exporting && <ActivityExport query={query} selected={[...selected]} onClose={() => setExporting(false)} />}
    </>}</TabPanel>
  </section>;
}

function ActivityExport({ query, selected, onClose }: { query: Record<string, unknown>; selected: string[]; onClose: () => void }) {
  const [scope, setScope] = useState("filtered"), [busy, setBusy] = useState(false), [notice, setNotice] = useState(""), [error, setError] = useState("");
  const gate = useRef(false), controller = useRef<AbortController>();
  useEffect(() => () => controller.current?.abort(), []);
  return <DetailPanel title="Transaktionen exportieren" onClose={() => { if (!gate.current) onClose(); }}><form className="wsForm" onSubmit={(event) => {
    event.preventDefault(); if (gate.current) return; gate.current = true; setBusy(true); setError(""); setNotice(""); controller.current = new AbortController();
    void fetch(API_BASE + "/api/v1/activity/export.csv", { method: "POST", signal: controller.current.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, scope, selected_ids: selected }) }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 413 ? "Mehr als 25.000 Zeilen. Zeitraum oder Filter eingrenzen und in mehreren Dateien exportieren." : "Export fehlgeschlagen. Auswahl und Filter prüfen.");
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `steuerreport-${scope}.csv`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(`${response.headers.get("X-Export-Row-Count") || "Unbekannte Anzahl"} Zeilen als CSV bereitgestellt. Der Browser-Download wurde ausgelöst; das Speichern auf dem Gerät bestätigt die Anwendung nicht.`);
    }).catch((caught) => { if (caught.name !== "AbortError") setError(caught.message); }).finally(() => { gate.current = false; setBusy(false); });
  }}><label>Exportumfang<select aria-label="Exportumfang" value={scope} disabled={busy} onChange={(event) => { setScope(event.target.value); setNotice(""); }}><option value="filtered">Aktuelle Filter · alle Ergebnisse, nicht nur diese Seite</option><option value="selected" disabled={!selected.length}>Ausgewählte Einträge ({selected.length}) innerhalb der aktuellen Filter</option><option value="all">Vollständige Historie · alle Filter ignorieren</option></select></label><p>Format: CSV mit Originalpräzision. {query.mode === "ledger" ? "Einzelne Ledger-Bewegungen" : "Kanonische Ereignisse"}. Maximal 25.000 Zeilen je Export; größere Datenmengen nach Zeitraum aufteilen. Kein gespeichertes Berichtspaket und keine Jahresfreigabe.</p>{error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}<div className="wsActionFooter"><button type="button" disabled={busy} onClick={onClose}>Schließen</button><button type="submit" disabled={busy || scope === "selected" && !selected.length}><Download size={16} />{busy ? "CSV wird erstellt" : "CSV erstellen und herunterladen"}</button></div></form></DetailPanel>;
}

function EventPanel({ id, tab, onTab, onClose }: { id: string; tab: string; onTab: (tab: string) => void; onClose: () => void }) {
  const resource = useResource<ActivityDetail>("event-detail:" + id, (signal) => readApi(`/api/v1/activity/events/${encodeURIComponent(id)}`, signal));
  const detail = resource.data?.event.event_id === id ? resource.data : undefined;
  const active = ["overview", "original", "ledger", "tax", "history"].includes(tab) ? tab : "overview";
  return <DetailPanel title="Transaktionsdetails" onClose={onClose}><ResourceNotice resource={resource} label="Ereignisdetails" />{detail && <><Tabs name="Ereignisdetails" active={active} onChange={onTab} items={[{ id: "overview", label: "Ereignis" }, { id: "original", label: "Originalbeleg" }, { id: "ledger", label: "Ledger" }, { id: "tax", label: "Steuerzuordnung" }, { id: "history", label: "Änderungen" }]} /><TabPanel name="Ereignisdetails" active={active}>
    {active === "overview" && <><dl className="wsFacts">{[["Ereignis-ID", detail.event.event_id], ["Zeitpunkt", timestamp(detail.event.event_time)], ["Quelle", detail.event.source], ["Typ", label(detail.event.event_type)], ["Asset und Menge", `${detail.event.quantity} ${detail.event.asset}`], ["Gegenwert", detail.event.quote_asset ? `${detail.event.quote_quantity} ${detail.event.quote_asset}` : "Nicht separat hinterlegt"], ["Gebühr", detail.event.fee_asset ? `${detail.event.fee_quantity} ${detail.event.fee_asset}` : "Nicht separat hinterlegt"], ["Transaktions-ID", detail.event.tx_id || "Nicht hinterlegt"]].map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl><p>{detail.transfer_relationship}</p><a className="wsButton" href="#flows?tab=transfers"><ArrowRight size={16} /> Transferkandidaten separat prüfen</a></>}
    {active === "original" && (detail.raw ? <><dl className="wsFacts">{["filename", "file_hash", "row_number", "batch_id"].map((key) => <div key={key}><dt>{{ filename: "Importdatei", file_hash: "Datei-Hash", row_number: "Originalzeile", batch_id: "Import-ID" }[key]}</dt><dd>{String(detail.raw?.[key] ?? "Nicht hinterlegt")}</dd></div>)}</dl><pre>{String(detail.raw.payload_json)}</pre><a className="wsButton" href={`${API_BASE}/api/v1/import/batches/${encodeURIComponent(String(detail.raw.batch_id))}/trace.json`} target="_blank" rel="noreferrer"><Download size={16} /> Import-Belegspur</a></> : <Empty title="Kein zugeordneter Rohbeleg">Originalquelle prüfen; fehlender Beleg ist kein bestätigter Geschäftsvorfall.</Empty>)}
    {active === "ledger" && <><p>{detail.ledger_count} berechnete Bewegungen zu diesem Ereignis. Anzeige maximal {detail.details_limit} Zeilen; die vollständige paginierte Ledger-Ansicht bleibt separat erreichbar.</p><RecordTable rows={detail.ledger} columns={["asset", "delta_quantity", "balance_quantity", "account"]} /></>}
    {active === "tax" && <><p>{detail.tax_lines_count} vorhandene Steuerzeilen. Keine eigene Neuberechnung oder neue fachliche Einordnung durch diese Ansicht.</p><RecordTable rows={detail.tax_lines} columns={["asset", "quantity", "acquisition_cost_eur", "disposal_proceeds_eur", "gain_loss_eur", "holding_days", "lot_id"]} /></>}
    {active === "history" && <>{!detail.corrections.length && !detail.decisions.length ? <Empty title="Keine verknüpfte freigegebene Änderung gefunden">Dies ist keine Aussage über außerhalb der Anwendung erfolgte Änderungen.</Empty> : <><RecordTable rows={detail.decisions} columns={["created_at", "title", "rationale", "evidence_ref"]} />{detail.corrections.map((correction, index) => <details key={index}><summary>Freigegebene Korrektur · {String(correction.change_set_id)}</summary><pre>{JSON.stringify(correction, null, 2)}</pre><a href={`${API_BASE}/api/v1/ai/changes/${encodeURIComponent(String(correction.change_set_id))}/audit.json`} target="_blank" rel="noreferrer">Audit-JSON öffnen</a></details>)}</>}<a className="wsButton" href="#ai"><ArrowRight size={16} /> Bestehenden KI-Korrekturablauf öffnen</a></>}
  </TabPanel></>}</DetailPanel>;
}

export function RecordTable({ rows, columns }: { rows: Record<string, unknown>[]; columns: string[] }) {
  const names: Record<string, string> = { asset: "Asset", quantity: "Menge", delta_quantity: "Mengenänderung", balance_quantity: "Bestand danach", account: "Konto", acquisition_cost_eur: "Anschaffungskosten EUR", disposal_proceeds_eur: "Erlös EUR", gain_loss_eur: "Gewinn/Verlust EUR", holding_days: "Haltedauer (Tage)", lot_id: "FIFO-Lot", created_at: "Zeitpunkt", title: "Entscheidung", rationale: "Begründung", evidence_ref: "Beleg" };
  return rows.length ? <div className="wsTableScroll"><table><thead><tr>{columns.map((column) => <th key={column}>{names[column] || column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{row[column] === null || row[column] === undefined ? "Nicht hinterlegt" : String(row[column])}</td>)}</tr>)}</tbody></table></div> : <Empty title="Keine zugeordneten Einträge vorhanden" />;
}
