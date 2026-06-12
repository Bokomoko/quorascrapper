"""Health probe tests."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from quorascrapper.ops.healthcheck import check_serve, check_serve_deps, check_serve_liveness


def test_check_serve_liveness_ok():
    payload = json.dumps({"ok": True, "service": "qsbk-serve", "kafka": True}).encode()
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = payload
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)

    with patch("quorascrapper.ops.healthcheck.urllib.request.urlopen", return_value=resp):
        assert check_serve_liveness(ping_url="http://127.0.0.1:8765/ping") == 0


def test_check_serve_liveness_not_ok():
    payload = json.dumps({"ok": False}).encode()
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = payload
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)

    with patch("quorascrapper.ops.healthcheck.urllib.request.urlopen", return_value=resp):
        assert check_serve_liveness(ping_url="http://127.0.0.1:8765/ping") == 1


def test_check_serve_is_liveness_only():
    with patch("quorascrapper.ops.healthcheck.check_serve_liveness", return_value=0) as ping:
        with patch("quorascrapper.ops.healthcheck.check_subscriber") as sub:
            assert check_serve() == 0
            ping.assert_called_once()
            sub.assert_not_called()


def test_check_serve_deps_runs_subscriber_and_ping():
    with patch("quorascrapper.ops.healthcheck.check_subscriber", return_value=0) as sub:
        with patch("quorascrapper.ops.healthcheck.check_serve_liveness", return_value=0) as ping:
            assert check_serve_deps() == 0
            sub.assert_called_once()
            ping.assert_called_once()
