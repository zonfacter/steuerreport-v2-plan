// Built-in Node assertions against the actual TypeScript modules, no new test framework.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const ts = require(path.join(root, "frontend/node_modules/typescript"));
const react = require(path.join(root, "frontend/node_modules/react"));
let hash = "#dashboard";
let writes = 0;
const window = { location: { get hash() { return hash; } }, history: {
  pushState: (_state, _title, next) => { hash = next; writes++; },
  replaceState: (_state, _title, next) => { hash = next; writes++; }
}, dispatchEvent: () => {} };
function load(file) {
  const source = fs.readFileSync(path.join(root, "frontend/src/workspace", file), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, window, Event: class {}, require: (id) => id === "react" ? react : { API_BASE: "" }, URLSearchParams, console });
  return exports;
}
const route = load("view-state.ts");
for (const invalid of ["#constructor", "#__proto__", "#unknown?key=secret"]) {
  assert.equal(route.parseView(invalid).section, "dashboard");
}
const normalized = route.viewHash(route.parseView("#flows?tab=no&page=0&size=17&sort=issues&status=failed&start=2025-02-30&q=private&api_key=secret"));
assert.equal(normalized, "#flows");
const state = route.parseView("#flows?tab=ledger&year=2024&page=3&size=10&sort=oldest&asset=BTC&source=s_aaaaaaaaaaaaaaaaaaaa&detail=evt-001");
assert.equal(route.viewHash(route.parseView("#admin?tab=updates")), "#admin?tab=updates");
assert.equal(route.viewHash(route.parseView(route.viewHash(state))), route.viewHash(state));
assert.equal(state.page, 3);
assert.equal(state.tab, "ledger");
const historyImport = route.parseView("#sources?detail=s_aaaaaaaaaaaaaaaaaaaa&detailTab=import&page=2&status=failed");
assert.equal(historyImport.detailTab, "import");
assert.equal(route.parseView(route.viewHash(historyImport)).detailTab, "import");
assert.equal(route.parseView(route.viewHash(historyImport)).page, 2);
assert.equal(route.parseView(route.viewHash(historyImport)).status, "failed");
hash = "#dashboard?year=2024";
route.navigateView("tax");
assert.equal(route.parseView(hash).year, "2024");
route.navigateView("sources", { page: 2, status: "failed" });
route.navigateView("tax");
route.navigateView("sources");
assert.equal(route.parseView(hash).page, 2);
assert.equal(route.parseView(hash).status, "failed");
const before = writes;
route.navigateView("sources");
assert.equal(writes, before, "Identische Navigation darf keine History-Schleife erzeugen.");
const values = load("resource.ts");
assert.equal(values.money(null), "Noch nicht verfügbar");
assert.equal(values.money(undefined), "Noch nicht verfügbar");
assert.equal(values.money("0.000000000000000000"), "0,00 EUR");
assert.equal(values.money("0E-18"), "0,00 EUR");
assert.equal(values.money("1.234E+4"), "12.340,00 EUR");
assert.equal(values.compareAmounts("0E-18", "0"), 0);
assert.equal(values.money("999999999999999999.995"), "1.000.000.000.000.000.000,00 EUR");
assert.equal(values.money("-0.005"), "-0,01 EUR");
assert.equal(values.money("-0.004"), "0,00 EUR");
assert.equal(values.compareAmounts("9007199254740992.01", "9007199254740992.02"), -1);
assert.equal(values.compareAmounts("-0.01", "0"), -1);
assert.equal(values.compareAmounts(null, "0"), -1);
assert.equal(values.compactQuantity("0.123456789012345678"), "0,12345678…");
assert.equal(values.compactQuantity("1.000000000000000000"), "1");
assert.equal(values.compactQuantity("0.000000000000000001"), "< 0,00000001");
assert.equal(values.compactQuantity("-0.000000000000000001"), "> -0,00000001");
const fixed = values.priceReference({ asset: "EUR", price_status: "fiat", priced_at_latest: "1970-01-01T00:00:00Z", price_sources: ["fiat:EUR"] });
assert.equal(fixed.label, "EUR-Referenzwert");
assert.equal(values.priceReference({ asset: "USD", price_status: "fiat", priced_at_latest: "1970-01-01T00:00:00" }).label, "Technischer Referenzwert, kein Kurszeitpunkt");
assert.equal(values.priceReference({ asset: "SOL", price_sources: [] }).label, "Preiszeitpunkt nicht verfügbar");
const historical = "2025-01-15T10:00:00Z";
assert.equal(values.priceReference({ asset: "SOL", price_status: "old", priced_at_latest: historical, price_sources: ["synthetic"] }).label, values.timestamp(historical));
assert.equal(values.priceReference({ asset: "TEST", price_status: "old", priced_at_latest: "1970-01-02T12:00:00Z" }).label, values.timestamp("1970-01-02T12:00:00Z"));
const context = route.parseView("#flows?tab=ledger&asset=EUR&account=a_aaaaaaaaaaaaaaaaaaaa&task=review_task_1234567890123456");
assert.equal(context.account, "a_aaaaaaaaaaaaaaaaaaaa");
assert.equal(route.parseView("#flows?account=alpha-account").account, "");
console.log("Workspace state: URL normalization, roundtrip, history, shared year, privacy, exact decimal formatting/sorting passed.");
