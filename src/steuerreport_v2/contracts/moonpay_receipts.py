from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


MoonpayReceiptStatus = Literal[
    "receipt_required",
    "receipt_invalid",
    "ready",
]


class MoonpayReceiptDecisionLayer(BaseModel):
    onchain_event_bound: bool = False
    provenance_sender_bound: bool = False
    receiver_wallet_bound: bool = False
    received_quantity_bound: bool = False
    payment_currency_eur: bool = False
    payment_amount_valid: bool = False
    payment_fee_valid: bool = False
    payment_time_plausible: bool = False
    document_integrity_valid: bool = False
    trade_history_row_bound: bool = False
    completed_buy_bound: bool = False
    fee_components_within_payment_amount: bool = False
    bank_debit_bound: bool = False
    gross_payment_reconciled: bool = False


class MoonpayReceiptItem(BaseModel):
    tx_id: str
    event_id: str
    event_time: datetime
    sender_address: str
    receiver_wallet: str
    asset: str = "SOL"
    received_quantity: Decimal
    provisional_market_value_eur: Decimal = Decimal("0")
    status: MoonpayReceiptStatus = "receipt_required"
    strict_ready: bool = False
    cost_basis_eur: Decimal | None = None
    payment_amount_eur: Decimal | None = None
    gross_payment_amount_eur: Decimal | None = None
    fee_eur: Decimal | None = None
    service_fee_eur: Decimal | None = None
    extra_fee_eur: Decimal | None = None
    network_fee_eur: Decimal | None = None
    payment_method: str | None = None
    paid_at: datetime | None = None
    receipt_received_quantity: Decimal | None = None
    moonpay_trade_id: str | None = None
    moonpay_operation: str | None = None
    moonpay_status: str | None = None
    moonpay_quote_currency: str | None = None
    payment_to_chain_seconds: int | None = None
    bank_debit_amount_eur: Decimal | None = None
    bank_booking_date: str | None = None
    bank_reference: str | None = None
    bank_evidence_sha256: str | None = None
    evidence_source: Literal["trade_history_csv", "individual_receipt"] | None = None
    document_filename: str | None = None
    document_media_type: str | None = None
    document_sha256: str | None = None
    document_size_bytes: int = 0
    document_download_url: str | None = None
    decision_layer: MoonpayReceiptDecisionLayer
    errors: list[str] = Field(default_factory=list)


class MoonpayTradeHistoryRow(BaseModel):
    trade_id: str
    operation: str
    status: str
    paid_at: datetime
    payment_currency: str
    payment_amount: Decimal
    gross_payment_amount: Decimal = Decimal("0")
    quote_currency: str
    asset: str | None = None
    received_quantity: Decimal
    service_fee_eur: Decimal = Decimal("0")
    extra_fee_eur: Decimal = Decimal("0")
    network_fee_eur: Decimal = Decimal("0")
    matched: bool = False
    matched_tx_id: str | None = None
    bank_debit_matched: bool = False
    bank_debit_amount_eur: Decimal | None = None
    bank_booking_date: str | None = None
    match_error: str | None = None


class MoonpayReceiptReport(BaseModel):
    generated_at: datetime
    status: Literal["evidence_required", "review_required", "ready"]
    strict_ready: bool = False
    sender_address: str
    manifest_path: str
    trade_history_path: str
    trade_history_exists: bool = False
    trade_history_sha256: str | None = None
    trade_history_size_bytes: int = 0
    trade_history_rows_count: int = 0
    completed_buy_rows_count: int = 0
    matched_trade_rows_count: int = 0
    unmatched_trade_rows_count: int = 0
    invalid_trade_rows_count: int = 0
    candidates_count: int = 0
    ready_count: int = 0
    missing_count: int = 0
    invalid_count: int = 0
    total_received_quantity: Decimal = Decimal("0")
    total_provisional_market_value_eur: Decimal = Decimal("0")
    total_base_payment_amount_eur: Decimal = Decimal("0")
    total_receipt_cost_basis_eur: Decimal = Decimal("0")
    total_fee_components_eur: Decimal = Decimal("0")
    total_bank_debits_eur: Decimal = Decimal("0")
    bank_camt_path: str | None = None
    bank_camt_exists: bool = False
    bank_camt_files_count: int = 0
    bank_camt_semantic_sha256: str | None = None
    bank_debits_count: int = 0
    bank_debits_matched_count: int = 0
    bank_debits_unmatched_count: int = 0
    items: list[MoonpayReceiptItem] = Field(default_factory=list)
    trade_rows: list[MoonpayTradeHistoryRow] = Field(default_factory=list)
    semantic_sha256: str
    methodology: str


class MoonpayReceiptUpsertRequest(BaseModel):
    tx_id: str = Field(min_length=32, max_length=128)
    payment_amount_eur: Decimal = Field(gt=0)
    fee_eur: Decimal = Field(default=Decimal("0"), ge=0)
    received_quantity: Decimal = Field(gt=0)
    payment_currency: Literal["EUR"] = "EUR"
    payment_method: str = Field(default="Apple Pay", min_length=2, max_length=80)
    paid_at: datetime
    filename: str = Field(min_length=1, max_length=180)
    media_type: Literal[
        "application/pdf",
        "image/jpeg",
        "image/png",
        "text/csv",
        "text/plain",
    ]
    content_base64: str = Field(min_length=4)
    note: str | None = Field(default=None, max_length=500)


class MoonpayReceiptUpsertResult(BaseModel):
    item: MoonpayReceiptItem
    manifest_path: str
    tax_rebuild_required: bool = True
    wallet_fifo_rerun_required: bool = True
    message: str
