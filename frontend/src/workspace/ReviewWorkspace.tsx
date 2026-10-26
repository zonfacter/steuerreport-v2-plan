import { type ReactNode, useEffect } from "react";
import { ArrowRight, ClipboardCheck } from "lucide-react";
import { navigateView, useViewState } from "./view-state";
import { readApi, useDebounced, useResource } from "./resource";
import { Badge, DetailPanel, Empty, label, ListTools, Pager, ResourceNotice, TabPanel, Tabs } from "./Ui";
import type { Status, Task } from "./types";

type Item = { task: Task; event_ids: string[]; source_ref: string | null };
type Page = { items: Item[]; total: number; unfiltered_total: number; blocking_total: number; page: number; pages: number; page_size: number; generated_at: string };
const categories = ["fifo", "price", "import", "wallet", "reconciliation", "evidence", "tax"];
export function ReviewWorkspace({ technical, onMode }: { technical: ReactNode; onMode: (mode: "tasks" | "evidence" | "expert") => void }) {
  const { view, set, search, setSearch, reset } = useViewState("review");
  const debounced = useDebounced(search);
  useEffect(() => { onMode(view.tab as "tasks" | "evidence" | "expert"); }, [view.tab]);
  const query = { search: debounced, category: view.category || null,
    priority: ["high", "medium", "low"].includes(view.status) ? view.status : null, year: view.year === "all" ? null : Number(view.year), page: view.page, page_size: view.size };
  const resource = useResource<Page>(view.tab === "tasks" ? "review:" + JSON.stringify(query) : null, (signal) => readApi("/api/v1/workspace/review/query", signal, query));
  const status = useResource<Status>(view.tab === "tasks" ? "review-status:" + view.year : null, (signal) => readApi(`/api/v1/workspace/status?year=${view.year === "all" ? "2025" : view.year}`, signal));
  useEffect(() => { if (resource.status === "ready" && resource.key === "review:" + JSON.stringify(query) && resource.data?.page !== view.page) set({ page: resource.data!.page }, true); }, [resource.status, resource.data?.page, view.page, resource.key, JSON.stringify(query)]);
  const filtered = !!search || !!view.category || !!view.status;
  const selected = useResource<Page>(view.detail ? "review-task:" + view.detail : null, (signal) => readApi("/api/v1/workspace/review/query", signal, { task_id: view.detail }));
  const active = selected.data?.items.find((item) => item.task.task_id === view.detail) || resource.data?.items.find((item) => item.task.task_id === view.detail);
  return <section className="wsPage" aria-label="Fachliche Aufgaben">
    <Tabs name="Reviewansicht" active={view.tab} items={[{ id: "tasks", label: "Aufgaben" }, { id: "evidence", label: "Belegspuren" }, { id: "expert", label: "Expertenmodus" }]} onChange={(tab) => set({ tab, detail: "" })} />
    <TabPanel name="Reviewansicht" active={view.tab}>{view.tab !== "tasks" ? <div className="wsTechnical">{technical}</div> : <>
      <ResourceNotice resource={resource} label="Prüfaufgaben" /><ResourceNotice resource={status} label="Prüfgrundlage" />
      {resource.data && <div className="wsSummaryLine"><span>{resource.data.unfiltered_total} Aufgaben im geprüften Datenstand</span><span>{resource.data.blocking_total} blockierende Aufgaben</span><span>Priorität aus vorhandenen Fachregeln</span></div>}
      <ListTools search={search} onSearch={setSearch} chips={[...(view.category ? [{ label: label(view.category), remove: () => set({ category: "" }) }] : []), ...(view.status ? [{ label: label(view.status), remove: () => set({ status: "" }) }] : [])]} onReset={reset}>
        <label>Kategorie<select aria-label="Aufgabenkategorie" value={view.category} onChange={(event) => set({ category: event.target.value })}><option value="">Alle Kategorien</option>{categories.map((category) => <option key={category} value={category}>{label(category)}</option>)}</select></label>
        <label>Priorität<select aria-label="Aufgabenpriorität" value={view.status} onChange={(event) => set({ status: event.target.value })}><option value="">Alle Prioritäten</option>{["high", "medium", "low"].map((priority) => <option key={priority} value={priority}>{label(priority)}</option>)}</select></label>
        <label>Steuerjahr<select aria-label="Aufgabenjahr" value={view.year} onChange={(event) => set({ year: event.target.value })}><option value="all">Alle Jahre und übergreifende Aufgaben</option>{Array.from({ length: 12 }, (_, index) => String(2020 + index)).map((year) => <option key={year}>{year}</option>)}</select></label>
      </ListTools>
      {resource.data && !resource.data.items.length ? <Empty title={filtered ? "Keine passenden Aufgaben" : !status.data ? "Aufgabenliste leer — Prüfgrundlage noch nicht vollständig geladen" : !status.data.events_count ? "Noch keine importierte Transaktionshistorie für die Prüfung" : "Keine Aufgaben im abgefragten Datenstand"} filtered={filtered} onReset={reset}>{!filtered && "Eine leere Aufgabenliste erteilt keine Jahresfreigabe. Quellenabdeckung, Berechnungsstand und Pflichtbelege bleiben separat zu prüfen."}</Empty>
        : <div className="wsTaskList">{resource.data?.items.map((item) => <article className="wsTaskRow" key={item.task.task_id}><div><div className="wsBadges"><Badge tone={item.task.priority === "high" ? "danger" : "warning"}>{label(item.task.priority)}</Badge><Badge>{label(item.task.category)}</Badge>{item.task.blocks_export && <Badge tone="danger">Blockiert das Fach-Gate</Badge>}</div><button type="button" className="wsTextButton" disabled={resource.stale} onClick={() => set({ detail: item.task.task_id })}>{item.task.title}</button><p>{item.task.detail}</p><small>{item.task.source_group || item.task.source}{item.task.asset ? ` · ${item.task.asset}` : ""}{item.task.tax_year ? ` · ${item.task.tax_year}` : ""}</small></div><button type="button" disabled={resource.stale} onClick={() => set({ detail: item.task.task_id })}><ClipboardCheck size={16} /> Prüfen</button></article>)}</div>}
      {resource.data && <Pager total={resource.data.total} page={resource.data.page} pages={resource.data.pages} size={view.size} onPage={(page) => set({ page })} onSize={(size) => set({ size })} disabled={resource.stale || resource.status === "loading"} />}
      {view.detail && <DetailPanel title={active?.task.title || "Prüfaufgabe"} onClose={() => set({ detail: "" })}>{!active ? <Empty title="Aufgabe nicht in der aktuellen Seite">Filter und Seite bleiben erhalten. Schließen und Liste aktualisieren.</Empty> : <><dl className="wsFacts"><div><dt>Problem</dt><dd>{active.task.detail}</dd></div><div><dt>Auswirkung</dt><dd>{active.task.blocks_export ? "Dieses Fach-Gate blockiert den Export. Weitere Jahres- und Belegvoraussetzungen bleiben separat bestehen." : "Prüfung erforderlich; keine eigenständige Aussage über die Jahresfreigabe."}</dd></div><div><dt>Benötigte Belege</dt><dd>{active.task.evidence_refs.length ? active.task.evidence_refs.map((value) => <div key={value}>{value}</div>) : "Die Aufgabe enthält keine konkrete Beleg-ID. Originalunterlagen zur genannten Quelle und Ursache prüfen."}</dd></div><div><dt>Nächster Schritt</dt><dd>{active.task.action_label}</dd></div></dl><div className="wsActionFooter">{active.event_ids.map((id) => <button key={id} type="button" onClick={() => navigateView("flows", { tab: "transactions", detail: id, detailTab: "overview", page: 1 })}><ArrowRight size={16} /> Betroffenes Ereignis öffnen</button>)}{active.source_ref && <button type="button" onClick={() => navigateView("sources", { detail: active.source_ref!, detailTab: "issues" })}><ArrowRight size={16} /> Betroffene Quelle öffnen</button>}<button type="button" onClick={() => openTaskWorkflow(active.task)}><ArrowRight size={16} /> Bestehenden Prüfablauf öffnen</button></div><details className="wsTechnical"><summary>Technische Zuordnung und Rohstatus</summary><pre>{JSON.stringify(active.task, null, 2)}</pre></details></>}</DetailPanel>}
    </>}</TabPanel>
  </section>;
}

function openTaskWorkflow(task: Task) {
  if (task.category === "import") navigateView("import");
  else if (["reconciliation", "wallet"].includes(task.category)) navigateView("sources");
  else if (task.category === "price") navigateView("portfolio", { tab: "expert" });
  else if (task.category === "evidence") navigateView("review", { tab: "evidence", detail: "" });
  else navigateView("tax", { tab: "details", year: String(task.tax_year || 2025) });
}
