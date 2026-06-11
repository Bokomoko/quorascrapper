import json
import sys
from typing import Any

from quorascrapper.logging_setup import init_logging
from quorascrapper.messaging.base import BaseSender

_sender_logger = init_logging("sender")


class StdoutSender(BaseSender):
    def __init__(self, stream=None):
        self._stream = stream or sys.stdout

    def _send(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        _sender_logger.info(
            "stdout_send", extra={"event": "stdout_send", "len": len(line)}
        )
        self._stream.write(line + "\n")
        self._stream.flush()
