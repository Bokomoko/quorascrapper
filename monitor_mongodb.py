#!/usr/bin/env python3
"""
MongoDB Live Monitor
Continuously monitors the MongoDB collection for new documents
"""

import os
import sys
import time
from datetime import datetime

try:
    from dotenv import load_dotenv
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Run: uv add pymongo python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()


def monitor_mongodb():
    """Continuously monitor MongoDB collection"""

    mongodb_uri = os.getenv("MONGODB_URI")
    database_name = os.getenv("MONGODB_DATABASE", "quora_data")
    collection_name = os.getenv("MONGODB_COLLECTION", "answers")

    if not mongodb_uri:
        print("❌ MONGODB_URI not found in .env file")
        return

    print("🔍 MongoDB Live Monitor")
    print("=" * 30)
    print(f"Database: {database_name}")
    print(f"Collection: {collection_name}")
    print("Press Ctrl+C to stop monitoring")
    print()

    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        db = client[database_name]
        collection = db[collection_name]

        last_count = 0

        while True:
            try:
                # Get current count
                current_count = collection.count_documents({})

                # Check if count changed
                if current_count != last_count:
                    print(
                        f"📊 {datetime.now().strftime('%H:%M:%S')} - Documents: {current_count} (+{current_count - last_count})"
                    )

                    # Show latest documents if count increased
                    if current_count > last_count:
                        latest_docs = (
                            collection.find()
                            .sort("_id", -1)
                            .limit(current_count - last_count)
                        )
                        for doc in latest_docs:
                            url = doc.get("url", "N/A")[:80] + (
                                "..." if len(doc.get("url", "")) > 80 else ""
                            )
                            print(f"   ✅ New: {url}")
                            if doc.get("test"):
                                print(f"      🧪 Test message")
                            print(f"      📅 {doc.get('processed_at', 'N/A')}")
                        print()

                    last_count = current_count
                else:
                    # Show periodic status
                    print(
                        f"⏱️  {datetime.now().strftime('%H:%M:%S')} - Monitoring... (Documents: {current_count})"
                    )

                time.sleep(5)  # Check every 5 seconds

            except KeyboardInterrupt:
                print("\n🛑 Monitoring stopped by user")
                break
            except Exception as e:
                print(f"❌ Error during monitoring: {e}")
                time.sleep(10)

        client.close()

    except PyMongoError as e:
        print(f"❌ MongoDB connection error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    monitor_mongodb()
