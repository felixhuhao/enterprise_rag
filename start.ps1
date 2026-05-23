$ErrorActionPreference = "Stop"

Write-Host "==> Enterprise RAG Platform — Quick Start"
Write-Host ""

# Check .env
if (-not (Test-Path .env)) {
    Write-Host "ERROR: .env not found. Copy .env.example and fill in required values:"
    Write-Host "  cp .env.example .env"
    Write-Host "  # Edit .env — DASHSCOPE_API_KEY is required"
    exit 1
}

# Start services
Write-Host "==> Starting services..."
docker compose up -d --build

# Wait for backend
Write-Host "==> Waiting for backend..."
$maxAttempts = 60
$attempt = 0
while ($attempt -lt $maxAttempts) {
    try {
        Invoke-WebRequest -Uri http://localhost:8010/health -UseBasicParsing -ErrorAction Stop | Out-Null
        break
    } catch {
        $attempt++
        Start-Sleep -Seconds 3
    }
}
if ($attempt -ge $maxAttempts) {
    Write-Host "ERROR: Backend did not become healthy within 3 minutes"
    exit 1
}
Write-Host "    Backend is healthy"

# Seed demo data
Write-Host "==> Seeding demo data..."
docker compose exec backend python scripts/seed_demo.py

Write-Host ""
Write-Host "==> Done! Open http://localhost:5173"
Write-Host "    Default token: enterprise-rag-dev-token"
