import { DetailPanel } from "./Ui";
import { money } from "./resource";

export const LOT_LINEAGE_LABELS: Record<string, string> = {
  direct: "Direkter Zugang", carried: "Ursprungslot fortgeführt", unresolved: "Herkunftskette offen"
};
export const LOT_CLASS_LABELS: Record<string, string> = {
  potential_business_inventory: "Potenziell betrieblich", origin_classification_review: "Ursprung einordnen",
  separate_income_review: "Einkunftsart prüfen", non_reward_origin: "Kein direkter Reward-Ursprung",
  missing_origin: "Ursprung nicht belegt"
};

export function LotOriginDetails({ row, onClose }: { row: Record<string, unknown>; onClose: () => void }) {
  const text = (value: unknown) => value == null || value === "" ? "Nicht verfügbar" : String(value);
  const path = Array.isArray(row.sample_lot_path) ? row.sample_lot_path.filter((value): value is string => typeof value === "string") : [];
  return <DetailPanel title="Ursprung der Verwertung" onClose={onClose}>
    {Number(row.tax_lines_count) > 1 && <p>{text(row.tax_lines_count)} zusammengefasste Verwertungszeilen. Die Ereignis-IDs und die Lot-Kette zeigen ein Beispiel; Beträge sind Gruppensummen.</p>}
    <dl className="lotOriginDetails">
      <dt>Asset</dt><dd>{text(row.asset)}</dd>
      <dt>Einordnung</dt><dd>{LOT_CLASS_LABELS[String(row.classification)] ?? "Noch nicht eingeordnet"}</dd>
      <dt>Herkunftskette</dt><dd>{LOT_LINEAGE_LABELS[String(row.lineage_status)] ?? "Noch nicht verfolgt"}</dd>
      <dt>Ursprüngliche Quelle</dt><dd>{text(row.origin_source)}</dd>
      <dt>Ursprünglicher Zugangstyp</dt><dd>{text(row.origin_event_type)}</dd>
      <dt>Konto / Wallet</dt><dd>{text(row.origin_account)}</dd>
      <dt>Ursprungsereignis</dt><dd><code>{text(row.sample_origin_event_id)}</code></dd>
      <dt>Direkt gespeichertes Zwischenereignis</dt><dd><code>{text(row.sample_direct_event_id)}</code></dd>
      <dt>Veräußerungsereignis</dt><dd><code>{text(row.sample_disposal_event_id)}</code></dd>
      <dt>Anschaffungskosten</dt><dd>{money(row.acquisition_cost_eur)}</dd>
      <dt>Veräußerungserlös</dt><dd>{money(row.disposal_proceeds_eur)}</dd>
      <dt>Gewinn / Verlust</dt><dd>{money(row.gain_loss_eur)}</dd>
    </dl>
    <p>{text(row.reason)}</p>
    {path.length > 0 && <section aria-label="Verknüpfte Lot-IDs"><h3>Lot-Verknüpfung</h3><ol>{path.map((id, index) => <li key={`${index}:${id}`}><code>{id}</code></li>)}</ol></section>}
    {row.lineage_reason != null && <details><summary>Technischer Prüfgrund</summary><code>{text(row.lineage_reason)}</code></details>}
  </DetailPanel>;
}
