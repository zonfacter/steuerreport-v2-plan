#!/usr/bin/env python3
"""Saubere Offline-DuckDB in eine neue Datei kopieren, vorhandene Ziele nie ersetzen."""
from steuerreport_v2.db.offline_snapshot import main


if __name__ == "__main__":
    raise SystemExit(main())
