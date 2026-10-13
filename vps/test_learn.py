import datetime as dt
from learn import parse_article, sm2

ART = """# Title Here

**TL;DR**
- one
- two

## Key takeaways
1. **Bold** point A
2. point B

## Quiz

**1. What is X?**
a) foo b) bar
<details><summary>Answer</summary><b>b.</b> Because bar.</details>

**2. Explain why:** Y happens.
<details><summary>Answer</summary>Because Z.</details>
"""


def test_parse_article():
    title, tldr, quiz, takeaways = parse_article(ART)
    assert title == "Title Here" and tldr == ["one", "two"] and takeaways == ["**Bold** point A", "point B"]
    assert quiz == [("What is X? a) foo b) bar", "b. Because bar."), ("Explain why: Y happens.", "Because Z.")]


def test_sm2_intervals_grow_and_reset_on_fail():
    card = {"ease": 2.5, "interval": 0, "reps": 0, "lapses": 0}
    e, i, r, l, due = sm2(card, 4, on="2026-01-01")
    assert (i, r, due) == (1, 1, "2026-01-02")
    e, i, r, l, _ = sm2({"ease": e, "interval": i, "reps": r, "lapses": l}, 4, on="2026-01-02")
    assert (i, r) == (6, 2)
    e, i, r, l, _ = sm2({"ease": e, "interval": i, "reps": r, "lapses": l}, 4, on="2026-01-08")
    assert i == 15
    _, i, r, l, _ = sm2({"ease": e, "interval": i, "reps": r, "lapses": l}, 1, on="2026-01-23")
    assert (i, r, l) == (1, 0, 1)


def test_parse_quiz_in_summary_variant():
    art = "# T\n\n## Quiz\n\n<details><summary>1. Why A?</summary>Because <b>B</b>.</details>\n"
    assert parse_article(art)[2] == [("Why A?", "Because B.")]


def test_theme_and_streak(tmp_path, monkeypatch):
    import learn
    assert learn.theme_of({"path": "sango/x/article.md", "title": "Masterclass On Loans", "tldr": "[]"}) == "Loans, EMIs & debt"
    assert learn.theme_of({"path": "youtube/y/article.md", "title": "Follow the Institution",
                           "tldr": '["Risk 1% per trade; book at 1:4"]'}) == "Trading"
    assert learn.theme_of({"path": "c4/strategic-hrm/03/article.md", "title": "x", "tldr": "[]"}) == "Strategic Hrm"
    monkeypatch.setattr(learn, "DB", tmp_path / "t.db")
    con = learn.db()
    for day in ["2026-01-01", "2026-01-02", "2026-01-04"]:
        con.execute("insert into activity values(?,?,?,?)", (day, "quiz", "1", day))
    assert learn.streak(con, on="2026-01-02") == 2      # today counted
    assert learn.streak(con, on="2026-01-03") == 2      # today empty -> count from yesterday
    assert learn.streak(con, on="2026-01-05") == 1      # the gap on the 3rd breaks the chain


def test_url_of(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_DOMAIN", "notes.example.com")
    import learn
    monkeypatch.setattr(learn, "ROOT", tmp_path)
    assert learn.url_of("sango/x/article.md") == "sango/x/article.md"     # site not built yet
    (tmp_path / "slugs.json").write_text('{"sango/x/article.md": "/sango/hello/"}')
    assert learn.url_of("sango/x/article.md") == "https://notes.example.com/sango/hello/"
