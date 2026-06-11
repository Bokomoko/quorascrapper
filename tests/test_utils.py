from quorascrapper.scraper.stats import (
    DEFAULT_PROFILE_URL,
    normalize_number,
    resolve_profile_url,
)


def test_normalize_number_basic():
    assert normalize_number("1") == 1
    assert normalize_number("123") == 123
    assert normalize_number("1,234") == 1234
    assert normalize_number("  987 \n") == 987


def test_normalize_number_mil():
    assert normalize_number("14 mil") == 14000
    assert normalize_number("14,7 mil") == 14700
    assert normalize_number("14.7 mil") == 14700


def test_resolve_profile_url_precedence():
    default = DEFAULT_PROFILE_URL
    assert resolve_profile_url("cli", "env", default) == "cli"
    assert resolve_profile_url(None, "env", default) == "env"
    assert resolve_profile_url(None, None, default) == default
