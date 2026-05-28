#!/usr/bin/env python3
"""
MongoDB Atlas Connection Test
Tests connection with provided credentials from .env file
"""

import os
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    print("Run: uv add pymongo python-dotenv")
    sys.exit(1)

# Load environment variables from .env file
load_dotenv()


def test_mongodb_connection():
    """Test MongoDB Atlas connection using .env configuration"""

    # Get MongoDB URI from environment
    mongodb_uri = os.getenv("MONGODB_URI")
    database = os.getenv("MONGODB_DATABASE", "quora_data")

    if not mongodb_uri:
        print("❌ MONGODB_URI not found in .env file")
        sys.exit(1)

    print("🧪 Testing MongoDB Atlas Connection")
    print("=" * 40)
    print(f"MongoDB URI: {mongodb_uri}")
    print(f"Database: {database}")
    print()

    print("🔗 Testing direct connection...")
    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)

        # Test connection
        client.admin.command("ping")

        # Test database access
        db = client[database]
        collection = db["test_connection"]

        # Insert test document
        test_doc = {
            "test": True,
            "timestamp": datetime.now(timezone.utc),
            "message": "Connection test successful",
        }

        result = collection.insert_one(test_doc)
        print("✅ Connection successful!")
        print("   - Ping: OK")
        print("   - Database access: OK")
        print(f"   - Insert test: OK (ID: {result.inserted_id})")

        # Clean up test document
        collection.delete_one({"_id": result.inserted_id})
        print("   - Cleanup: OK")

        client.close()
        return mongodb_uri

    except PyMongoError as e:
        print(f"❌ Connection failed: {e}")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None


if __name__ == "__main__":
    working_uri = test_mongodb_connection()

    if working_uri:
        print("\n🎉 MongoDB Atlas connection test PASSED!")
        print("   Ready to run Kafka subscriber")
    else:
        print("\n💥 MongoDB Atlas connection test FAILED!")
        print("\n💡 Troubleshooting:")
        print("   1. Check if your MongoDB Atlas cluster is running")
        print("   2. Verify the cluster hostname in Atlas dashboard")
        print("   3. Ensure IP whitelist allows your current IP")
        print("   4. Verify username/password in .env file")
        sys.exit(1)
