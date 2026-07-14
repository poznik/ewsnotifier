from __future__ import annotations

from datetime import UTC, datetime

from notifier.utils import (
    build_preview,
    contains_keyword,
    escape_markdown_v2,
    extract_url,
    format_duration,
    format_markdown_quote,
)


class TestEscapeMarkdownV2:
    def test_escapes_special_characters(self):
        assert escape_markdown_v2("a_b*c[d](e)") == r"a\_b\*c\[d\]\(e\)"

    def test_escapes_backslash(self):
        assert escape_markdown_v2("a\\b") == "a\\\\b"

    def test_plain_text_unchanged(self):
        assert escape_markdown_v2("Привет мир") == "Привет мир"


class TestExtractUrl:
    def test_none_and_empty(self):
        assert extract_url(None) is None
        assert extract_url("") is None
        assert extract_url("нет ссылок") is None

    def test_plain_url(self):
        assert extract_url("Ссылка: https://example.com/meet все") == "https://example.com/meet"

    def test_angle_brackets_stripped(self):
        # Outlook locations often look like "Teams <https://…>" (finding C2)
        assert (
            extract_url("Teams-встреча <https://teams.microsoft.com/l/meetup-join/abc>")
            == "https://teams.microsoft.com/l/meetup-join/abc"
        )

    def test_trailing_punctuation_stripped(self):
        assert extract_url("(https://example.com/x),") == "https://example.com/x"
        assert extract_url("см. https://example.com/x.") == "https://example.com/x"

    def test_inner_punctuation_kept(self):
        assert (
            extract_url("https://example.com/a?b=1&c=2#frag далее")
            == "https://example.com/a?b=1&c=2#frag"
        )


class TestFormatDuration:
    def _dt(self, minutes: int) -> tuple[datetime, datetime]:
        start = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
        from datetime import timedelta

        return start, start + timedelta(minutes=minutes)

    def test_minutes_only(self):
        assert format_duration(*self._dt(45)) == "45 мин"

    def test_hours_only(self):
        assert format_duration(*self._dt(120)) == "2 ч"

    def test_hours_and_minutes(self):
        assert format_duration(*self._dt(90)) == "1 ч 30 мин"

    def test_negative_clamped(self):
        start, end = self._dt(30)
        assert format_duration(end, start) == "0 мин"


class TestContainsKeyword:
    def test_no_substring_false_positive(self):
        assert not contains_keyword("everything is broken", ["ok"])

    def test_whole_word_match(self):
        assert contains_keyword("all is ok now", ["ok"])

    def test_case_insensitive_cyrillic(self):
        assert contains_keyword("СРОЧНО ответить", ["срочно"])

    def test_hash_tag_keyword(self):
        assert contains_keyword("см. #warning тут", ["#warning"])
        assert not contains_keyword("см. #warnings тут", ["#warning"])

    def test_phrase(self):
        assert contains_keyword("нужно asap please сделать", ["asap please"])

    def test_empty_keywords(self):
        assert not contains_keyword("любой текст", [])
        assert not contains_keyword("любой текст", ["", "  "])


class TestBuildPreview:
    def test_html_stripped(self):
        text = "<p>Первая строка</p><p>Вторая &amp; строка</p>"
        assert build_preview(text) == "Первая строка\nВторая & строка"

    def test_cid_and_noise_removed(self):
        text = "[cid:image001.png@01D]\nВажный текст\n[image: logo]"
        assert build_preview(text) == "Важный текст"

    def test_urls_removed(self):
        text = "Смотри https://example.com/very/long тут"
        assert build_preview(text) == "Смотри   тут"

    def test_max_lines(self):
        text = "один\nдва\nтри\nчетыре"
        assert build_preview(text, max_lines=2) == "один\nдва"

    def test_max_chars(self):
        text = "x" * 500
        assert len(build_preview(text, max_chars=200)) <= 200


class TestFormatMarkdownQuote:
    def test_quote_lines(self):
        assert format_markdown_quote("a\nb") == "> a\n> b"

    def test_empty(self):
        assert format_markdown_quote("") == ""
