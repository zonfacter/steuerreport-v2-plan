from __future__ import annotations

import csv
from io import StringIO


class BitgetCsvStructureError(ValueError):
    """Raised when a Bitget CSV row contains non-empty fields without headers."""


class BitgetCsvDictReader(csv.DictReader):
    def __next__(self) -> dict[str | None, str | list[str] | None]:
        row = super().__next__()
        extra_values = row.pop(None, None)
        if extra_values is not None:
            values = extra_values if isinstance(extra_values, list) else [extra_values]
            if any(value is not None and str(value).strip() for value in values):
                raise BitgetCsvStructureError(
                    f"Bitget CSV-Zeile {self.reader.line_num} enthaelt nichtleere "
                    "Felder hinter der Kopfzeile."
                )
        return row


def dict_reader(content: str, dialect: csv.Dialect) -> BitgetCsvDictReader:
    return BitgetCsvDictReader(
        StringIO(content),
        dialect=dialect,
        skipinitialspace=True,
    )
