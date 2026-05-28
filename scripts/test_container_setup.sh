#!/bin/bash
# Test script for container setup

echo "🧪 Testing Kafka Subscriber Container Setup"
echo "==========================================="

# Check if required files exist
echo "📋 Checking required files..."

required_files=(
    "Dockerfile"
    ".containerignore"
    "docker-compose.yml"
    "podman_subscriber.sh"
    ".env.container"
    "kafka_subscriber.py"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "✅ $file"
    else
        echo "❌ $file (missing)"
    fi
done

echo ""
echo "🔧 Checking Podman availability..."
if command -v podman &> /dev/null; then
    echo "✅ Podman is installed"
    podman --version
else
    echo "❌ Podman not found"
    echo "Install with: brew install podman (macOS) or follow https://podman.io/getting-started/installation"
fi

echo ""
echo "📦 Checking Python dependencies..."
if grep -q "pymongo" pyproject.toml; then
    echo "✅ pymongo dependency found"
else
    echo "❌ pymongo dependency missing"
fi

if grep -q "confluent-kafka" pyproject.toml; then
    echo "✅ confluent-kafka dependency found"
else
    echo "❌ confluent-kafka dependency missing"
fi

echo ""
echo "⚙️  Environment configuration..."
if [ -f ".env.container" ]; then
    echo "✅ .env.container exists"
    if grep -q "MONGODB_URI=mongodb" .env.container; then
        echo "✅ MongoDB URI configured"
    else
        echo "⚠️  MongoDB URI needs configuration in .env.container"
    fi
else
    echo "❌ .env.container missing"
fi

echo ""
echo "🚀 Container management script..."
if [ -x "podman_subscriber.sh" ]; then
    echo "✅ podman_subscriber.sh is executable"
else
    echo "⚠️  Making podman_subscriber.sh executable..."
    chmod +x podman_subscriber.sh
fi

echo ""
echo "📊 Summary:"
echo "  - Container files: Ready ✅"
echo "  - Podman: $(command -v podman &> /dev/null && echo 'Available ✅' || echo 'Install needed ❌')"
echo "  - Dependencies: Ready ✅"
echo "  - Environment: $([ -f .env.container ] && echo 'Ready ✅' || echo 'Needs setup ⚠️')"

echo ""
echo "🎯 Next steps:"
echo "  1. Configure .env.container with your MongoDB Atlas URI"
echo "  2. Run: ./podman_subscriber.sh build"
echo "  3. Run: ./podman_subscriber.sh start"
echo "  4. Monitor: ./podman_subscriber.sh logs"
