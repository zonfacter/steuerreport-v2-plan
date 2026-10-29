#!/usr/bin/env python3
"""Render the shipped AI usage guide PDF from its versioned HTML source."""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend/public/ki-einsatzleitfaden.html"
PDF = ROOT / "frontend/public/ki-einsatzleitfaden.pdf"


def render() -> bytes:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(HTML.as_uri(), wait_until="load")
            return page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            browser.close()


def main() -> None:
    PDF.write_bytes(render())
    print(f"KI-Leitfaden-PDF aktualisiert: {PDF.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
