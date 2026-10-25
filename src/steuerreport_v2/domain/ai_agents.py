"""Portable role profiles and versioned application knowledge, without operator data."""
import json

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.ai_agents import AiAgentProfile, AiAgentsStatus, AiAgentsWrite
from steuerreport_v2.db.ai_corrections import FIELDS, digest, json_text


KEY = "ai.agents.config"
DEFAULTS = (
    ("coordinator", "Koordinator", "Strukturiere die Aufgabe, trenne bestaetigte Angaben, Hypothesen und fehlende Belege. Benenne zustaendige Fachrollen und naechste Pruefschritte. Delegation ist eine Empfehlung, kein automatisch gestarteter weiterer Modellaufruf."),
    ("import_sources", "Import- und Quellenpruefung", "Pruefe Feldzuordnung, Richtung, Einheiten, Zeitzone und Quellenherkunft. Unterscheide Rohbeleg und normalisiertes Ereignis. Ein Mapping-Vorschlag aendert keinen Parser. Fehlende Pflichtwerte nicht erfinden. Dateihashes sind Herkunftsnachweise, keine inhaltliche Freigabe."),
    ("crypto_forensics", "Krypto-Forensik", "Pruefe ausgewaehlte Ereignisse auf moegliche Dubletten, Transferpaare und widersprechende Quellen. Betrachte Ereignis-/Transaktionskennung, Zeitpunkt, Asset, Menge, Gegenrichtung und Gebuehren gemeinsam. Gleiche Betraege allein beweisen keine Dublette. Keine automatische Loeschung; keine behauptete Onchain-Pruefung ohne vorliegenden Beleg."),
    ("wallet_fifo", "Wallet- und FIFO-Pruefung", "Pruefe Anschaffungs-/Abgangsreihenfolge, Account-/Wallet-Zuordnung, Lot-Herkunft und Luecken anhand des bereitgestellten Ausschnitts. Keine fiktiven Kaeufe oder Nullkosten annehmen. Das Sprachmodell rechnet keinen verlaesslichen FIFO; Auswirkungen muss die bestehende Anwendungspipeline berechnen."),
    ("tax_rewards", "Steuer-, Mining- und Reward-Pruefung", "Unterscheide Trading, Mining, Rewards, Staking, Derivate und reine Transfers anhand der bereitgestellten Belege. Privat/Betrieblich ist keine automatische Token-Eigenschaft. Keine abschliessende steuerliche Einordnung oder Korrekturpflicht behaupten. Rechtsstaende und fehlende Tatsachen ausdruecklich offenlassen; Quellen nur nennen, wenn sie vorliegen."),
    ("valuation", "Preis- und Stichtagspruefung", "Pruefe Preis-/FX-Einheit, Zeitpunkt, Asset, Quelle und Genauigkeit. Tokenmengen sind keine EUR-Werte. Keinen aktuellen Preis still fuer ein frueheres Jahr verwenden. EUR-Einzahlung, Auszahlung, Handelsvolumen, Gewinn/Verlust und interne Transfers getrennt behandeln. Preise nur mit konkretem Beleg vorschlagen."),
    ("documentation", "Dokumentation und Audit", "Formuliere neutrale Zusammenfassungen und Pruefvermerke mit den bereitgestellten Belegkennungen. Trenne Fakten, Eigenangaben, Hypothesen und offene Punkte. Keine erfundenen Nachweise, keine Rechtsfreigabe und keine Aussage, ein Hash garantiere Wahrheit oder gerichtliche Verwertbarkeit."),
)


class AiAgentError(ValueError):
    pass


def knowledge():
    return {
        "version": "steuerreport-agent-knowledge-v1", "software_version": __version__,
        "data_model": {"raw_import_batches": "Dateiname und Datei-SHA256", "raw_objects": "Unveraenderte Importzeilen mit Zeilennummer und Payload",
                       "canonical_events": "Normalisierte Ereignisse mit stabiler ID und Rohzeilenbezug",
                       "price_ledger": "EUR-Preise mit Zeitpunkt, Quelle und Konfidenz",
                       "derived": "Bestaende, Flows, FIFO-Lots/Steuerzeilen und Derivate sind berechnete Ergebnisse, keine frei editierbaren Originalbelege"},
        "tools": {"data_context": "Anwenderfilter waehlen Ereignisse oder nicht abgeleitete Preise aus; nur ausdruecklich ausgewaehlte Zeilen werden gesendet",
                  "propose_corrections": {kind: sorted(fields) for kind, fields in FIELDS.items()},
                  "preview": "Bestehende deterministische Pipeline auf privater Datenbankkopie; exakter Kosten-/Erloes-/Gewinnabgleich",
                  "apply": "Nur nach menschlicher Freigabe; atomarer Datenbank- und Ledgerwechsel, Versionsschutz, Audit und getrennt freizugebende Ruecknahme"},
        "limits": ["Maximal 25 ausgewaehlte Zielzeilen und 32000 Zeichen Anfrage", "Kein automatischer Chatverlauf oder beliebiger Datenbankzugriff",
                   "Keine Websuche, Onchain-/Connector-Abfrage, Datei-/Bildanalyse, SQL, Shell oder Softwareaenderung durch das Modell",
                   "Keine eigenen Tools oder neuen Befugnisse durch Agentenrollen; Freigaben gelten fuer alle Rollen",
                   "Keine automatische Anonymisierung oder steuerliche Freigabe", "Handelsvolumen ist weder Einkommen noch Auszahlung"],
        "workflow": ["Kontext auswaehlen und pruefen", "Bei Cloud explizit freigeben", "Beleggestuetzten Vorschlag validieren",
                     "Einzeln auswaehlen oder bearbeiten", "Vorschau berechnen", "Menschlich pruefen und freigeben", "Audit herunterladen"],
    }


class AiAgentService:
    def __init__(self, store):
        self.store = store

    def status(self):
        rows = {row.key: row.value_json for row in self.store.list_admin_settings()}
        try:
            profiles = [AiAgentProfile.model_validate(item) for item in json.loads(rows[KEY])] if KEY in rows else [AiAgentProfile(agent_id=key, name=name, instructions=instructions) for key, name, instructions in DEFAULTS]
            self._check(profiles)
        except (ValueError, TypeError, KeyError):
            raise AiAgentError("ai_agents_config_invalid") from None
        app_knowledge = knowledge()
        return AiAgentsStatus(profiles=profiles, knowledge=app_knowledge, knowledge_sha256=digest(app_knowledge),
                              revision=digest({"profiles": [item.model_dump() for item in profiles], "knowledge": app_knowledge}))

    @staticmethod
    def _check(profiles):
        if {item.agent_id for item in profiles} != {item[0] for item in DEFAULTS} or len(profiles) != 7 or not any(item.enabled for item in profiles):
            raise AiAgentError("ai_agents_config_invalid")

    def save(self, payload: AiAgentsWrite):
        self._check(payload.profiles)
        with self.store.exclusive_access():
            if payload.revision != self.status().revision:
                raise AiAgentError("ai_agent_revision_conflict")
            self.store.write_admin_settings_batch([AdminSettingWrite(key=KEY, value_json=json_text([item.model_dump() for item in payload.profiles]))], [])
        return self.status()

    def bundle(self, agent_id, *, expected_revision=None, provider="local", default_model=""):
        status = self.status()
        if expected_revision is not None and expected_revision != status.revision:
            raise AiAgentError("ai_agent_revision_conflict")
        profile = next((item for item in status.profiles if item.agent_id == agent_id), None)
        if profile is None or not profile.enabled:
            raise AiAgentError("ai_agent_unavailable")
        override = profile.models.model_dump()[provider]
        snapshot = {"agent_id": profile.agent_id, "name": profile.name, "instructions": profile.instructions,
                    "revision": status.revision, "knowledge_sha256": status.knowledge_sha256, "knowledge": status.knowledge,
                    "requested_model": override or default_model, "model_override": bool(override)}
        prompt = "\nFachrolle und Anwendungswissen (keine zusaetzlichen Befugnisse):\n" + json_text(snapshot)
        return snapshot, prompt, override or None
