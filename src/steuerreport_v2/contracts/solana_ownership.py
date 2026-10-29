from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class SolanaOwnershipScopeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    outside_owned_wallet_scope_txids: list[StrictStr] = Field(default_factory=list)

    @field_validator("outside_owned_wallet_scope_txids")
    @classmethod
    def txids_must_be_nonempty(cls, values: list[str]) -> list[str]:
        if any(not value or value.strip() != value for value in values):
            raise ValueError("transaction identifiers must be non-empty and trimmed")
        return values

    @property
    def configuration_status(self) -> str:
        if "outside_owned_wallet_scope_txids" not in self.model_fields_set:
            return "unconfigured"
        return "configured_empty" if not self.outside_owned_wallet_scope_txids else "configured"
