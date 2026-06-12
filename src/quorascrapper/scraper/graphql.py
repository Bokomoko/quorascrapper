"""GraphQL-based answer pagination for Quora user profiles.

Quora's profile "answers" tab is backed by a Relay persisted query
(``UserProfileAnswersMostRecent_RecentAnswers_Query``) served from
``POST /graphql/gql_para_POST``. It uses a simple offset cursor: ``after``
is an integer string and ``endCursor`` from each response feeds the next
request until ``pageInfo.hasNextPage`` is false.

We drive it through the *existing* authenticated Selenium session via an
in-page ``fetch`` so cookies, formkey and origin/referer are carried for
free instead of being reconstructed by hand. The pure mapping helpers
(``qtext_to_plain``, ``extract_answers_connection``, ``map_edge_to_payload``)
are kept side-effect free so they can be unit tested without a browser.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator
from urllib.parse import urlsplit

ANSWERS_QUERY_NAME = "UserProfileAnswersMostRecent_RecentAnswers_Query"
ANSWERS_CONNECTION_KEY = "recentPublicAndPinnedAnswersConnection"

_UID_RE = re.compile(r'"rootQueryVariables"\s*:\s*\{\s*"uid"\s*:\s*(\d+)')
_FORMKEY_RE = re.compile(r'"formkey"\s*:\s*"([0-9a-fA-F]+)"')
_REVISION_RE = re.compile(r'"revision"\s*:\s*"([\w-]+)"')

# Async in-page fetch. Selenium injects the completion callback as the last arg.
_FETCH_JS = """
const cb = arguments[arguments.length - 1];
const endpoint = arguments[0];
const headers = arguments[1];
const body = arguments[2];
fetch(endpoint, {
  method: 'POST',
  credentials: 'include',
  headers: headers,
  body: body,
})
  .then(function (r) {
    return r.text().then(function (t) { return {status: r.status, text: t}; });
  })
  .then(function (res) { cb({ok: true, status: res.status, text: res.text}); })
  .catch(function (e) { cb({ok: false, error: String(e)}); });
"""


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme or "https"
    return f"{scheme}://{parts.netloc}"


def endpoint_url(origin: str, query_name: str = ANSWERS_QUERY_NAME) -> str:
    return f"{origin}/graphql/gql_para_POST?q={query_name}"


def build_request_body(
    uid: int,
    query_hash: str,
    *,
    first: int,
    after: str | None,
    answer_filter_tid: Any = None,
) -> str:
    """Serialize the persisted-query POST body exactly as the page does."""
    variables: dict[str, Any] = {
        "uid": uid,
        "first": first,
        "answerFilterTid": answer_filter_tid,
    }
    if after is not None:
        variables["after"] = after
    return json.dumps(
        {
            "queryName": ANSWERS_QUERY_NAME,
            "variables": variables,
            "extensions": {"hash": query_hash},
        },
        ensure_ascii=False,
    )


def qtext_to_plain(qtext: Any) -> str:
    """Flatten Quora's qtext document (sections/spans) into plain text.

    Accepts either an already-parsed dict or the JSON string form found in
    ``node.content`` / ``question.title``.
    """
    if not qtext:
        return ""
    if isinstance(qtext, str):
        try:
            qtext = json.loads(qtext)
        except (ValueError, TypeError):
            return qtext.strip()
    if not isinstance(qtext, dict):
        return ""
    lines: list[str] = []
    for section in qtext.get("sections", []) or []:
        spans = section.get("spans", []) or []
        line = "".join(span.get("text", "") for span in spans)
        lines.append(line)
    return "\n".join(lines).strip()


def extract_answers_connection(response: dict[str, Any]) -> dict[str, Any] | None:
    """Return the answers connection dict (edges + pageInfo) or None."""
    if not isinstance(response, dict):
        return None
    user = (response.get("data") or {}).get("user") or {}
    conn = user.get(ANSWERS_CONNECTION_KEY)
    if isinstance(conn, dict):
        return conn
    # Fallback: locate any connection-shaped object with edges + pageInfo.
    for value in user.values():
        if isinstance(value, dict) and "edges" in value and "pageInfo" in value:
            return value
    return None


def map_edge_to_payload(node: dict[str, Any]) -> dict[str, Any] | None:
    """Map a single answer ``edge.node`` to a pipeline payload.

    The pipeline keys on ``url`` (hashed for dedupe); the remaining fields
    enrich the stored document. Returns None for nodes without a usable URL.
    """
    if not isinstance(node, dict):
        return None
    url = node.get("url") or node.get("permaUrl")
    if not url:
        return None

    question = node.get("question") or {}
    payload: dict[str, Any] = {
        "url": url,
        "aid": node.get("aid"),
        "question_title": qtext_to_plain(question.get("title")),
        "answer_text": qtext_to_plain(node.get("content")),
        "num_upvotes": node.get("numUpvotes"),
        "num_views": node.get("numViews"),
        "num_comments": node.get("numDisplayComments"),
        "num_shares": node.get("numShares"),
        "is_pinned": node.get("isPinned"),
        "creation_time": node.get("creationTime"),
        "updated_time": node.get("updatedTime"),
    }
    if question.get("url"):
        payload["question_url"] = question["url"]
    text = payload["answer_text"]
    if text:
        payload["answer_preview"] = text[:280]
    return {k: v for k, v in payload.items() if v not in (None, "")}


def extract_page_context(driver, page_source: str | None = None) -> dict[str, Any]:
    """Read uid / formkey / revision from the loaded profile page."""
    src = page_source if page_source is not None else (driver.page_source or "")
    uid_match = _UID_RE.search(src)
    formkey_match = _FORMKEY_RE.search(src)
    revision_match = _REVISION_RE.search(src)
    return {
        "uid": int(uid_match.group(1)) if uid_match else None,
        "formkey": formkey_match.group(1) if formkey_match else None,
        "revision": revision_match.group(1) if revision_match else None,
    }


def _fetch_page(
    driver,
    endpoint: str,
    headers: dict[str, str],
    body: str,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    try:
        driver.set_script_timeout(30)
    except Exception:
        pass
    result = driver.execute_async_script(_FETCH_JS, endpoint, headers, body)
    if not result or not result.get("ok"):
        logger.error(
            "graphql_fetch_failed",
            extra={"event": "graphql_fetch_failed", "error": (result or {}).get("error")},
        )
        return None
    if result.get("status") and int(result["status"]) >= 400:
        logger.error(
            "graphql_http_error",
            extra={"event": "graphql_http_error", "status": result.get("status")},
        )
        return None
    try:
        return json.loads(result.get("text") or "")
    except ValueError as exc:
        logger.error(
            "graphql_decode_error",
            extra={"event": "graphql_decode_error", "error": str(exc)},
        )
        return None


def paginate_answers(
    driver,
    *,
    profile_url: str,
    uid: int,
    formkey: str,
    query_hash: str,
    revision: str | None,
    page_size: int,
    limit: int,
    logger: logging.Logger,
    start_after: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield answer payloads by walking the cursor until exhausted or limit hit."""
    origin = origin_of(profile_url)
    endpoint = endpoint_url(origin)
    headers = {"content-type": "application/json", "quora-formkey": formkey}
    if revision:
        headers["quora-revision"] = revision

    after = start_after
    emitted = 0
    page = 0
    while emitted < limit:
        body = build_request_body(uid, query_hash, first=page_size, after=after)
        response = _fetch_page(driver, endpoint, headers, body, logger)
        if response is None:
            break
        conn = extract_answers_connection(response)
        if conn is None:
            logger.error(
                "graphql_no_connection",
                extra={"event": "graphql_no_connection", "page": page},
            )
            break

        edges = conn.get("edges") or []
        for edge in edges:
            if emitted >= limit:
                break
            payload = map_edge_to_payload((edge or {}).get("node") or {})
            if payload:
                emitted += 1
                yield payload

        page_info = conn.get("pageInfo") or {}
        page += 1
        logger.info(
            "graphql_page_done",
            extra={
                "event": "graphql_page_done",
                "page": page,
                "edges": len(edges),
                "emitted": emitted,
                "has_next": page_info.get("hasNextPage"),
            },
        )
        if not page_info.get("hasNextPage"):
            break
        next_after = page_info.get("endCursor")
        if not next_after or next_after == after:
            logger.warning("graphql_cursor_stalled", extra={"event": "graphql_cursor_stalled"})
            break
        after = str(next_after)
