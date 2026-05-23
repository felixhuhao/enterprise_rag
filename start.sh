#!/usr/bin/env bash
set -e

echo "==> Enterprise RAG Platform — Quick Start"
echo ""

# Check .env
if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example and fill in required values:"
    echo "  cp .env.example .env"
    echo "  # Edit .env — DASHSCOPE_API_KEY is required"
    exit 1
fi

# Start services
echo "==> Starting services..."
docker compose up -d --build

# Wait for backend
echo "==> Waiting for backend..."
until curl -sf http://localhost:8010/health > /dev/null 2>&1; do
    sleep 3
done
echo "    Backend is healthy"

# Seed demo data
echo "==> Seeding demo data..."
docker compose exec backend python scripts/seed_demo.py

echo ""
echo "==> Done! Open http://localhost:5173"
echo "    Default token: enterprise-rag-dev-token"
