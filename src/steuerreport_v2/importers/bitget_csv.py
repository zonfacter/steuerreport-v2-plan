from __future__ import annotations

import csv
from io import StringIO


class BitgetCsvStructureError(ValueError):
    """Raised when a Bitget CSV row contains non-empty fields without headers."""


def validate_extra_values(values: list[str | None], row_number: int) -> None:
    if any(value is not None and str(value).strip() for value in values):
        raise BitgetCsvStructureError(
            f"Bitget CSV-Zeile {row_number} enthaelt nichtleere "
            "Felder hinter der Kopfzeile."
        )


class BitgetCsvDictReader(csv.DictReader):
    def __next__(self) -> dict[str | None, str | list[str] | None]:
        row = super().__next__()
        extra_values = row.pop(None, None)
        if extra_values is not None:
            values = extra_values if isinstance(extra_values, list) else [extra_values]
            validate_extra_values(values, self.reader.line_num)
        return row


def dict_reader(content: str, dialect: csv.Dialect) -> BitgetCsvDictReader:
    return BitgetCsvDictReader(
        StringIO(content.removeprefix("\ufeff")),
        dialect=dialect,
        skipinitialspace=True,
    )
