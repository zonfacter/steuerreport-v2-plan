"""Conservative read projection; archived bytes remain historical evidence."""

PRICE_GATE_VERSION = "known_daily_references_v2"


def project_valuation_validity(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Ungueltiges Stichtagsarchiv")
    result = dict(payload)
    historical_status = result.get("status")
    historical_ready = result.get("strict_ready") is True
    current = result.get("price_gate_version") == PRICE_GATE_VERSION
    result["historical_status"] = historical_status
    result["historical_strict_ready"] = historical_ready
    result["current_validity"] = "versioned_gate" if current else "unverified_legacy_gate"
    if not current:
        for key in ("cutoff_price_gate", "valuation_price_gate"):
            original = result.get(key)
            if isinstance(original, dict):
                result["historical_" + key] = original
                result[key] = _unverified_gate(original)
        summary = result.get("summary")
        if isinstance(summary, dict):
            summary = dict(summary)
            for key in ("cutoff_price_gate", "valuation_price_gate"):
                if isinstance(summary.get(key), dict):
                    summary[key] = _unverified_gate(summary[key])
            result["summary"] = summary
        result["strict_ready"] = False
        result["status"] = "blocked"
        result["findings"] = [
            *(result.get("findings") or []),
            "Archivlauf ohne aktuelle Preisgate-Version: historische Freigabe ist nicht aktuell bestaetigt.",
        ]
    return result


def _unverified_gate(gate: dict) -> dict:
    return {
        **gate,
        "status": "blocked",
        "strict_ready": False,
        "findings": [*(gate.get("findings") or []), "Historisches Preisgate ist nicht aktuell bestaetigt."],
    }
