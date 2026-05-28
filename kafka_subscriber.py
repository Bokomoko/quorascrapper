#!/usr/bin/env python3
"""
Kafka Consumer for Quora Scraper - MongoDB Atlas Integration

Subscribes to Kafka messages from quora-answers topic and stores them in MongoDB Atlas.
Uses environment variables for configuration.

Environment Variables:
- KAFKA_BOOTSTRAP: Kafka broker address (default: bokomint.local:19092)
- KAFKA_TOPIC: Kafka topic to consume (default: quora-answers)
- KAFKA_GROUP_ID: Consumer group ID (default: quora-consumer-group)
- MONGODB_URI: MongoDB Atlas connection string
- MONGODB_DATABASE: Database name (default: quora_data)
- MONGODB_COLLECTION: Collection name (default: answers)
- LOG_LEVEL: Logging level (default: INFO)
"""

import json
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Literal, Optional

try:
    from confluent_kafka import Consumer, KafkaError  # type: ignore
except ImportError:
    print("Error: confluent-kafka not installed. Run: uv add confluent-kafka")
    sys.exit(1)

try:
    from pymongo import ASCENDING, MongoClient  # type: ignore
    from pymongo.errors import PyMongoError  # type: ignore
except ImportError:
    print("Error: pymongo not installed. Run: uv add pymongo")
    sys.exit(1)

# Load .env if present
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    pass

from logging_setup import init_logging  # unified logging

logger = init_logging("subscriber")

ProcessResult = Literal["stored", "skipped", "retry"]

_active_subscriber: Optional["KafkaMongoSubscriber"] = None


class KafkaMongoSubscriber:
    def __init__(self):
        # Kafka configuration
        self.kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "bokomint.local:19092")
        self.kafka_topic = os.environ.get("KAFKA_TOPIC", "quora-answers")
        self.kafka_group_id = os.environ.get("KAFKA_GROUP_ID", "quora-consumer-group")

        # MongoDB configuration
        self.mongodb_uri = os.environ.get("MONGODB_URI")
        self.mongodb_database = os.environ.get("MONGODB_DATABASE", "quora_data")
        self.mongodb_collection = os.environ.get("MONGODB_COLLECTION", "answers")

        if not self.mongodb_uri:
            raise ValueError("MONGODB_URI environment variable is required")

        # Initialize connections
        self.consumer: Optional[Consumer] = None
        self.mongo_client: Optional[MongoClient] = None
        self.mongo_db = None
        self.mongo_collection = None

        # Statistics
        self.messages_processed = 0
        self.messages_stored = 0
        self.errors_count = 0

        # Shutdown flag
        self.shutdown = False

    def setup_kafka_consumer(self):
        """Initialize Kafka consumer"""
        try:
            consumer_config = {
                "bootstrap.servers": self.kafka_bootstrap,
                "group.id": self.kafka_group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }

            self.consumer = Consumer(consumer_config)
            self.consumer.subscribe([self.kafka_topic])
            logger.info(
                "kafka_consumer_initialized",
                extra={
                    "event": "kafka_consumer_initialized",
                    "broker": self.kafka_bootstrap,
                    "topic": self.kafka_topic,
                },
            )

        except Exception as e:
            logger.error(f"Failed to initialize Kafka consumer: {e}")
            raise

    def setup_mongodb_connection(self):
        """Initialize MongoDB Atlas connection"""
        try:
            self.mongo_client = MongoClient(self.mongodb_uri)

            # Test connection
            self.mongo_client.admin.command("ping")

            self.mongo_db = self.mongo_client[self.mongodb_database]
            self.mongo_collection = self.mongo_db[self.mongodb_collection]

            self.mongo_collection.create_index(
                [("hash", ASCENDING)],
                unique=True,
                sparse=True,
                name="hash_unique",
            )

            logger.info(
                "mongodb_connected",
                extra={
                    "event": "mongodb_connected",
                    "database": self.mongodb_database,
                    "collection": self.mongodb_collection,
                },
            )

        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def process_message(self, message_value: str) -> ProcessResult:
        """Process a single Kafka message and store in MongoDB.

        Returns:
            stored: written to MongoDB (commit offset)
            skipped: unrecoverable bad message (commit offset)
            retry: transient failure (do not commit)
        """
        try:
            data = json.loads(message_value)
        except json.JSONDecodeError as e:
            logger.error(
                "invalid_json", extra={"event": "invalid_json", "error": str(e)}
            )
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
            document = {
                **data,
                "processed_at": datetime.now(timezone.utc),
                "source": "quora_scraper",
            }

            filter_key = (
                {"hash": data["hash"]} if "hash" in data else {"url": data.get("url")}
            )

            result = self.mongo_collection.replace_one(
                filter_key, document, upsert=True
            )

            if result.upserted_id:
                logger.info(
                    "mongo_upsert_inserted",
                    extra={
                        "event": "mongo_upsert",
                        "action": "insert",
                        "url": data.get("url"),
                        "hash": data.get("hash"),
                    },
                )
            else:
                logger.debug(
                    "mongo_upsert_updated",
                    extra={
                        "event": "mongo_upsert",
                        "action": "update",
                        "url": data.get("url"),
                        "hash": data.get("hash"),
                    },
                )

            self.messages_stored += 1
            return "stored"

        except PyMongoError as e:
            logger.error(
                "mongodb_error", extra={"event": "mongodb_error", "error": str(e)}
            )
            self.errors_count += 1
            return "retry"

        except Exception as e:
            logger.error(
                "unexpected_error",
                extra={"event": "unexpected_error", "error": str(e)},
            )
            self.errors_count += 1
            return "retry"

    def consume_messages(self):
        """Main consumer loop"""
        logger.info("consumer_loop_start", extra={"event": "consumer_loop_start"})

        try:
            while not self.shutdown:
                msg = self.consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug(
                            "partition_eof",
                            extra={
                                "event": "partition_eof",
                                "topic": msg.topic(),
                                "partition": msg.partition(),
                            },
                        )
                    else:
                        logger.error(
                            "kafka_error",
                            extra={"event": "kafka_error", "error": str(msg.error())},
                        )
                        self.errors_count += 1
                    continue

                self.messages_processed += 1
                message_value = msg.value().decode("utf-8")

                logger.debug(
                    "message_received",
                    extra={
                        "event": "message_received",
                        "preview": message_value[:100],
                    },
                )

                outcome = self.process_message(message_value)
                if outcome in ("stored", "skipped"):
                    self.consumer.commit(message=msg, asynchronous=False)

                if self.messages_processed % 10 == 0:
                    self.print_stats()

        except KeyboardInterrupt:
            logger.info("interrupt", extra={"event": "interrupt"})
            self.shutdown = True

        except Exception as e:
            logger.error(
                "fatal_consumer_error",
                extra={"event": "fatal_consumer_error", "error": str(e)},
            )
            raise

    def print_stats(self):
        """Print processing statistics"""
        logger.info(
            "stats",
            extra={
                "event": "stats",
                "processed": self.messages_processed,
                "stored": self.messages_stored,
                "errors": self.errors_count,
            },
        )

    def cleanup(self):
        """Clean up resources"""
        logger.info("cleanup", extra={"event": "cleanup"})

        if self.consumer:
            try:
                self.consumer.close()
                logger.info("kafka_closed", extra={"event": "kafka_closed"})
            except Exception as e:
                logger.error(f"Error closing Kafka consumer: {e}")

        if self.mongo_client:
            try:
                self.mongo_client.close()
                logger.info("mongodb_closed", extra={"event": "mongodb_closed"})
            except Exception as e:
                logger.error(f"Error closing MongoDB connection: {e}")

        self.print_stats()

    def run(self):
        """Main entry point"""
        try:
            logger.info("subscriber_start", extra={"event": "subscriber_start"})

            self.setup_kafka_consumer()
            self.setup_mongodb_connection()
            self.consume_messages()

        except Exception as e:
            logger.error(f"Failed to run subscriber: {e}")
            return 1

        finally:
            self.cleanup()

        return 0


def signal_handler(signum, frame):
    """Request graceful shutdown on SIGINT/SIGTERM."""
    logger.info("Received signal %s, shutting down...", signum)
    if _active_subscriber is not None:
        _active_subscriber.shutdown = True
    else:
        sys.exit(0)


def main():
    """Main function"""
    global _active_subscriber

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    required_env_vars = ["MONGODB_URI"]
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]

    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        logger.error("Please set MONGODB_URI to your MongoDB Atlas connection string")
        return 1

    try:
        subscriber = KafkaMongoSubscriber()
        _active_subscriber = subscriber
        return subscriber.run()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
