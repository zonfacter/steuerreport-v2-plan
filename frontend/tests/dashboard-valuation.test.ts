import { test } from "node:test";
import assert from "node:assert/strict";
import {
  dashboardHistoryPath, dashboardHistoryPoints, dashboardHistoryWindow,
  dashboardPriceState, dashboardValuationState, type DashboardAsset
} from "../src/workspace/dashboard-valuation";
import { parseView, viewHash } from "../src/workspace/view-state";

const now = new Date("2026-10-30T12:00:00Z");
const asset: DashboardAsset = {
  asset: "TEST", quantity: "2", value_eur: "10", price_status: "fresh",
  priced_at_latest: "2026-10-30T11:00:00Z", price_sources: ["fixture"]
};

test("stored prices distinguish fresh, old, future, missing and unproven values", () => {
  assert.equal(dashboardPriceState(asset, now), "fresh");
  assert.equal(dashboardPriceState({ ...asset, priced_at_latest: "2026-10-26T12:00:00Z" }, now), "old");
  assert.equal(dashboardPriceState({ ...asset, price_status: "stale" }, now), "old");
  assert.equal(dashboardPriceState({ ...asset, price_status: "outdated" }, now), "old");
  assert.equal(dashboardPriceState({ ...asset, priced_at_latest: "2026-10-30T12:00:01Z" }, now), "future");
  assert.equal(dashboardPriceState({ ...asset, price_status: "missing", priced_at_latest: null }, now), "missing");
  assert.equal(dashboardPriceState({ ...asset, priced_at_latest: null }, now), "unknown");
  assert.equal(dashboardPriceState({ ...asset, priced_at_latest: "invalid" }, now), "unknown");
  assert.equal(dashboardPriceState({ ...asset, price_sources: [] }, now), "unknown");
  assert.equal(dashboardPriceState({ ...asset, price_sources: ["  DeRiVeD:event_quote"] }, now), "derived");
  assert.equal(dashboardPriceState({ ...asset, asset: "EUR", price_status: "fiat", priced_at_latest: "1970-01-01T00:00:00Z", price_sources: ["fiat:EUR"] }, now), "fiat");
});

test("valuation remains incomplete or uncertain even when it has a numeric total", () => {
  assert.deepEqual(dashboardValuationState([asset], [], now), { incomplete: false, uncertain: false });
  assert.deepEqual(dashboardValuationState([asset], ["MISSING"], now), { incomplete: true, uncertain: false });
  assert.deepEqual(dashboardValuationState([{ ...asset, price_status: "missing" }], [], now), { incomplete: true, uncertain: true });
  assert.deepEqual(dashboardValuationState([{ ...asset, priced_at_latest: "2026-10-30T13:00:00Z" }], [], now), { incomplete: false, uncertain: true });
});

test("history uses an open end for the current UTC year and day-end for past years", () => {
  const window = dashboardHistoryWindow("2026", now);
  assert.deepEqual(window, { from: "2026-01-01", to: "2026-10-30", openEnd: true });
  assert.equal(dashboardHistoryPath(window!), "/api/v1/portfolio/value-history?from_date=2026-01-01&interval=month&max_points=13");
  const previous = dashboardHistoryWindow("2025", now);
  assert.deepEqual(previous, { from: "2025-01-01", to: "2025-12-31", openEnd: false });
  assert.equal(dashboardHistoryPath(previous!), "/api/v1/portfolio/value-history?from_date=2025-01-01&interval=month&max_points=13&to_date=2025-12-31");
  assert.equal(dashboardHistoryWindow("2027", now), null);
  assert.equal(dashboardHistoryWindow("invalid", now), null);
  assert.deepEqual(dashboardHistoryWindow("2026", new Date("2026-01-01T12:00:00Z")), { from: "2026-01-01", to: "2026-01-01", openEnd: true });
  assert.deepEqual(dashboardHistoryWindow("2024", new Date("2024-02-29T12:00:00Z")), { from: "2024-01-01", to: "2024-02-29", openEnd: true });
});

test("history_year is dashboard-only, validated and independent of the tax year", () => {
  const current = String(new Date().getUTCFullYear());
  const past = String(Number(current) - 1);
  const dashboard = parseView(`#dashboard?tab=development&year=2024&history_year=${past}`);
  assert.equal(dashboard.year, "2024");
  assert.equal(dashboard.historyYear, past);
  assert.equal(parseView(viewHash(dashboard)).historyYear, past);
  assert.equal(parseView(`#dashboard?year=2024&history_year=${Number(current) + 1}`).historyYear, current);
  assert.equal(parseView("#dashboard?history_year=garbage").historyYear, current);
  const tax = parseView(`#tax?year=2024&history_year=${past}`);
  assert.equal(tax.year, "2024");
  assert.equal(tax.historyYear, "");
  assert.doesNotMatch(viewHash(tax), /history_year/);
});

test("previous-year responses and points outside the requested window are hidden", () => {
  const data = { points: [
    { date: "2025-12-31", as_of: "2025-12-31T23:59:59.999999Z" },
    { date: "2026-01-01", as_of: "2026-01-01T23:59:59.999999Z" },
    { date: "2026-06-01", as_of: "2026-10-30T12:00:01Z" },
    { date: "2026-07-01", as_of: "invalid" },
    { date: "2026-10-30", as_of: "2026-10-30T11:59:59Z" },
    { date: "2026-10-30", as_of: "2026-10-30T23:59:59.999999Z" }
  ] };
  const window = { from: "2026-01-01", to: "2026-10-30" };
  assert.deepEqual(dashboardHistoryPoints(data, "old", "new", window, now), []);
  assert.deepEqual(dashboardHistoryPoints(data, "new", "new", window, now), [
    { date: "2026-01-01", as_of: "2026-01-01T23:59:59.999999Z" },
    { date: "2026-10-30", as_of: "2026-10-30T11:59:59Z" }
  ]);
  assert.deepEqual(dashboardHistoryPoints(data, "new", null, window, now), []);
});
