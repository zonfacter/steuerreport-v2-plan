from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import secrets
from uuid import uuid4

from nacl.bindings import crypto_core_ed25519_is_valid_point
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from steuerreport_v2.contracts.connectors import (
    ConnectorCatalogEntry,
    ConnectorCatalogReport,
    ConnectorConnection,
    ConnectorSecurityStatus,
    MobileConnectorPairing,
    MobileConnectorPairingRequest,
    MobileConnectorScope,
    MobileConnectorSession,
    MobileConnectorSessionExchangeRequest,
    MobileConnectorSessionToken,
    WalletOwnershipChallenge,
    WalletOwnershipChallengeRequest,
    WalletOwnershipVerificationResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connector_bootstrap import read_token
from steuerreport_v2.domain.mobile_documents import MobileDocumentInboxService
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
        return read_token()

    def authorize(self, authorization: str | None) -> None:
        expected = self.setup_token()
        if not expected:
            raise RuntimeError("connector_setup_auth_not_configured")
        supplied = self._bearer_token(authorization)
        if not hmac.compare_digest(supplied.strip(), expected):
            raise PermissionError("connector_setup_bearer_invalid")

    def authorize_scoped(
        self,
        store: DuckDbStore,
        authorization: str | None,
        required_scope: MobileConnectorScope,
    ) -> MobileConnectorSession | None:
        expected = self.setup_token()
        if not authorization and not expected:
            raise RuntimeError("connector_setup_auth_not_configured")
        supplied = self._bearer_token(authorization)
        if expected and hmac.compare_digest(supplied, expected):
            return None
        if supplied.startswith("srv2m_"):
            return ConnectorService(store).authorize_mobile_session(
                supplied,
                required_scope=required_scope,
            )
        raise PermissionError("connector_setup_bearer_invalid")

    def security_status(self, store: DuckDbStore) -> ConnectorSecurityStatus:
        vault = secret_vault_status(store)
        auth_mode = "setup_token" if self.setup_token() else "disabled"
        active_mobile_sessions = ConnectorService(store).active_mobile_session_count()
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
            connector_writes_enabled=(
                auth_mode != "disabled" or active_mobile_sessions > 0
            ),
            internet_ready=False,
            public_base_url=public_base_url,
            mobile_pairing_enabled=auth_mode == "setup_token",
            active_mobile_sessions=active_mobile_sessions,
            vault=vault,
            blockers=blockers,
        )

    @staticmethod
    def _bearer_token(authorization: str | None) -> str:
        scheme, separator, supplied = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not supplied.strip():
            raise PermissionError("connector_setup_bearer_required")
        return supplied.strip()


class ConnectorService:
    CHALLENGE_TTL = timedelta(minutes=5)
    MOBILE_PAIRING_TTL = timedelta(minutes=10)
    MOBILE_PAIRING_MAX_ATTEMPTS = 5
    MOBILE_PAIRING_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    MOBILE_SCOPES: tuple[MobileConnectorScope, ...] = (
        "connector:read",
        "wallet:verify",
        "document:upload",
    )

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def catalog(self) -> ConnectorCatalogReport:
        security = ConnectorAccessPolicy().security_status(self.store)
        mobile_document_inbox = MobileDocumentInboxService(self.store).summary()
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
            mobile_document_inbox=mobile_document_inbox,
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

    def create_mobile_pairing(
        self,
        payload: MobileConnectorPairingRequest,
        *,
        now: datetime | None = None,
    ) -> MobileConnectorPairing:
        issued_at = self._utc(now or datetime.now(timezone.utc))
        expires_at = issued_at + self.MOBILE_PAIRING_TTL
        pairing_id = str(uuid4())
        device_name = " ".join(payload.device_name.split())
        if not device_name:
            raise ValueError("mobile_device_name_required")
        scopes = self._normalize_mobile_scopes(payload.scopes)
        compact_code = "".join(
            secrets.choice(self.MOBILE_PAIRING_CODE_ALPHABET) for _ in range(20)
        )
        pairing_code = "-".join(
            compact_code[index : index + 5] for index in range(0, 20, 5)
        )
        with self.store.connect() as con:
            con.execute(
                """
                insert into mobile_connector_pairings (
                    pairing_id, code_hash, device_name, platform, scopes_json,
                    session_ttl_hours, issued_at, expires_at, status,
                    attempt_count, exchanged_at, session_id
                ) values (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, null, null)
                """,
                [
                    pairing_id,
                    self._secret_hash(compact_code),
                    device_name[:120],
                    payload.platform,
                    json.dumps(scopes, separators=(",", ":")),
                    payload.session_ttl_hours,
                    issued_at,
                    expires_at,
                ],
            )
        return MobileConnectorPairing(
            pairing_id=pairing_id,
            pairing_code=pairing_code,
            device_name=device_name[:120],
            platform=payload.platform,
            scopes=scopes,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def exchange_mobile_pairing(
        self,
        payload: MobileConnectorSessionExchangeRequest,
        *,
        now: datetime | None = None,
    ) -> MobileConnectorSessionToken:
        checked_at = self._utc(now or datetime.now(timezone.utc))
        compact_code = self._normalize_pairing_code(payload.pairing_code)
        with self.store.connect() as con:
            row = con.execute(
                """
                select pairing_id, code_hash, device_name, platform, scopes_json,
                       session_ttl_hours, expires_at, status, attempt_count
                from mobile_connector_pairings
                where pairing_id = ?
                """,
                [payload.pairing_id.strip()],
            ).fetchone()
            if row is None or str(row[7]) != "pending":
                raise ValueError("mobile_pairing_invalid")
            if checked_at > self._utc(row[6]):
                con.execute(
                    """
                    update mobile_connector_pairings
                    set status = 'expired'
                    where pairing_id = ? and status = 'pending'
                    """,
                    [str(row[0])],
                )
                raise ValueError("mobile_pairing_expired")
            if not hmac.compare_digest(
                self._secret_hash(compact_code),
                str(row[1]),
            ):
                attempt_count = int(row[8]) + 1
                status = (
                    "failed"
                    if attempt_count >= self.MOBILE_PAIRING_MAX_ATTEMPTS
                    else "pending"
                )
                con.execute(
                    """
                    update mobile_connector_pairings
                    set attempt_count = ?, status = ?
                    where pairing_id = ? and status = 'pending'
                    """,
                    [attempt_count, status, str(row[0])],
                )
                raise ValueError("mobile_pairing_invalid")

            scopes = self._normalize_mobile_scopes(json.loads(str(row[4])))
            session_id = str(uuid4())
            access_token = f"srv2m_{secrets.token_urlsafe(32)}"
            expires_at = checked_at + timedelta(hours=int(row[5]))
            con.execute(
                """
                insert into mobile_connector_sessions (
                    session_id, token_hash, device_name, platform, scopes_json,
                    created_at, expires_at, last_used_at, revoked_at
                ) values (?, ?, ?, ?, ?, ?, ?, null, null)
                """,
                [
                    session_id,
                    self._secret_hash(access_token),
                    str(row[2]),
                    str(row[3]),
                    json.dumps(scopes, separators=(",", ":")),
                    checked_at,
                    expires_at,
                ],
            )
            con.execute(
                """
                update mobile_connector_pairings
                set status = 'exchanged', exchanged_at = ?, session_id = ?
                where pairing_id = ? and status = 'pending'
                """,
                [checked_at, session_id, str(row[0])],
            )
        session = MobileConnectorSession(
            session_id=session_id,
            device_name=str(row[2]),
            platform=str(row[3]),
            scopes=scopes,
            created_at=checked_at,
            expires_at=expires_at,
            status="active",
        )
        return MobileConnectorSessionToken(
            access_token=access_token,
            session=session,
        )

    def mobile_sessions(
        self,
        *,
        now: datetime | None = None,
    ) -> list[MobileConnectorSession]:
        checked_at = self._utc(now or datetime.now(timezone.utc))
        with self.store.connect() as con:
            rows = con.execute(
                """
                select session_id, device_name, platform, scopes_json,
                       created_at, expires_at, last_used_at, revoked_at
                from mobile_connector_sessions
                order by created_at desc, session_id
                """
            ).fetchall()
        return [self._mobile_session_from_row(row, checked_at) for row in rows]

    def authorize_mobile_session(
        self,
        access_token: str,
        *,
        required_scope: MobileConnectorScope,
        now: datetime | None = None,
    ) -> MobileConnectorSession:
        checked_at = self._utc(now or datetime.now(timezone.utc))
        if not access_token.startswith("srv2m_"):
            raise PermissionError("mobile_session_invalid")
        token_hash = self._secret_hash(access_token)
        with self.store.connect() as con:
            row = con.execute(
                """
                select session_id, device_name, platform, scopes_json,
                       created_at, expires_at, last_used_at, revoked_at
                from mobile_connector_sessions
                where token_hash = ?
                """,
                [token_hash],
            ).fetchone()
            if row is None:
                raise PermissionError("mobile_session_invalid")
            session = self._mobile_session_from_row(row, checked_at)
            if session.status == "revoked":
                raise PermissionError("mobile_session_revoked")
            if session.status == "expired":
                raise PermissionError("mobile_session_expired")
            if required_scope not in session.scopes:
                raise PermissionError("mobile_session_scope_missing")
            con.execute(
                """
                update mobile_connector_sessions
                set last_used_at = ?
                where session_id = ? and revoked_at is null
                """,
                [checked_at, session.session_id],
            )
        return session.model_copy(update={"last_used_at": checked_at})

    def revoke_mobile_session(
        self,
        session_id: str,
        *,
        now: datetime | None = None,
    ) -> MobileConnectorSession:
        revoked_at = self._utc(now or datetime.now(timezone.utc))
        with self.store.connect() as con:
            row = con.execute(
                """
                select session_id, device_name, platform, scopes_json,
                       created_at, expires_at, last_used_at, revoked_at
                from mobile_connector_sessions
                where session_id = ?
                """,
                [session_id.strip()],
            ).fetchone()
            if row is None:
                raise ValueError("mobile_session_not_found")
            if row[7] is None:
                con.execute(
                    """
                    update mobile_connector_sessions
                    set revoked_at = ?
                    where session_id = ? and revoked_at is null
                    """,
                    [revoked_at, str(row[0])],
                )
        return self._mobile_session_from_row(
            (*row[:7], row[7] or revoked_at),
            revoked_at,
        )

    def active_mobile_session_count(self, *, now: datetime | None = None) -> int:
        checked_at = self._utc(now or datetime.now(timezone.utc))
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(*)
                from mobile_connector_sessions
                where revoked_at is null and expires_at > ?
                """,
                [checked_at],
            ).fetchone()
        return int(row[0]) if row else 0

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
            if len(public_key) != 32 or len(signature_bytes) != 64 or not crypto_core_ed25519_is_valid_point(public_key):
                raise BadSignatureError
            VerifyKey(public_key).verify(message.encode("utf-8"), signature_bytes)
        except (BadSignatureError, ValueError) as exc:
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
        elif connector_id == "document-scan":
            configured = bool(ConnectorAccessPolicy().setup_token())
            connection_status = "configured" if configured else "not_configured"
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

    @classmethod
    def _mobile_session_from_row(
        cls,
        row: tuple[object, ...],
        checked_at: datetime,
    ) -> MobileConnectorSession:
        revoked_at = cls._utc(row[7]) if row[7] is not None else None
        expires_at = cls._utc(row[5])
        status = (
            "revoked"
            if revoked_at is not None
            else "expired"
            if checked_at > expires_at
            else "active"
        )
        return MobileConnectorSession(
            session_id=str(row[0]),
            device_name=str(row[1]),
            platform=str(row[2]),
            scopes=cls._normalize_mobile_scopes(json.loads(str(row[3]))),
            created_at=cls._utc(row[4]),
            expires_at=expires_at,
            last_used_at=cls._utc(row[6]) if row[6] is not None else None,
            revoked_at=revoked_at,
            status=status,
        )

    @classmethod
    def _normalize_mobile_scopes(
        cls,
        scopes: list[str] | tuple[str, ...],
    ) -> list[MobileConnectorScope]:
        requested = {str(scope).strip() for scope in scopes}
        unknown = requested.difference(cls.MOBILE_SCOPES)
        if unknown:
            raise ValueError("mobile_session_scope_invalid")
        normalized = [scope for scope in cls.MOBILE_SCOPES if scope in requested]
        if not normalized:
            raise ValueError("mobile_session_scope_required")
        return normalized

    @classmethod
    def _normalize_pairing_code(cls, pairing_code: str) -> str:
        compact = "".join(character for character in pairing_code.upper() if character != "-")
        if len(compact) != 20 or any(
            character not in cls.MOBILE_PAIRING_CODE_ALPHABET for character in compact
        ):
            raise ValueError("mobile_pairing_invalid")
        return compact

    @staticmethod
    def _secret_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_solana_address(address: str) -> None:
        try:
            decoded = decode_base58(address)
        except ValueError as exc:
            raise ValueError("invalid_solana_wallet_address") from exc
        if len(decoded) != 32 or not crypto_core_ed25519_is_valid_point(decoded):
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
                "availability": "available",
                "mobile_platforms": ["android", "ios"],
                "capabilities": [
                    "pdf",
                    "jpeg",
                    "png",
                    "sha256_evidence",
                    "review_inbox",
                ],
                "required_fields": ["document"],
                "safety_notes": [
                    "Uploads bleiben bis zur fachlichen Review steuerlich wirkungslos."
                ],
                "limitation": "OCR und fachliche Weiterleitung sind getrennte Review-Schritte.",
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
