export * from "../src/workspace/resource";
import type { Resource } from "../src/workspace/resource";

export function useResource<T>(key: string | null): Resource<T> {
  const fixtures = (globalThis as typeof globalThis & { dashboardFixtures?: Record<string, unknown> }).dashboardFixtures || {};
  const data = key === null ? undefined : fixtures[key.startsWith("dashboard-history:") ? "history" : key.split(":")[0]];
  return data === undefined
    ? { status: "initial", stale: false, reload: () => {} }
    : { status: "ready", stale: false, key: key || undefined, data: data as T, reload: () => {} };
}
