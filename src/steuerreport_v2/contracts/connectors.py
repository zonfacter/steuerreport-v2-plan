from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ConnectorCategory = Literal[
    "wallet",
    "exchange",
    "data_provider",
    "bank",
    "payment_provider",
    "document",
    "payment_reference",
]
ConnectorAuthMethod = Literal[
    "wallet_signature",
    "api_key",
    "oauth_partner",
    "oauth_redirect",
    "file_import",
    "server_api_key",
    "device_capture",
    "bank_reconciliation",
]
ConnectorAvailability = Literal[
    "available",
    "server_admin_only",
    "planned",
    "partner_access_required",
    "evidence_only",
]
ConnectorConnectionStatus = Literal[
    "configured",
    "not_configured",
    "ownership_verified_pending_registry",
    "registered",
    "revoked",
]


class ConnectorVaultStatus(BaseModel):
    configured: bool = False
    require_encrypted_secrets: bool = False
    key_id: str | None = None
    encrypted_secrets: int = 0
    plaintext_secrets: int = 0
    unreadable_secrets: int = 0
    status: Literal["encrypted", "migration_required", "not_configured", "error"]


class ConnectorSecurityStatus(BaseModel):
    auth_mode: Literal["disabled", "setup_token", "oidc"] = "disabled"
    connector_writes_enabled: bool = False
    internet_ready: bool = False
    public_base_url: str | None = None
    owner_scope: Literal["single_user_local", "multi_tenant"] = "single_user_local"
    vault: ConnectorVaultStatus
    blockers: list[str] = Field(default_factory=list)


class ConnectorCatalogEntry(BaseModel):
    connector_id: str
    label: str
    category: ConnectorCategory
    auth_method: ConnectorAuthMethod
    availability: ConnectorAvailability
    connection_status: ConnectorConnectionStatus = "not_configured"
    mobile_platforms: list[Literal["android", "ios", "web"]] = Field(
        default_factory=list
    )
    capabilities: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    limitation: str | None = None
    last_sync_at: datetime | None = None


class ConnectorConnection(BaseModel):
    connection_id: str
    connector_id: str
    external_identifier: str
    display_label: str
    source_id: str | None = None
    status: ConnectorConnectionStatus
    created_at: datetime
    verified_at: datetime | None = None
    revoked_at: datetime | None = None
    last_sync_at: datetime | None = None
    tax_activation: Literal["review_required", "registry_active"] = "review_required"


class ConnectorCatalogReport(BaseModel):
    generated_at: datetime
    security: ConnectorSecurityStatus
    connectors: list[ConnectorCatalogEntry]
    connections: list[ConnectorConnection] = Field(default_factory=list)
    methodology: str


class WalletOwnershipChallengeRequest(BaseModel):
    wallet_address: str
    wallet_provider: Literal["phantom", "jupiter", "solflare", "other"] = "other"
    display_label: str | None = None


class WalletOwnershipChallenge(BaseModel):
    challenge_id: str
    connector_id: Literal["solana-wallet"] = "solana-wallet"
    wallet_address: str
    wallet_provider: str
    message: str
    issued_at: datetime
    expires_at: datetime
    signature_encoding: Literal["base58"] = "base58"
    status: Literal["pending"] = "pending"


class WalletOwnershipVerificationRequest(BaseModel):
    challenge_id: str
    signature: str


class WalletOwnershipVerificationResult(BaseModel):
    status: Literal["ownership_verified_pending_registry", "registered"]
    connection: ConnectorConnection
    registry_match: bool = False
    message: str


class SecretVaultMigrationResult(BaseModel):
    generated_at: datetime
    status: Literal["encrypted", "no_changes", "blocked"]
    encrypted_now: int = 0
    already_encrypted: int = 0
    plaintext_remaining: int = 0
    unreadable_secrets: int = 0
    key_id: str | None = None
    message: str
