from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class PrivateDisposalThresholdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    other_private_gain_loss_eur: Decimal | None = Field(default=None, allow_inf_nan=False)
    confirm_other_private_disposals_complete: StrictBool = False


class PrivateDisposalThresholdAssessment(BaseModel):
    year: int
    policy_version: str = "de_estg23_freigrenze_2009_2026_v1"
    threshold_eur: Decimal | None
    calculated_crypto_gain_loss_eur: Decimal
    other_private_gain_loss_eur: Decimal | None
    total_private_gain_loss_eur: Decimal | None
    status: Literal["context_required", "below_threshold", "threshold_reached", "unsupported_year"]
    threshold_reached: bool | None
    final_filing_allowed: bool = False
    methodology: str
    source_refs: list[str]
