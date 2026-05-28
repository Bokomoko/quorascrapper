import hashlib
import json
import os
import sys
from typing import Any, Optional

from logging_setup import init_logging

_sender_logger = init_logging("sender")


class BaseSender:
    def send(self, obj: dict[str, Any]) -> None:
        """Public entry point: ensure hash and delegate to transport.

        - Accepts a JSON-able dict with at least {"url": str}
        - Always compute a 16-byte hex hash from the URL and set obj["hash"]
        - Delegates final delivery to subclass via _send
        """
        url = obj.get("url")
        if url:
            obj["hash"] = hashlib.blake2s(
                str(url).encode("utf-8"), digest_size=16
            ).hexdigest()
        self._send(obj)

    def _send(self, obj: dict[str, Any]) -> None:
        raise NotImplementedError

    def flush(self, timeout: Optional[float] = None) -> None:
        pass

    def close(self) -> None:
        pass


class StdoutSender(BaseSender):
    """Writes one JSON object per line to stdout: {"url": "..."}."""

    def __init__(self, stream=None):
        self._stream = stream or sys.stdout

    def _send(self, obj: dict[str, Any]) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        _sender_logger.info(
            "stdout_send", extra={"event": "stdout_send", "len": len(line)}
        )
        self._stream.write(line + "\n")
        self._stream.flush()


class KafkaSender(BaseSender):
    """Sends URLs to Kafka, one message per URL (value is the JSON line)."""

    def __init__(self, bootstrap: Optional[str] = None, topic: Optional[str] = None):
        try:
            from confluent_kafka import Producer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("confluent-kafka is required for KafkaSender") from e

        self.bootstrap = bootstrap or os.environ.get(
            "KAFKA_BOOTSTRAP", "bokomint.local:19092"
        )
        self.topic = topic or os.environ.get("KAFKA_TOPIC", "quora-answers")
        self._producer = Producer({"bootstrap.servers": self.bootstrap})

    def _send(self, obj: dict[str, Any]) -> None:
        url = obj.get("url", "")
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")

        def delivery_report(err, msg):  # pragma: no cover (observability only)
            if err is not None:
                _sender_logger.error(
                    "kafka_delivery_failed",
                    extra={
                        "event": "kafka_delivery_failed",
                        "url": str(url)[:100],
                        "error": str(err),
                    },
                )
            # On success, stay silent to keep output minimal

        _sender_logger.info(
            "kafka_produce",
            extra={"event": "kafka_produce", "topic": self.topic, "size": len(payload)},
        )
        self._producer.produce(self.topic, value=payload, callback=delivery_report)
        # Let the producer poll to drive callbacks
        self._producer.poll(0)

    def flush(self, timeout: Optional[float] = None) -> None:
        if timeout is None:
            self._producer.flush()
        else:
            # confluent_kafka expects seconds as float
            self._producer.flush(timeout)

    def close(self) -> None:
        try:
            # Drive delivery callbacks briefly then flush with a generous timeout
            self._producer.poll(0.5)
            self._producer.flush(15)
            _sender_logger.info("kafka_close", extra={"event": "kafka_close"})
        except Exception:
            pass
