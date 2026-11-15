"""Konkrete Importbelegbindung, ausdruecklich keine Preiszeit-Zulassung."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from steuerreport_v2.contracts.price_evidence import EvidenceDatetime, EvidenceDecimal, EvidenceHash


class PreparedPriceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    price_id: UUID
    price_fingerprint: EvidenceHash
    asset: str = Field(strict=True, min_length=1, max_length=200)
    price_eur: EvidenceDecimal
    stored_reference_at: EvidenceDatetime


class PriceImportOriginalRef(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    sha256: EvidenceHash
    byte_length: int = Field(strict=True, ge=1, le=2 * 1024 * 1024)
    download_url: str
    filename: str | None = Field(default=None, min_length=1, max_length=180)


class PriceImportEvidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    format_version: Literal[1] = 1
    status: Literal["verified_import_binding"] = "verified_import_binding"
    integrity_scope: Literal["selected_price_only"] = "selected_price_only"
    preview_id: UUID
    preview_sha256: EvidenceHash
    price_id: UUID
    price_fingerprint: EvidenceHash
    asset: str
    price_eur: EvidenceDecimal
    stored_reference_at: EvidenceDatetime
    originals: list[PriceImportOriginalRef] = Field(min_length=1, max_length=1000)
    strict_eligible: Literal[False] = False
    admission_status: Literal["not_reviewed"] = "not_reviewed"
    observed_at: None = None
    price_published_at: None = None
    fx_published_at: None = None
    explanation: str = (
        "Die konkrete Preiszeile ist an Vorschau, Importentscheidung und die angegebenen "
        "Originalbytes gebunden. Keine bestaetigte Inhalts-, Beobachtungs-, Veroeffentlichungs- "
        "oder Methodenzulassung; keine Mengen-, Steuerjahres- oder Dossierfreigabe."
    )
