import { type ReactNode, useEffect, useRef, useState } from "react";
import { ArrowRight, Download, FileText, RefreshCw } from "lucide-react";
import { API_BASE } from "../api-base";
import { navigateView, useViewState } from "./view-state";
import { ApiReadError, money, readApi, timestamp, useResource } from "./resource";
import { DetailPanel, Empty, ResourceNotice, TabPanel, Tabs } from "./Ui";
import { StatusSummary } from "./DashboardWorkspace";
import { TaxYearPdfReports } from "./TaxYearPdfReports";
import type { Status } from "./types";

type Annual = { year: number; state: string; realized_gain_loss_eur: string; tax_free_gain_loss_eur: string; rewards_income_eur: string; derivative_pnl_eur: string; taxable_disposal_proceeds_eur: string; acquisition_cost_eur: string; tax_lines_count: number; issues: { code: string; message: string }[]; methodology: string };
type ExportReadiness = { technical_export_allowed?: boolean; final_filing_allowed?: boolean; filing_status?: "technical_only" | "blocked" };
export function YearWorkspace({ kind, technical, onMode }: { kind: "tax" | "export"; technical: ReactNode; onMode: (mode: string) => void }) {
  const { view, set } = useViewState(kind);
  useEffect(() => { onMode(view.tab); }, [view.tab]);
  const status = useResource<Status>(`${kind}-status:${view.year}`, (signal) => readApi(`/api/v1/workspace/status?year=${view.year}`, signal));
  const year = useResource<Annual>(`${kind}-year:${view.year}`, (signal) => readApi(`/api/v1/tax-years/${view.year}`, signal));
  const exportReadiness = useResource<ExportReadiness>(kind === "export" ? "year-export-readiness" : null, (signal) => readApi("/api/v1/export/readiness", signal));
  const [download, setDownload] = useState<"zip" | "csv" | null>(null);
  useEffect(() => { setDownload(null); }, [view.year]);
  const current = status.status === "ready" && !status.stale && status.key === `${kind}-status:${view.year}` && status.data?.year === Number(view.year) ? status.data : undefined;
  const annualCurrent = year.status === "ready" && !year.stale && year.key === `${kind}-year:${view.year}` && year.data?.year === Number(view.year);
  const binding = current?.readiness.snapshot_binding_status;
  const finalAvailable = !!(current?.final_available && current.preview_available && annualCurrent && !current.calculation_stale && binding === "current" && current.readiness.can_file_without_review && current.readiness.ready_years.includes(Number(view.year)));
  const bindingLabel = !current ? status.status === "error" ? "Prüfstand nicht verfügbar" : "Prüfstand wird geladen" : binding ? ({ missing: "Methoden-Prüfstand fehlt", unbound: "Methoden-Prüfstand ohne Eingangsbindung", stale: "Eingangsbindung veraltet", current: "Eingangsbindung aktuell" }[binding]) : "Eingangsbindung nicht bestätigt";
  const packageLabel = finalAvailable ? "Jahres-Belegpaket" : "Vorschau-Belegpaket";
  const technicalCurrent = exportReadiness.status === "ready" && !exportReadiness.stale;
  const technicalLabel = !technicalCurrent || exportReadiness.data?.technical_export_allowed === undefined ? "Technischer PDF-Export nicht bestätigt" : exportReadiness.data.technical_export_allowed ? "Technischer PDF-Export möglich; keine finale Jahresfreigabe" : "Technischer PDF-Export gesperrt";
  const safeStatus = current && { ...current, final_available: finalAvailable, summary: finalAvailable ? current.summary : current.preview_available ? "Vorschau verfügbar – finale Abgabe nicht freigegeben" : "Noch keine berechnete Jahresvorschau bestätigt", dimensions: { ...current.dimensions, year: finalAvailable ? current.dimensions.year : "Keine finale Jahresfreigabe", export: finalAvailable ? current.dimensions.export : "Nur Vorschau" } };
  const standard = kind === "tax" ? "guided" : "packages";
  return <section className="wsPage" aria-label={kind === "tax" ? "Steuerjahr und Voraussetzungen" : "Berichte mit eindeutigem Umfang"}>
    <ResourceNotice resource={status} label="Jahresvoraussetzungen" />{safeStatus && <StatusSummary status={safeStatus} />}
    <section aria-label="Paketstatus und Datenbindung"><h3>{finalAvailable ? "Jahresfreigabe bestätigt" : "Vorschau · keine finale Jahresfreigabe"} · {view.year}</h3><div className="wsSummaryLine"><span>{bindingLabel}</span><span>{annualCurrent ? "Jahresauswertung geladen" : year.status === "error" ? "Jahresauswertung nicht verfügbar" : "Jahresauswertung wird geladen"}</span></div></section>
    <Tabs name={kind === "tax" ? "Steuerjahresansicht" : "Berichtsansicht"} active={view.tab} onChange={(tab) => set({ tab })} items={kind === "tax" ? [{ id: "guided", label: "Jahresübersicht" }, { id: "details", label: "Belege und Eingabehilfe" }, { id: "expert", label: "Expertenmodus" }] : [{ id: "packages", label: "Berichte und Umfang" }, { id: "evidence", label: "Belegindex" }, { id: "expert", label: "Globale Reportwerkzeuge" }]} />
    <TabPanel name={kind === "tax" ? "Steuerjahresansicht" : "Berichtsansicht"} active={view.tab}>{view.tab !== standard ? <div className="wsTechnical">{technical}</div> : <>
      <ResourceNotice resource={year} label="Jahresauswertung" />
      {kind === "tax" ? <><MethodologySnapshotAction selectedYear={view.year} />{current && !current.preview_available ? <Empty title="Für dieses Jahr ist noch keine belastbare berechnete Vorschau bestätigt">Originaldaten und Berechnung prüfen. Bereits vorhandene technische Belege bleiben in der Detailansicht erreichbar.</Empty> : annualCurrent && year.data && <div className="wsTableScroll"><table><thead><tr><th>Bereich · {view.year}</th><th>Berechneter Betrag</th></tr></thead><tbody>{[["Private Veräußerungen: Gewinn / Verlust", year.data.realized_gain_loss_eur], ["Steuerfreie Veräußerungen: Gewinn / Verlust", year.data.tax_free_gain_loss_eur], ["Rewards / Mining / Staking", year.data.rewards_income_eur], ["Derivate: Ergebnis", year.data.derivative_pnl_eur], ["Veräußerungserlöse (keine EUR-Auszahlung)", year.data.taxable_disposal_proceeds_eur], ["Anschaffungskosten", year.data.acquisition_cost_eur]].map(([name, value]) => <tr key={name}><td>{name}</td><td>{current?.preview_available ? money(value) : "Prüfgrundlage nicht bestätigt"}</td></tr>)}</tbody></table></div>}
        <div className="wsActionFooter"><button type="button" onClick={() => set({ tab: "details" })}><FileText size={16} /> Belege und Eingabehilfe öffnen</button><button type="button" onClick={() => navigateView("review", { year: view.year })}><ArrowRight size={16} /> Hinweise für dieses Jahr</button><button type="button" onClick={() => navigateView("export", { year: view.year })}><Download size={16} /> Berichte und Umfang prüfen</button></div></>
        : <><div className="wsSummaryLine">Exportumfang: Steuerjahr {view.year}. Filter und Auswahl aus der Transaktionsliste werden hier nicht übernommen.</div><div className="wsReportList"><div><div><strong>Lesende Jahresvorschau</strong><small>HTML · Jahr {view.year} · keine neue Freigabe</small></div><a className="wsButton" href={`${API_BASE}/api/v1/tax-years/${view.year}/filing-summary.html`} target="_blank" rel="noreferrer"><FileText size={16} /> Vorschau öffnen</a></div><div><div><strong>{packageLabel}</strong><small>ZIP · Jahr {view.year} · {finalAvailable ? "Jahresfreigabe im aktuellen Prüfstand bestätigt" : "vorläufig, nicht zur finalen Abgabe freigegeben"}</small><small>Erstellt / aktualisiert einen lokalen Paket-Cache. Maßgeblich sind Status und Eingangsbindung im Paket.</small></div><button type="button" disabled={!current?.events_count} onClick={() => setDownload("zip")}><Download size={16} /> {finalAvailable ? "Paket erstellen / laden" : "Vorschaupaket erstellen / laden"}</button></div><div><div><strong>Jahrescheckliste</strong><small>CSV · Jahr {view.year} · lesend, keine Entscheidung</small></div><button type="button" disabled={!current} onClick={() => setDownload("csv")}><Download size={16} /> Checkliste laden</button></div><div><div><strong>Bestehende PDF-/Reportwerkzeuge</strong><small>Globaler Umfang gemäß vorhandenem Backend; nicht automatisch auf das gewählte Jahr begrenzt</small><small>{technicalLabel}</small></div><button type="button" onClick={() => set({ tab: "expert" })}><ArrowRight size={16} /> Umfang und Fach-Gates prüfen</button></div></div><TaxYearPdfReports year={view.year} canGenerate={!!(annualCurrent && current?.preview_available && !current.calculation_stale)} /></>}
    </>}</TabPanel>
    {download && <ReportDownload key={`${view.year}:${download}`} year={view.year} kind={download} packageLabel={packageLabel} onClose={() => setDownload(null)} />}
  </section>;
}

type FilingReadinessReport = { input_binding_sha256?: string | null; latest_tax_run_id?: string | null; available_years: number[]; ready_years: number[]; conservative_appendix_years: number[]; review_years: number[]; blocked_years: number[]; empty_years: number[] };
type FilingReadinessSnapshot = { status: "available" | "missing" | "invalid"; binding_status?: "current" | "stale" | "unbound" | "missing" | null; generated_at: string; note: string };
type FilingReadinessSnapshotRefresh = { operation_id: string; scope: "years_2021_2025"; status: "completed" | "stale"; binding_status: "current" | "stale" | "unbound"; completed_at: string; report: FilingReadinessReport; final_approval_granted: false; tax_data_changed: false; external_provider_calls_made: false };

function MethodologySnapshotAction({ selectedYear }: { selectedYear: string }) {
  const snapshot = useResource<FilingReadinessSnapshot>("filing-readiness-snapshot", (signal) => readApi("/api/v1/tax-methodology/bmf-filing-readiness-snapshot", signal));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<FilingReadinessSnapshotRefresh | null>(null);
  const runningRef = useRef(false);
  const bindingLabels = { current: "Eingangsbindung aktuell", stale: "Eingangsbindung veraltet", unbound: "Eingangsbindung nicht bestätigt", missing: "Prüfstand fehlt" };

  const refresh = async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const current = await readApi<FilingReadinessReport>("/api/v1/tax-methodology/bmf-filing-readiness");
      if (!current.input_binding_sha256) throw new Error("Die aktuelle Eingangsbindung fehlt; es wurde kein Snapshot erzeugt.");
      const created = await readApi<FilingReadinessSnapshotRefresh>(
        "/api/v1/tax-methodology/bmf-filing-readiness-snapshot",
        undefined,
        {
          scope: "years_2021_2025",
          expected_input_binding_sha256: current.input_binding_sha256,
          expected_latest_tax_run_id: current.latest_tax_run_id ?? null,
        },
      );
      setResult(created);
      window.dispatchEvent(new Event("steuerreport:refresh"));
    } catch (caught) {
      const code = caught instanceof ApiReadError ? caught.code : undefined;
      setError(code === "filing_readiness_inputs_changed"
        ? "Die Eingaben haben sich seit dem gelesenen Prüfstand geändert. Status neu laden und erneut starten."
        : code === "filing_readiness_snapshot_refresh_running"
          ? "Eine andere Erzeugung läuft bereits. Warte auf deren Abschluss und lade den Status erneut."
          : code === "filing_readiness_snapshot_write_failed"
            ? "Speichern fehlgeschlagen. Schreibbarkeit und verfügbaren Speicher im persistenten Anwendungsdatenbereich prüfen."
            : caught instanceof Error ? caught.message : "Der Prüfstand konnte nicht erzeugt werden.");
      window.dispatchEvent(new Event("steuerreport:refresh"));
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  };

  const binding = snapshot.data?.binding_status ?? (snapshot.data?.status === "missing" ? "missing" : null);
  return <section aria-label="Gebundener BMF-Methoden-Prüfstand">
    <h3>Gebundener BMF-Methoden-Prüfstand</h3>
    <p className="wsSummaryLine">Umfang: alle verfügbaren Jahre 2021–2025, nicht nur das ausgewählte Jahr {selectedYear}. Der Vorgang speichert einen an Eingaben und Berechnungslauf gebundenen Bericht. Er ändert keine Steuerdaten, importiert nichts, fragt keine Anbieter ab und erteilt weder menschliche Methodenprüfung noch finale Abgabefreigabe.</p>
    <p role="status">{snapshot.status === "loading" ? "Gespeicherten Prüfstand wird gelesen" : snapshot.status === "error" ? "Gespeicherter Prüfstand nicht lesbar" : binding ? bindingLabels[binding] : "Eingangsbindung wird geprüft"}{snapshot.data?.generated_at ? ` · geprüft ${timestamp(snapshot.data.generated_at)}` : ""}</p>
    {snapshot.data?.note && <p>{snapshot.data.note}</p>}
    {snapshot.error && <p role="alert" className="error">{snapshot.error}</p>}
    {running && <p role="status">Prüfstand-Erzeugung läuft. Eingaben werden vor und nach dem Schreiben verglichen.</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {result && <p role="status">{result.status === "completed" ? "Prüfstand erstellt; Eingangsbindung ist aktuell." : "Prüfstand erstellt, aber Eingaben änderten sich währenddessen; nicht aktuell."} Umfang {result.scope.replace("years_", "")}; operation {result.operation_id}; abgeschlossen {timestamp(result.completed_at)}. BMF-ready: {result.report.ready_years.length}, konservativer Anhang: {result.report.conservative_appendix_years.length}, Review: {result.report.review_years.length}, blockiert: {result.report.blocked_years.length}, leer: {result.report.empty_years.length}. Keine finale Freigabe.</p>}
    <div className="wsActionFooter"><button type="button" disabled={running} onClick={() => void refresh()}><RefreshCw size={16} />{running ? "Prüfstand wird erzeugt" : "Prüfstand 2021–2025 erzeugen / erneuern"}</button></div>
  </section>;
}

function ReportDownload({ year, kind, packageLabel, onClose }: { year: string; kind: "zip" | "csv"; packageLabel: string; onClose: () => void }) {
  const running = useRef(false);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  return <DetailPanel title={kind === "zip" ? packageLabel : "Jahrescheckliste"} onClose={() => { if (!busy) onClose(); }}><p>Umfang: ausschließlich Steuerjahr {year}, keine Transaktionslistenfilter oder Auswahl. {kind === "zip" ? "Der vorhandene Exportpfad berechnet Nachweise und speichert einen lokalen ZIP-Cache. Ein Download erteilt keine finale Jahresfreigabe. Status, offene Punkte und Eingangsbindung im Paket sind maßgeblich. Der Vorgang kann länger dauern." : "Die CSV-Checkliste wird aus dem vorhandenen Jahresstand gelesen und erteilt keine finale Jahresfreigabe."}</p>{notice && <p role="status">{notice}</p>}{error && <p role="alert" className="error">{error}</p>}<div className="wsActionFooter"><button type="button" disabled={busy} onClick={onClose}>Schließen</button><button type="button" disabled={busy || !!notice} onClick={() => { if (running.current) return; running.current = true; setBusy(true); setError(""); void fetch(`${API_BASE}/api/v1/export/tax-years/${year}/${kind === "zip" ? "evidence-package.zip" : "filing-checklist.csv"}`).then(async (response) => { if (!response.ok) throw new Error("Export konnte nicht erstellt werden. Voraussetzungen prüfen."); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `steuerreport-${year}.${kind}`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice("Datei vollständig vom Server empfangen und dem Browser zum Speichern bereitgestellt. Keine Bestätigung des lokalen Speichervorgangs oder einer finalen Jahresfreigabe."); }).catch((caught) => setError(caught.message)).finally(() => { running.current = false; setBusy(false); }); }}><Download size={16} />{busy ? "Datei wird vorbereitet" : "Bestätigen und herunterladen"}</button></div></DetailPanel>;
}
