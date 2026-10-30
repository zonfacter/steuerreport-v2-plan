"""Serializes Binance spot matching and import writes in the single-worker app."""
from threading import RLock


BINANCE_SPOT_IMPORT_LOCK = RLock()
