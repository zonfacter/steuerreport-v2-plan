import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { Ban, Check, Download, FileSearch, LoaderCircle, RefreshCw, X } from "lucide-react";
import { API_BASE } from "../api-base";
import { newRequestId } from "../request-id";
import { sha256Bytes } from "../sha256";
import { HelpTip } from "../Help";
import { canonicalDecimal } from "./resource";

type Original = { sha256: string; byte_length: number; filename?: string | null };
export type PriceAdmissionProps = {
  previewId: string; priceId: string; previewSha256: string; priceFingerprint: string;
  asset: string; originals: Original[]; priceEur?: string; storedReferenceAt?: string;
};
type Identity = { asset: string; network: string; contract: string; decimals: number };
type Fx = { base: string; quote: string; rate: string; reference_at: string; published_at: string;
  evidence_sha256: string; locator: string; source: string; captured_at?: string };
type Observation = { identity: Identity; quote_currency: string; value: string; kind: string;
  observed_at: string | null; period_start: string | null; period_end: string | null;
  published_at: string; evidence_sha256: string; locator: string; source: string; fx: Fx | null; captured_at?: string };
type Method = { method_id: string; version: number; kind: string; daily_statistic: string | null;
  daily_time: string | null; timezone: string; availability_rule: string; fx_max_age_days: number | null; evidence_sha256: string };
type MethodFile = { filename: string; media_type: string; content_base64: string; sha256: string; byte_length: number };
type Draft = { request_id: string; preview_sha256: string; price_fingerprint: string; valuation_at: string;
  identity: Identity; observation: Observation; method: Method;
  method_original: { filename: string; media_type: string; content_base64: string }; actor: string; rationale: string };
type Assessment = { policy_id: string; policy_version: number; status: string; strict_eligible: boolean;
  binding_sha256: string; decision_id: string | null; reason_codes: string[];
  original_integrity_verified: boolean; evidence_origin: string };
type Decision = { decision_id: string; actor: string; rationale: string; created_at: string; [key: string]: unknown };
type Report = { format_version: number; status: "prepared" | "blocked" | "human_approved" | "revoked" | "rejected";
  request_id: string; preview_id: string; price_id: string; draft_sha256: string; price_fingerprint: string;
  validation_policy_sha256: string;
  created_at: string; valuation_at: string; identity: Identity; observation: Observation; method: Method;
  actor: string; rationale: string; assessment: Assessment; can_apply: boolean; decision: Decision | null;
  revocation: Decision | null; method_original: Original; originals: Original[] };
export type PriceAdmissionReport = Report;
type Form = Record<typeof fields[number], string>;
const fields = ["network", "contract", "decimals", "valuation", "currency", "value", "kind", "observed", "start", "end", "published",
  "original", "locator", "source", "methodId", "version", "statistic", "dailyTime", "timezone", "availability", "fxAge",
  "fxPair", "fxRate", "fxReference", "fxPublished", "fxOriginal", "fxLocator", "fxSource", "actor", "rationale"] as const;
const initial = (): Form => ({ ...Object.fromEntries(fields.map((name) => [name, ""])), currency: "EUR", kind: "observed_quote",
  fxPair: "USD/EUR", availability: "available_at_cutoff" } as Form);
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const sha = /^[a-f0-9]{64}$/;
const text = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0 && v.length <= 4096;
const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const hash = (v: unknown): v is string => typeof v === "string" && sha.test(v);
const id = (v: unknown): v is string => typeof v === "string" && uuid.test(v);
const decimal = (v: unknown): v is string => typeof v === "string" && v.length <= 100
  && /^(?:\d+(?:\.\d+)?)(?:[eE][+-]?\d{1,4})?$/.test(v) && canonicalDecimal(v) !== null && /[1-9]/.test(canonicalDecimal(v)!);
const integer = (v: unknown, low: number, high: number) => Number.isSafeInteger(v) && Number(v) >= low && Number(v) <= high;
const MAX = 2 * 1024 * 1024;
const grid: CSSProperties = { display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))", minWidth: 0 };
const band: CSSProperties = { border: 0, borderTop: "1px solid #cbd8ce", padding: "16px 0", margin: 0, minWidth: 0 };
const wrap: CSSProperties = { overflowWrap: "anywhere", minWidth: 0, maxWidth: "100%" };

// Keep microseconds when comparing UTC instants; Date alone would lose them.
function instant(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
  if (!match) return null;
  const date = new Date(match[1] + "Z");
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 19) === match[1]
    ? match[1] + "." + (match[2] || "").padEnd(6, "0") + "Z" : null;
}
function utc(value: string) { return instant(value.length === 16 ? value + ":00Z" : value + "Z"); }
function timezone(value: unknown) {
  if (!text(value)) return false;
  try { new Intl.DateTimeFormat("de-DE", { timeZone: value }); return true; } catch { return false; }
}
function validIdentity(v: unknown): v is Identity {
  return object(v) && text(v.asset) && text(v.network) && text(v.contract) && integer(v.decimals, 0, 255);
}
function validOriginal(v: unknown): v is Original {
  return object(v) && hash(v.sha256) && integer(v.byte_length, 1, MAX)
    && (v.filename === undefined || v.filename === null || (text(v.filename) && v.filename.length <= 180));
}
function sameIdentity(a: Identity, b: Identity) { return a.asset === b.asset && a.network === b.network && a.contract === b.contract && a.decimals === b.decimals; }
function validObservation(v: unknown): v is Observation {
  if (!object(v) || !validIdentity(v.identity) || !["EUR", "USD"].includes(String(v.quote_currency))
    || !decimal(v.value) || !instant(v.published_at) || !instant(v.captured_at) || !hash(v.evidence_sha256) || !text(v.locator) || !text(v.source)) return false;
  if (v.kind === "observed_quote" ? !instant(v.observed_at) || v.period_start !== null || v.period_end !== null
    : v.kind !== "daily_reference" || v.observed_at !== null || !instant(v.period_start) || !instant(v.period_end)) return false;
  if (v.quote_currency === "EUR") return v.fx === null;
  const fx = v.fx;
  return object(fx) && ["USD/EUR", "EUR/USD"].includes(`${fx.base}/${fx.quote}`) && decimal(fx.rate)
    && !!instant(fx.reference_at) && !!instant(fx.published_at) && !!instant(fx.captured_at)
    && hash(fx.evidence_sha256) && text(fx.locator) && text(fx.source);
}
function validMethod(v: unknown): v is Method {
  return object(v) && text(v.method_id) && integer(v.version, 1, Number.MAX_SAFE_INTEGER)
    && ["observed_quote", "daily_reference"].includes(String(v.kind)) && timezone(v.timezone)
    && ["available_at_cutoff", "retrospective_daily_reference"].includes(String(v.availability_rule))
    && (v.fx_max_age_days === null || integer(v.fx_max_age_days, 0, 7)) && hash(v.evidence_sha256)
    && (v.kind === "observed_quote" ? v.daily_statistic === null && v.daily_time === null
      : ["daily_mean", "daily_close", "daily_fixed_time"].includes(String(v.daily_statistic))
        && (v.daily_statistic === "daily_fixed_time" ? typeof v.daily_time === "string" && /^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?$/.test(v.daily_time) : v.daily_time === null));
}
function validDecision(v: unknown): v is Decision {
  return object(v) && text(v.decision_id) && text(v.actor) && text(v.rationale) && !!instant(v.created_at);
}
function readReport(raw: unknown, props: PriceAdmissionProps, valuation: string, expected?: { request_id: string; draft_sha256?: string }, draft?: Draft): Report {
  const bad = () => { throw new Error("invalid_report"); };
  if (!object(raw)) return bad();
  const a = raw.assessment;
  if (raw.format_version !== 1 || !["prepared", "blocked", "human_approved", "revoked", "rejected"].includes(String(raw.status))
    || !id(raw.request_id) || raw.preview_id !== props.previewId || raw.price_id !== props.priceId
    || raw.price_fingerprint !== props.priceFingerprint || !hash(raw.draft_sha256) || !hash(raw.validation_policy_sha256)
    || !instant(raw.created_at) || instant(raw.valuation_at) !== instant(valuation)
    || !validIdentity(raw.identity) || raw.identity.asset !== props.asset || !validObservation(raw.observation)
    || !sameIdentity(raw.identity, raw.observation.identity) || !validMethod(raw.method) || raw.method.kind !== raw.observation.kind
    || !text(raw.actor) || !text(raw.rationale) || typeof raw.can_apply !== "boolean"
    || !validOriginal(raw.method_original) || raw.method_original.sha256 !== raw.method.evidence_sha256
    || !Array.isArray(raw.originals) || !raw.originals.length || raw.originals.length > 1000 || !raw.originals.every(validOriginal)
    || new Set(raw.originals.map((v) => v.sha256)).size !== raw.originals.length
    || !raw.originals.every((v) => props.originals.some((p) => p.sha256 === v.sha256 && p.byte_length === v.byte_length))
    || !props.originals.some((p) => p.sha256 === (raw.observation as Observation).evidence_sha256)
    || !raw.originals.some((p) => p.sha256 === (raw.observation as Observation).evidence_sha256)
    || (raw.observation.fx !== null && !props.originals.some((p) => p.sha256 === (raw.observation as Observation).fx?.evidence_sha256))
    || (raw.observation.fx !== null && !raw.originals.some((p) => p.sha256 === (raw.observation as Observation).fx?.evidence_sha256))
    || !object(a) || a.policy_id !== "stichtag-price-evidence-admission" || a.policy_version !== 1
    || !["human_approved", "not_approved", "rejected"].includes(String(a.status)) || !hash(a.binding_sha256)
    || typeof a.strict_eligible !== "boolean" || typeof a.original_integrity_verified !== "boolean"
    || !Array.isArray(a.reason_codes) || !a.reason_codes.every(text)
    || !(a.decision_id === null || text(a.decision_id))
    || !(raw.decision === null || validDecision(raw.decision)) || !(raw.revocation === null || validDecision(raw.revocation))) return bad();
  const approved = raw.status === "human_approved";
  if (approved !== a.strict_eligible || approved !== (a.status === "human_approved")
    || a.evidence_origin !== (approved ? "operator_confirmed" : "unverified")
    || (approved && (!a.original_integrity_verified || a.reason_codes.length || !validDecision(raw.decision)
      || a.decision_id !== raw.decision.decision_id || raw.decision.actor !== raw.actor || raw.decision.rationale !== raw.rationale
      || raw.revocation !== null || raw.can_apply))
    || (raw.can_apply && (raw.status !== "prepared" || !a.original_integrity_verified || raw.decision !== null || raw.revocation !== null
      || a.decision_id !== null || a.reason_codes.length !== 1 || a.reason_codes[0] !== "approval_missing"))
    || (raw.status === "revoked" && !validDecision(raw.revocation))
    || (expected && (raw.request_id !== expected.request_id || (expected.draft_sha256 && raw.draft_sha256 !== expected.draft_sha256)))) return bad();
  const report = raw as unknown as Report;
  if (draft && report.request_id === draft.request_id) {
    // Compare the human inputs, not the server-owned capture timestamps.
    const normalize = (value: unknown, key = ""): unknown => {
      if (Array.isArray(value)) return value.map((v) => normalize(v));
      if (object(value)) return Object.fromEntries(Object.keys(value).sort().filter((k) => k !== "captured_at").map((k) => [k, normalize(value[k], k)]));
      if (key.endsWith("_at") || ["period_start", "period_end"].includes(key)) return value === null ? null : instant(value);
      if (["value", "rate"].includes(key) && typeof value === "string") return canonicalDecimal(value)!.replace(/^0+(?=\d)/, "").replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
      if (key === "daily_time" && typeof value === "string") return (value.length === 5 ? value + ":00" : value).replace(/\.0+$/, "");
      return value;
    };
    if (!sameIdentity(report.identity, draft.identity) || report.actor !== draft.actor || report.rationale !== draft.rationale
      || JSON.stringify(normalize(report.observation)) !== JSON.stringify(normalize(draft.observation))
      || JSON.stringify(normalize(report.method)) !== JSON.stringify(normalize(draft.method))
      || report.method_original.byte_length !== fileLength(draft.method_original.content_base64)) return bad();
  }
  return report;
}
function fileLength(base64: string) { return base64.length / 4 * 3 - (base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0); }
async function api(path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
  const response = await fetch(API_BASE + path, { signal, method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const envelope: unknown = await response.json();
  if (!response.ok || !object(envelope) || !["ok", "warning"].includes(String(envelope.status)) || !("data" in envelope)) {
    const first = object(envelope) && Array.isArray(envelope.errors) ? envelope.errors[0] : null;
    throw new AdmissionError(object(first) && typeof first.code === "string" ? first.code : "request_failed");
  }
  return envelope.data;
}
class AdmissionError extends Error { constructor(public readonly code: string) { super("request_failed"); } }
const apiErrors: Record<string, string> = {
  price_admission_policy_changed: "Prüfmethode geändert, neue Vorschau erforderlich. Keine Zustimmung möglich.",
  price_admission_policy_unavailable: "Prüfmethode derzeit nicht verfügbar. Keine Zustimmung möglich; später erneut lesen.",
};
const titles = { prepared: "Technische Vorschau – noch nicht bestätigt", blocked: "Technische Prüfung blockiert",
  human_approved: "Menschliche Bestätigung für diese Preis-ID und diesen Bewertungszeitpunkt gespeichert",
  revoked: "Menschliche Bestätigung widerrufen", rejected: "Bestätigung nicht anerkannt" };
const reasons: Record<string, string> = { approval_missing: "Menschliche Bestätigung fehlt noch.", original_missing: "Ein erforderlicher Originalbeleg fehlt.",
  original_integrity_mismatch: "Originalbytes stimmen nicht mit ihrer Prüfsumme überein.", asset_identity_mismatch: "Assetidentität stimmt nicht überein.",
  price_value_mismatch: "Kurswert und gespeicherter Preis stimmen nicht überein.", daily_period_not_one_local_day: "Die Periode entspricht keinem lokalen Kalendertag.",
  price_reference_after_cutoff: "Die Preisreferenz liegt nach dem Bewertungszeitpunkt.", price_publication_after_cutoff: "Die Veröffentlichung liegt nach dem Bewertungszeitpunkt.",
  daily_period_required: "Beginn und Ende der Tagesperiode müssen ausdrücklich belegt sein.",
  daily_reference_outside_period: "Bewertungszeitpunkt oder gespeicherte Referenzzeit liegt außerhalb der Tagesperiode.",
  daily_statistic_required: "Die ausdrückliche Tagesstatistik fehlt.", price_publication_before_period_end: "Das Tagesergebnis wurde vor Periodenende veröffentlicht.",
  daily_time_mismatch: "Tagesstatistik und lokale Methodenuhrzeit passen nicht zusammen.", daily_time_nonexistent: "Die lokale Uhrzeit existiert an diesem Tag nicht.",
  daily_time_ambiguous: "Die lokale Uhrzeit ist an diesem Tag mehrdeutig.", price_publication_before_daily_fixed_time: "Die Veröffentlichung liegt vor der festen Methodenuhrzeit.",
  eur_identity_uses_legacy_policy: "Für 1 EUR = 1 EUR gilt die bestehende EUR-Identitätsregel, keine Marktkursbestätigung.",
  price_value_invalid: "Der Kurswert ist nicht zulässig.", price_confidence_invalid: "Die gespeicherte Preisqualität ist nicht zulässig.",
  reference_kind_mismatch: "Beobachtungsart und Methode passen nicht zusammen.", observed_quote_time_invalid: "Der Quote benötigt genau eine ausdrückliche Beobachtungszeit.",
  observed_quote_time_mismatch: "Beobachtungszeit und gespeicherte Referenzzeit stimmen nicht überein.", price_publication_before_observation: "Die Veröffentlichung liegt vor der Beobachtung.",
  observed_quote_has_daily_method: "Ein beobachteter Quote darf keine Tagesstatistik verwenden.", retrospective_requires_daily_reference: "Eine rückblickende Verfügbarkeitsregel benötigt eine ausdrückliche Tagesreferenz.",
  price_capture_before_publication: "Die Veröffentlichung liegt nach der serverseitigen Erfassung.", stored_reference_after_cutoff: "Die gespeicherte Referenzzeit liegt nach dem Bewertungszeitpunkt.",
  direct_eur_has_fx: "Ein direkter EUR-Quote darf keine zusätzliche FX-Umrechnung enthalten.", fx_evidence_required: "Der USD-Quote benötigt einen ausdrücklichen FX-Beleg.",
  fx_max_age_required: "Das maximale FX-Alter fehlt.", fx_reference_age_invalid: "Das FX-Alter liegt außerhalb der ausdrücklichen Methodengrenze.",
  fx_capture_before_publication: "Die FX-Veröffentlichung liegt nach der serverseitigen Erfassung.", fx_publication_before_reference: "Die FX-Veröffentlichung liegt vor ihrer Referenzzeit.",
  fx_reference_after_cutoff: "Die FX-Referenz liegt nach dem Bewertungszeitpunkt.", fx_publication_after_cutoff: "Die FX-Veröffentlichung liegt nach dem Bewertungszeitpunkt.",
  fx_rate_invalid: "Der FX-Kurswert ist nicht zulässig.", fx_converted_value_mismatch: "Die FX-Umrechnung stimmt nicht mit dem gespeicherten EUR-Preis überein.",
  fx_conversion_unrepresentable: "Die FX-Umrechnung ist nicht exakt im erforderlichen Zahlenbereich darstellbar.",
  approval_binding_mismatch: "Die gespeicherte Bestätigung passt nicht zur Faktenbindung.", approval_updated: "Die ursprüngliche Bestätigung wurde verändert.",
  approval_acknowledgement_missing: "Eine ausdrückliche Pflichtbestätigung fehlt.", approval_before_capture: "Die Bestätigung liegt vor der serverseitigen Erfassung.",
  approval_revoked: "Die Bestätigung wurde ausdrücklich widerrufen.", price_admission_revoked: "Die Bestätigung wurde ausdrücklich widerrufen.",
  price_admission_policy_changed: "Prüfmethode geändert, neue Vorschau erforderlich.",
  price_admission_policy_unavailable: "Prüfmethode derzeit nicht verfügbar. Keine Zustimmung möglich." };

export function PriceAdmission(props: PriceAdmissionProps) {
  return <AdmissionForm key={JSON.stringify(props)} {...props} />;
}
function AdmissionForm(props: PriceAdmissionProps) {
  const [form, setForm] = useState(initial);
  const [file, setFile] = useState<MethodFile>();
  const [hashing, setHashing] = useState(false);
  const [report, setReport] = useState<Report>();
  const [empty, setEmpty] = useState(false);
  const [error, setError] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [busy, setBusy] = useState("");
  const [acks, setAcks] = useState([false, false]);
  const [revoke, setRevoke] = useState({ actor: "", rationale: "", ack: false });
  const controller = useRef<AbortController>();
  const serial = useRef(0);
  const fileSerial = useRef(0);
  const pending = useRef<Draft>();
  const saved = useRef<Report>();
  const supported = id(props.previewId) && id(props.priceId) && hash(props.previewSha256) && hash(props.priceFingerprint)
    && text(props.asset) && Array.isArray(props.originals) && props.originals.length > 0 && props.originals.length <= 1000
    && props.originals.every(validOriginal) && new Set(props.originals.map((v) => v.sha256)).size === props.originals.length;
  useEffect(() => () => { controller.current?.abort(); ++serial.current; ++fileSerial.current; }, []);
  const invalidate = () => {
    controller.current?.abort(); ++serial.current; setBusy(""); setReport(undefined); setEmpty(false); setAcks([false, false]); setRevoke({ actor: "", rationale: "", ack: false }); setError(""); setErrorCode("");
  };
  const change = (name: keyof Form, value: string) => { invalidate(); pending.current = undefined; saved.current = undefined; setForm((f) => ({ ...f, [name]: value })); };
  const cancel = () => { invalidate(); setError("Anfrage abgebrochen. Eine bereits serverseitig gespeicherte Wirkung ist damit nicht zurückgenommen; Status erneut lesen."); };
  const upload = async (selected?: File) => {
    invalidate(); pending.current = undefined; saved.current = undefined; setFile(undefined);
    const sequence = ++fileSerial.current;
    setHashing(false);
    if (!selected) return;
    if (!selected.size || selected.size > MAX || !text(selected.name) || selected.name.length > 180
      || /[\\/\x00-\x1f\x7f]/.test(selected.name) || [".", ".."].includes(selected.name)) {
      setError("Methodendokument: regulärer Dateiname und 1 Byte bis 2 MiB erforderlich."); return;
    }
    setHashing(true);
    try {
      const bytes = new Uint8Array(await selected.arrayBuffer());
      if (bytes.byteLength !== selected.size) throw new Error("file_changed");
      const digest = await sha256Bytes(bytes);
      const checksum = Array.from(new Uint8Array(digest), (v) => v.toString(16).padStart(2, "0")).join("");
      const chunks: string[] = [];
      for (let offset = 0; offset < bytes.length; offset += 16384) chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 16384)));
      if (sequence !== fileSerial.current) return;
      setFile({ filename: selected.name, media_type: /^[A-Za-z0-9!#$&^_.+-]+\/[A-Za-z0-9!#$&^_.+-]+$/.test(selected.type) ? selected.type : "application/octet-stream",
        content_base64: btoa(chunks.join("")), sha256: checksum, byte_length: bytes.length });
    } catch { if (sequence === fileSerial.current) setError("Methodendokument konnte nicht gehasht werden. Datei erneut auswählen."); }
    finally { if (sequence === fileSerial.current) setHashing(false); }
  };
  function draft(): Omit<Draft, "request_id"> | null {
    if (!supported || !file || hashing || !utc(form.valuation) || !decimal(form.value) || !/^\d+$/.test(form.decimals)
      || !integer(Number(form.decimals), 0, 255) || !/^\d+$/.test(form.version) || !integer(Number(form.version), 1, Number.MAX_SAFE_INTEGER)
      || !timezone(form.timezone) || ![form.network, form.contract, form.methodId, form.actor, form.rationale, form.locator, form.source].every(text)
      || !props.originals.some((v) => v.sha256 === form.original) || !utc(form.published)) return null;
    const daily = form.kind === "daily_reference", usd = form.currency === "USD";
    if (daily ? !utc(form.start) || !utc(form.end) || utc(form.start)! >= utc(form.end)! || !form.statistic
      || (form.statistic === "daily_fixed_time" && !/^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(form.dailyTime))
      : !utc(form.observed)) return null;
    if (usd && (!decimal(form.fxRate) || !utc(form.fxReference) || !utc(form.fxPublished)
      || ![form.fxLocator, form.fxSource].every(text) || !props.originals.some((v) => v.sha256 === form.fxOriginal)
      || !/^\d+$/.test(form.fxAge) || !integer(Number(form.fxAge), 0, 7))) return null;
    const identity = { asset: props.asset, network: form.network, contract: form.contract, decimals: Number(form.decimals) };
    const [base, quote] = form.fxPair.split("/");
    return { preview_sha256: props.previewSha256, price_fingerprint: props.priceFingerprint, valuation_at: utc(form.valuation)!, identity,
      observation: { identity, quote_currency: form.currency, value: form.value, kind: form.kind,
        observed_at: daily ? null : utc(form.observed), period_start: daily ? utc(form.start) : null, period_end: daily ? utc(form.end) : null,
        published_at: utc(form.published)!, evidence_sha256: form.original, locator: form.locator, source: form.source,
        fx: usd ? { base, quote, rate: form.fxRate, reference_at: utc(form.fxReference)!, published_at: utc(form.fxPublished)!,
          evidence_sha256: form.fxOriginal, locator: form.fxLocator, source: form.fxSource } : null },
      method: { method_id: form.methodId, version: Number(form.version), kind: form.kind, daily_statistic: daily ? form.statistic : null,
        daily_time: daily && form.statistic === "daily_fixed_time" ? form.dailyTime : null, timezone: form.timezone,
        availability_rule: daily ? form.availability : "available_at_cutoff", fx_max_age_days: usd ? Number(form.fxAge) : null, evidence_sha256: file.sha256 },
      method_original: { filename: file.filename, media_type: file.media_type, content_base64: file.content_base64 }, actor: form.actor, rationale: form.rationale };
  }
  const base = `/api/v1/prices/historical/previews/${props.previewId}/prices/${props.priceId}`;
  async function run(kind: "prepare" | "reload" | "status" | "apply" | "revoke") {
    if (!supported || busy) return;
    let body: unknown, path = "", expected: { request_id: string; draft_sha256?: string } | undefined;
    let valuation = utc(form.valuation);
    if (kind === "prepare") {
      const value = draft(); if (!value) return;
      if (!pending.current) pending.current = { request_id: newRequestId(), ...value };
      body = pending.current; expected = { request_id: pending.current.request_id }; valuation = pending.current.valuation_at;
      path = "/admission-previews";
    } else if (kind === "status") {
      if (!valuation) return;
      path = `/admissions?valuation_at=${encodeURIComponent(valuation)}`;
    } else {
      const target = report || saved.current;
      const requestId = target?.request_id || pending.current?.request_id;
      if (!requestId || !valuation) return;
      expected = { request_id: requestId, draft_sha256: target?.draft_sha256 };
      path = `/admission-previews/${requestId}`;
      if (kind === "apply") {
        if (!report?.can_apply || !acks.every(Boolean)) return;
        body = { draft_sha256: report.draft_sha256, acknowledge_original_verified: true, acknowledge_scope_limited: true }; path += "/apply";
      }
      if (kind === "revoke") {
        if (report?.status !== "human_approved" || !revoke.ack || !text(revoke.actor) || !text(revoke.rationale)) return;
        path = `/admissions/${requestId}/revoke`;
        body = { draft_sha256: report.draft_sha256, actor: revoke.actor, rationale: revoke.rationale, acknowledge_revocation: true };
      }
    }
    if (!valuation) return;
    controller.current?.abort(); const request = new AbortController(); controller.current = request;
    const sequence = ++serial.current;
    saved.current = kind === "prepare" ? undefined : report || saved.current;
    setReport(undefined); setAcks([false, false]); setRevoke((value) => ({ ...value, ack: false })); setEmpty(false); setError(""); setErrorCode(""); setBusy(kind);
    try {
      const raw = await api(base + path, request.signal, body);
      if (request.signal.aborted || sequence !== serial.current) return;
      if (kind === "status" && raw === null) { saved.current = undefined; setEmpty(true); return; }
      const value = readReport(raw, props, valuation, expected, pending.current);
      if (kind === "apply" && value.status !== "human_approved") throw new Error("apply_not_confirmed");
      if (kind === "revoke" && value.status !== "revoked") throw new Error("revoke_not_confirmed");
      setReport(value); saved.current = value;
    } catch (failure) {
      if (!request.signal.aborted && sequence === serial.current) {
        const code = failure instanceof AdmissionError ? failure.code : "";
        setErrorCode(code);
        setError(apiErrors[code] || "Antwort nicht eindeutig bestätigt oder Anfrage fehlgeschlagen. Eingaben bleiben erhalten. Gespeicherten Status erneut lesen; keine automatische Wiederholung.");
      }
    } finally { if (sequence === serial.current) setBusy(""); }
  }
  const input = (name: keyof Form, label: string, type = ["decimals", "version", "fxAge"].includes(name) ? "number" : "text", hint?: string) => <div key={name} style={wrap}>
    <label>{label}<input type={type} step={type === "datetime-local" ? "any" : type === "number" ? "1" : undefined} value={form[name]} maxLength={4096}
      min={type === "number" ? (name === "version" ? 1 : 0) : undefined} max={name === "decimals" ? 255 : name === "fxAge" ? 7 : undefined}
      inputMode={type === "text" && ["value", "fxRate"].includes(name) ? "decimal" : undefined}
      onChange={(e) => change(name, e.target.value)} autoComplete="off" /></label>
    {hint && <HelpTip label={label}>{hint}</HelpTip>}
  </div>;
  const select = (name: keyof Form, label: string, options: [string, string][], placeholder = true) => <label key={name} style={wrap}>{label}
    <select aria-label={label} value={form[name]} onChange={(e) => change(name, e.target.value)}>{placeholder && <option value="">Auswählen</option>}{options.map(([v, title]) => <option key={v} value={v}>{title}</option>)}</select>
  </label>;
  const originalOptions: [string, string][] = supported ? props.originals.map((v, i) => [v.sha256, `${i + 1}: ${v.filename || "Original"} · ${v.sha256.slice(0, 12)} · ${v.byte_length} Byte`]) : [];
  const date = (name: keyof Form, label: string) => input(name, label + " (UTC)", "datetime-local");
  const validDraft = draft() !== null;
  return <details className="wsTechnical" style={wrap}>
    <summary>Preiszeit und Methode menschlich bestätigen</summary>
    <p>Nur {props.asset}, diese Preis-ID und ein ausdrücklich gewählter Bewertungszeitpunkt. Keine automatische Echtheits-, Token-, Steuerjahres- oder Rechtsfreigabe.</p>
    {!supported ? <p role="alert">Verifizierte Importbindung fehlt oder ist ungültig. Keine Bestätigung möglich.</p> : <>
      <details className="wsTechnical"><summary>Gebundener Importkontext</summary><p style={wrap}>Preis-ID: {props.priceId}<br />Vorschau: {props.previewId}<br />Vorschau-SHA: {props.previewSha256}<br />Preis-Fingerprint: {props.priceFingerprint}</p>
        <p>Gespeicherter EUR-Wert: {props.priceEur ?? "nicht mitgegeben"}<br />Gespeicherte Referenzzeit: {props.storedReferenceAt ?? "nicht mitgegeben"}. Kein Beobachtungs- oder Veröffentlichungsnachweis.</p>
        <ul style={wrap}>{props.originals.map((v) => <li key={v.sha256} style={wrap}>{v.filename || "Original"}: {v.sha256} · {v.byte_length} Byte</li>)}</ul>
      </details>
      <form className="wsForm" onSubmit={(e: FormEvent) => { e.preventDefault(); void run("prepare"); }}>
        <fieldset style={band}><legend>1. Identität und Bewertungszeitpunkt</legend><div style={grid}>
          {input("network", "Netzwerk")}{input("contract", "Contract / eindeutige Assetkennung")}{input("decimals", "Token-Dezimalstellen")}
          {date("valuation", "Bewertungszeitpunkt")}
        </div><div className="wsActionFooter"><button type="button" disabled={!utc(form.valuation) || !!busy} onClick={() => void run("status")}><RefreshCw size={16} />Bestätigungsstatus lesen</button></div></fieldset>
        <fieldset style={band}><legend>2. Beobachtung und Preisoriginal</legend><div style={grid}>
          {select("currency", "Kurswährung", [["EUR", "EUR"], ["USD", "USD"]], false)}
          {input("value", "Beobachteter Kurswert", "text", "Exakter positiver Dezimalwert mit Punkt, ohne Tausendertrennzeichen. Kein Ersatz des gespeicherten Preises.")}
          {select("kind", "Referenzart", [["observed_quote", "Beobachteter Quote"], ["daily_reference", "Explizite Tagesreferenz"]], false)}
          {form.kind === "observed_quote" ? date("observed", "Beobachtet am") : <>{date("start", "Periodenbeginn")}{date("end", "Periodenende (exklusiv)")}</>}
          {date("published", "Preis veröffentlicht am")}{select("original", "Preisoriginal", originalOptions)}
          {input("locator", "Fundstelle im Preisoriginal")}{input("source", "Preisquelle")}
        </div><small>Beobachtung und Veröffentlichung sind menschliche Transkriptionen. Erfassungszeiten setzt ausschließlich der Server bei Vorlage.</small></fieldset>
        {form.currency === "USD" && <fieldset style={band}><legend>3. USD-/EUR-Umrechnung</legend><div style={grid}>
          {select("fxPair", "FX-Richtung", [["USD/EUR", "USD → EUR (multiplizieren)"], ["EUR/USD", "EUR → USD (dividieren)"]], false)}
          {input("fxRate", "FX-Kurswert")}{date("fxReference", "FX-Referenzzeit")}{date("fxPublished", "FX veröffentlicht am")}
          {select("fxOriginal", "FX-Original", originalOptions)}{input("fxLocator", "Fundstelle im FX-Original")}{input("fxSource", "FX-Quelle")}
          {input("fxAge", "Maximales FX-Alter in Tagen (0–7)")}
        </div></fieldset>}
        <fieldset style={band}><legend>{form.currency === "USD" ? "4" : "3"}. Ausdrückliche Methode</legend><div style={grid}>
          {input("methodId", "Methodenkennung")}{input("version", "Methodenversion")}
          {input("timezone", "Methodenzeitzone", "text", "IANA-Zeitzone, zum Beispiel Europe/Berlin oder UTC. Alle eingegebenen Zeitpunkte bleiben ausdrücklich UTC; Tagesgrenzen müssen zur Methode passen.")}
          {form.kind === "daily_reference" && <>
            {select("statistic", "Tagesstatistik", [["daily_mean", "Tagesmittel"], ["daily_fixed_time", "Fester Tageszeitpunkt"], ["daily_close", "Tagesschluss"]])}
            {form.statistic === "daily_fixed_time" && input("dailyTime", "Lokale Methodenuhrzeit", "time")}
            {select("availability", "Verfügbarkeitsregel", [["available_at_cutoff", "Am Bewertungszeitpunkt verfügbar"], ["retrospective_daily_reference", "Ausdrücklich rückblickende Tagesreferenz"]], false)}
          </>}
          <label>Methodendokument (1 Byte bis 2 MiB)<input type="file" onChange={(e) => void upload(e.target.files?.[0])} /></label>
        </div>{hashing && <p role="status">Methodendokument wird gehasht.</p>}{file && <p style={wrap}>Methodendokument: {file.filename} · {file.byte_length} Byte<br />SHA-256: <code>{file.sha256}</code></p>}</fieldset>
        <fieldset style={band}><legend>Person und Begründung</legend><div style={grid}>{input("actor", "Bestätigende Person")}
          <label>Begründung<textarea aria-label="Begründung" value={form.rationale} maxLength={4096} onChange={(e) => change("rationale", e.target.value)} rows={3} /></label>
        </div></fieldset>
        <div className="wsActionFooter"><button className="wsPrimary" type="submit" disabled={!validDraft || !!busy}><FileSearch size={16} />Technische Vorschau vorbereiten</button>
          {(errorCode === "price_admission_policy_changed" || report?.assessment.reason_codes.includes("price_admission_policy_changed")) && <button type="button" disabled={!validDraft || !!busy} onClick={() => { pending.current = undefined; saved.current = undefined; void run("prepare"); }}><FileSearch size={16} />Neue technische Vorschau vorbereiten</button>}
          {(pending.current || saved.current) && <button type="button" disabled={!!busy || !utc(form.valuation)} onClick={() => void run("reload")}><RefreshCw size={16} />Vorschau erneut lesen</button>}
        </div>
        {!validDraft && !hashing && <small>Alle Fakten, die ausdrückliche Methode, Person, Begründung und ein gültiges Methodendokument sind für die technische Vorschau erforderlich.</small>}
      </form>
      {busy && <div className="wsResource" role="status"><LoaderCircle size={16} className="spin" />{busy === "apply" ? "Bestätigung wird gespeichert." : busy === "revoke" ? "Widerruf wird gespeichert." : "Technische Prüfung läuft."}<button type="button" onClick={cancel}><X size={16} />Abbrechen</button></div>}
      {error && <p role="alert" className="wsInlineWarning">{error}</p>}
      {empty && <p role="status">Keine Bestätigung für diesen Bewertungszeitpunkt gespeichert.</p>}
      {report && <section aria-label="Gebundene Preiszeitprüfung" style={wrap}>
        <h3 style={{ fontSize: 16 }}>{titles[report.status]}</h3>
        <p>Bewertungszeitpunkt: {report.valuation_at}<br />Netzwerk: {report.identity.network} · Contract: {report.identity.contract} · Dezimalstellen: {report.identity.decimals}<br />
          Kurs: {report.observation.value} {report.observation.quote_currency} · {report.observation.kind === "observed_quote" ? `Beobachtung: ${report.observation.observed_at}` : `Periode: ${report.observation.period_start} bis ${report.observation.period_end} (exklusiv)`}<br />
          Veröffentlicht: {report.observation.published_at}<br />Serverseitig erfasst: {report.observation.captured_at}<br />Person: {report.actor}<br />Begründung: {report.rationale}</p>
        <p>Keine Gesamtfreigabe. Bestehende Preiswahl und weitere Stichtagsprüfungen bleiben unabhängig.</p>
        <details className="wsTechnical"><summary>Methode, Originale und technische Bindung</summary>
          <p>Methode: {report.method.method_id} · Version {report.method.version} · {report.method.timezone}<br />Referenzart: {report.method.kind} · Tagesstatistik: {report.method.daily_statistic || "nicht anwendbar"} · lokale Uhrzeit: {report.method.daily_time || "nicht anwendbar"}<br />Verfügbarkeit: {report.method.availability_rule}<br />Maximales FX-Alter: {report.method.fx_max_age_days ?? "nicht anwendbar"}<br />Preisquelle: {report.observation.source}<br />Fundstelle: {report.observation.locator}</p>
          {report.observation.fx && <p>FX: {report.observation.fx.base}/{report.observation.fx.quote} · {report.observation.fx.rate}<br />Referenz: {report.observation.fx.reference_at}<br />Veröffentlicht: {report.observation.fx.published_at}<br />Serverseitig erfasst: {report.observation.fx.captured_at}<br />Quelle: {report.observation.fx.source}<br />Fundstelle: {report.observation.fx.locator}</p>}
          <p>Request-ID: {report.request_id}<br />Draft-SHA: {report.draft_sha256}<br />Prüfpolicy-SHA: {report.validation_policy_sha256}<br />Faktenbindung: {report.assessment.binding_sha256}<br />Methodenoriginal-SHA: {report.method_original.sha256}<br />Preisoriginal-SHA: {report.observation.evidence_sha256}</p>
          {report.decision && <p>Bestätigungsentscheidung: {report.decision.decision_id}<br />Person: {report.decision.actor}<br />Begründung: {report.decision.rationale}<br />Gespeichert: {report.decision.created_at}</p>}
          {report.revocation && <p>Widerrufsentscheidung: {report.revocation.decision_id}<br />Person: {report.revocation.actor}<br />Begründung: {report.revocation.rationale}<br />Gespeichert: {report.revocation.created_at}</p>}
          <a className="wsButton" style={wrap} download href={`${API_BASE}${base}/admission-previews/${report.request_id}/method-original`}><Download size={16} />Methodendokument herunterladen</a>
        </details>
        {report.assessment.reason_codes.length > 0 && <ul style={wrap}>{report.assessment.reason_codes.map((reason, index) => <li key={index}>{reasons[reason] || "Eine technische Voraussetzung ist offen; Beleg und Methode prüfen."}</li>)}</ul>}
        {report.can_apply && <div className="wsForm" style={band}>
          <label style={{ display: "flex", alignItems: "start", gap: 10 }}><input type="checkbox" checked={acks[0]} onChange={(e) => setAcks([e.target.checked, acks[1]])} />Ich habe die Originale geprüft und Identität, Kurs, Preiszeiten, FX und Methode anhand der Belege bestätigt.</label>
          <label style={{ display: "flex", alignItems: "start", gap: 10 }}><input type="checkbox" checked={acks[1]} onChange={(e) => setAcks([acks[0], e.target.checked])} />Ich bestätige ausschließlich diese Preis-ID, Methode und diesen Bewertungszeitpunkt, keine Steuerjahres- oder Rechtsfreigabe.</label>
          <div><button type="button" className="wsPrimary" disabled={!acks.every(Boolean) || !!busy} onClick={() => void run("apply")}><Check size={16} />Menschliche Bestätigung speichern</button></div>
        </div>}
        {report.status === "human_approved" && <details className="wsTechnical"><summary>Bestätigung ausdrücklich widerrufen</summary><div className="wsForm" style={band}>
          <label>Widerrufende Person<input value={revoke.actor} maxLength={4096} onChange={(e) => setRevoke({ ...revoke, actor: e.target.value, ack: false })} /></label>
          <label>Widerrufsbegründung<textarea aria-label="Widerrufsbegründung" value={revoke.rationale} maxLength={4096} onChange={(e) => setRevoke({ ...revoke, rationale: e.target.value, ack: false })} /></label>
          <label style={{ display: "flex", alignItems: "start", gap: 10 }}><input type="checkbox" checked={revoke.ack} onChange={(e) => setRevoke({ ...revoke, ack: e.target.checked })} />Ich widerrufe diese Bestätigung ausdrücklich. Alte Entscheidungen und Originale bleiben erhalten.</label>
          <div><button type="button" disabled={!text(revoke.actor) || !text(revoke.rationale) || !revoke.ack || !!busy} onClick={() => void run("revoke")}><Ban size={16} />Bestätigung widerrufen</button></div>
        </div></details>}
      </section>}
    </>}
  </details>;
}
