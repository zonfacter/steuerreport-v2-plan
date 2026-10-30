export type DashboardAsset = {
  asset: string;
  quantity: string;
  value_eur: string;
  price_status: string;
  priced_at_latest: string | null;
  price_sources: string[];
};

export type DashboardPriceState = "fiat" | "fresh" | "old" | "future" | "missing" | "unknown" | "derived";

export function dashboardPriceState(row: DashboardAsset, now = new Date()): DashboardPriceState {
  const sources = row.price_sources || [];
  if (row.asset.toUpperCase() === "EUR" && sources.includes("fiat:EUR")) return "fiat";
  if (row.price_status === "missing") return "missing";
  if (!row.priced_at_latest || !sources.length) return "unknown";
  const value = /(?:Z|[+-]\d\d:\d\d)$/.test(row.priced_at_latest) ? row.priced_at_latest : row.priced_at_latest + "Z";
  const priceTime = Date.parse(value);
  if (!Number.isFinite(priceTime) || !Number.isFinite(now.getTime())) return "unknown";
  if (priceTime > now.getTime()) return "future";
  if (sources.some((source) => source.trim().toLowerCase().startsWith("derived:"))) return "derived";
  if (row.price_status === "stale" || row.price_status === "outdated" || now.getTime() - priceTime >= 4 * 86400000) return "old";
  return row.price_status === "fresh" ? "fresh" : "unknown";
}

export const dashboardPriceLabels: Record<DashboardPriceState, string> = {
  fiat: "EUR-Referenzwert",
  fresh: "Gespeicherter Zeitstempel höchstens 3 volle Tage alt; Anbieterzeit ungeprüft",
  old: "Gespeicherter Kurs veraltet",
  future: "Kurszeitpunkt liegt in der Zukunft",
  missing: "Kurs fehlt",
  unknown: "Kursstand nicht verlässlich ausgewiesen",
  derived: "Abgeleiteter Kurs, unabhängiger Preisnachweis offen"
};

export function dashboardValuationState(assets: DashboardAsset[], missingAssets: string[], now = new Date()) {
  const states = assets.map((asset) => dashboardPriceState(asset, now));
  const incomplete = missingAssets.length > 0 || states.some((state) => state === "missing");
  const uncertain = states.some((state) => state !== "fiat");
  return { incomplete, uncertain };
}

export function dashboardHistoryWindow(year: string, now = new Date()) {
  if (!/^(20\d{2}|2100)$/.test(year) || !Number.isFinite(now.getTime())) return null;
  const today = now.toISOString().slice(0, 10);
  const currentYear = today.slice(0, 4);
  if (year > currentYear) return null;
  const openEnd = year === currentYear;
  return { from: `${year}-01-01`, to: openEnd ? today : `${year}-12-31`, openEnd };
}

export function dashboardHistoryPath(window: { from: string; to: string; openEnd: boolean }) {
  const query = new URLSearchParams({ from_date: window.from, interval: "month", max_points: "13" });
  if (!window.openEnd) query.set("to_date", window.to);
  return `/api/v1/portfolio/value-history?${query}`;
}

export function dashboardHistoryPoints<T extends { date: string; as_of: string }>(
  data: { points: T[] } | undefined, dataKey: string | undefined, requestedKey: string | null,
  window: { from: string; to: string } | null, now = new Date()
): T[] {
  if (!window || !requestedKey || dataKey !== requestedKey || !Number.isFinite(now.getTime())) return [];
  return (data?.points || []).filter((point) => {
    const asOf = /(?:Z|[+-]\d\d:\d\d)$/.test(point.as_of) ? Date.parse(point.as_of) : NaN;
    return point.date >= window.from && point.date <= window.to && Number.isFinite(asOf) && asOf <= now.getTime();
  });
}
