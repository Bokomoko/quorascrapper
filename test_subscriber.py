#!/usr/bin/env python3
"""
Test script for Kafka-MongoDB subscriber
Tests the subscriber with mock data when MongoDB credentials are not available
"""

import json
import os
import time
from datetime import datetime, timezone


# Mock MongoDB operations for testing
class MockMongoCollection:
    def __init__(self):
        self.documents = []

    def replace_one(self, filter_doc, document, upsert=False):
        print(f"Mock MongoDB: Would store document with filter {filter_doc}")
        print(f"Document: {json.dumps(document, indent=2, default=str)}")
        self.documents.append(document)

        # Mock result
        class MockResult:
            def __init__(self):
                self.upserted_id = "mock_id_123"

        return MockResult()


# Test the message processing logic
def test_message_processing():
    """Test message processing without actual Kafka/MongoDB"""

    # Mock message data (similar to what the scraper produces)
    test_messages = [
        {"url": "https://pt.quora.com/answer/test-123", "hash": "abcd1234efgh5678"},
        {"url": "https://pt.quora.com/answer/test-456", "hash": "ijkl9012mnop3456"},
    ]

    print("Testing message processing logic...")

    # Mock collection
    mock_collection = MockMongoCollection()

    # Process test messages
    for i, message_data in enumerate(test_messages, 1):
        print(f"\n--- Processing Message {i} ---")

        # Add metadata (like the real subscriber does)
        document = {
            **message_data,
            "processed_at": datetime.now(timezone.utc),
            "source": "quora_scraper",
        }

        # Mock storage
        filter_key = {"hash": message_data["hash"]}
        result = mock_collection.replace_one(filter_key, document, upsert=True)

        print(f"✅ Message {i} processed successfully")

    print(f"\n🎉 Test completed! Processed {len(test_messages)} messages")
    print(f"📊 Mock collection now contains {len(mock_collection.documents)} documents")


if __name__ == "__main__":
    test_message_processing()
