import json
import os
import subprocess
import sys

import pytest

from steuerreport_v2.private_settings import _read_profile, private_alias, private_config_path, private_template, private_value


@pytest.fixture(autouse=True)
def clear_profile_cache():
    _read_profile.cache_clear()
    yield
    _read_profile.cache_clear()


def test_no_operator_account_is_assumed_without_configuration(monkeypatch):
    monkeypatch.delenv("STEUERREPORT_PRIVATE_PROFILE", raising=False)
    monkeypatch.delenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", raising=False)
    assert private_value("primary_solana_wallet") == ""


def test_private_profile_and_explicit_environment_override(tmp_path, monkeypatch):
    profile = tmp_path / "private.json"
    profile.write_text(json.dumps({"primary_solana_wallet": "fixture-wallet"}))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.delenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", raising=False)
    assert private_value("primary_solana_wallet") == "fixture-wallet"
    monkeypatch.setenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", "override-wallet")
    assert private_value("primary_solana_wallet") == "override-wallet"


def test_malformed_explicit_profile_fails_without_disclosing_its_contents(tmp_path, monkeypatch):
    profile = tmp_path / "private.json"
    profile.write_text("invalid fixture content")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    with pytest.raises(RuntimeError, match="^private_profile_unreadable$"):
        private_value("primary_solana_wallet")


def test_private_config_directory_stays_external(tmp_path, monkeypatch):
    config = tmp_path / "source_registry.json"
    config.write_text("{}")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path))
    assert private_config_path("source_registry.json") == config
    with pytest.raises(ValueError):
        private_config_path("../source_registry.json")


def test_private_template_uses_configured_values_without_embedded_addresses(monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", "fixture-wallet")
    assert private_template("Wallet.{primary_solana_wallet}-month.csv") == "Wallet.fixture-wallet-month.csv"


def test_private_alias_is_derived_from_configuration(monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", "fixture-wallet")
    assert private_alias("primary_solana_wallet", 3, 4) == "fix...llet"
    monkeypatch.setenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", "")
    assert private_alias("primary_solana_wallet", 3, 4) == ""


def test_unconfigured_application_does_not_treat_empty_accounts_as_owned():
    environment = dict(os.environ)
    environment["STEUERREPORT_PRIVATE_PROFILE"] = ""
    result = subprocess.run(
        [sys.executable, "-c", (
            "from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService as S; "
            "from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService as M; "
            "assert not S.KNOWN_OWN_SOLANA_WALLETS; "
            "assert not S.KNOWN_OWN_CEX_DEPOSIT_ADDRESSES; "
            "assert not S.HISTORICAL_STAKING_WALLETS; "
            "assert not M.KNOWN_RECEIVER_WALLETS"
        )], env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
