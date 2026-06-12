import json
import logging

from quorascrapper.scraper import graphql

logger = logging.getLogger("test")


def test_qtext_to_plain_from_string():
    doc = json.dumps({"sections": [{"spans": [{"text": "Hello "}, {"text": "world"}]}]})
    assert graphql.qtext_to_plain(doc) == "Hello world"


def test_qtext_to_plain_multi_section_and_empty():
    doc = {"sections": [{"spans": [{"text": "a"}]}, {"spans": [{"text": "b"}]}]}
    assert graphql.qtext_to_plain(doc) == "a\nb"
    assert graphql.qtext_to_plain(None) == ""
    assert graphql.qtext_to_plain("") == ""


def test_build_request_body_matches_capture():
    body = json.loads(
        graphql.build_request_body(26316467, "deadbeef", first=3, after="5")
    )
    assert body["queryName"] == graphql.ANSWERS_QUERY_NAME
    assert body["variables"] == {
        "uid": 26316467,
        "first": 3,
        "answerFilterTid": None,
        "after": "5",
    }
    assert body["extensions"] == {"hash": "deadbeef"}


def test_build_request_body_omits_after_when_none():
    body = json.loads(graphql.build_request_body(1, "h", first=10, after=None))
    assert "after" not in body["variables"]


def _make_response(cursor_end, has_next, nodes):
    return {
        "data": {
            "user": {
                graphql.ANSWERS_CONNECTION_KEY: {
                    "pageInfo": {"endCursor": cursor_end, "hasNextPage": has_next},
                    "edges": [{"node": n} for n in nodes],
                }
            }
        }
    }


def test_extract_answers_connection_fallback():
    resp = {"data": {"user": {"someOtherConn": {"edges": [], "pageInfo": {}}}}}
    conn = graphql.extract_answers_connection(resp)
    assert conn is not None and "edges" in conn
    assert graphql.extract_answers_connection({}) is None


def test_map_edge_to_payload():
    node = {
        "url": "https://pt.quora.com/Foo/answer/123",
        "aid": 123,
        "numUpvotes": 6,
        "numViews": 122,
        "numDisplayComments": 8,
        "isPinned": False,
        "creationTime": 1774022120910669,
        "question": {
            "title": json.dumps({"sections": [{"spans": [{"text": "Q?"}]}]}),
            "url": "https://pt.quora.com/Foo",
        },
        "content": json.dumps({"sections": [{"spans": [{"text": "Answer body"}]}]}),
    }
    p = graphql.map_edge_to_payload(node)
    assert p["url"] == node["url"]
    assert p["question_title"] == "Q?"
    assert p["answer_text"] == "Answer body"
    assert p["answer_preview"] == "Answer body"
    assert p["num_upvotes"] == 6
    assert p["question_url"] == "https://pt.quora.com/Foo"
    # isPinned False is dropped by the empty-value filter only for None/""
    assert graphql.map_edge_to_payload({}) is None


def test_extract_page_context_parses_page_source():
    src = (
        'window.ansFrontendGlobals.earlySettings = {"formkey": "abc123", "x": 1};'
        '..."revision": "rev999", ...'
        '"rootQueryVariables": {"uid": 26316467, "initialTab": "Answers"}'
    )
    ctx = graphql.extract_page_context(None, page_source=src)
    assert ctx == {"uid": 26316467, "formkey": "abc123", "revision": "rev999"}


class FakeDriver:
    """Returns canned GraphQL responses in sequence for execute_async_script."""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def set_script_timeout(self, _):
        pass

    def execute_async_script(self, _js, endpoint, headers, body):
        self.calls.append(json.loads(body)["variables"].get("after"))
        page = self._pages.pop(0)
        return {"ok": True, "status": 200, "text": json.dumps(page)}


def test_paginate_answers_walks_cursor_until_done():
    pages = [
        _make_response("5", True, [{"url": "u1", "aid": 1}, {"url": "u2", "aid": 2}]),
        _make_response("8", False, [{"url": "u3", "aid": 3}]),
    ]
    driver = FakeDriver(pages)
    out = list(
        graphql.paginate_answers(
            driver,
            profile_url="https://pt.quora.com/profile/Foo/answers",
            uid=1,
            formkey="fk",
            query_hash="h",
            revision="r",
            page_size=2,
            limit=100,
            logger=logger,
        )
    )
    assert [p["url"] for p in out] == ["u1", "u2", "u3"]
    # First request had no cursor, second used endCursor "5".
    assert driver.calls == [None, "5"]


def test_paginate_answers_respects_limit():
    pages = [_make_response("5", True, [{"url": "u1"}, {"url": "u2"}, {"url": "u3"}])]
    driver = FakeDriver(pages)
    out = list(
        graphql.paginate_answers(
            driver,
            profile_url="https://pt.quora.com/profile/Foo/answers",
            uid=1,
            formkey="fk",
            query_hash="h",
            revision=None,
            page_size=10,
            limit=2,
            logger=logger,
        )
    )
    assert len(out) == 2
