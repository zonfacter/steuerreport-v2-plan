import { useRef, useState } from "react";
import { Download, FileText, RefreshCw } from "lucide-react";
import { API_BASE } from "../api-base";
import { money, readApi, timestamp, useResource } from "./resource";

type PdfFile = {
  file_index: number;
  filename: string;
  page_count: number;
  size_bytes: number;
  sha256: string;
  download_endpoint: string;
};
type PdfManifest = {
  artifact_id: string;
  year: number;
  created_at: string;
  report_status: "preview";
  final_filing_allowed: false;
  calculation_run_id: string;
  input_binding_sha256: string;
  manifest_sha256: string;
  summary: {
    taxable_private_disposals_eur: string;
    taxable_disposal_proceeds_eur: string;
    acquisition_cost_eur: string;
    rewards_mining_staking_income_eur: string;
    derivative_pnl_eur: string;
    tax_free_private_disposals_eur: string;
    tax_free_lines_count: number;
  };
  tax_line_count: number;
  reward_asset_row_count: number;
  reward_missing_value_count: number;
  derivative_line_count: number;
  derivative_missing_price_count: number;
  unmatched_disposals: number;
  missing_price_groups: number;
  technical_status: { status: "technical_only" | "blocked"; technical_export_allowed: boolean };
  files: PdfFile[];
};
type PdfArtifact = { manifest: PdfManifest; manifest_endpoint: string };
type PdfArchive = { year: number; artifacts: PdfArtifact[] };

const PDF_ERRORS: Record<string, string> = {
  tax_year_out_of_range: "Das ausgewählte Steuerjahr liegt außerhalb des unterstützten Bereichs.",
  tax_calculation_run_missing: "Für dieses Jahr gibt es noch keinen Berechnungslauf. Erst Daten und Steuerjahr prüfen.",
  tax_calculation_run_binding_mismatch: "Der Berechnungslauf passt nicht zur aktuellen Datenbindung. Status aktualisieren und neu berechnen.",
  filing_inputs_changed_create_a_new_report: "Die Eingaben haben sich während der Erstellung geändert. Der Bericht wurde nicht als aktueller Prüfstand bestätigt.",
  tax_line_read_model_count_mismatch: "Die Jahreszeilen stimmen nicht mit dem gespeicherten Steuerstand überein. Berichtserstellung abgebrochen.",
  derivative_line_read_model_count_mismatch: "Die Derivatezeilen stimmen nicht mit dem gespeicherten Jahresstand überein. Berichtserstellung abgebrochen.",
  tax_year_pdf_archive_path_invalid: "Der private Berichtsarchivpfad ist ungültig. Administrator soll den Anwendungsdatenpfad prüfen.",
  tax_year_pdf_manifest_integrity_failed: "Das archivierte Berichtmanifest besteht die Integritätsprüfung nicht.",
  tax_year_pdf_file_integrity_failed: "Eine archivierte PDF-Datei besteht die Integritätsprüfung nicht.",
};

function errorMessage(code: unknown): string {
  return typeof code === "string" && PDF_ERRORS[code]
    ? PDF_ERRORS[code]
    : "Der Jahresbericht konnte nicht geladen oder erstellt werden. Status und Eingaben prüfen.";
}

async function createPdfReport(year: string): Promise<PdfArtifact> {
  const response = await fetch(`${API_BASE}/api/v1/tax-years/${year}/reports/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  let envelope: { data?: PdfArtifact; errors?: { code?: string }[]; detail?: unknown };
  try {
    envelope = await response.json();
  } catch {
    throw new Error("Der Server hat keine lesbare Antwort auf die Berichtserstellung geliefert.");
  }
  if (!response.ok || !envelope.data) {
    throw new Error(errorMessage(envelope.detail ?? envelope.errors?.[0]?.code));
  }
  return envelope.data;
}

function sizeLabel(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function TaxYearPdfReports({ year, canGenerate }: { year: string; canGenerate: boolean }) {
  const path = `/api/v1/tax-years/${year}/reports/pdf`;
  const archive = useResource<PdfArchive>(`tax-year-pdf-archive:${year}`, (signal) => readApi<PdfArchive>(path, signal));
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const creatingRef = useRef(false);

  const create = async () => {
    if (creatingRef.current || !canGenerate) return;
    creatingRef.current = true;
    setCreating(true);
    setError("");
    setNotice("");
    try {
      await createPdfReport(year);
      setNotice("Jahres-PDF-Vorschau wurde archiviert. Sie ist nicht final und erteilt keine Abgabefreigabe.");
      window.dispatchEvent(new Event("steuerreport:refresh"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Bericht konnte nicht erstellt werden.");
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  };

  const artifacts = archive.data?.artifacts ?? [];
  return <section aria-label={`Jahres-PDF-Berichte ${year}`} className="wsYearPdf">
    <div className="wsYearPdfHeading">
      <div><strong>Jahresbericht als PDF-Vorschau</strong><small>Steuerjahr {year} · gebundener Berechnungslauf · append-only Archiv · niemals finale Freigabe</small></div>
      <button type="button" disabled={!canGenerate || creating} onClick={() => void create()}>
        {creating ? <RefreshCw size={16} className="spin" /> : <FileText size={16} />}
        {creating ? "Vorschau wird erstellt" : "Jahres-PDF-Vorschau erzeugen"}
      </button>
    </div>
    {!canGenerate && <p className="wsInlineNote">Erst den aktuellen Jahresstand laden. Ohne bestätigte Jahresvorschau ist die Berichtserstellung gesperrt.</p>}
    {archive.status === "loading" && <p role="status">Archivierte Jahresberichte werden geladen.</p>}
    {archive.status === "error" && <div role="alert" className="error">{archive.error} <button type="button" className="ghostButton" onClick={archive.reload}>Archiv erneut laden</button></div>}
    {archive.stale && archive.data && <p role="status">Vorheriger Archivstand vom {timestamp(archive.updatedAt)}; Aktualisierung läuft oder ist fehlgeschlagen.</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {archive.status === "ready" && !archive.stale && artifacts.length === 0 && <p className="wsInlineNote">Für {year} sind noch keine Jahres-PDFs archiviert.</p>}
    {artifacts.length > 0 && <div className="wsYearPdfList" aria-label="Archivierte Jahresberichte">
      {artifacts.map(({ manifest, manifest_endpoint }) => <article key={manifest.artifact_id} className="wsYearPdfItem">
        <div className="wsYearPdfMeta">
          <strong>{timestamp(manifest.created_at)}</strong>
          <span>Vorschau · nicht final</span>
          <span>{manifest.tax_line_count} Steuerzeilen · {manifest.reward_asset_row_count} Reward-/Einkommensgruppen · {manifest.derivative_line_count} Derivatezeilen</span>
          <span>{manifest.technical_status.technical_export_allowed ? "Technischer Export möglich; keine Abgabefreigabe" : "Technisches Fach-Gate blockiert"}</span>
          <span>Private Veräußerungen, Gewinn/Verlust: {money(manifest.summary.taxable_private_disposals_eur)} · steuerfreie Veräußerungen, Gewinn/Verlust: {money(manifest.summary.tax_free_private_disposals_eur)}</span>
          <span>Rewards/Mining/Staking-Einkünfte: {money(manifest.summary.rewards_mining_staking_income_eur)} · Derivate-Ergebnis: {money(manifest.summary.derivative_pnl_eur)}</span>
          <span>Veräußerungserlöse (kein EUR-Auszahlungsbetrag): {money(manifest.summary.taxable_disposal_proceeds_eur)} · Anschaffungskosten: {money(manifest.summary.acquisition_cost_eur)}</span>
          {(manifest.reward_missing_value_count > 0 || manifest.derivative_missing_price_count > 0 || manifest.unmatched_disposals > 0 || manifest.missing_price_groups > 0) && <span className="wsYearPdfWarning">Offene Beleg-/Bewertungspunkte: {manifest.reward_missing_value_count} Reward-Werte, {manifest.derivative_missing_price_count} Derivatepreise, {manifest.unmatched_disposals} nicht zugeordnete Veräußerungen, {manifest.missing_price_groups} fehlende Preisgruppen.</span>}
          <code title={manifest.calculation_run_id}>Lauf {manifest.calculation_run_id}</code>
        </div>
        <div className="wsYearPdfFiles">
          <a className="wsButton" href={`${API_BASE}${manifest_endpoint}`} download><Download size={16} /> Manifest JSON</a>
          {manifest.files.map((file) => <a className="wsButton" key={file.file_index} href={`${API_BASE}${file.download_endpoint}`} download={file.filename}>
            <Download size={16} /> PDF {file.file_index} · {file.page_count} Seiten · {sizeLabel(file.size_bytes)}
          </a>)}
        </div>
        <details><summary>Prüfbindung und Dateihashes</summary><dl>
          <dt>Artefakt-ID</dt><dd><code>{manifest.artifact_id}</code></dd>
          <dt>Eingabebindung SHA-256</dt><dd><code>{manifest.input_binding_sha256}</code></dd>
          <dt>Manifest SHA-256</dt><dd><code>{manifest.manifest_sha256}</code></dd>
          {manifest.files.map((file) => <div key={`hash-${file.file_index}`}><dt>{file.filename} SHA-256</dt><dd><code>{file.sha256}</code></dd></div>)}
        </dl></details>
      </article>)}
    </div>}
  </section>;
}
