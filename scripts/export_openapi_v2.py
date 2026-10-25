#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEFAULT_OUTPUT = ROOT / "docs/openapi/steuerreport-v2-openapi.json"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Documentation must never depend on (or publish) operator profiles or paths.
for name in list(os.environ):
    if name.startswith("STEUERREPORT_"):
        del os.environ[name]
os.environ.update({
    "STEUERREPORT_V2_ROOT": "/opt/steuerreport",
    "STEUERREPORT_V2_DB": ":memory:",
    "STEUERREPORT_USERTRANSFER_ROOT": "/var/lib/steuerreport/imports",
    "STEUERREPORT_STATE_DIR": "/var/lib/steuerreport",
    "STEUERREPORT_PRIVATE_PROFILE": "",
    "STEUERREPORT_PRIVATE_CONFIG_DIR": "/var/lib/steuerreport/configs",
})

from steuerreport_v2.api.app import create_app  # noqa: E402
from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402


def render_openapi() -> str:
    app = create_app(DuckDbStore(":memory:"))
    schema = app.openapi()
    schema["x-api-lifecycle"] = (
        "experimental_read_pairing_wallet_ownership_and_document_inbox"
    )
    schema["x-decimal-transport"] = "string"
    schema["x-tax-day-timezone"] = "Europe/Berlin"
    schema["x-production-security"] = (
        "Mobile connector sessions are paired through a local setup bearer, scoped, stored as hashes and revocable, "
        "but the API has no global user authentication. "
        "Keep it in a trusted LAN/VPN or place TLS and authentication in front of it."
    )
    return json.dumps(schema, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the deterministic Steuerreport V2 OpenAPI schema")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    rendered = render_openapi()
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            print(f"outdated:{output}")
            return 1
        print(f"current:{output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"generated:{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
