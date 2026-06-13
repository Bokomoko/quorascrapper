import json

from quorascrapper.filter.core import (
    canonical_profile_url,
    dedupe_rows,
    load_export,
    normalize_row,
    parse_csv,
    parse_jsonl,
    profile_userid,
    to_csv,
    url_hash,
)


def test_answer_url_kind():
    from quorascrapper.filter.core import answer_url_kind

    assert (
        answer_url_kind(
            "https://pt.quora.com/profile/Jo%C3%A3o/answer/123456789012-Some-slug"
        )
        == "profile"
    )
    assert (
        answer_url_kind(
            "https://pt.quora.com/Quais-foram-os-melhores-governos/answer/Jo%C3%A3o-Eurico"
        )
        == "question"
    )
    assert answer_url_kind("https://example.com/nope") == "invalid"


def test_url_hash_stable():
    h = url_hash("https://pt.quora.com/answer/123")
    assert len(h) == 32
    assert h == url_hash("https://pt.quora.com/answer/123")


def test_parse_csv_and_add_hash():
    raw = "url,seen_at\nhttps://pt.quora.com/answer/1,2026-01-01T00:00:00Z\n"
    rows = parse_csv(raw)
    assert len(rows) == 1
    assert rows[0]["hash"] == url_hash("https://pt.quora.com/answer/1")
    assert rows[0]["seen_at"] == "2026-01-01T00:00:00Z"


def test_parse_jsonl_skips_non_answer():
    raw = (
        '{"url":"https://pt.quora.com/question/q"}\n'
        '{"url":"https://pt.quora.com/answer/abc"}\n'
    )
    rows = parse_jsonl(raw)
    assert len(rows) == 1
    assert "/answer/" in rows[0]["url"]


def test_dedupe_by_hash():
    row = {"url": "https://x/a/1", "hash": url_hash("https://x/a/1")}
    assert len(dedupe_rows([row, row])) == 1


def test_load_export_jsonl_file(tmp_path):
    p = tmp_path / "export.jsonl"
    p.write_text('{"url":"https://pt.quora.com/answer/x"}\n', encoding="utf-8")
    rows = load_export(p)
    assert len(rows) == 1
    assert "hash" in rows[0]


def test_load_export_json_document(tmp_path):
    p = tmp_path / "export.json"
    p.write_text(
        json.dumps(
            {
                "answers": [
                    {
                        "question_title": "What is X?",
                        "answer_url": "https://pt.quora.com/answer/abc",
                        "seen_at": "2026-01-01T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = load_export(p)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://pt.quora.com/answer/abc"
    assert rows[0]["question_title"] == "What is X?"


def test_normalize_row_passes_through_profile_fields():
    row = normalize_row(
        {
            "url": "https://pt.quora.com/profile/alice/answer/1",
            "userid": "deadbeef",
            "profile_name": "alice",
            "profile_url": "https://pt.quora.com/profile/alice",
            "profile_display_name": "Alice A.",
            "profile_answer_count": 42,
        }
    )
    assert row is not None
    assert row["userid"] == "deadbeef"
    assert row["profile_name"] == "alice"
    assert row["profile_url"] == "https://pt.quora.com/profile/alice"
    assert row["profile_display_name"] == "Alice A."
    assert row["profile_answer_count"] == 42


def test_canonical_profile_url_normalizes_variants():
    base = "https://pt.quora.com/profile/Alice-Silva"
    assert canonical_profile_url(base) == base
    assert canonical_profile_url(base + "/answers") == base
    assert canonical_profile_url(base + "/answers/") == base
    assert canonical_profile_url(base + "/questions") == base
    assert canonical_profile_url(base + "/") == base
    assert canonical_profile_url(base + "?foo=1#frag") == base
    # host lowercased + scheme forced to https
    assert canonical_profile_url("http://PT.Quora.com/profile/Alice-Silva") == base
    # scheme-less input is handled best-effort
    assert canonical_profile_url("pt.quora.com/profile/Alice-Silva/answers") == base
    assert canonical_profile_url("") == ""


def test_profile_userid_is_stable_across_variants():
    base = "https://pt.quora.com/profile/Alice-Silva"
    uid = profile_userid(base)
    assert uid == url_hash(base)
    assert len(uid) == 32
    assert profile_userid(base + "/answers") == uid
    assert profile_userid(base + "/answers/") == uid
    assert profile_userid(base + "/") == uid
    assert profile_userid("http://PT.Quora.com/profile/Alice-Silva") == uid
    # different profile -> different userid
    assert profile_userid("https://pt.quora.com/profile/Bob") != uid
    # path case is significant (Quora slugs are case-sensitive)
    assert profile_userid("https://pt.quora.com/profile/alice-silva") != uid


def test_to_csv_roundtrip():
    rows = [{"url": "https://x/a/1", "hash": "abc", "seen_at": "t"}]
    out = to_csv(rows)
    assert "url,hash,seen_at" in out
    assert "abc" in out
