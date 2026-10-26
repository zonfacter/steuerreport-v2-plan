"""Lokale, ausdrueckliche Inbetriebnahme; niemals ein unauthentifizierter Web-Endpunkt."""
from __future__ import annotations

import argparse
import json
import sys

from steuerreport_v2.domain.connector_bootstrap import initialize_token, read_token, token_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "status", "show-token"))
    args = parser.parse_args()
    try:
        if args.action == "init":
            result = initialize_token()
        elif args.action == "status":
            result = {"configured": bool(read_token()), "file": str(token_path()) if token_path() else None,
                      "secret_returned": False}
        else:
            if not sys.stdout.isatty():
                parser.exit(2, "Passwortanzeige nur in einer privaten interaktiven Konsole (Docker: exec -it).\n")
            token = read_token()
            if not token:
                raise RuntimeError("connector_setup_not_available; run_init_or_check_private_file")
            print(token)
            return
    except (OSError, RuntimeError):
        parser.exit(2, "Connector-Einrichtung nicht moeglich. Privaten Pfad, Dateirechte und vorhandene Konfiguration pruefen; nichts wurde ersetzt.\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
