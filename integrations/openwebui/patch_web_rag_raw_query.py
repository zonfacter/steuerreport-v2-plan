#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


TARGET = Path("/app/backend/open_webui/utils/middleware.py")
OLD = """        if len(queries) == 0:
            queries = [get_last_user_message(body['messages']) or '']

        try:
"""
NEW = """        raw_query = get_last_user_message(body['messages']) or ''
        web_search_only = bool(files) and all(
            item.get('type') == 'web_search' for item in files
        )
        if raw_query and web_search_only:
            queries = [raw_query]
        elif raw_query and raw_query not in queries:
            queries.append(raw_query)
        if len(queries) == 0:
            queries = [raw_query]

        try:
"""


def patch_source(source: str) -> str:
    count = source.count(OLD)
    if count != 1:
        raise ValueError(f"expected one retrieval-query fallback, found {count}")
    return source.replace(OLD, NEW, 1)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TARGET
    source = path.read_text(encoding="utf-8")
    path.write_text(patch_source(source), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
