"""Kafka consumer that stores messages in MongoDB.

Retry policy:
- stored: Mongo write succeeded -> commit Kafka offset
- skipped: invalid JSON/payload -> commit offset (poison pill)
- retry: PyMongoError -> do not commit (redelivery)
"""

from __future__ import annotations

import json
from typing import Literal, Optional

from confluent_kafka import Consumer, KafkaError  # type: ignore
from pymongo.errors import PyMongoError  # type: ignore

from quorascrapper.config import Settings
from quorascrapper.logging_setup import init_logging
from quorascrapper.subscriber.storage import connect_mongo, ensure_indexes, upsert_answer

logger = init_logging("subscriber")

ProcessResult = Literal["stored", "skipped", "retry"]


class KafkaMongoSubscriber:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        errors = self.settings.validate_subscriber()
        if errors:
            raise ValueError("; ".join(errors))

        self.consumer: Optional[Consumer] = None
        self.mongo_client = None
        self.mongo_collection = None

        self.messages_processed = 0
        self.messages_stored = 0
        self.errors_count = 0
        self.shutdown = False

    def setup_kafka_consumer(self) -> None:
        consumer_config = {
            "bootstrap.servers": self.settings.kafka_bootstrap,
            "group.id": self.settings.kafka_group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
        self.consumer = Consumer(consumer_config)
        self.consumer.subscribe([self.settings.kafka_topic])
        logger.info(
            "kafka_consumer_initialized",
            extra={
                "event": "kafka_consumer_initialized",
                "broker": self.settings.kafka_bootstrap,
                "topic": self.settings.kafka_topic,
            },
        )

    def setup_mongodb_connection(self) -> None:
        self.mongo_client, self.mongo_collection = connect_mongo(self.settings)
        ensure_indexes(self.mongo_collection)
        logger.info(
            "mongodb_connected",
            extra={
                "event": "mongodb_connected",
                "database": self.settings.mongodb_database,
                "collection": self.settings.mongodb_collection,
            },
        )

    def process_message(self, message_value: str) -> ProcessResult:
        try:
            data = json.loads(message_value)
        except json.JSONDecodeError as exc:
            logger.error("invalid_json", extra={"event": "invalid_json", "error": str(exc)})
            self.errors_count += 1
            return "skipped"

        if not isinstance(data, dict) or not data.get("url"):
            logger.error(
                "invalid_payload",
                extra={"event": "invalid_payload", "preview": message_value[:100]},
            )
            self.errors_count += 1
            return "skipped"

        try:
            upsert_answer(self.mongo_collection, data)
        except PyMongoError as exc:
            logger.error("mongodb_error", extra={"event": "mongodb_error", "error": str(exc)})
            self.errors_count += 1
            return "retry"

        self.messages_stored += 1
        return "stored"

    def consume_messages(self) -> None:
        logger.info("consumer_loop_start", extra={"event": "consumer_loop_start"})
        while not self.shutdown:
            msg = self.consumer.poll(timeout=1.0)
            if msg is None:
                continue

            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error(
                        "kafka_error",
                        extra={"event": "kafka_error", "error": str(msg.error())},
                    )
                    self.errors_count += 1
                continue

            self.messages_processed += 1
            message_value = msg.value().decode("utf-8")
            outcome = self.process_message(message_value)
            if outcome in ("stored", "skipped"):
                self.consumer.commit(message=msg, asynchronous=False)

            if self.messages_processed % 10 == 0:
                self.print_stats()

    def print_stats(self) -> None:
        logger.info(
            "stats",
            extra={
                "event": "stats",
                "processed": self.messages_processed,
                "stored": self.messages_stored,
                "errors": self.errors_count,
            },
        )

    def cleanup(self) -> None:
        logger.info("cleanup", extra={"event": "cleanup"})
        if self.consumer:
            try:
                self.consumer.close()
            except Exception as exc:
                logger.error("Error closing Kafka consumer: %s", exc)
        if self.mongo_client:
            try:
                self.mongo_client.close()
            except Exception as exc:
                logger.error("Error closing MongoDB connection: %s", exc)
        self.print_stats()

    def run(self) -> int:
        try:
            logger.info("subscriber_start", extra={"event": "subscriber_start"})
            self.setup_kafka_consumer()
            self.setup_mongodb_connection()
            self.consume_messages()
        except Exception as exc:
            logger.error("Failed to run subscriber: %s", exc)
            return 1
        finally:
            self.cleanup()
        return 0
