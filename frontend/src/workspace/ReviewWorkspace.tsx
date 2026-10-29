import { type ReactNode, useEffect } from "react";
import { ArrowRight, ClipboardCheck } from "lucide-react";
import { navigateView, useViewState } from "./view-state";
import { readApi, useDebounced, useResource } from "./resource";
import { Badge, DetailPanel, Empty, label, ListTools, Pager, ResourceNotice, TabPanel, Tabs } from "./Ui";
import type { Status, ReviewItem } from "./types";
import { ContextNote, evidenceLabel, openLedgerContext, openManualCorrectionContext, openSourceContext } from "./ReviewContext";

type Item = ReviewItem;
type Page = { items: Item[]; total: number; unfiltered_total: number; blocking_total: number; page: number; pages: number; page_size: number; generated_at: string };
const categories = ["fifo", "price", "import", "wallet", "reconciliation", "evidence", "tax"];
export function ReviewWorkspace({ technical, onMode }: { technical: ReactNode; onMode: (mode: "tasks" | "evidence" | "expert") => void }) {
  const { view, set, search, setSearch, reset } = useViewState("review");
  const debounced = useDebounced(search);
  useEffect(() => { onMode(view.tab as "tasks" | "evidence" | "expert"); }, [view.tab]);
  const query = { search: debounced, category: view.category || null,
    priority: ["high", "medium", "low"].includes(view.status) ? view.status : null, year: view.year === "all" ? null : Number(view.year), page: view.page, page_size: view.size };
  const sourceQuery = view.source ? { ...query, source_ref: view.source } : query;
  const resource = useResource<Page>(view.tab === "tasks" ? "review:" + JSON.stringify(sourceQuery) : null, (signal) => readApi("/api/v1/workspace/review/query", signal, sourceQuery));
  const status = useResource<Status>(view.tab === "tasks" ? "review-status:" + view.year : null, (signal) => readApi(`/api/v1/workspace/status?year=${view.year === "all" ? "2025" : view.year}`, signal));
  useEffect(() => { if (resource.status === "ready" && resource.key === "review:" + JSON.stringify(sourceQuery) && resource.data?.page !== view.page) set({ page: resource.data!.page }, true); }, [resource.status, resource.data?.page, view.page, resource.key, JSON.stringify(sourceQuery)]);
  const filtered = !!search || !!view.category || !!view.status || !!view.source;
  return <section className="wsPage" aria-label="Fachliche Aufgaben">
    <Tabs name="Reviewansicht" active={view.tab} items={[{ id: "tasks", label: "Aufgaben" }, { id: "evidence", label: "Belegspuren" }, { id: "expert", label: "Expertenmodus" }]} onChange={(tab) => set({ tab, detail: "" })} />
    <TabPanel name="Reviewansicht" active={view.tab}>{view.tab !== "tasks" ? <div className="wsTechnical">{technical}</div> : <>
      <ResourceNotice resource={resource} label="Prüfaufgaben" /><ResourceNotice resource={status} label="Prüfgrundlage" />
      {resource.data && <div className="wsSummaryLine"><span>{resource.data.unfiltered_total} {resource.data.unfiltered_total === 1 ? "Aufgabe" : "Aufgaben"} im geprüften Datenstand</span><span>{resource.data.blocking_total} {resource.data.blocking_total === 1 ? "blockierende Aufgabe" : "blockierende Aufgaben"}</span><span>Priorität aus vorhandenen Fachregeln</span></div>}
      <ListTools search={search} onSearch={setSearch} chips={[
        ...(view.source ? [{ label: "Quellenbezug aktiv", remove: () => set({ source: "" }) }] : []),
        ...(view.category ? [{ label: label(view.category), remove: () => set({ category: "" }) }] : []),
        ...(view.status ? [{ label: label(view.status), remove: () => set({ status: "" }) }] : [])
      ]} onReset={reset}>
        <label>Kategorie<select aria-label="Aufgabenkategorie" value={view.category} onChange={(event) => set({ category: event.target.value })}><option value="">Alle Kategorien</option>{categories.map((category) => <option key={category} value={category}>{label(category)}</option>)}</select></label>
        <label>Priorität<select aria-label="Aufgabenpriorität" value={view.status} onChange={(event) => set({ status: event.target.value })}><option value="">Alle Prioritäten</option>{["high", "medium", "low"].map((priority) => <option key={priority} value={priority}>{label(priority)}</option>)}</select></label>
        <label>Steuerjahr<select aria-label="Aufgabenjahr" value={view.year} onChange={(event) => set({ year: event.target.value })}><option value="all">Alle Jahre und übergreifende Aufgaben</option>{Array.from({ length: 12 }, (_, index) => String(2020 + index)).map((year) => <option key={year}>{year}</option>)}</select></label>
      </ListTools>
      {resource.data && !resource.data.items.length ? <Empty title={filtered ? "Keine passenden Aufgaben" : !status.data ? "Aufgabenliste leer — Prüfgrundlage noch nicht vollständig geladen" : !status.data.events_count ? "Noch keine importierte Transaktionshistorie für die Prüfung" : "Keine Aufgaben im abgefragten Datenstand"} filtered={filtered} onReset={reset}>{!filtered && "Eine leere Aufgabenliste erteilt keine Jahresfreigabe. Quellenabdeckung, Berechnungsstand und Pflichtbelege bleiben separat zu prüfen."}</Empty>
        : <div className="wsTaskList">{resource.data?.items.map((item) => <article className="wsTaskRow" key={item.task.task_id}><div><div className="wsBadges"><Badge tone={item.task.priority === "high" ? "danger" : "warning"}>{label(item.task.priority)}</Badge><Badge>{label(item.task.category)}</Badge>{item.task.blocks_export && <Badge tone="danger">Blockiert das Fach-Gate</Badge>}</div><button type="button" className="wsTextButton" disabled={resource.stale} onClick={() => set({ detail: item.task.task_id })}>{item.task.title}</button><p>{item.task.detail}</p><small>{item.context_label || item.task.source_group || "Fachliche Prüfung"}{item.task.tax_year ? ` · ${item.task.tax_year}` : ""}</small></div><button type="button" disabled={resource.stale} onClick={() => set({ detail: item.task.task_id })}><ClipboardCheck size={16} /> Prüfen</button></article>)}</div>}
      {resource.data && <Pager total={resource.data.total} page={resource.data.page} pages={resource.data.pages} size={view.size} onPage={(page) => set({ page })} onSize={(size) => set({ size })} disabled={resource.stale || resource.status === "loading"} />}
      {view.detail && <ReviewTaskPanel key={view.detail} taskId={view.detail} onClose={() => set({ detail: "" })} />}
    </>}</TabPanel>
  </section>;
}

function ReviewTaskPanel({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const selected = useResource<Page>("review-task:" + taskId, (signal) => readApi("/api/v1/workspace/review/query", signal, { task_id: taskId }));
  const active = selected.data?.items.find((item) => item.task.task_id === taskId);
  return <DetailPanel title={active?.task.title || "Prüfaufgabe"} onClose={onClose}>
    <ResourceNotice resource={selected} label="Prüfaufgabe" />
    {selected.status === "ready" && !active && <Empty title="Prüfaufgabe nicht gefunden">Diese Aufgabe ist im abgefragten Datenstand nicht mehr vorhanden. Filter und Seite bleiben erhalten.</Empty>}
    {active && <><ContextNote item={active} /><dl className="wsFacts"><div><dt>Problem</dt><dd>{active.task.detail}</dd></div><div><dt>Auswirkung</dt><dd>{active.task.blocks_export ? "Dieses Fach-Gate blockiert den Export. Weitere Jahres- und Belegvoraussetzungen bleiben separat bestehen." : "Prüfung erforderlich; keine eigenständige Aussage über die Jahresfreigabe."}</dd></div><div><dt>Benötigte Belege</dt><dd>{active.task.evidence_refs.length ? active.task.evidence_refs.map((value) => <div key={value}>{evidenceLabel(value, active)}</div>) : "Die Aufgabe enthält keine konkrete Beleg-ID. Originalunterlagen zur genannten Quelle und Ursache prüfen."}</dd></div><div><dt>Nächster Schritt</dt><dd>{active.task.action_label}</dd></div></dl><div className="wsActionFooter">{active.event_ids.map((id) => <div key={id} className="wsActionGroup"><button type="button" disabled={selected.stale} onClick={() => navigateView("flows", { tab: "transactions", detail: id, detailTab: "overview", page: 1, task: active.task.task_id, source: active.source_ref || "", account: active.account_ref || "", ...(active.task.tax_year ? { year: String(active.task.tax_year) } : {}) })}><ArrowRight size={16} /> Betroffenes Ereignis öffnen</button><button type="button" disabled={selected.stale} onClick={() => openManualCorrectionContext({ targetId: id, year: active.task.tax_year ? String(active.task.tax_year) : undefined, task: active.task.task_id, source: active.source_ref || "", account: active.account_ref || "", evidenceId: active.raw_evidence_by_event?.[id] || "", returnTo: "review" })}><ArrowRight size={16} /> Manuelle Korrektur vorbereiten</button></div>)}{active.source_ref && <button type="button" disabled={selected.stale} onClick={() => openSourceContext(active)}><ArrowRight size={16} /> Betroffene Quelle öffnen</button>}<button type="button" disabled={selected.stale} onClick={() => openTaskWorkflow(active)}><ArrowRight size={16} /> Bestehenden Prüfablauf öffnen</button></div><details className="wsTechnical"><summary>Technische Zuordnung und Rohstatus</summary><pre>{JSON.stringify(active.task, null, 2)}</pre></details></>}
  </DetailPanel>;
}

function openTaskWorkflow(item: ReviewItem) {
  const task = item.task;
  if (item.account_ref && task.category === "reconciliation") { openLedgerContext(item); return; }
  if (task.category === "import") navigateView("import");
  else if (["reconciliation", "wallet"].includes(task.category) && item.source_ref) openSourceContext(item);
  else if (["reconciliation", "wallet"].includes(task.category)) openLedgerContext(item);
  else if (task.category === "price") navigateView("portfolio", { tab: "expert" });
  else if (task.category === "evidence") navigateView("review", { tab: "evidence", detail: "" });
  else navigateView("tax", { tab: "details", year: String(task.tax_year || 2025) });
}
