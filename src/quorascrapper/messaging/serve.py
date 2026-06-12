"""POST extension exports to a running ``qsbk serve`` instance."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from quorascrapper.messaging.base import BaseSender

DEFAULT_SERVE_URL = "http://127.0.0.1:8765"


class ServeSender(BaseSender):
    def __init__(self, base_url: str | None = None, *, timeout: float = 120.0):
        self.base_url = (
            base_url or os.getenv("QSBK_SERVE_URL") or DEFAULT_SERVE_URL
        ).rstrip("/")
        self.timeout = timeout
        self._batch: list[dict] = []
        self.last_report: dict | None = None

    def send(self, payload: dict) -> None:
        self._batch.append(payload)

    def flush(self) -> None:
        if not self._batch:
            self.last_report = {
                "published": 0,
                "skipped": 0,
                "skipped_mongo": 0,
                "urls": [],
            }
            return

        body = json.dumps({"answers": self._batch}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/upsert",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                self.last_report = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"qsbk serve upsert failed ({exc.code}): {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"qsbk serve not reachable at {self.base_url}: {exc.reason}"
            ) from exc
        finally:
            self._batch = []

    def close(self) -> None:
        return None
