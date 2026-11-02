import { build } from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const output = mkdtempSync(join(tmpdir(), "steuerreport-dashboard-tests-"));
await build({
  entryPoints: ["tests/dashboard-valuation.test.ts", "tests/dashboard-render.test.tsx"],
  outdir: output,
  bundle: true,
  platform: "node",
  format: "cjs",
  define: { "import.meta.env.VITE_API_BASE": '"http://example.invalid"' },
  plugins: [{
    name: "synthetic-dashboard-resources",
    setup(builder) {
      builder.onResolve({ filter: /^\.\/resource$/ }, (args) =>
        args.importer.endsWith("DashboardWorkspace.tsx")
          ? { path: resolve("tests/dashboard-resource-fixture.ts") }
          : undefined);
    }
  }]
});
const result = spawnSync(process.execPath, ["--test", join(output, "dashboard-valuation.test.js"), join(output, "dashboard-render.test.js")], { stdio: "inherit" });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
