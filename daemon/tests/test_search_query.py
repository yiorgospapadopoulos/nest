import sqlite3

import pytest

from harness.search.query import MAX_TERMS, fts_query


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("login bug", '"login" "bug"'),
        ('"login bug" fix', '"login bug" "fix"'),
        ("auth*", '"auth"*'),
        ("auth**", '"auth"*'),
        # FTS operators and syntax are searched as plain words.
        ("NOT a OR b", '"NOT" "a" "OR" "b"'),
        ("col:value (x) ^y", '"col:value" "(x)" "^y"'),
        ('say "hi', '"say" "hi"'),
        # A quote inside a word starts a phrase.
        ('it"s', '"it" "s"'),
        ("  spaced\tout\n", '"spaced" "out"'),
    ],
)
def test_user_text_becomes_a_quoted_fts_query(text: str, expected: str) -> None:
    assert fts_query(text) == expected


@pytest.mark.parametrize("text", ["", "   ", '""', "*", "- + :", '"..."'])
def test_text_without_words_gives_no_query(text: str) -> None:
    assert fts_query(text) is None


def test_terms_beyond_the_limit_are_dropped() -> None:
    query = fts_query(" ".join(f"w{n}" for n in range(MAX_TERMS + 5)))

    assert query is not None
    assert query.count('"w') == MAX_TERMS


@pytest.mark.parametrize(
    "text",
    ['"', 'a"b"c', "NEAR(a b)", "a AND", "OR", "*a", "a:*", "{a b}: c", "'quoted'", "a - b", "ü*"],
)
def test_any_text_is_valid_fts_syntax(text: str) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(text)")
    conn.execute("INSERT INTO t VALUES ('a b c NEAR OR AND quoted über')")
    query = fts_query(text)

    if query is not None:
        conn.execute("SELECT * FROM t WHERE t MATCH ?", (query,)).fetchall()
