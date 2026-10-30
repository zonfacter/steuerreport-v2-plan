import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { dashboardHistoryWindow } from "../src/workspace/dashboard-valuation";

const globals = globalThis as typeof globalThis & { dashboardFixtures?: Record<string, unknown> };

test("initial ledger history keeps the tax-year hash and performs no request during rendering", async () => {
  const hash = "#dashboard?tab=development&year=2024";
  Object.assign(globalThis, { window: { location: { hash } } });
  const originalFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = (() => { requests++; throw new Error("unexpected request"); }) as typeof fetch;
  try {
    const { DashboardWorkspace } = await import("../src/workspace/DashboardWorkspace");
    const html = renderToStaticMarkup(createElement(DashboardWorkspace));
    assert.match(html, /Kalenderjahr der Ledger-Historie/);
    assert.match(html, /keine individuelle Kursentwicklung/i);
    assert.match(html, /zum Tagesende UTC/);
    assert.match(html, /heutige Punkt/);
    assert.match(html, new RegExp(`<option value="${new Date().getUTCFullYear()}" selected`));
    assert.match(html, /Das Kalenderjahr ändert nicht das Steuerjahr/);
    assert.equal(window.location.hash, hash);
    assert.equal(requests, 0);
  } finally {
    globalThis.fetch = originalFetch;
    delete globals.dashboardFixtures;
    Reflect.deleteProperty(globalThis, "window");
  }
});

test("dashboard labels synthetic missing, old and future prices and stored live anchors", async () => {
  Object.assign(globalThis, { window: { location: { hash: "#dashboard?year=2024" } } });
  const now = Date.now();
  const row = (asset: string, price_status: string, priced_at_latest: string | null) => ({
    asset, quantity: "1", value_eur: "10", price_status, priced_at_latest, price_sources: ["fixture"]
  });
  globals.dashboardFixtures = {
    "dashboard-status": { year: 2024, balance_entries: 1, events_count: 1, dimensions: {}, next_section: "sources" },
    "dashboard-portfolio": { total_value_eur: "20", positions: [{}], missing_price_assets: ["MISSING"], asset_summary: [
      row("MISSING", "missing", null), row("OLD", "fresh", new Date(now - 5 * 86400000).toISOString()),
      row("FUTURE", "fresh", new Date(now + 86400000).toISOString()),
      { ...row("EUR", "fiat", "1970-01-01T00:00:00Z"), price_sources: ["fiat:EUR"] }
    ] },
    "dashboard-sources": { sources: [{ ref: "fixture", label: "Fixture", live_balance_status: "available", live_value_eur: "10", live_assets_count: 1, live_unpriced_assets_count: 0 }] }
  };
  try {
    const { DashboardWorkspace } = await import("../src/workspace/DashboardWorkspace");
    const html = renderToStaticMarkup(createElement(DashboardWorkspace));
    assert.match(html, /Unvollständiger gespeicherter Teilwert/);
    assert.match(html, /Gespeicherter Kurs veraltet/);
    assert.match(html, /Kurszeitpunkt liegt in der Zukunft/);
    assert.match(html, /Nicht bewertet/);
    assert.match(html, /gespeicherte Live-Anker/);
    assert.match(html, /Kursstand nicht ausgewiesen/);
    assert.equal((html.match(/EUR-Referenzwert/g) || []).length, 1);
    assert.match(html, /Fester Wert: 1 EUR = 1 EUR/);
    assert.match(html, /Bewertungsquelle in Details/);
    assert.doesNotMatch(html, /Berechneter Ledger-Bestand/);
  } finally {
    delete globals.dashboardFixtures;
    Reflect.deleteProperty(globalThis, "window");
  }
});

test("ledger history labels partial and unavailable values instead of complete zeroes", async () => {
  const year = String(new Date().getUTCFullYear());
  const range = dashboardHistoryWindow(year);
  if (!range) return;
  Object.assign(globalThis, { window: { location: { hash: "#dashboard?tab=development&year=2024" } } });
  globals.dashboardFixtures = {
    "dashboard-status": { year: 2024, balance_entries: 1, events_count: 1, dimensions: {}, next_section: "sources" },
    history: { points: [
      { date: range.from, as_of: `${range.from}T00:00:00Z`, positions_count: 0, total_value_eur: "0", missing_price_assets: [] },
      { date: range.to, as_of: new Date(Date.now() - 1000).toISOString(), positions_count: 1, total_value_eur: "10", missing_price_assets: ["TEST"] },
      { date: `${Number(year) + 1}-01-01`, as_of: `${Number(year) + 1}-01-01T23:59:59Z`, positions_count: 1, total_value_eur: "99", missing_price_assets: [] }
    ] }
  };
  try {
    const { DashboardWorkspace } = await import("../src/workspace/DashboardWorkspace");
    const html = renderToStaticMarkup(createElement(DashboardWorkspace));
    assert.match(html, /Kein bewerteter Bestand nachgewiesen/);
    assert.match(html, /Unvollständiger Teilwert/);
    assert.match(html, /Stichtag:/);
    assert.match(html, /Kurse fehlen: TEST/);
    assert.doesNotMatch(html, new RegExp(`${Number(year) + 1}-01-01`));
  } finally {
    delete globals.dashboardFixtures;
    Reflect.deleteProperty(globalThis, "window");
  }
});
