import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_helium_solana_rewards_rpc_v2.py"
SPEC = importlib.util.spec_from_file_location("verify_helium_solana_rewards_rpc_v2", SCRIPT_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_redact_rpc_url_hides_secret_segments():
    assert (
        MODULE._redact_rpc_url("https://solana-mainnet.g.alchemy.com/v2/secret-key")
        == "https://solana-mainnet.g.alchemy.com/v2/<redacted>"
    )
    assert (
        MODULE._redact_rpc_url("https://mainnet.helius-rpc.com/?api-key=secret-key&x=1")
        == "https://mainnet.helius-rpc.com/?api-key=<redacted>&x=1"
    )
