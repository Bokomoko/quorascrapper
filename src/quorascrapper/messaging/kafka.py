import json
from typing import Any, Optional

from quorascrapper.config import Settings
from quorascrapper.logging_setup import init_logging
from quorascrapper.messaging.base import BaseSender

_sender_logger = init_logging("sender")


class KafkaSender(BaseSender):
    def __init__(
        self,
        bootstrap: Optional[str] = None,
        topic: Optional[str] = None,
        settings: Optional[Settings] = None,
    ):
        try:
            from confluent_kafka import Producer  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("confluent-kafka is required for KafkaSender") from e

        cfg = settings or Settings.from_env()
        self.bootstrap = bootstrap or cfg.kafka_bootstrap
        self.topic = topic or cfg.kafka_topic
        if not self.bootstrap:
            raise ValueError("KAFKA_BOOTSTRAP is required for KafkaSender")
        self._producer = Producer({"bootstrap.servers": self.bootstrap})

    def _send(self, obj: dict[str, Any]) -> None:
        url = obj.get("url", "")
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")

        def delivery_report(err, msg):  # pragma: no cover
            if err is not None:
                _sender_logger.error(
                    "kafka_delivery_failed",
                    extra={
                        "event": "kafka_delivery_failed",
                        "url": str(url)[:100],
                        "error": str(err),
                    },
                )

        _sender_logger.info(
            "kafka_produce",
            extra={"event": "kafka_produce", "topic": self.topic, "size": len(payload)},
        )
        self._producer.produce(self.topic, value=payload, callback=delivery_report)
        self._producer.poll(0)

    def flush(self, timeout: Optional[float] = None) -> None:
        if timeout is None:
            self._producer.flush()
        else:
            self._producer.flush(timeout)

    def close(self) -> None:
        try:
            self._producer.poll(0.5)
            self._producer.flush(15)
            _sender_logger.info("kafka_close", extra={"event": "kafka_close"})
        except Exception:
            pass
