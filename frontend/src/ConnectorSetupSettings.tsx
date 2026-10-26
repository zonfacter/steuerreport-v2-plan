import { useState } from "react";
import { Copy, RefreshCw, ShieldCheck } from "lucide-react";
import { AdminEnvironmentState, useAdminEnvironment } from "./ConnectionSettings";
import { HelpTip } from "./Help";
import { readApi, useResource } from "./workspace/resource";

type Catalog = { security: { auth_mode: string; connector_writes_enabled: boolean } };
const COMMANDS = {
  ghcr: "docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup",
  docker: "docker compose exec steuerreport python -m steuerreport_v2.connector_setup",
  native: "python3 -m steuerreport_v2.connector_setup"
};

export function ConnectorSetupSettings() {
  const environment = useAdminEnvironment();
  const catalog = useResource<Catalog>("connector-setup-security", (signal) => readApi("/api/v1/connectors/catalog", signal));
  const [installation, setInstallation] = useState<keyof typeof COMMANDS>("ghcr");
  const [notice, setNotice] = useState("");
  const ready = catalog.status === "ready" && catalog.data?.security.auth_mode === "setup_token";
  return <section className="installationSettings" aria-label="Wallet-Eigentumsnachweis">
    <div className="panelToolbar"><div className="pageTitle"><h2>Wallet-Eigentumsnachweis</h2><HelpTip label="Geschützte Connector-Einrichtung">Das separate Einrichtungspasswort schützt lokale Connector-Funktionen. Es ist kein Börsenschlüssel und kein privater Wallet-Schlüssel. Die Signaturprüfung bleibt erforderlich.</HelpTip></div>
      <button type="button" className="ghostButton" title="Connector-Einrichtung neu prüfen" aria-label="Connector-Einrichtung neu prüfen" disabled={catalog.status === "loading"} onClick={catalog.reload}><RefreshCw size={16} /></button></div>
    <AdminEnvironmentState environment={environment} />
    {catalog.status === "loading" && <p role="status">Connector-Einrichtung wird geprüft.</p>}
    {catalog.status === "error" && <p role="alert">Der Einrichtungsstatus ist nicht verfügbar. Neu prüfen; keine Freigabe wurde geändert.</p>}
    {catalog.status === "ready" && <p role="status"><ShieldCheck size={16} /> {ready ? "Einrichtungspasswort vorhanden. Für den Wallet-Nachweis wird es im geschützten Eingabefeld benötigt." : "Das lokale Einrichtungspasswort ist noch nicht vorbereitet. Die Connector-Funktionen bleiben geschützt."}</p>}
    {environment.status === "ready" && !environment.locked && <>
      <label htmlFor="connector-installation-type">Installationsart</label><select id="connector-installation-type" value={installation} onChange={(event) => { setInstallation(event.target.value as keyof typeof COMMANDS); setNotice(""); }}>
        <option value="ghcr">Docker Compose – GHCR-Image</option><option value="docker">Docker Compose – lokaler Build</option><option value="native">Native Installation</option>
      </select>
      <p>Die folgenden Befehle gehören in die private Serverkonsole mit administrativem Zugriff, nicht in ein Wallet oder einen Chat. Bei manuell benannten Containern den passenden Namen mit <code>docker exec -it</code> verwenden.</p>
      {(!ready ? ["init", "show-token"] : ["show-token"]).map((action) => <div key={action} className="installationSection">
        <strong>{action === "init" ? "Bestehende Installation ausdrücklich vorbereiten" : "Passwort ausschließlich lokal anzeigen"}</strong>
        <div className="adminFormActions"><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", minWidth: 0 }}>{COMMANDS[installation]} {action}</pre><button type="button" className="ghostButton" title="Befehl kopieren" aria-label={`${action === "init" ? "Aktivierungsbefehl" : "Anzeigebefehl"} kopieren`} onClick={() => {
          if (!navigator.clipboard) { setNotice("Befehl bitte direkt aus der Anzeige kopieren."); return; }
          void navigator.clipboard.writeText(`${COMMANDS[installation]} ${action}`).then(() => setNotice("Befehl kopiert."), () => setNotice("Befehl bitte direkt aus der Anzeige kopieren."));
        }}><Copy size={16} /></button></div>
      </div>)}
      <p>Neue Docker-Installationen bereiten das Passwort automatisch vor. Bei bestehenden Installationen erzeugt <code>init</code> es nur auf ausdrücklichen Aufruf; vorhandene Schlüssel und Passwörter werden nicht ersetzt. Danach den Status neu prüfen, ein Neustart ist nicht erforderlich.</p>
      <p>Unter <strong>Quellen &amp; Wallets → Quelle hinzufügen → Solana-Wallet</strong> das Passwort in <strong>Connector-Setup-Token</strong> einfügen. Es bleibt nur im aktuellen Formular, nicht in URL oder Browserspeicher. Danach die angezeigte Nachricht mit der eigenen Wallet signieren. Die steuerliche Aktivierung ist davon getrennt.</p>
      <p className="adminInlineHelp">Die Web-API liefert das Einrichtungspasswort niemals aus. <code>show-token</code> funktioniert nur in einer interaktiven Konsole. Keine Seed-Phrase, keinen privaten Wallet-Schlüssel und keine Börsen-Handels- oder Auszahlungsrechte angeben.</p>
    </>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
