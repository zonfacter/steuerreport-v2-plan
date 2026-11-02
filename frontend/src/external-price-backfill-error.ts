export function externalPriceBackfillError(_cause: unknown): string {
  return "Externer Preisbackfill fehlgeschlagen oder Antwort ausgeblieben. "
    + "Ob Preise gespeichert wurden, ist unbekannt; auch Pipelinefolgen koennen unbekannt oder teilweise sein. "
    + "Nicht erneut starten, bevor Preisbestand und abgeleitete Daten geprueft wurden.";
}
