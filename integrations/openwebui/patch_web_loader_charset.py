#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


TARGET = Path("/app/backend/open_webui/retrieval/web/utils.py")
OLD = "                        return await response.text()\n"
NEW = """                        body = await response.read()
                        content_type = response.headers.get('Content-Type', '').lower()
                        if 'application/pdf' in content_type or body.startswith(b'%PDF-'):
                            from io import BytesIO
                            from pypdf import PdfReader

                            return '\\n\\n'.join(
                                page.extract_text() or '' for page in PdfReader(BytesIO(body)).pages
                            )
                        if response.charset:
                            return body.decode(response.charset, errors='replace')

                        # Some German primary sources declare their charset only
                        # in the HTML meta tag. Preserve that content for RAG.
                        from bs4 import UnicodeDammit

                        return (
                            UnicodeDammit(body, is_html=True).unicode_markup
                            or body.decode('utf-8', errors='replace')
                        )
"""


def patch_source(source: str) -> str:
    count = source.count(OLD)
    if count != 1:
        raise ValueError(f"expected one aiohttp text decoder, found {count}")
    return source.replace(OLD, NEW, 1)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TARGET
    source = path.read_text(encoding="utf-8")
    path.write_text(patch_source(source), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
