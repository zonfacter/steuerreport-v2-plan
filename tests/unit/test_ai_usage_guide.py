from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import tomllib

from pypdf import PdfReader

from steuerreport_v2.contracts.ai import AiTaskCreate


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ai_usage_guide", ROOT / "scripts/generate_ai_usage_guide_v2.py")
GUIDE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUIDE)


def test_ai_usage_guide_and_markdown_are_current():
    for name, content in GUIDE.render().items():
        assert (ROOT / name).read_bytes() == content, name


def test_guide_covers_each_task_type_without_claiming_special_engines():
    source = (ROOT / "frontend/src/AiWorkspace.tsx").read_text()
    types = {value for _label, value in GUIDE.TYPES}
    assert types == {"review", "risk_scan", "import_mapping", "documentation"}
    for value in types:
        assert f'<option value="{value}">' in source
    assert {case["type"] for case in GUIDE.CASES} == types
    assert len(GUIDE.CASES) == 6
    assert "nur organisatorische Kennzeichnungen" in GUIDE.TYPE_NOTE


def test_guide_describes_real_input_limits_privacy_and_no_automatic_context():
    metadata = AiTaskCreate.model_fields["prompt"].metadata
    assert any(getattr(item, "max_length", None) == 32000 for item in metadata)
    text = (ROOT / "docs/KI_EINSATZLEITFADEN.md").read_text()
    for fragment in (
        "32000", "nicht automatisch anonymisiert", "keine SQL-", "keine angeschlossene Websuche",
        "nicht automatisch als Chatverlauf", "kein Pruefnachweis", "kein garantiert exakter Summenabgleich",
        "keine steuerliche oder rechtliche Freigabe", "Seed-Phrasen", "lokal im Aufgabenverlauf",
    ):
        assert fragment.lower() in text.lower(), fragment
    assert '/ki-einsatzleitfaden.html' in (ROOT / "frontend/src/AiWorkspace.tsx").read_text()


class GuideLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


def test_guide_has_unique_anchors_and_shipped_local_document_links():
    parser = GuideLinks()
    parser.feed((ROOT / "frontend/public/ki-einsatzleitfaden.html").read_text())
    assert len(parser.ids) == len(set(parser.ids))
    for link in parser.links:
        if link.startswith("#"):
            assert link[1:] in parser.ids
        elif link.startswith("/") and link.split("#")[0] != "/":
            assert (ROOT / "frontend/public" / link.split("#")[0].lstrip("/")).is_file(), link


def test_usage_pdf_is_readable_and_within_page_limit():
    pdf = PdfReader(ROOT / "frontend/public/ki-einsatzleitfaden.pdf")
    assert 1 <= len(pdf.pages) <= 100
    text = " ".join(" ".join(page.extract_text() for page in pdf.pages).split())
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert f"Version {version}" in text
    for fragment in ("KI: Einsatz und Grenzen", "Konkrete Einsatzfaelle", "32000", "nicht automatisch anonymisiert", "organisatorische Kennzeichnungen"):
        assert fragment in text, fragment
