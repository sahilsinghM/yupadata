import os
os.environ.setdefault("NOTES_DOMAIN", "notes.example.com")
import json
import notes_site as notes


def test_urls_stable_and_unique():
    assert notes.url_for("c4/strategic-hrm/05/article.md", "Strategic HRM, Session 5: Performance Management") \
        == "/c4/strategic-hrm/05-performance-management/"
    assert notes.url_for("c4/fm/01/article.md", "Session 1 – Introduction to Financial Modelling") == "/c4/fm/01-introduction-to-financial-modelling/"
    slugs = notes.assign([("sango/a/article.md", "Loans & Money"), ("sango/b/article.md", "Loans & Money")], {})
    assert notes.slugify("Rokade's Strategy Doesn’t") == "rokades-strategy-doesnt"
    assert slugs == {"sango/a/article.md": "/sango/loans-money/", "sango/b/article.md": "/sango/loans-money-2/"}
    # an existing article keeps its url even if a newer one would want it
    assert notes.assign([("sango/c/article.md", "Loans & Money")], {"sango/b/article.md": "/sango/loans-money/"})["sango/c/article.md"] == "/sango/loans-money-2/"


def test_build(tmp_path, monkeypatch):
    lib = tmp_path / "library/sango/x"; (lib / "frames").mkdir(parents=True)
    (lib / "article.md").write_text("# Hello World\n\n![f](frames/0001.jpg)\n</script>")
    (lib / "frames/0001.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(notes, "LIB", tmp_path / "library"); monkeypatch.setattr(notes, "SLUGS", tmp_path / "slugs.json")
    monkeypatch.setattr(notes, "OUT", tmp_path / "www")
    notes.build()
    art = tmp_path / "www/sango/hello-world"
    assert (art / "frames/0001.jpg").exists() and "</script>\\n" not in (art / "index.html").read_text()
    assert json.loads((tmp_path / "www/search.json").read_text())[0]["u"] == "/sango/hello-world/"
    assert "Hello World" in (tmp_path / "www/sango/index.html").read_text()
