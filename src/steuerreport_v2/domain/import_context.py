from __future__ import annotations

import re
from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_FIXED_OFFSET = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")
_PAIR = re.compile(r"^[A-Z0-9]{2,20}(?:_[A-Z0-9]{2,20})?$")


def timezone_from_name(value: str) -> tzinfo:
    name = value.strip()
    if name == "UTC":
        return timezone.utc
    match = _FIXED_OFFSET.fullmatch(name)
    if match:
        hours, minutes = int(match.group(2)), int(match.group(3))
        if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
            raise ValueError("import_timezone_invalid")
        offset = timedelta(hours=hours, minutes=minutes)
        if match.group(1) == "-":
            offset = -offset
        return timezone(offset, name)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("import_timezone_invalid") from None


def bitget_import_context(
    *,
    export_timezone: str | None,
    product_scope: str | None,
    margin_pair: str | None,
    allow_legacy_defaults: bool = False,
) -> dict[str, str]:
    context: dict[str, str] = {"context_version": "1"}
    if export_timezone is None or not export_timezone.strip():
        if not allow_legacy_defaults:
            raise ValueError("bitget_export_timezone_required")
        context.update({
            "export_timezone": "UTC+08:00",
            "timezone_basis": "legacy_default_unverified",
        })
    else:
        name = export_timezone.strip()
        timezone_from_name(name)
        context.update({"export_timezone": name, "timezone_basis": "operator_selected"})

    if product_scope not in {"spot", "usdt_futures", "isolated_margin"}:
        if not allow_legacy_defaults:
            raise ValueError("bitget_product_scope_required")
        context["product_scope"] = "unspecified_legacy"
    else:
        context["product_scope"] = product_scope

    if context["product_scope"] == "isolated_margin":
        normalized_pair = (margin_pair or "").strip().upper().replace("/", "_").replace("-", "_")
        if not normalized_pair or not _PAIR.fullmatch(normalized_pair):
            raise ValueError("bitget_margin_pair_required")
        context["margin_pair"] = normalized_pair
    elif margin_pair:
        raise ValueError("bitget_margin_pair_not_applicable")
    return context
