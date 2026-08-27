from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from steuerreport_v2.contracts.connectors import (
    ConnectorCatalogEntry,
    ConnectorCatalogReport,
    ConnectorConnection,
    ConnectorSecurityStatus,
    WalletOwnershipChallenge,
    WalletOwnershipChallengeRequest,
    WalletOwnershipVerificationResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secret_vault import secret_vault_status
from steuerreport_v2.domain.secrets import secret_metadata
from steuerreport_v2.domain.source_registry import SourceRegistryService


BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {character: index for index, character in enumerate(BASE58_ALPHABET)}


def decode_base58(value: str) -> bytes:
    normalized = value.strip()
    if not normalized:
        raise ValueError("base58_value_required")
    number = 0
    for character in normalized:
        if character not in BASE58_INDEX:
            raise ValueError("invalid_base58_character")
        number = number * 58 + BASE58_INDEX[character]
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(normalized) - len(normalized.lstrip("1"))
    return b"\x00" * leading_zeroes + decoded


class ConnectorAccessPolicy:
    TOKEN_FILE_ENV = "STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE"
    PUBLIC_BASE_URL_ENV = "STEUERREPORT_V2_PUBLIC_BASE_URL"

    def setup_token(self) -> str:
        configured = os.environ.get(self.TOKEN_FILE_ENV, "").strip()
        if not configured:
            return ""
        path = Path(configured).expanduser()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def authorize(self, authorization: str | None) -> None:
        expected = self.setup_token()
        if not expected:
            raise RuntimeError("connector_setup_auth_not_configured")
        scheme, separator, supplied = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not supplied:
            raise PermissionError("connector_setup_bearer_required")
        if not hmac.compare_digest(supplied.strip(), expected):
            raise PermissionError("connector_setup_bearer_invalid")

    def security_status(self, store: DuckDbStore) -> ConnectorSecurityStatus:
        vault = secret_vault_status(store)
        auth_mode = "setup_token" if self.setup_token() else "disabled"
        public_base_url = os.environ.get(self.PUBLIC_BASE_URL_ENV, "").strip() or None
        blockers: list[str] = []
        if auth_mode == "disabled":
            blockers.append("connector_setup_auth_missing")
        if not vault.configured:
            blockers.append("secret_vault_not_configured")
        elif vault.plaintext_secrets:
            blockers.append("plaintext_secrets_require_migration")
        if not public_base_url or not public_base_url.lower().startswith("https://"):
            blockers.append("https_public_base_url_missing")
        blockers.append("oidc_not_implemented")
        return ConnectorSecurityStatus(
            auth_mode=auth_mode,
            connector_writes_enabled=auth_mode != "disabled",
            internet_ready=False,
            public_base_url=public_base_url,
            vault=vault,
            blockers=blockers,
        )


class ConnectorService:
    CHALLENGE_TTL = timedelta(minutes=5)

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def catalog(self) -> ConnectorCatalogReport:
        security = ConnectorAccessPolicy().security_status(self.store)
        connections = self.connections()
        registered_wallets = self._registered_wallet_addresses()
        connection_by_connector = {item.connector_id: item for item in connections}
        entries = [
            self._catalog_entry(spec, connection_by_connector, registered_wallets)
            for spec in self._specs()
        ]
        return ConnectorCatalogReport(
            generated_at=datetime.now(timezone.utc),
            security=security,
            connectors=entries,
            connections=connections,
            methodology=(
                "Read-only Connector-Katalog. Konfiguration oder Wallet-Signatur aktiviert keine "
                "Steuerquelle automatisch; neue Wallets bleiben bis zur Quellenregistry-Pruefung "
                "ownership_verified_pending_registry."
            ),
        )

    def connections(self) -> list[ConnectorConnection]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select connection_id, connector_id, external_identifier,
                       display_label, source_id, status, created_at, verified_at,
                       revoked_at, last_sync_at
                from connector_connections
                order by created_at, connection_id
                """
            ).fetchall()
        return [self._connection_from_row(row) for row in rows]

    def create_wallet_challenge(
        self,
        payload: WalletOwnershipChallengeRequest,
        *,
        now: datetime | None = None,
    ) -> WalletOwnershipChallenge:
        issued_at = self._utc(now or datetime.now(timezone.utc))
        expires_at = issued_at + self.CHALLENGE_TTL
        wallet_address = payload.wallet_address.strip()
        self._validate_solana_address(wallet_address)
        display_label = (payload.display_label or "Solana Wallet").strip()[:120]
        challenge_id = str(uuid4())
        nonce = secrets.token_urlsafe(24)
        message = "\n".join(
            (
                "Steuerreport V2 Wallet-Eigentumsnachweis",
                "Domain: steuerreport-v2.local",
                f"Wallet: {wallet_address}",
                f"Provider: {payload.wallet_provider}",
                f"Challenge: {challenge_id}",
                f"Nonce: {nonce}",
                f"Issued-At: {issued_at.isoformat()}",
                f"Expires-At: {expires_at.isoformat()}",
                "Purpose: read-only tax source ownership verification",
                "No transaction will be signed.",
            )
        )
        with self.store.connect() as con:
            con.execute(
                """
                insert into wallet_ownership_challenges (
                    challenge_id, connector_id, wallet_address, wallet_provider,
                    display_label, message, nonce_hash, issued_at, expires_at,
                    status, verified_at, signature
                ) values (?, 'solana-wallet', ?, ?, ?, ?, ?, ?, ?, 'pending', null, null)
                """,
                [
                    challenge_id,
                    wallet_address,
                    payload.wallet_provider,
                    display_label,
                    message,
                    hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
                    issued_at,
                    expires_at,
                ],
            )
        return WalletOwnershipChallenge(
            challenge_id=challenge_id,
            wallet_address=wallet_address,
            wallet_provider=payload.wallet_provider,
            message=message,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def verify_wallet_challenge(
        self,
        challenge_id: str,
        signature: str,
        *,
        now: datetime | None = None,
    ) -> WalletOwnershipVerificationResult:
        checked_at = self._utc(now or datetime.now(timezone.utc))
        with self.store.connect() as con:
            row = con.execute(
                """
                select challenge_id, connector_id, wallet_address, wallet_provider,
                       display_label, message, issued_at, expires_at, status
                from wallet_ownership_challenges
                where challenge_id = ?
                """,
                [challenge_id.strip()],
            ).fetchone()
        if row is None:
            raise ValueError("wallet_challenge_not_found")
        if str(row[8]) != "pending":
            raise ValueError("wallet_challenge_not_pending")
        expires_at = self._utc(row[7])
        if checked_at > expires_at:
            self._update_challenge_status(str(row[0]), "expired", checked_at)
            raise ValueError("wallet_challenge_expired")

        wallet_address = str(row[2])
        message = str(row[5])
        try:
            public_key = decode_base58(wallet_address)
            signature_bytes = decode_base58(signature)
            if len(public_key) != 32 or len(signature_bytes) != 64:
                raise InvalidSignature
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                signature_bytes,
                message.encode("utf-8"),
            )
        except (InvalidSignature, ValueError) as exc:
            self._update_challenge_status(str(row[0]), "failed", checked_at)
            raise ValueError("wallet_signature_invalid") from exc

        source_id = self._registered_wallet_source_id(wallet_address)
        status = "registered" if source_id else "ownership_verified_pending_registry"
        connection = self._upsert_wallet_connection(
            wallet_address=wallet_address,
            wallet_provider=str(row[3]),
            display_label=str(row[4]),
            source_id=source_id,
            status=status,
            verified_at=checked_at,
        )
        with self.store.connect() as con:
            con.execute(
                """
                update wallet_ownership_challenges
                set status = 'verified', verified_at = ?, signature = ?
                where challenge_id = ? and status = 'pending'
                """,
                [checked_at, signature.strip(), str(row[0])],
            )
        return WalletOwnershipVerificationResult(
            status=status,
            connection=connection,
            registry_match=source_id is not None,
            message=(
                "Wallet-Eigentum kryptografisch verifiziert; bestehender Registry-Eintrag erkannt."
                if source_id
                else "Wallet-Eigentum kryptografisch verifiziert; steuerliche Aktivierung wartet auf Quellenregistry-Review."
            ),
        )

    def _upsert_wallet_connection(
        self,
        *,
        wallet_address: str,
        wallet_provider: str,
        display_label: str,
        source_id: str | None,
        status: str,
        verified_at: datetime,
    ) -> ConnectorConnection:
        with self.store.connect() as con:
            existing = con.execute(
                """
                select connection_id, created_at
                from connector_connections
                where connector_id = 'solana-wallet' and external_identifier = ?
                """,
                [wallet_address],
            ).fetchone()
            connection_id = str(existing[0]) if existing else str(uuid4())
            created_at = self._utc(existing[1]) if existing else verified_at
            metadata_json = json.dumps(
                {"wallet_provider": wallet_provider},
                separators=(",", ":"),
            )
            if existing:
                con.execute(
                    """
                    update connector_connections
                    set display_label = ?, source_id = ?, status = ?,
                        metadata_json = ?, verified_at = ?, revoked_at = null
                    where connection_id = ?
                    """,
                    [
                        display_label,
                        source_id,
                        status,
                        metadata_json,
                        verified_at,
                        connection_id,
                    ],
                )
            else:
                con.execute(
                    """
                    insert into connector_connections (
                        connection_id, connector_id, external_identifier, display_label,
                        source_id, status, metadata_json, created_at, verified_at,
                        revoked_at, last_sync_at
                    ) values (?, 'solana-wallet', ?, ?, ?, ?, ?, ?, ?, null, null)
                    """,
                    [
                        connection_id,
                        wallet_address,
                        display_label,
                        source_id,
                        status,
                        metadata_json,
                        created_at,
                        verified_at,
                    ],
                )
        return ConnectorConnection(
            connection_id=connection_id,
            connector_id="solana-wallet",
            external_identifier=wallet_address,
            display_label=display_label,
            source_id=source_id,
            status=status,
            created_at=created_at,
            verified_at=verified_at,
            tax_activation="registry_active" if source_id else "review_required",
        )

    def _catalog_entry(
        self,
        spec: dict[str, object],
        connection_by_connector: dict[str, ConnectorConnection],
        registered_wallets: set[str],
    ) -> ConnectorCatalogEntry:
        connector_id = str(spec["connector_id"])
        configured = False
        connection_status = "not_configured"
        last_sync_at = None
        if connector_id == "solana-wallet":
            configured = bool(registered_wallets or connection_by_connector.get(connector_id))
            if registered_wallets:
                connection_status = "registered"
            elif connector_id in connection_by_connector:
                connection_status = connection_by_connector[connector_id].status
        else:
            secret_keys = list(spec.get("secret_keys", []))
            if secret_keys:
                metadata = secret_metadata(self.store, [str(key) for key in secret_keys])
                configured = metadata["keys_present"] == metadata["keys_required"]
                connection_status = "configured" if configured else "not_configured"
            last_sync_at = self._last_sync_at(connector_id)
        return ConnectorCatalogEntry(
            connector_id=connector_id,
            label=str(spec["label"]),
            category=str(spec["category"]),
            auth_method=str(spec["auth_method"]),
            availability=str(spec["availability"]),
            connection_status=connection_status,
            mobile_platforms=list(spec.get("mobile_platforms", [])),
            capabilities=list(spec.get("capabilities", [])),
            required_fields=list(spec.get("required_fields", [])),
            safety_notes=list(spec.get("safety_notes", [])),
            limitation=str(spec["limitation"]) if spec.get("limitation") else None,
            last_sync_at=last_sync_at,
        )

    def _last_sync_at(self, connector_id: str) -> datetime | None:
        live_connector = {"jupiter": "jup_wallet"}.get(connector_id, connector_id)
        with self.store.connect() as con:
            row = con.execute(
                """
                select max(fetched_at)
                from portfolio_live_connector_runs
                where connector_id = ?
                """,
                [live_connector],
            ).fetchone()
        return self._utc(row[0]) if row and row[0] is not None else None

    def _registered_wallet_addresses(self) -> set[str]:
        addresses: set[str] = set()
        for entry in SourceRegistryService(self.store).config().entries:
            if entry.source_type not in {"wallet", "legacy_wallet"}:
                continue
            if entry.ownership not in {"owned", "owned_historical_route"}:
                continue
            addresses.update(
                identifier.value
                for identifier in entry.identifiers
                if identifier.kind in {"account", "wallet", "address"}
                and "..." not in identifier.value
            )
        return addresses

    def _registered_wallet_source_id(self, address: str) -> str | None:
        for entry in SourceRegistryService(self.store).config().entries:
            if entry.ownership not in {"owned", "owned_historical_route"}:
                continue
            if any(
                identifier.value == address
                and identifier.kind in {"account", "wallet", "address"}
                for identifier in entry.identifiers
            ):
                return entry.source_id
        return None

    def _update_challenge_status(
        self,
        challenge_id: str,
        status: str,
        checked_at: datetime,
    ) -> None:
        with self.store.connect() as con:
            con.execute(
                """
                update wallet_ownership_challenges
                set status = ?, verified_at = ?
                where challenge_id = ? and status = 'pending'
                """,
                [status, checked_at, challenge_id],
            )

    @staticmethod
    def _connection_from_row(row: tuple[object, ...]) -> ConnectorConnection:
        status = str(row[5])
        return ConnectorConnection(
            connection_id=str(row[0]),
            connector_id=str(row[1]),
            external_identifier=str(row[2]),
            display_label=str(row[3]),
            source_id=str(row[4]) if row[4] is not None else None,
            status=status,
            created_at=ConnectorService._utc(row[6]),
            verified_at=ConnectorService._utc(row[7]) if row[7] is not None else None,
            revoked_at=ConnectorService._utc(row[8]) if row[8] is not None else None,
            last_sync_at=ConnectorService._utc(row[9]) if row[9] is not None else None,
            tax_activation="registry_active" if status == "registered" else "review_required",
        )

    @staticmethod
    def _validate_solana_address(address: str) -> None:
        try:
            decoded = decode_base58(address)
        except ValueError as exc:
            raise ValueError("invalid_solana_wallet_address") from exc
        if len(decoded) != 32:
            raise ValueError("invalid_solana_wallet_address")

    @staticmethod
    def _utc(value: object) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError("datetime_required")
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _specs() -> tuple[dict[str, object], ...]:
        read_only = ["Nur Leserechte verwenden.", "Keine Trade-, Transfer- oder Withdraw-Rechte."]
        return (
            {
                "connector_id": "solana-wallet",
                "label": "Solana Wallet (Phantom, Jupiter, Solflare)",
                "category": "wallet",
                "auth_method": "wallet_signature",
                "availability": "available",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["ownership_proof", "public_history", "live_balance"],
                "required_fields": ["wallet_address", "signature"],
                "safety_notes": ["Niemals Seed Phrase oder Private Key eingeben."],
                "limitation": "Die Signatur beweist Eigentum, aktiviert aber keine Steuerquelle ohne Registry-Review.",
            },
            {
                "connector_id": "binance",
                "label": "Binance",
                "category": "exchange",
                "auth_method": "api_key",
                "availability": "server_admin_only",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["balances", "spot_history", "earn", "deposits", "withdrawals"],
                "required_fields": ["api_key", "api_secret"],
                "secret_keys": ["secret.cex.binance.api_key", "secret.cex.binance.api_secret"],
                "safety_notes": read_only,
                "limitation": "Historische Produktgrenzen erfordern weiterhin Exporte.",
            },
            {
                "connector_id": "bitget",
                "label": "Bitget",
                "category": "exchange",
                "auth_method": "api_key",
                "availability": "server_admin_only",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["balances", "spot_history", "deposits", "withdrawals"],
                "required_fields": ["api_key", "api_secret", "passphrase"],
                "secret_keys": [
                    "secret.cex.bitget.api_key",
                    "secret.cex.bitget.api_secret",
                    "secret.cex.bitget.passphrase",
                ],
                "safety_notes": read_only,
            },
            {
                "connector_id": "pionex",
                "label": "Pionex",
                "category": "exchange",
                "auth_method": "api_key",
                "availability": "server_admin_only",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["trading_balance", "spot_history"],
                "required_fields": ["api_key", "api_secret"],
                "secret_keys": ["secret.cex.pionex.api_key", "secret.cex.pionex.api_secret"],
                "safety_notes": read_only,
                "limitation": "Trading-Balance schliesst Bot- und Earn-Produkte nicht vollstaendig ein.",
            },
            {
                "connector_id": "coinbase",
                "label": "Coinbase",
                "category": "exchange",
                "auth_method": "api_key",
                "availability": "server_admin_only",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["balances", "account_history"],
                "required_fields": ["api_key", "api_secret"],
                "secret_keys": ["secret.cex.coinbase.api_key", "secret.cex.coinbase.api_secret"],
                "safety_notes": read_only,
            },
            {
                "connector_id": "jupiter",
                "label": "Jupiter Daten-API",
                "category": "data_provider",
                "auth_method": "server_api_key",
                "availability": "server_admin_only",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["token_metadata", "token_risk", "portfolio_enrichment"],
                "required_fields": ["api_key"],
                "secret_keys": ["secret.jupiter.api_key"],
                "safety_notes": ["API-Key bleibt ausschliesslich auf dem Server."],
                "limitation": "Ergaenzungsquelle; kein Eigentums- oder Steuerbeleg allein.",
            },
            {
                "connector_id": "solscan",
                "label": "Solscan Beleg-API",
                "category": "data_provider",
                "auth_method": "server_api_key",
                "availability": "server_admin_only",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["decoded_transactions", "account_history", "explorer_evidence"],
                "required_fields": ["api_key"],
                "secret_keys": ["secret.solscan.api_key"],
                "safety_notes": ["API-Key bleibt ausschliesslich auf dem Server."],
                "limitation": "Oeffentliche Blockchain-Daten; kein Benutzerkonto-Connector.",
            },
            {
                "connector_id": "alchemy",
                "label": "Alchemy Solana RPC",
                "category": "data_provider",
                "auth_method": "server_api_key",
                "availability": "server_admin_only",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": [
                    "transaction_history",
                    "decoded_transactions",
                    "balance_evidence",
                ],
                "required_fields": ["api_key"],
                "secret_keys": ["secret.alchemy.api_key"],
                "safety_notes": ["API-Key bleibt ausschliesslich auf dem Server."],
                "limitation": "RPC-Belegquelle; keine automatische steuerliche Klassifizierung.",
            },
            {
                "connector_id": "bank-psd2",
                "label": "Bankkonto via PSD2",
                "category": "bank",
                "auth_method": "oauth_redirect",
                "availability": "planned",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["balances", "transactions", "consent_refresh"],
                "required_fields": ["institution", "consent"],
                "safety_notes": ["Keine Onlinebanking-Zugangsdaten in Steuerreport eingeben."],
                "limitation": "Historische Reichweite und Consent-Dauer sind bankabhaengig.",
            },
            {
                "connector_id": "moonpay",
                "label": "MoonPay",
                "category": "payment_provider",
                "auth_method": "oauth_partner",
                "availability": "partner_access_required",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["transactions", "fees", "wallet_destination", "csv_import"],
                "required_fields": ["partner_connection_or_csv"],
                "safety_notes": ["Kurzlebige Client-Tokens nicht dauerhaft speichern."],
                "limitation": "Direkter Connect-Flow benoetigt MoonPay-Partnerzugang; CSV bleibt Fallback.",
            },
            {
                "connector_id": "paypal",
                "label": "PayPal",
                "category": "payment_provider",
                "auth_method": "oauth_partner",
                "availability": "partner_access_required",
                "mobile_platforms": ["android", "ios", "web"],
                "capabilities": ["transactions", "fees", "csv_import"],
                "required_fields": ["partner_connection_or_csv"],
                "safety_notes": ["PayPal-Passwort niemals in Steuerreport eingeben."],
                "limitation": "Drittzugriff erfordert Partnerzugang; API-Historie ist zeitlich begrenzt.",
            },
            {
                "connector_id": "document-scan",
                "label": "Dokumente und Belege scannen",
                "category": "document",
                "auth_method": "device_capture",
                "availability": "planned",
                "mobile_platforms": ["android", "ios"],
                "capabilities": ["pdf", "jpeg", "ocr", "sha256_evidence"],
                "required_fields": ["document"],
                "safety_notes": ["OCR-Ergebnisse muessen vor Steueruebernahme bestaetigt werden."],
            },
            {
                "connector_id": "apple-pay",
                "label": "Apple Pay Zahlungsabgleich",
                "category": "payment_reference",
                "auth_method": "bank_reconciliation",
                "availability": "evidence_only",
                "mobile_platforms": ["ios"],
                "capabilities": ["bank_match", "merchant_match", "payment_reference"],
                "required_fields": ["bank_transaction", "merchant_receipt"],
                "safety_notes": ["Abgleich erfolgt ueber Bank und Zahlungsanbieter."],
                "limitation": "Kein allgemeiner deutscher Apple-Pay-Historienconnector verfuegbar.",
            },
        )
