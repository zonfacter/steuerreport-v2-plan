import assert from "node:assert/strict";
import { test } from "node:test";
import { externalPriceBackfillError } from "../src/external-price-backfill-error";

test("backfill failures do not assert storage or rollback and warn against retry", () => {
  const causes = [
    new Error("/api/v1/prices/backfill/external: HTTP 500"),
    new Error("Timeout nach 180s"),
    new TypeError("Failed to fetch"),
    new Error("SYNTHETIC_SECRET_CANARY"),
  ];
  for (const cause of causes) {
    const message = externalPriceBackfillError(cause);
    assert.match(message, /Ob Preise gespeichert wurden, ist unbekannt/);
    assert.match(message, /Pipelinefolgen koennen unbekannt oder teilweise sein/);
    assert.match(message, /Nicht erneut starten/);
    assert.doesNotMatch(message, /SYNTHETIC_SECRET_CANARY|Rollback|zurueckgerollt/);
  }
});
