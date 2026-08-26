from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT / "integrations/openwebui/patch_rag_source_url.py"


def load_patch_module():
    spec = importlib.util.spec_from_file_location("openwebui_rag_source_url_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patch_exposes_http_metadata_source_as_escaped_url_attribute():
    module = load_patch_module()
    source = "before\n" + module.OLD_IMPORT + module.OLD_SOURCE + "after\n"

    patched = module.patch_source(source)

    assert "from html import escape" in patched
    assert "from datetime import datetime, timezone" in patched
    assert "src_url = meta.get('source')" in patched
    assert "escape(src_url, quote=True)" in patched
    assert "startswith(('http://', 'https://'))" in patched
    assert "Source retrieved at UTC: {retrieved_at_utc}" in patched
    assert module.OLD_SOURCE not in patched


def test_patch_rejects_unknown_or_already_patched_source():
    module = load_patch_module()

    for source in ("unrelated", module.NEW_IMPORT + module.NEW_SOURCE):
        try:
            module.patch_source(source)
        except ValueError as exc:
            assert "expected one" in str(exc)
        else:
            raise AssertionError("unexpected source must be rejected")
