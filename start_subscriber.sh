#!/bin/bash
# Kafka-MongoDB Subscriber Startup Script

set -e  # Exit on any error

echo "🚀 Starting Kafka-MongoDB Subscriber..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Creating from template..."
    cp .env.example .env
    echo "📝 Please edit .env with your MongoDB Atlas connection string:"
    echo "   MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority"
    echo ""
    echo "Then run this script again."
    exit 1
fi

# Check if MONGODB_URI is set
if ! grep -q "^MONGODB_URI=mongodb" .env; then
    echo "❌ MONGODB_URI not properly configured in .env file"
    echo "📝 Please set your MongoDB Atlas connection string in .env:"
    echo "   MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority"
    exit 1
fi

echo "✅ Configuration found"

# Load environment variables
export $(grep -v '^#' .env | xargs)

echo "📡 Kafka Broker: ${KAFKA_BOOTSTRAP:-bokomint.local:19092}"
echo "📋 Kafka Topic: ${KAFKA_TOPIC:-quora-answers}"
echo "🗄️  MongoDB Database: ${MONGODB_DATABASE:-quora_data}"
echo "📄 MongoDB Collection: ${MONGODB_COLLECTION:-answers}"
echo ""

echo "🔄 Starting subscriber..."
echo "Press Ctrl+C to stop"
echo ""

# Run the subscriber
uv run kafka_subscriber.py
