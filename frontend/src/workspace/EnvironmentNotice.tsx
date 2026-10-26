import { FlaskConical } from "lucide-react";
import { readApi, useResource } from "./resource";

export function EnvironmentNotice({ enabled }: { enabled: boolean }) {
  const environment = useResource<{ synthetic_preview: boolean; read_only: boolean }>(
    enabled ? "workspace-environment" : null,
    (signal) => readApi("/api/v1/workspace/environment", signal)
  );
  return environment.data?.synthetic_preview && environment.data.read_only ? <aside className="wsSandboxNotice" role="note" aria-label="Synthetische Testumgebung"><FlaskConical size={18} /><span><strong>Testumgebung · ausschließlich synthetische Daten.</strong> Externe Abrufe und schreibende API-Aktionen sind gesperrt.</span></aside> : null;
}
