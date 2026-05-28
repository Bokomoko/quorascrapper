#!/usr/bin/env python3
"""
Check MongoDB for recent test data
Verifies that messages are being stored correctly
"""

import os
import sys
from datetime import datetime, timedelta, timezone

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


def check_mongodb_data():
    """Check for recent data in MongoDB"""

    mongodb_uri = os.getenv("MONGODB_URI")
    database_name = os.getenv("MONGODB_DATABASE", "quora_data")
    collection_name = os.getenv("MONGODB_COLLECTION", "answers")

    if not mongodb_uri:
        print("❌ MONGODB_URI not found in .env file")
        return False

    print("📊 Checking MongoDB Data")
    print("=" * 25)
    print(f"Database: {database_name}")
    print(f"Collection: {collection_name}")
    print()

    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        db = client[database_name]
        collection = db[collection_name]

        # Count total documents
        total_count = collection.count_documents({})
        print(f"📈 Total documents: {total_count}")

        # Check for recent documents (last 10 minutes)
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        recent_count = collection.count_documents(
            {"processed_at": {"$gte": recent_time}}
        )
        print(f"🕐 Recent documents (last 10 min): {recent_count}")

        # Show latest documents
        print("\n📄 Latest documents:")
        latest_docs = collection.find().sort("_id", -1).limit(3)

        for i, doc in enumerate(latest_docs, 1):
            print(f"  {i}. URL: {doc.get('url', 'N/A')}")
            print(f"     Hash: {doc.get('hash', 'N/A')}")
            print(f"     Test: {doc.get('test', False)}")
            if "processed_at" in doc:
                print(f"     Processed: {doc['processed_at']}")
            print()

        client.close()
        return True

    except PyMongoError as e:
        print(f"❌ MongoDB error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = check_mongodb_data()
    if success:
        print("✅ MongoDB data check completed!")
    else:
        print("❌ MongoDB data check failed!")
        sys.exit(1)
