import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

test("dashboard history URL survives reload and browser navigation without changing tax year", async () => {
  if (!process.env.PLAYWRIGHT_CORE || !process.env.CHROMIUM_EXECUTABLE) {
    throw new Error("Set PLAYWRIGHT_CORE and CHROMIUM_EXECUTABLE to local installations");
  }
  const { chromium } = await import(process.env.PLAYWRIGHT_CORE);
  const cacheDir = mkdtempSync(join(tmpdir(), "steuerreport-vite-test-"));
  const server = await createServer({
    configFile: false, envFile: false, root: process.cwd(), plugins: [react()],
    cacheDir,
    define: { "import.meta.env.VITE_API_BASE": JSON.stringify("http://fixture.invalid") },
    server: { host: "127.0.0.1", port: 0 }
  });
  let browser;
  try {
    await server.listen();
    const address = server.httpServer.address();
    const origin = `http://127.0.0.1:${address.port}`;
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE, headless: true, args: ["--no-sandbox"] });
    const page = await browser.newPage();
    const requests = [];
    const blocked = [];
    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin === origin && !url.pathname.startsWith("/api/")) return route.continue();
      if (url.origin !== "http://fixture.invalid" || !url.pathname.startsWith("/api/") || request.method() !== "GET") {
        blocked.push(`${request.method()} ${url.origin}${url.pathname}`);
        return route.abort();
      }
      requests.push(url);
      let data = {};
      if (url.pathname === "/api/v1/workspace/status") data = {
        year: Number(url.searchParams.get("year")), balance_entries: 1, events_count: 1, owned_sources_count: 1,
        dimensions: {}, next_section: "sources", next_action: "Prüfen", summary: "Test", final_available: false
      };
      if (url.pathname === "/api/v1/portfolio/snapshot") data = { total_value_eur: "0", positions: [], asset_summary: [], missing_price_assets: [] };
      if (url.pathname === "/api/v1/workspace/sources") data = { sources: [] };
      if (url.pathname === "/api/v1/cockpit/summary") data = { portfolio_performance: { live_value_eur: null }, live_reconciliation: {} };
      if (url.pathname === "/api/v1/portfolio/value-history") {
        const to = url.searchParams.get("to_date");
        const day = to || new Date().toISOString().slice(0, 10);
        data = { points: [
          { date: day, as_of: to ? `${to}T23:59:59.999999Z` : new Date(Date.now() - 5000).toISOString(), total_value_eur: "10", positions_count: 1, missing_price_assets: [] },
          { date: day, as_of: new Date(Date.now() + 3600000).toISOString(), total_value_eur: "999", positions_count: 1, missing_price_assets: [] }
        ], methodology: "synthetic" };
      }
      return route.fulfill({ status: 200, contentType: "application/json", headers: { "Access-Control-Allow-Origin": "*" }, body: JSON.stringify({ status: "ok", data }) });
    });
    const current = new Date().getUTCFullYear();
    const past = String(current - 1);
    const older = String(current - 2);
    await page.goto(`${origin}/#dashboard?tab=development&year=2024`);
    const historyYear = page.getByLabel("Kalenderjahr der Ledger-Historie");
    await historyYear.waitFor();
    await page.waitForFunction((year) => new URLSearchParams(location.hash.split("?")[1]).get("history_year") === year, String(current));
    await page.getByText("Stichtag:", { exact: false }).waitFor();
    assert.equal(await page.getByLabel("Gemeinsames Steuerjahr").inputValue(), "2024");
    assert.equal(await historyYear.inputValue(), String(current));
    assert.ok(requests.some((url) => url.pathname.endsWith("/value-history") && url.searchParams.get("from_date") === `${current}-01-01` && !url.searchParams.has("to_date")));
    assert.equal(await page.getByText("999,00 EUR", { exact: false }).count(), 0);

    await historyYear.selectOption(past);
    await page.waitForFunction((year) => new URLSearchParams(location.hash.split("?")[1]).get("history_year") === year, past);
    await page.waitForFunction((date) => document.querySelector('[aria-label="Historische Ledgerwerte"]')?.textContent.includes(date), `${past}-12-31`);
    assert.ok(requests.some((url) => url.pathname.endsWith("/value-history") && url.searchParams.get("to_date") === `${past}-12-31`));
    await historyYear.selectOption(older);
    await page.waitForFunction((year) => new URLSearchParams(location.hash.split("?")[1]).get("history_year") === year, older);
    await page.waitForFunction((date) => document.querySelector('[aria-label="Historische Ledgerwerte"]')?.textContent.includes(date), `${older}-12-31`);
    await page.goBack();
    await page.waitForFunction((year) => document.querySelector('[aria-label="Kalenderjahr der Ledger-Historie"]')?.value === year, past);
    await page.waitForFunction((date) => document.querySelector('[aria-label="Historische Ledgerwerte"]')?.textContent.includes(date), `${past}-12-31`);
    await page.goBack();
    await page.waitForFunction((year) => document.querySelector('[aria-label="Kalenderjahr der Ledger-Historie"]')?.value === year, String(current));
    await page.getByText("Stichtag:", { exact: false }).waitFor();
    await page.goForward();
    await page.waitForFunction((year) => document.querySelector('[aria-label="Kalenderjahr der Ledger-Historie"]')?.value === year, past);
    await page.waitForFunction((date) => document.querySelector('[aria-label="Historische Ledgerwerte"]')?.textContent.includes(date), `${past}-12-31`);
    await page.reload();
    await page.waitForFunction((year) => document.querySelector('[aria-label="Kalenderjahr der Ledger-Historie"]')?.value === year, past);
    await page.waitForFunction((date) => document.querySelector('[aria-label="Historische Ledgerwerte"]')?.textContent.includes(date), `${past}-12-31`);
    assert.equal(await page.getByLabel("Gemeinsames Steuerjahr").inputValue(), "2024");

    await page.goto(`${origin}/#dashboard?tab=development&year=2024&history_year=2099`);
    await page.waitForFunction((year) => new URLSearchParams(location.hash.split("?")[1]).get("history_year") === year, String(current));
    assert.equal(await page.getByLabel("Gemeinsames Steuerjahr").inputValue(), "2024");
    assert.deepEqual(blocked, []);
  } finally {
    if (browser) await browser.close();
    await server.close();
    rmSync(cacheDir, { recursive: true, force: true });
  }
});
