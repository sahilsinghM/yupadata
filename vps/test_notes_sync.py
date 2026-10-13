from notes_sync import html_to_text, notion_title, safe_id


def test_html_to_text_keeps_structure():
    h = "<html><body><h1>Loans</h1><p>EMI = principal + interest</p><ul><li>fixed</li><li>floating</li></ul></body></html>"
    assert html_to_text(h) == "# Loans\nEMI = principal + interest\n- fixed\n- floating"


def test_notion_title_and_safe_id():
    page = {"properties": {"Name": {"type": "title", "title": [{"plain_text": "Trading "}, {"plain_text": "rules"}]}}}
    assert notion_title(page) == "Trading rules"
    assert safe_id("0-ABC!{x}/y") == "0-ABCxy"
