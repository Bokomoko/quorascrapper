import json
import os
import sys
from typing import Optional


class BaseSender:
    def send(self, url: str) -> None:
        raise NotImplementedError

    def flush(self, timeout: Optional[float] = None) -> None:
        pass

    def close(self) -> None:
        pass


class StdoutSender(BaseSender):
    """Writes one JSON object per line to stdout: {"url": "..."}."""

    def __init__(self, stream=None):
        self._stream = stream or sys.stdout

    def send(self, url: str) -> None:
        obj = {"url": url}
        self._stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._stream.flush()


class KafkaSender(BaseSender):
    """Sends URLs to Kafka, one message per URL (value is the JSON line)."""

    def __init__(self, bootstrap: Optional[str] = None, topic: Optional[str] = None):
        try:
            from confluent_kafka import Producer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("confluent-kafka is required for KafkaSender") from e

        self.bootstrap = bootstrap or os.environ.get(
            "KAFKA_BOOTSTRAP", "192.168.1.116:9092"
        )
        self.topic = topic or os.environ.get("KAFKA_TOPIC", "quora-answers")
        self._producer = Producer({"bootstrap.servers": self.bootstrap})

    def send(self, url: str) -> None:
        payload = json.dumps({"url": url}, ensure_ascii=False).encode("utf-8")

        def delivery_report(err, msg):  # pragma: no cover (observability only)
            if err is not None:
                sys.stderr.write(f"[KAFKA][FAIL] {url[:100]} | Reason: {err}\n")
            # On success, stay silent to keep output minimal

        self._producer.produce(self.topic, value=payload, callback=delivery_report)
        # Let the producer poll to drive callbacks
        self._producer.poll(0)

    def flush(self, timeout: Optional[float] = None) -> None:
        if timeout is None:
            self._producer.flush()
        else:
            self._producer.flush(int(timeout))

    def close(self) -> None:
        try:
            self._producer.flush(5)
        except Exception:
            pass
