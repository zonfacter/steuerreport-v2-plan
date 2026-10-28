import { useEffect, useState } from "react";

const TABS: Record<string, readonly string[]> = {
  dashboard: ["holdings", "sources", "development"], sources: ["list", "expert"],
  flows: ["transactions", "ledger", "flows", "transfers"], review: ["tasks", "evidence", "expert"],
  tax: ["guided", "details", "expert"], export: ["packages", "evidence", "expert"],
  import: ["assistant", "preflight", "expert"], portfolio: ["overview", "reconciliation", "prices", "expert"],
  admin: ["overview", "updates"], ai: ["text", "changes"], help: ["overview"],
  stichtage: ["overview"], zugewinn: ["overview"]
};
export type ViewState = {
  section: string; tab: string; page: number; size: number; sort: string; year: string;
  asset: string; source: string; status: string; type: string; start: string; end: string;
  detail: string; detailTab: string; detailPage: number; category: string; account: string; task: string;
};
const TYPES = ["trade", "transfer", "fee", "reward", "income", "staking", "mining", "derivative", "unknown"];
const STATUSES = ["configured", "setup", "failed", "stale", "reconciliation", "review", "present", "none", "high", "medium", "low", "fifo", "price", "import", "wallet", "evidence", "tax"];
const lastViews = new Map<string, ViewState>();
const localSearch = new Map<string, string>();
const viewsEvent = "steuerreport:viewchange";
let selectedYear = "2025";

export function clearViewSearch(section: string) {
  localSearch.delete(section);
  window.dispatchEvent(new Event(viewsEvent));
}

function validDate(value: string) {
  return /^20\d{2}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
function defaultYear(section: string) { return ["dashboard", "tax", "export"].includes(section) ? "2025" : "all"; }
export function parseView(hash = window.location.hash): ViewState {
  const [name, query = ""] = hash.replace(/^#\/?/, "").split("?", 2);
  const section = Object.hasOwn(TABS, name) ? name : "dashboard";
  const values = new URLSearchParams(query);
  const int = (key: string, fallback: number, max: number) => /^\d{1,7}$/.test(values.get(key) || "") ? Math.max(1, Math.min(max, Number(values.get(key)))) : fallback;
  const candidateYear = values.get("year") || defaultYear(section);
  const year = candidateYear === "all" && !["dashboard", "tax", "export"].includes(section) ? "all" : /^(20\d{2}|2100)$/.test(candidateYear) ? candidateYear : defaultYear(section);
  const state: ViewState = {
    section, tab: TABS[section].includes(values.get("tab") || "") ? values.get("tab")! : TABS[section][0],
    page: int("page", 1, 1_000_000), size: [10, 25, 50, 100].includes(Number(values.get("size"))) ? Number(values.get("size")) : 25,
    sort: ["newest", "oldest", "name", "value", "issues"].includes(values.get("sort") || "") ? values.get("sort")! : section === "sources" ? "name" : "newest",
    year, asset: /^[A-Za-z0-9._:-]{1,128}$/.test(values.get("asset") || "") ? values.get("asset")! : "",
    source: /^s_[a-f0-9]{20}$/.test(values.get("source") || "") ? values.get("source")! : "",
    account: /^a_[a-f0-9]{20}$/.test(values.get("account") || "") ? values.get("account")! : "",
    task: /^[A-Za-z0-9_-]{1,80}$/.test(values.get("task") || "") ? values.get("task")! : "",
    status: STATUSES.includes(values.get("status") || "") ? values.get("status")! : "",
    type: TYPES.includes(values.get("type") || "") ? values.get("type")! : "",
    category: ["fifo", "price", "import", "wallet", "reconciliation", "evidence", "tax"].includes(values.get("category") || "") ? values.get("category")! : "",
    start: validDate(values.get("start") || "") ? values.get("start")! : "",
    end: validDate(values.get("end") || "") ? values.get("end")! : "",
    detail: /^(s_[a-f0-9]{20}|[A-Za-z0-9_-]{1,80})$/.test(values.get("detail") || "") ? values.get("detail")! : "",
    detailTab: ["overview", "holdings", "transactions", "import", "issues", "settings", "original", "ledger", "tax", "history"].includes(values.get("detailTab") || "") ? values.get("detailTab")! : "overview",
    detailPage: int("detailPage", 1, 1_000_000)
  };
  if (state.start && state.end && state.start > state.end) state.end = "";
  if (section === "flows" && !["newest", "oldest"].includes(state.sort)) state.sort = "newest";
  if (section === "sources" && !["name", "value", "issues"].includes(state.sort)) state.sort = "name";
  const validStatuses = section === "sources" ? ["configured", "setup", "failed", "stale", "reconciliation", "review"] : section === "review" ? ["high", "medium", "low"] : section === "flows" ? ["present", "none"] : [];
  if (!validStatuses.includes(state.status)) state.status = "";
  return state;
}

export function viewHash(view: ViewState) {
  const values = new URLSearchParams();
  if (view.tab !== TABS[view.section][0]) values.set("tab", view.tab);
  if (view.year !== defaultYear(view.section)) values.set("year", view.year);
  if (view.page !== 1) values.set("page", String(view.page));
  if (view.size !== 25) values.set("size", String(view.size));
  if (view.sort !== (view.section === "sources" ? "name" : "newest")) values.set("sort", view.sort);
  for (const key of ["asset", "source", "status", "type", "start", "end", "detail", "category", "account", "task"] as const) if (view[key]) values.set(key, view[key]);
  if (view.detail && view.detailTab !== "overview") values.set("detailTab", view.detailTab);
  if (view.detail && view.detailPage !== 1) values.set("detailPage", String(view.detailPage));
  return `#${view.section}${values.size ? "?" + values.toString() : ""}`;
}

export function navigateView(section: string, patch: Partial<ViewState> = {}, replace = false) {
  if (!Object.hasOwn(TABS, section)) section = "dashboard";
  const current = parseView();
  if (current.year !== "all") selectedYear = current.year;
  lastViews.set(current.section, current);
  const base = section === current.section ? current : lastViews.get(section) || parseView("#" + section);
  const candidate = { ...base, ...(["dashboard", "tax", "export"].includes(section) && current.section !== section ? { year: selectedYear } : {}), ...patch, section };
  const next = parseView(viewHash(candidate));
  const hash = viewHash(next);
  if (hash !== window.location.hash) {
    window.history[replace ? "replaceState" : "pushState"](null, "", hash);
    window.dispatchEvent(new Event(viewsEvent));
  }
}

export function useViewState(section: string, trackAllSections = false) {
  const [view, setView] = useState(() => parseView());
  const [search, setSearchState] = useState(() => localSearch.get(section) || "");
  useEffect(() => { setSearchState(localSearch.get(section) || ""); }, [section]);
  useEffect(() => {
    const update = () => {
      const next = parseView();
      setSearchState(localSearch.get(section) || "");
      if (trackAllSections || next.section === section) setView(next);
      const canonical = viewHash(next);
      if (window.location.hash !== canonical) window.history.replaceState(null, "", canonical);
    };
    update();
    window.addEventListener("hashchange", update); window.addEventListener("popstate", update); window.addEventListener(viewsEvent, update);
    return () => { window.removeEventListener("hashchange", update); window.removeEventListener("popstate", update); window.removeEventListener(viewsEvent, update); };
  }, [section, trackAllSections]);
  const set = (patch: Partial<ViewState>, replace = false) => {
    const reset = ["asset", "source", "status", "type", "sort", "size", "year", "start", "end", "category", "account"].some((key) => key in patch);
    navigateView(section, { ...(reset && !("page" in patch) ? { page: 1 } : {}), ...patch }, replace);
  };
  const setSearch = (value: string) => { const safe = value.slice(0, 200); localSearch.set(section, safe); setSearchState(safe); set({ page: 1 }); };
  const reset = () => { setSearch(""); set({ asset: "", source: "", status: "", type: "", start: "", end: "", category: "", account: "", page: 1 }); };
  const actual = parseView();
  const scoped = trackAllSections || view.section === section ? view : actual.section === section ? actual : parseView("#" + section);
  return { view: scoped, set, search, setSearch, reset };
}

export function listenView(listener: () => void) {
  for (const event of ["hashchange", "popstate", viewsEvent]) window.addEventListener(event, listener);
  return () => { for (const event of ["hashchange", "popstate", viewsEvent]) window.removeEventListener(event, listener); };
}
