"""Local HTTP server: extension checkmarks + Kafka ingest gateway."""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from quorascrapper.config import Settings, load_project_env
from quorascrapper.ops.serve_store import ClassifyReport, PublishReport, ServeState, validate_serve_settings

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 10 * 1024 * 1024


class QsbkHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, state: ServeState):
        self.state = state
        super().__init__(server_address, RequestHandlerClass)


class QsbkHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        print(f"[qsbk serve] {self.address_string()} - {format % args}", file=sys.stderr)

    @property
    def state(self) -> ServeState:
        return self.server.state  # type: ignore[attr-defined]

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Cache the preflight so streamed batch POSTs don't re-OPTIONS each time.
        # Chrome caps this at 7200s; that's plenty for a long backfill run.
        self.send_header("Access-Control-Max-Age", "7200")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            self._json_response(400, {"error": "empty request body"})
            return None
        if length > MAX_BODY_BYTES:
            self._json_response(413, {"error": "payload too large"})
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid JSON"})
            return None
        if not isinstance(data, dict):
            self._json_response(400, {"error": "JSON object expected"})
            return None
        return data

    def _json_response(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in ("/health", "/ping"):
            self._json_response(
                200,
                {
                    "ok": True,
                    "service": "qsbk-serve",
                    "kafka": bool(self.state.settings.kafka_bootstrap),
                },
            )
            return

        if path != "/known":
            self.send_response(404)
            self.end_headers()
            return

        # Optional ?profile_url=<encoded> scopes known/dedup to that profile's
        # own collection; absent → global default ("answers") behavior.
        profile_url = (parse_qs(parsed.query).get("profile_url") or [None])[0]
        self._json_response(200, self.state.known_snapshot(profile_url=profile_url))

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path not in ("/upsert", "/publish", "/check"):
            self.send_response(404)
            self.end_headers()
            return

        data = self._read_json_body()
        if data is None:
            return

        answers = data.get("answers")
        if answers is None and data.get("url"):
            answers = [data]
        if not isinstance(answers, list):
            self._json_response(400, {"error": "answers array required"})
            return

        force = bool(data.get("force", False))
        # Optional profile identity scopes dedup to the profile's own
        # collection; absent → global default ("answers") behavior.
        profile_url = data.get("profile_url") or None
        userid = data.get("userid") or None

        if path == "/check":
            try:
                report: ClassifyReport = self.state.classify_answers(
                    answers, force=force, profile_url=profile_url, userid=userid
                )
            except Exception as exc:
                print(f"[qsbk serve] POST /check failed: {exc}", file=sys.stderr)
                self._json_response(503, {"error": str(exc)})
                return
            print(
                f"[qsbk serve] POST /check {len(answers)} in → "
                f"{report.new_count} new, {report.skipped_count} skipped",
                file=sys.stderr,
            )
            self._json_response(200, report.as_dict())
            return

        try:
            report: PublishReport = self.state.publish_answers(
                answers, force=force, profile_url=profile_url, userid=userid
            )
        except Exception as exc:
            print(f"[qsbk serve] POST {path} failed: {exc}", file=sys.stderr)
            self._json_response(503, {"error": str(exc)})
            return

        print(
            f"[qsbk serve] POST {path} {len(answers)} in → "
            f"published {report.published}, skipped {report.skipped}",
            file=sys.stderr,
        )
        self._json_response(200, report.as_dict())


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    parser = argparse.ArgumentParser(
        prog="qsbk serve",
        description="Local API: GET /known (checkmarks), POST /upsert → Kafka (subscriber upserts Mongo).",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    errors = validate_serve_settings(settings)
    if errors:
        print("; ".join(errors), file=sys.stderr)
        return 1

    state = ServeState(settings)
    try:
        state.connect()
    except Exception as exc:
        print(f"Kafka setup failed: {exc}", file=sys.stderr)
        return 1

    base = f"http://{args.host}:{args.port}"
    server = QsbkHTTPServer((args.host, args.port), QsbkHandler, state)
    print(f"qsbk serve {base}")
    print(f"  GET  {base}/health  — ping (extension enables Kafka when ok)")
    print(f"  GET  {base}/ping    — alias of /health")
    print(f"  GET  {base}/known   — ingested URLs (from MongoDB)")
    print(f"  POST {base}/check   — classify new vs MongoDB duplicates")
    print(f"  POST {base}/upsert   — publish new answers to Kafka")
    print(f"  ingest: qsbk ingest export.json --sender serve")
    print(f"  run subscriber: quora-subscriber  (or docker compose)")
    print("  Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
        state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
