#!/usr/bin/env python3
"""Render the shipped import-format PDF from its generated HTML source."""
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend/public/importformate.html"
PDF = ROOT / "frontend/public/importformate.pdf"


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file://") else route.abort())
            page.goto(HTML.as_uri(), wait_until="load")
            PDF.write_bytes(page.pdf(format="A4", print_background=True, prefer_css_page_size=True))
        finally:
            browser.close()
    print(f"Importformat-PDF aktualisiert: {PDF.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
