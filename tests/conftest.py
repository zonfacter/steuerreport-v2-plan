import os
from pathlib import Path


# Tests always use generated fixture identities, never the operator's profile.
os.environ["STEUERREPORT_PRIVATE_PROFILE"] = str(Path(__file__).parent / "fixture_profile.json")
os.environ.pop("STEUERREPORT_PRIVATE_CONFIG_DIR", None)
