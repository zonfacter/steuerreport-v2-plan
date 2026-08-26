from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = ROOT / "integrations/openwebui/patch_web_rag_raw_query.py"


def load_patch_module():
    spec = importlib.util.spec_from_file_location("openwebui_web_rag_raw_query_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patch_keeps_raw_user_question_as_retrieval_query():
    module = load_patch_module()
    patched = module.patch_source("before\n" + module.OLD + "after\n")

    assert "raw_query = get_last_user_message" in patched
    assert "web_search_only = bool(files)" in patched
    assert "queries = [raw_query]" in patched
    assert "queries.append(raw_query)" in patched
    assert module.OLD not in patched


def test_patch_rejects_unknown_or_already_patched_source():
    module = load_patch_module()
    for source in ("unrelated", module.NEW):
        try:
            module.patch_source(source)
        except ValueError as exc:
            assert "expected one" in str(exc)
        else:
            raise AssertionError("unexpected source must be rejected")
