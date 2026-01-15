# run_app.ps1 - One-click script to run the Medical Auditor safely

Write-Host "🛑 Cleaning up old instances..."
# Stop Python if running
Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue

# Stop and Remove Docker containers named 'medical-audit'
docker stop medical-audit 2>$null
docker rm medical-audit 2>$null

Write-Host "🐳 Building Docker Image..."
# Build the image
docker build -t medical-audit .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed!"
    exit 1
}

Write-Host "🚀 Starting Application..."
Write-Host "   -> Access at http://localhost:5000"
Write-Host "   -> Press Ctrl+C to stop"

# Run with --rm (auto-delete on exit) and --name (easy to identify)
docker run --rm --name medical-audit --env-file .env -p 5000:5000 medical-audit
