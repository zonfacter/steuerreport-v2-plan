import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../api-base";

export type Resource<T> = { status: "initial" | "loading" | "ready" | "empty" | "error"; data?: T; stale: boolean; error?: string; updatedAt?: string; key?: string; reload: () => void };
export async function readApi<T>(path: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const response = await fetch(API_BASE + path, { signal, method: body === undefined ? "GET" : "POST", headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const envelope = await response.json();
  if (!response.ok || envelope.status === "error") throw new Error(response.status === 404 ? "Datensatz nicht mehr verfügbar. Ansicht aktualisieren." : response.status === 409 ? "Ein Vorgang läuft bereits oder die Voraussetzungen sind noch offen." : "Daten konnten nicht geladen werden. Erneut versuchen.");
  return envelope.data;
}
export function useResource<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): Resource<T> {
  const loader = useRef(load); loader.current = load;
  const serial = useRef(0);
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<Omit<Resource<T>, "reload">>({ status: "initial", stale: false });
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => { window.addEventListener("steuerreport:refresh", reload); return () => window.removeEventListener("steuerreport:refresh", reload); }, [reload]);
  useEffect(() => {
    const version = ++serial.current;
    if (key === null) { setState({ status: "initial", stale: false }); return; }
    const controller = new AbortController();
    setState((previous) => ({ ...previous, status: "loading", stale: previous.data !== undefined, error: undefined }));
    void loader.current(controller.signal).then((data) => {
      if (!controller.signal.aborted && version === serial.current) setState({ status: "ready", data, stale: false, key, updatedAt: new Date().toISOString() });
    }).catch((error) => {
      if (!controller.signal.aborted && version === serial.current) setState((previous) => ({ ...previous, status: "error", stale: previous.data !== undefined, error: error instanceof Error ? error.message : "Anfrage fehlgeschlagen." }));
    });
    return () => { controller.abort(); };
  }, [key, revision]);
  return { ...state, reload };
}
export function useDebounced(value: string, delay = 300) {
  const [ready, setReady] = useState(value);
  useEffect(() => { const timer = window.setTimeout(() => setReady(value), delay); return () => window.clearTimeout(timer); }, [value, delay]);
  return ready;
}

export function canonicalDecimal(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const parts = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,4}))?$/.exec(String(value));
  if (!parts) return null;
  const exponent = Number(parts[4] || 0);
  if (Math.abs(exponent) > 1000) return null;
  const digits = parts[2] + (parts[3] || ""), point = parts[2].length + exponent;
  return parts[1] + (point <= 0 ? "0." + "0".repeat(-point) + digits : point >= digits.length ? digits + "0".repeat(point - digits.length) : digits.slice(0, point) + "." + digits.slice(point));
}
export function money(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Noch nicht verfügbar";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(canonicalDecimal(value) || "");
  if (!match) return "Noch nicht verfügbar";
  const fraction = (match[3] || "").padEnd(3, "0");
  const cents = BigInt(match[2]) * 100n + BigInt(fraction.slice(0, 2)) + (fraction[2] >= "5" ? 1n : 0n);
  const digits = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${match[1] && cents ? "-" : ""}${digits},${(cents % 100n).toString().padStart(2, "0")} EUR`;
}
export function compareAmounts(a: string | null, b: string | null): number {
  a = canonicalDecimal(a); b = canonicalDecimal(b);
  if (a === null || b === null) return a === b ? 0 : a === null ? -1 : 1;
  const [wholeA, fractionA = ""] = a.split("."), [wholeB, fractionB = ""] = b.split(".");
  const precision = Math.max(fractionA.length, fractionB.length);
  const integer = (whole: string, fraction: string) => BigInt(whole.replace("-", "") + fraction.padEnd(precision, "0")) * (whole.startsWith("-") ? -1n : 1n);
  const left = integer(wholeA, fractionA), right = integer(wholeB, fractionB);
  return left < right ? -1 : left > right ? 1 : 0;
}
export function timestamp(value?: string | null): string {
  if (!value) return "Noch kein Datenstand";
  const utc = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : value + "Z";
  const date = new Date(utc);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "long", timeZone: "Europe/Berlin" }).format(date) : "Zeitpunkt unbekannt";
}

export function priceReference(row: { asset: string; price_status?: string; priced_at_latest?: string | null; price_sources?: string[] }) {
  const sources = row.price_sources || [];
  if (row.asset.toUpperCase() === "EUR" && sources.includes("fiat:EUR")) {
    return { label: "EUR-Referenzwert", source: "Fester Wert: 1 EUR = 1 EUR" };
  }
  const instant = row.priced_at_latest && (/(?:Z|[+-]\d\d:\d\d)$/.test(row.priced_at_latest) ? row.priced_at_latest : row.priced_at_latest + "Z");
  const epoch = instant && new Date(instant).getTime() === 0;
  return {
    label: !row.priced_at_latest ? "Preiszeitpunkt nicht verfügbar" : epoch && row.price_status === "fiat" ? "Technischer Referenzwert, kein Kurszeitpunkt" : timestamp(row.priced_at_latest),
    source: sources.length ? "Bewertungsquelle in Details" : "Quelle nicht hinterlegt"
  };
}

export function compactQuantity(value: string | null | undefined, places = 8): string {
  const canonical = canonicalDecimal(value);
  if (canonical === null) return "Nicht verfügbar";
  const [whole, raw = ""] = canonical.split(".");
  const fraction = raw.replace(/0+$/, "");
  const truncated = fraction.length > places;
  if (truncated && BigInt(whole) === 0n && /^0+$/.test(fraction.slice(0, places))) {
    return `${whole.startsWith("-") ? "> -" : "< "}0,${"0".repeat(places - 1)}1`;
  }
  const integer = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return integer + (fraction ? "," + fraction.slice(0, places) : "") + (truncated ? "…" : "");
}
