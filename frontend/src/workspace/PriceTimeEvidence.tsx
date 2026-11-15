export type PriceTimeAssessment = {
  policy_id: "stichtag-temporal-evidence";
  policy_version: 1;
  asset: string;
  status: "fixed_eur_identity" | "unverified_time" | "missing" | "future_reference" | "non_positive";
  strict_eligible: boolean;
  reference_kind: "fixed_identity" | "daily_reference_candidate" | "derived_reference_candidate" | "unknown";
  stored_reference_at: string | null;
  observed_at: string | null;
  period_start: string | null;
  period_end: string | null;
  price_published_at: string | null;
  fx_published_at: string | null;
  valuation_method_id: string | null;
  valuation_method_version: number | null;
  price_evidence_ref: string | null;
  fx_evidence_ref: string | null;
  reason_codes: string[];
  explanation: string;
};

const statusText: Record<PriceTimeAssessment["status"], string> = {
  fixed_eur_identity: "EUR-Identität: 1 EUR = 1 EUR. Kein Marktkurs.",
  unverified_time: "Zeitbeleg nicht belegt.",
  missing: "Preis- oder Zeitreferenz fehlt.",
  future_reference: "Referenzzeit liegt nach dem Stichtag.",
  non_positive: "Preisreferenz nicht positiv.",
};
const referenceText: Record<PriceTimeAssessment["reference_kind"], string> = {
  fixed_identity: "Zeitlose EUR-Identität; kein beobachteter Marktkurs.",
  daily_reference_candidate: "Hinweis auf eine Tagesreferenz aus ungeprüftem Quellenlabel.",
  derived_reference_candidate: "Hinweis auf eine abgeleitete Referenz aus ungeprüftem Quellenlabel.",
  unknown: "Referenzart unbekannt; Quellenlabel ist kein Zeitbeleg.",
};
const absentEvidence = [
  "observed_at", "period_start", "period_end", "price_published_at", "fx_published_at",
  "valuation_method_id", "valuation_method_version", "price_evidence_ref", "fx_evidence_ref",
] as const;

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function utcReference(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.getUTCFullYear() > 0
    && parsed.toISOString().slice(0, 19) === value.slice(0, 19);
}
function supportedAssessment(value: unknown): value is PriceTimeAssessment {
  if (!isObject(value) || value.policy_id !== "stichtag-temporal-evidence" || value.policy_version !== 1
    || typeof value.asset !== "string" || !value.asset.trim()
    || typeof value.status !== "string" || !Object.hasOwn(statusText, value.status)
    || typeof value.reference_kind !== "string" || !Object.hasOwn(referenceText, value.reference_kind)
    || typeof value.strict_eligible !== "boolean" || typeof value.explanation !== "string"
    || !Array.isArray(value.reason_codes) || !value.reason_codes.every((code) => typeof code === "string" && code.length > 0)
    || (value.stored_reference_at !== null && !utcReference(value.stored_reference_at))
    || !absentEvidence.every((field) => value[field] === null)) return false;
  // Policy 1 kennt hier noch keine beleggebundene Marktpreis- oder Methodenfreigabe.
  if (value.status === "fixed_eur_identity") {
    return value.asset === "EUR" && value.strict_eligible === true
      && value.reference_kind === "fixed_identity" && value.stored_reference_at === null;
  }
  return value.strict_eligible === false && value.reference_kind !== "fixed_identity"
    && (value.status !== "future_reference" || value.stored_reference_at !== null);
}

export function PriceTimeEvidence({ assessment }: { assessment?: PriceTimeAssessment | null }) {
  const supported = supportedAssessment(assessment);
  return <div role="group" aria-label="Zeitbeleg" style={{ minWidth: 0, maxWidth: "100%", overflowWrap: "anywhere", fontSize: "13px", lineHeight: 1.5 }}>
    {!supported ? <>
      <p><strong>Zeitbeleg nicht ermittelt.</strong></p>
      <p>Keine aktuelle, konsistente Zeitbelegbewertung verfügbar. Beobachtung und Methodenfreigabe sind nicht nachgewiesen.</p>
    </> : <AssessmentDetails assessment={assessment} />}
  </div>;
}

function AssessmentDetails({ assessment }: { assessment: PriceTimeAssessment }) {
  const identity = assessment.status === "fixed_eur_identity";
  return <>
    <p><strong>{statusText[assessment.status]}</strong></p>
    <p>Gespeicherter Referenzzeitwert: {identity ? "Zeitlos; kein Kursereignis." : assessment.stored_reference_at
      ? <time dateTime={assessment.stored_reference_at}>{assessment.stored_reference_at} (UTC)</time> : "Nicht vorhanden."}</p>
    {!identity && <p>Der gespeicherte Ledger-Zeitwert belegt weder Beobachtung noch Veröffentlichung oder Methodenfreigabe.</p>}
    <details className="wsTechnical" key={JSON.stringify(assessment)} style={{ padding: "6px 0" }}>
      <summary>Zeitbeleg im Detail</summary>
      <p>{referenceText[assessment.reference_kind]}</p>
      {identity && <p>Die reine EUR-Währungsidentität benötigt keinen Marktkurs-Zeitbeleg. Sie ist keine fachliche Jahresfreigabe.</p>}
      <dl style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 13rem), 1fr))", gap: "8px 16px", margin: "12px 0" }}>
        {["Beobachtungszeit", "Periodenbeginn", "Periodenende", "Preisveröffentlichung", "FX-Veröffentlichung",
          "Freigegebene Bewertungsmethode", "Methodenversion", "Preis-Originalbeleg", "FX-Originalbeleg"].map((label) => <div key={label} style={{ minWidth: 0 }}>
          <dt style={{ fontWeight: 600 }}>{label}</dt><dd style={{ margin: 0 }}>Nicht belegt.</dd>
        </div>)}
      </dl>
      <p>Lesepolicy: <code>{assessment.policy_id}</code>, Version {assessment.policy_version}.</p>
      {assessment.reason_codes.length > 0 && <><p>Prüfgründe der API:</p><ul aria-label="API-Prüfgründe">{assessment.reason_codes.map((code, index) => <li key={index}><code>{code}</code></li>)}</ul></>}
    </details>
  </>;
}
