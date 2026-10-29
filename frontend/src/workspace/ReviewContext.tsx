import { ArrowLeft, ArrowRight } from "lucide-react";
import { clearViewSearch, navigateView, parseView } from "./view-state";
import type { ReviewItem } from "./types";

export function reviewTaskCount(source: { review_tasks_count?: number; ambiguous_review_tasks_count?: number }) {
  return (source.review_tasks_count || 0) + (source.ambiguous_review_tasks_count || 0);
}
export function sourceHasHints(source: { issues_count: number; review_tasks_count?: number; ambiguous_review_tasks_count?: number; warning?: string | null }) {
  return source.issues_count > 0 || reviewTaskCount(source) > 0 || !!source.warning;
}

export function openLedgerContext(item: ReviewItem) {
  clearViewSearch("flows");
  navigateView("flows", {
    tab: "ledger", source: item.source_ref || "", account: item.account_ref || "",
    asset: item.task.asset || "", type: "", status: "", start: "", end: "",
    year: item.task.tax_year ? String(item.task.tax_year) : "all", page: 1,
    detail: "", task: item.task.task_id
  });
}

export function openSourceContext(item: ReviewItem, ref = item.source_ref) {
  if (ref) navigateView("sources", { detail: ref, detailTab: "issues", task: item.task.task_id });
}

export function openManualCorrectionContext(context: {
  targetId: string; kind?: "event" | "price"; year?: string; task?: string;
  source?: string; account?: string; evidenceId?: string; returnTo: "review" | "flows" | "sources";
}) {
  const current = parseView();
  navigateView("ai", {
    tab: "changes", target: context.targetId, targetKind: context.kind || "event",
    year: context.year || current.year, task: context.task || "", source: context.source || "",
    account: context.account || "", evidenceId: context.evidenceId || "", returnTo: context.returnTo,
    detail: "", detailTab: "overview", page: 1
  });
}

export function ReviewReturn({ task }: { task: string }) {
  return task ? <button type="button" className="wsReturn" onClick={() => navigateView("review", { detail: task })}><ArrowLeft size={16} /> Zur Review-Aufgabe zurück</button> : null;
}

export function ContextNote({ item }: { item: ReviewItem }) {
  return <div className={item.context_status === "matched" ? "wsMuted" : "wsInlineWarning"}>
    <strong>{item.context_label || item.task.source_group || "Fachliche Prüfung"}</strong>
    <p>{item.context_note || "Die konkrete Zuordnung ist noch zu prüfen."}</p>
    {item.context_status === "ambiguous" && <div className="wsActionFooter">{item.candidate_source_refs.map((ref, index) => <button key={ref} type="button" onClick={() => openSourceContext(item, ref)}><ArrowRight size={16} /> Mögliche Quelle {index + 1} prüfen</button>)}</div>}
  </div>;
}

export function evidenceLabel(reference: string, item: ReviewItem): string {
  if (reference.startsWith("account:")) return `${item.context_label || "Kontobezug"} — Prüfbezug, kein Originalbeleg`;
  if (reference.startsWith("event:") || reference.startsWith("canonical:")) return "Ereignisbezug: " + reference.split(":").slice(1).join(":");
  return reference;
}
