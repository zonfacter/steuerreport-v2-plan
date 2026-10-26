import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, ArrowLeft, ArrowRight, Check, ChevronDown, LoaderCircle, Search, X } from "lucide-react";
import { HelpTip } from "../Help";
import { compactQuantity, type Resource, timestamp } from "./resource";

export const LABELS: Record<string, string> = {
  known_wallet_missing_import: "Wallet bekannt — Transaktionen noch nicht importiert", missing_live_anchor: "Noch kein aktueller Vergleichsbestand verfügbar",
  missing_credentials: "API-Zugangsdaten fehlen", missing_snapshot: "Noch kein gespeicherter Prüfstand vorhanden", ledger_only: "Nur aus importierten Transaktionen berechnet",
  configured: "Eingerichtet", registered: "Registriert", imported: "Dateiimport vorhanden", not_required: "Kein API-Zugang erforderlich", not_configured: "Einrichtung erforderlich",
  missing: "Noch nicht verfügbar", fresh: "Datenstand aktuell", stale: "Datenstand veraltet", failed: "Abruf fehlgeschlagen", error: "Prüfung fehlgeschlagen",
  refreshed: "Abruf erfolgreich", empty_response: "Leerer Bestand bestätigt", missing_configuration: "Konfiguration fehlt", fetch_failed: "Abruf fehlgeschlagen",
  ownership_verified_pending_registry: "Eigentum bestätigt — Quellenfreigabe offen", pending_registry: "Quellenfreigabe offen", not_assessed: "Noch nicht geprüft",
  live: "Gespeicherter Live-Bestand", live_api: "Gespeicherter API-Bestand", live_snapshot: "Gespeicherter Live-Bestand", stored_live_snapshot: "Gespeicherter Live-Bestand", ledger: "Berechneter Ledger-Bestand",
  expected_zero_policy_no_current_live: "Keine aktuelle Bestandsbestätigung — technische Nullannahme",
  ledger_fallback: "Berechneter Ledger-Bestand", unavailable: "Bewertung noch nicht verfügbar", high: "Hohe Priorität", medium: "Mittlere Priorität", low: "Niedrige Priorität",
  fifo: "Anschaffungen / FIFO", price: "Preise und Werte", import: "Datenimport", wallet: "Wallet-Zuordnung", reconciliation: "Quellenabgleich", evidence: "Belege", tax: "Steuerliche Einordnung",
  trade: "Handel / Swap", transfer: "Transfer", fee: "Gebühr", reward: "Reward", income: "Ertrag", staking: "Staking", mining: "Mining", derivative: "Derivat", unknown: "Unbekannter Typ",
  exchange: "Börse", solana_wallet: "Solana-Wallet", data_provider: "Datendienst", owned: "Eigene Quelle", owned_historical_route: "Eigener historischer Quellenpfad",
  complete: "Vorhandene Prüfung vollständig", partial: "Abdeckung unvollständig", available: "Verfügbar", server_admin_only: "Lokale Einrichtung", planned: "Geplant", partner_access_required: "Partnerzugang erforderlich",
  evidence_only: "Nur Belegquelle", ledger_fallback_missing_live: "Ledger-Wert — Live-Vergleich fehlt"
};
export function label(value?: string | null, fallback = "Details prüfen") { return value ? LABELS[value] || fallback : "Noch nicht geprüft"; }
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "warning" | "danger" | "ok" }) { return <span className={`wsBadge ${tone}`}>{children}</span>; }
export function ExactQuantity({ value }: { value: string | null | undefined }) {
  const compact = compactQuantity(value);
  return /[…<>]/.test(compact) ? <details className="wsQuantity"><summary aria-label={`Exakten Mengenwert anzeigen: ${compact}`}>{compact}</summary><code>{value}</code></details> : <span title={value || undefined}>{compact}</span>;
}
export function ResourceNotice<T>({ resource, label: name = "Daten" }: { resource: Resource<T>; label?: string }) {
  if (resource.status === "initial" || resource.status === "loading") return <div className="wsResource" role="status"><LoaderCircle size={16} className="spin" /> {name}: Ladevorgang läuft.{resource.data !== undefined && <span>Vorheriger Stand vom {timestamp(resource.updatedAt)} bleibt sichtbar.</span>}</div>;
  if (resource.status === "error") return <div className="wsResource error" role="alert"><AlertCircle size={17} /><span>{name}: {resource.error}{resource.data !== undefined && ` Vorheriger Stand vom ${timestamp(resource.updatedAt)} bleibt sichtbar und ist veraltet.`}</span><button type="button" onClick={resource.reload}>Erneut versuchen</button></div>;
  return null;
}
export function Empty({ title, children, filtered = false, onReset }: { title: string; children?: ReactNode; filtered?: boolean; onReset?: () => void }) { return <div className="wsEmpty" role="status"><strong>{title}</strong>{children && <p>{children}</p>}{filtered && <button type="button" onClick={onReset}><X size={16} /> Filter zurücksetzen</button>}</div>; }
export function Tabs({ name, items, active, onChange }: { name: string; items: readonly { id: string; label: string }[]; active: string; onChange: (id: string) => void }) {
  const id = tabId(name);
  return <div className="wsTabs" role="tablist" aria-label={name}>{items.map((item, index) => <button key={item.id} type="button" id={`${id}-${item.id}`} role="tab" aria-controls={`${id}-panel-${item.id}`} aria-selected={active === item.id} tabIndex={active === item.id ? 0 : -1} onClick={() => onChange(item.id)} onKeyDown={(event) => {
    if (["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) {
      event.preventDefault(); const at = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
      onChange(items[at].id); document.getElementById(`${id}-${items[at].id}`)?.focus();
    }
  }}>{item.label}</button>)}</div>;
}
function tabId(name: string) { return "ws-tabs-" + name.toLowerCase().replace(/[^a-z0-9]/g, "-"); }
export function TabPanel({ name, active, children }: { name?: string; active: string; children: ReactNode }) {
  return <div className="wsTabPanel" role={name ? "tabpanel" : undefined} id={name ? `${tabId(name)}-panel-${active}` : undefined} aria-labelledby={name ? `${tabId(name)}-${active}` : undefined}>{children}</div>;
}
export function ListTools({ search, onSearch, children, chips, onReset }: { search: string; onSearch: (text: string) => void; children?: ReactNode; chips: { label: string; remove: () => void }[]; onReset: () => void }) {
  return <div className="wsFilters"><div className="wsFilterInputs"><label className="wsSearch">Suche<span><Search size={17} aria-hidden="true" /><input type="search" aria-label="Liste durchsuchen" maxLength={200} value={search} onChange={(event) => onSearch(event.target.value)} /></span></label><HelpTip label="Vertrauliche Suche">Suchtext bleibt nur für diesen geöffneten Anwendungstab im Speicher. Er steht weder in der Ansichts-URL noch im lokalen Dauerspeicher. Nach einem Neuladen wird die Suche aus Datenschutzgründen geleert.</HelpTip>{children}</div>
    {(chips.length > 0 || search) && <div className="wsFilterChips" aria-label="Aktive Filter">{search && <button type="button" onClick={() => onSearch("")}>Suche aktiv<X size={13} /></button>}{chips.map((chip) => <button key={chip.label} type="button" onClick={chip.remove}>{chip.label}<X size={13} /></button>)}<button type="button" onClick={onReset}>Alle Filter zurücksetzen</button></div>}
  </div>;
}
export function Pager({ total, page, pages, size, onPage, onSize, disabled = false }: { total: number; page: number; pages: number; size: number; onPage: (page: number) => void; onSize?: (size: number) => void; disabled?: boolean }) {
  return <div className="wsPager"><span role="status">{total} Treffer · Seite {page} von {Math.max(1, pages)}</span>{onSize && <label>Pro Seite<select aria-label="Einträge pro Seite" value={size} onChange={(event) => onSize(Number(event.target.value))}>{[10, 25, 50, 100].map((count) => <option key={count}>{count}</option>)}</select></label>}<div className="buttonRow"><button type="button" aria-label="Vorherige Seite" title="Vorherige Seite" disabled={disabled || page <= 1} onClick={() => onPage(page - 1)}><ArrowLeft size={17} /></button><button type="button" aria-label="Nächste Seite" title="Nächste Seite" disabled={disabled || page >= pages} onClick={() => onPage(page + 1)}><ArrowRight size={17} /></button></div></div>;
}
export function DetailPanel({ title, onClose, children, dirty = false }: { title: string; onClose: () => void; children: ReactNode; dirty?: boolean }) {
  const dialog = useRef<HTMLDivElement>(null);
  const heading = useId();
  const close = useRef(onClose); close.current = onClose;
  const changed = useRef(dirty); changed.current = dirty;
  const requestClose = () => { if (!changed.current || window.confirm("Ungespeicherte Änderungen verwerfen?")) close.current(); };
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const previous = document.body.style.overflow; document.body.style.overflow = "hidden";
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") { if (document.querySelector('[role="tooltip"]')) return; event.preventDefault(); requestClose(); }
      if (event.key === "Tab") {
        const focusable = Array.from(dialog.current?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex='0']") || []).filter((element) => element.getClientRects().length > 0);
        const first = focusable[0], last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    const beforeUnload = (event: BeforeUnloadEvent) => { if (changed.current) { event.preventDefault(); event.returnValue = ""; } };
    // The background stays out of the keyboard and accessibility tree while a panel is open.
    const root = document.getElementById("root"); const wasInert = root?.inert || false; if (root) root.inert = true;
    document.addEventListener("keydown", keyboard); window.addEventListener("beforeunload", beforeUnload);
    return () => { document.body.style.overflow = previous; if (root) root.inert = wasInert; document.removeEventListener("keydown", keyboard); window.removeEventListener("beforeunload", beforeUnload); if (before?.isConnected) before.focus({ preventScroll: true }); else document.getElementById("page-heading")?.focus({ preventScroll: true }); };
  }, []);
  return createPortal(<div className="wsPanelBackdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) requestClose(); }}><div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={heading} className="wsDetailPanel"><header><h2 id={heading}>{title}</h2><button type="button" aria-label="Details schließen" title="Details schließen" onClick={requestClose}><X size={20} /></button></header><div className="wsPanelBody">{children}</div></div></div>, document.body);
}
export function ActionConfirm({ title, effect, command, onDone, onClose }: { title: string; effect: string; command: () => Promise<string>; onDone: () => void; onClose: () => void }) {
  const running = useRef(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [result, setResult] = useState("");
  return <DetailPanel title={title} onClose={() => { if (!running.current) onClose(); }}><p>{effect}</p>{error && <p role="alert" className="error">{error}</p>}{result && <p role="status">{result}</p>}<div className="wsActionFooter"><button type="button" onClick={onClose} disabled={busy}>{result ? "Schließen" : "Abbrechen"}</button><button type="button" className="wsPrimary" disabled={busy || !!result} onClick={() => {
    if (running.current) return; running.current = true; setBusy(true); setError("");
    void command().then((message) => { setResult(message); onDone(); }).catch((caught) => { setError(caught instanceof Error ? caught.message : "Vorgang fehlgeschlagen."); onDone(); }).finally(() => { running.current = false; setBusy(false); });
  }}>{busy ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}{busy ? "Vorgang läuft" : "Bestätigen und starten"}</button></div></DetailPanel>;
}
export function RowMenu({ children }: { children: ReactNode }) { return <details className="wsRowMenu" onKeyDown={(event) => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); event.stopPropagation(); } }}><summary aria-label="Weitere Quellenaktionen" title="Weitere Quellenaktionen"><ChevronDown size={18} /></summary><div>{children}</div></details>; }
