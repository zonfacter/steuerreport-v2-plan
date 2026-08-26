from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT / "integrations/openwebui/patch_web_loader_charset.py"


def load_patch_module():
    spec = importlib.util.spec_from_file_location("openwebui_web_loader_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patch_replaces_only_the_aiohttp_default_decoder():
    module = load_patch_module()
    source = "before\n" + module.OLD + "after\n"

    patched = module.patch_source(source)

    assert "await response.read()" in patched
    assert "'application/pdf' in content_type" in patched
    assert "PdfReader(BytesIO(body)).pages" in patched
    assert "UnicodeDammit(body, is_html=True)" in patched
    assert "return await response.text()" not in patched
    assert patched.startswith("before\n")
    assert patched.endswith("after\n")


def test_patch_rejects_unknown_or_already_patched_source():
    module = load_patch_module()

    for source in ("unrelated", module.NEW):
        try:
            module.patch_source(source)
        except ValueError as exc:
            assert "expected one" in str(exc)
        else:
            raise AssertionError("unexpected source must be rejected")
