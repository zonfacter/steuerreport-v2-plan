from bs4 import BeautifulSoup
import extract_msg


def test_msg_parser_dependencies_and_css_selector_are_available():
    assert extract_msg.openMsg
    soup = BeautifulSoup('<div><p class="item">Text</p></div>', "html.parser")
    assert soup.select_one("div > p.item").get_text() == "Text"
