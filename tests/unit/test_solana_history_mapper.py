from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json

import pytest

from steuerreport_v2.importers.solana_history_mapper import transaction_rows


WALLET = "SyntheticWallet"
MINT = "CaseSensitiveMintAbc"


def transaction(*, keys=None, pre=None, post=None, fee=5000, err=None):
    return {
        "blockTime": 1735689600,
        "meta": {
            "err": err, "fee": fee,
            "preBalances": pre if pre is not None else [2_000_000_000],
            "postBalances": post if post is not None else [1_999_995_000],
            "preTokenBalances": [], "postTokenBalances": [],
        },
        "transaction": {"message": {"accountKeys": keys if keys is not None else [WALLET]}},
    }


def token(amount="1234567", *, mint=MINT, owner=WALLET, index=0, decimals=6):
    return {"accountIndex": index, "mint": mint, "owner": owner,
            "uiTokenAmount": {"amount": amount, "decimals": decimals,
                              "uiAmountString": "999", "uiAmount": 999.0}}


def map_rows(tx, symbols=None):
    return transaction_rows(WALLET, "SyntheticSignature", tx, symbols or {})


def signed(row):
    return Decimal(row["quantity"]) * (-1 if row["side"] == "out" else 1)


def test_fee_only_preserves_original_payload_deterministically():
    tx = transaction()
    original = deepcopy(tx)
    rows = map_rows(tx)
    assert [(r["event_type"], r["side"], r["quantity"]) for r in rows] == [
        ("network_fee", "out", "0.000005")]
    assert rows[0]["history_mapper_version"] == "2"
    assert rows[0]["timestamp_utc"] == "2025-01-01T00:00:00+00:00"
    assert rows[0]["tx_id"] == "SyntheticSignature"
    assert rows[0]["wallet_address"] == WALLET
    assert rows[0]["asset"] == "SOL"
    assert json.loads(rows[0]["raw_transaction"]) == original == tx
    assert map_rows(dict(reversed(list(tx.items())))) == rows


def test_fee_and_inbound_token_stay_separate_transfers_not_rewards_or_swaps():
    tx = transaction()
    tx["meta"]["postTokenBalances"] = [token()]
    rows = map_rows(tx, {MINT: "KNOWN"})
    assert [(r["event_type"], r["asset"], r["side"], r["quantity"]) for r in rows] == [
        ("token_transfer", "KNOWN", "in", "1.234567"),
        ("network_fee", "SOL", "out", "0.000005")]
    assert rows[0]["mint"] == MINT
    for row in rows:
        assert row["history_mapper_version"] == "2"
        assert json.loads(row["raw_transaction"]) == tx


@pytest.mark.parametrize("delta", [-1_000_000_000, 1_000_000_000])
def test_sol_transfer_excludes_fee_only_for_wallet_payer(delta):
    tx = transaction(post=[2_000_000_000 + delta - 5000])
    rows = map_rows(tx)
    assert rows[0]["event_type"] == "sol_transfer"
    assert signed(rows[0]) == Decimal(delta) / 10**9
    assert rows[1]["event_type"] == "network_fee"
    assert sum(map(signed, rows)) == Decimal(delta - 5000) / 10**9


@pytest.mark.parametrize("delta", [-1_000_000_000, 1_000_000_000])
@pytest.mark.parametrize("parsed", [False, True])
def test_sol_send_receive_with_other_payer_has_no_wallet_fee(delta, parsed):
    keys = ["OtherPayer", WALLET]
    if parsed:
        keys = [{"pubkey": key} for key in keys]
    tx = transaction(keys=keys, pre=[10000, 2_000_000_000], post=[5000, 2_000_000_000 + delta])
    rows = map_rows(tx)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "sol_transfer"
    assert signed(rows[0]) == Decimal(delta) / 10**9


def test_failed_transaction_only_emits_wallet_fee_even_with_bogus_deltas():
    tx = transaction(err={"InstructionError": [0, "SyntheticFailure"]}, post=[0])
    tx["meta"]["postTokenBalances"] = [token(owner=None)]
    rows = map_rows(tx)
    assert [(r["event_type"], r["quantity"], r["side"]) for r in rows] == [
        ("network_fee", "0.000005", "out")]
    assert json.loads(rows[0]["raw_transaction"]) == tx


def test_failed_transaction_with_other_payer_emits_nothing():
    tx = transaction(keys=["OtherPayer", WALLET], pre=[10000, 100], post=[5000, 100], err={})
    assert map_rows(tx) == []


def test_case_distinct_mints_keep_separate_uppercase_safe_identities():
    tx = transaction(keys=[WALLET, "TokenAccount"], pre=[2_000_000_000, 0], post=[1_999_995_000, 0])
    tx["meta"]["postTokenBalances"] = [token(), token(index=1, mint=MINT.swapcase())]
    tokens = [row for row in map_rows(tx, {MINT.upper(): "UNSAFE"}) if row["event_type"] == "token_transfer"]
    assert len({r["asset"] for r in tokens}) == 2
    assert {r["mint"] for r in tokens} == {MINT, MINT.swapcase()}
    for row in tokens:
        assert row["asset"] == "SOLANA_" + hashlib.sha256(row["mint"].encode()).hexdigest().upper()
        assert row["asset"] == row["asset"].upper()


@pytest.mark.parametrize("owner", [None, ""])
@pytest.mark.parametrize("field", ["preTokenBalances", "postTokenBalances"])
def test_ambiguous_owner_fails_closed(owner, field):
    tx = transaction()
    tx["meta"][field] = [token(owner=owner)]
    with pytest.raises(ValueError, match="owner"):
        map_rows(tx)


def test_absent_owner_is_not_adopted_from_other_balance():
    tx = transaction()
    tx["meta"]["preTokenBalances"] = [token()]
    tx["meta"]["postTokenBalances"] = [token()]
    del tx["meta"]["postTokenBalances"][0]["owner"]
    with pytest.raises(ValueError, match="owner"):
        map_rows(tx)


def test_explicit_other_owner_is_not_wallet_balance():
    tx = transaction()
    tx["meta"]["postTokenBalances"] = [token(owner="OtherOwner")]
    assert [r["event_type"] for r in map_rows(tx)] == ["network_fee"]


def test_same_symbol_different_mints_are_not_aggregated():
    tx = transaction(keys=[WALLET, "TokenAccount"], pre=[10000, 0], post=[5000, 0])
    tx["meta"]["postTokenBalances"] = [token(), token(index=1, mint="OtherMint")]
    rows = map_rows(tx, {MINT: "SAME", "OtherMint": "SAME"})
    assert [(r["asset"], r["mint"]) for r in rows[:-1]] == [("SAME", MINT), ("SAME", "OtherMint")]


def test_raw_integer_arithmetic_is_independent_of_decimal_precision():
    tx = transaction(fee=0, post=[2_000_000_000])
    tx["meta"]["preTokenBalances"] = [token("18446744073709551614", decimals=18)]
    tx["meta"]["postTokenBalances"] = [token("18446744073709551615", decimals=18)]
    with localcontext() as context:
        context.prec = 2
        rows = map_rows(tx)
    assert rows[0]["quantity"] == "0.000000000000000001"


def test_ui_amount_string_fallback_without_float_arithmetic():
    tx = transaction()
    entry = token()
    entry["uiTokenAmount"] = {"uiAmountString": "0.000000000000000001", "uiAmount": 1e-18}
    tx["meta"]["postTokenBalances"] = [entry]
    assert map_rows(tx)[0]["quantity"] == "0.000000000000000001"


@pytest.mark.parametrize("amount", [
    {"uiAmount": 1.5}, {"uiAmountString": "NaN"}, {"uiAmountString": "-1"},
    {"amount": "12"}, {"amount": 1.2, "decimals": 6},
    {"amount": "1", "decimals": True}, {"amount": "1", "decimals": 256},
    {"uiAmountString": "0.01", "decimals": 1},
])
def test_incomplete_or_invalid_token_amount_fails_closed(amount):
    tx = transaction()
    entry = token()
    entry["uiTokenAmount"] = amount
    tx["meta"]["postTokenBalances"] = [entry]
    with pytest.raises(ValueError):
        map_rows(tx)


@pytest.mark.parametrize("time", [None, "1735689600", True, -1, 1.5, 10**30])
def test_missing_or_invalid_time_fails_closed(time):
    tx = transaction()
    tx["blockTime"] = time
    with pytest.raises(ValueError, match="blockTime"):
        map_rows(tx)


def test_epoch_zero_is_valid_not_missing():
    tx = transaction()
    tx["blockTime"] = 0
    assert map_rows(tx)[0]["timestamp_utc"] == "1970-01-01T00:00:00+00:00"


@pytest.mark.parametrize("field,value", [
    ("fee", None), ("fee", True), ("fee", -1), ("fee", "5000"),
    ("preBalances", []), ("postBalances", None), ("postBalances", [1.5]),
    ("postBalances", [-1]), ("preTokenBalances", None), ("postTokenBalances", None),
])
def test_incomplete_meta_never_fabricates_rows(field, value):
    tx = transaction()
    tx["meta"][field] = value
    with pytest.raises(ValueError):
        map_rows(tx)


@pytest.mark.parametrize("field", ["blockTime", "meta", "transaction"])
def test_required_transaction_fields_cannot_be_missing(field):
    tx = transaction()
    del tx[field]
    with pytest.raises(ValueError):
        map_rows(tx)


def test_missing_execution_status_is_not_assumed_success():
    tx = transaction()
    del tx["meta"]["err"]
    with pytest.raises(ValueError):
        map_rows(tx)


def test_loaded_addresses_resolve_wallet_without_charging_other_payer_fee():
    tx = transaction(keys=["OtherPayer"], pre=[10000, 0], post=[5000, 123])
    tx["meta"]["loadedAddresses"] = {"writable": [WALLET], "readonly": []}
    rows = map_rows(tx)
    assert len(rows) == 1 and rows[0]["quantity"] == "0.000000123"
    assert rows[0]["event_type"] == "sol_transfer"


def test_multiple_wallet_token_accounts_are_aggregated_per_exact_mint():
    tx = transaction(keys=[WALLET, "TokenAccount"], pre=[10000, 0], post=[5000, 0])
    tx["meta"]["preTokenBalances"] = [token("1000000"), token("2000000", index=1)]
    tx["meta"]["postTokenBalances"] = [token("1500000"), token("2500000", index=1)]
    rows = map_rows(tx)
    assert rows[0]["quantity"] == "1"
    assert rows[0]["side"] == "in"


def test_token_account_owner_change_uses_only_explicit_wallet_balances():
    tx = transaction()
    tx["meta"]["preTokenBalances"] = [token()]
    tx["meta"]["postTokenBalances"] = [token(owner="OtherOwner")]
    assert map_rows(tx)[0]["side"] == "out"


def test_opposite_token_balance_signs_are_not_inferred_to_be_swap():
    tx = transaction(keys=[WALLET, "TokenAccount"], pre=[10000, 0], post=[5000, 0])
    tx["meta"]["preTokenBalances"] = [token()]
    tx["meta"]["postTokenBalances"] = [token(index=1, mint="OtherMint")]
    rows = map_rows(tx)
    assert [(r["event_type"], r["side"]) for r in rows] == [
        ("token_transfer", "out"), ("token_transfer", "in"), ("network_fee", "out")]


def test_wallet_absent_from_native_keys_can_receive_explicitly_owned_token():
    tx = transaction(keys=["OtherPayer"])
    tx["meta"]["postTokenBalances"] = [token()]
    rows = map_rows(tx)
    assert len(rows) == 1 and rows[0]["event_type"] == "token_transfer"


def test_zero_fee_and_zero_deltas_emit_nothing():
    assert map_rows(transaction(fee=0, post=[2_000_000_000])) == []


@pytest.mark.parametrize("error", [False, True, 0, [], 1.5])
def test_invalid_execution_status_is_not_assumed_failure_or_success(error):
    with pytest.raises(ValueError, match="error status"):
        map_rows(transaction(err=error))


def test_missing_time_field_cannot_be_replaced_by_empty_timestamp():
    tx = transaction()
    del tx["blockTime"]
    with pytest.raises(ValueError, match="blockTime"):
        map_rows(tx)


@pytest.mark.parametrize("field", ["preTokenBalances", "postTokenBalances"])
def test_missing_token_balance_array_is_not_assumed_empty(field):
    tx = transaction()
    del tx["meta"][field]
    with pytest.raises(ValueError, match=field):
        map_rows(tx)


def test_token_decimals_must_be_consistent_across_transaction():
    tx = transaction()
    tx["meta"]["preTokenBalances"] = [token(decimals=6)]
    tx["meta"]["postTokenBalances"] = [token(decimals=9)]
    with pytest.raises(ValueError, match="decimals"):
        map_rows(tx)


@pytest.mark.parametrize("index", [-1, True, 1, "0"])
def test_invalid_token_account_index_fails_closed(index):
    tx = transaction()
    tx["meta"]["postTokenBalances"] = [token(index=index)]
    with pytest.raises(ValueError, match="accountIndex"):
        map_rows(tx)


def test_parsed_loaded_keys_are_not_appended_twice():
    tx = transaction(keys=[{"pubkey": "OtherPayer"}, {"pubkey": WALLET}],
                     pre=[10000, 0], post=[5000, 123])
    tx["meta"]["loadedAddresses"] = {"writable": [WALLET], "readonly": []}
    rows = map_rows(tx)
    assert len(rows) == 1 and rows[0]["quantity"] == "0.000000123"
