#!/usr/bin/env python3
"""
Test Kafka Producer Connectivity
Sends a test message to verify Kafka is working
"""

import json
import os
import sys
from datetime import datetime, timezone

try:
    from confluent_kafka import Producer
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Run: uv add confluent-kafka python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()


def test_kafka_producer():
    """Test Kafka producer connectivity"""

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP", "bokomint.local:19092")
    topic = os.getenv("KAFKA_TOPIC", "quora-answers")

    print("🧪 Testing Kafka Producer")
    print("=" * 30)
    print(f"Bootstrap servers: {bootstrap_servers}")
    print(f"Topic: {topic}")
    print()

    # Configure producer
    producer_config = {
        "bootstrap.servers": bootstrap_servers,
        "client.id": "test-producer",
    }

    try:
        producer = Producer(producer_config)

        # Create test message
        test_message = {
            "url": "https://test.example.com/test-answer",
            "hash": "test123abc456def",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "test": True,
        }

        # Send message
        producer.produce(
            topic,
            key="test-key",
            value=json.dumps(test_message),
            callback=delivery_callback,
        )

        # Wait for delivery
        producer.flush(10)  # Wait up to 10 seconds

        print("✅ Test message sent successfully!")
        return True

    except Exception as e:
        print(f"❌ Failed to send test message: {e}")
        return False


def delivery_callback(err, msg):
    """Callback for message delivery confirmation"""
    if err is not None:
        print(f"❌ Message delivery failed: {err}")
    else:
        print(f"✅ Message delivered to {msg.topic()} [{msg.partition()}]")


if __name__ == "__main__":
    success = test_kafka_producer()
    if success:
        print("\n🎉 Kafka producer test PASSED!")
    else:
        print("\n💥 Kafka producer test FAILED!")
        sys.exit(1)
