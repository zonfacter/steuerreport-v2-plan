import type { PriceAdmissionReport } from "./PriceAdmission";
import { PriceTimeEvidence, type PriceTimeAssessment } from "./PriceTimeEvidence";
import { timestamp } from "./resource";

function instant(value: unknown) {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return null;
  const match = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
  return match ? match[1] + "." + (match[2] || "").padEnd(6, "0") + "Z" : null;
}

export function PriceAdmissionEvidence({ admission, legacy, asset, valuationAt }: {
  admission?: PriceAdmissionReport | null; legacy?: PriceTimeAssessment | null; asset: string; valuationAt?: string;
}) {
  if (!admission) return <PriceTimeEvidence assessment={legacy} />;
  const approved = admission.status === "human_approved" && admission.assessment?.strict_eligible === true
    && admission.assessment.status === "human_approved" && admission.assessment.evidence_origin === "operator_confirmed"
    && admission.assessment.original_integrity_verified === true && admission.assessment.reason_codes?.length === 0
    && typeof admission.validation_policy_sha256 === "string" && /^[a-f0-9]{64}$/.test(admission.validation_policy_sha256)
    && admission.identity?.asset === asset && instant(admission.valuation_at) !== null
    && instant(admission.valuation_at) === instant(valuationAt) && admission.decision != null && admission.revocation == null;
  return <div className="wsResource">
    <p role="status">{approved ? "Preiszeit und Methode für diesen Bewertungszeitpunkt menschlich bestätigt." : "Keine aktuell bestätigte Preiszeit-/Methodenzuordnung."}</p>
    <p>Keine Anbieterzertifizierung oder Steuerjahresfreigabe. Preiswahl und Tokenprüfung bleiben getrennt.</p>
    {approved && <dl>
      <dt>Bewertungszeitpunkt</dt><dd>{timestamp(admission.valuation_at)}</dd>
      <dt>Belegart</dt><dd>{admission.observation.kind === "daily_reference" ? "Ausdrückliche Tagesreferenz, kein einzelner Ausführungskurs" : "Menschlich geprüfte Quote-Transkription"}</dd>
      <dt>Beobachtung / Periode</dt><dd>{admission.observation.kind === "observed_quote" ? timestamp(admission.observation.observed_at)
        : `${timestamp(admission.observation.period_start)} bis ${timestamp(admission.observation.period_end)} (exklusiv)`}</dd>
      <dt>Veröffentlichung</dt><dd>{timestamp(admission.observation.published_at)}</dd>
      <dt>FX-Veröffentlichung</dt><dd>{admission.observation.fx ? timestamp(admission.observation.fx.published_at) : "Direkt-EUR; nicht erforderlich"}</dd>
      <dt>Methode</dt><dd>{admission.method.method_id} · Version {admission.method.version} · {admission.method.timezone}</dd>
      <dt>Verfügbarkeit</dt><dd>{admission.method.availability_rule === "retrospective_daily_reference" ? "Ausdrücklich rückblickende Tagesmethode" : "Belegt am Bewertungszeitpunkt verfügbar"}</dd>
      <dt>Bestätigende Person</dt><dd>{admission.decision?.actor}</dd>
    </dl>}
    <details className="wsTechnical"><summary>Entscheidung und Legacy-Diagnose</summary>
      <p>Preis-ID: <code>{admission.price_id}</code><br />Entscheidung: <code>{admission.decision?.decision_id || "nicht gespeichert"}</code><br />Prüfpolicy-SHA: <code>{admission.validation_policy_sha256}</code></p>
      <PriceTimeEvidence assessment={legacy} />
    </details>
  </div>;
}
