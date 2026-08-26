#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


TARGET = Path("/app/backend/open_webui/utils/middleware.py")
OLD_IMPORT = "from concurrent.futures import ThreadPoolExecutor\n"
NEW_IMPORT = OLD_IMPORT + "from datetime import datetime, timezone\nfrom html import escape\n"
OLD_SOURCE = """            src_name = source.get('source', {}).get('name')
            src_type = source.get('source', {}).get('type')
            src_rid = source.get('source', {}).get('id')
            body = doc if include_content else ''
            context_string += (
                f'<source id="{source_ids[source_id]}"'
                + (f' name="{src_name}"' if src_name else '')
                + (f' resource-type="{src_type}"' if src_type else '')
                + (f' resource-id="{src_rid}"' if src_rid else '')
                + f'>{body}</source>\\n'
            )
"""
NEW_SOURCE = """            src_name = source.get('source', {}).get('name')
            src_type = source.get('source', {}).get('type')
            src_rid = source.get('source', {}).get('id')
            src_url = meta.get('source')
            if not isinstance(src_url, str) or not src_url.startswith(('http://', 'https://')):
                src_url = None
            body = doc if include_content else ''
            if src_url and include_content:
                retrieved_at_utc = datetime.now(timezone.utc).date().isoformat()
                body = (
                    f'Source URL: {src_url}\\n'
                    f'Source retrieved at UTC: {retrieved_at_utc}\\n{body}'
                )
            context_string += (
                f'<source id="{source_ids[source_id]}"'
                + (f' name="{src_name}"' if src_name else '')
                + (f' url="{escape(src_url, quote=True)}"' if src_url else '')
                + (f' resource-type="{src_type}"' if src_type else '')
                + (f' resource-id="{src_rid}"' if src_rid else '')
                + f'>{body}</source>\\n'
            )
"""


def patch_source(source: str) -> str:
    import_count = source.count(OLD_IMPORT)
    block_count = source.count(OLD_SOURCE)
    if import_count != 1 or block_count != 1:
        raise ValueError(
            f"expected one middleware import and source block, found {import_count}/{block_count}"
        )
    return source.replace(OLD_IMPORT, NEW_IMPORT, 1).replace(OLD_SOURCE, NEW_SOURCE, 1)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else TARGET
    source = path.read_text(encoding="utf-8")
    path.write_text(patch_source(source), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
