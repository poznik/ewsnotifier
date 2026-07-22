from __future__ import annotations

from datetime import UTC, datetime

from notifier.utils import (
    build_preview,
    contains_keyword,
    escape_markdown_v2,
    escape_markdown_v2_url,
    extract_url,
    format_duration,
    format_markdown_quote,
    format_minutes,
    plural_meetings,
    plural_minutes,
    url_host,
)


class TestEscapeMarkdownV2:
    def test_escapes_special_characters(self):
        assert escape_markdown_v2("a_b*c[d](e)") == r"a\_b\*c\[d\]\(e\)"

    def test_escapes_backslash(self):
        assert escape_markdown_v2("a\\b") == "a\\\\b"

    def test_plain_text_unchanged(self):
        assert escape_markdown_v2("Привет мир") == "Привет мир"


class TestEscapeMarkdownV2Url:
    def test_dots_dashes_underscores_left_intact(self):
        url = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x@thread.v2/0"
        assert escape_markdown_v2_url(url) == url

    def test_closing_paren_escaped(self):
        assert escape_markdown_v2_url("https://x.io/a(b)c") == "https://x.io/a(b\\)c"

    def test_backslash_escaped(self):
        assert escape_markdown_v2_url("https://x.io/a\\b") == "https://x.io/a\\\\b"


class TestUrlHost:
    def test_host_from_url(self):
        assert url_host("https://nexign.ktalk.ru/BSS_Project_Status") == "nexign.ktalk.ru"
        assert url_host("https://trueconf.nexign.com/r/42?x=1") == "trueconf.nexign.com"

    def test_www_stripped(self):
        assert url_host("https://www.example.com/x") == "example.com"

    def test_no_host_returns_none(self):
        assert url_host("not a url") is None
        assert url_host("nexign.ktalk.ru/x") is None  # scheme-less → no host parsed


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


class TestFormatMinutes:
    def test_minutes_only(self):
        assert format_minutes(45) == "45 мин"

    def test_hours_and_minutes(self):
        assert format_minutes(150) == "2 ч 30 мин"

    def test_negative_clamped(self):
        assert format_minutes(-5) == "0 мин"


class TestPluralMeetings:
    def test_agreement(self):
        assert plural_meetings(1) == "1 встреча"
        assert plural_meetings(2) == "2 встречи"
        assert plural_meetings(5) == "5 встреч"
        assert plural_meetings(11) == "11 встреч"  # teens are all "встреч"
        assert plural_meetings(21) == "21 встреча"


class TestPluralMinutes:
    def test_agreement(self):
        assert plural_minutes(1) == "1 минуту"
        assert plural_minutes(2) == "2 минуты"
        assert plural_minutes(5) == "5 минут"
        assert plural_minutes(11) == "11 минут"
        assert plural_minutes(21) == "21 минуту"
        assert plural_minutes(43) == "43 минуты"


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
