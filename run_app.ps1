# run_app.ps1 - One-click script to run the Medical Auditor safely

Write-Host "� Checking Docker status..."
docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ Docker is not running."

    $dockerPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerPath) {
        Write-Host "   -> Starting Docker Desktop..."
        Start-Process $dockerPath

        Write-Host "   -> Waiting for Docker to be ready (this may take a minute)..."
        $retries = 60
        while ($retries -gt 0) {
            Write-Host -NoNewline "."
            Start-Sleep -Seconds 2
            docker info > $null 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "`n✅ Docker is ready!"
                break
            }
            $retries--
        }

        if ($retries -eq 0) {
            Write-Error "`n❌ Timed out waiting for Docker to start. Please start it manually."
            exit 1
        }
    }
    else {
        Write-Error "❌ Docker Desktop not found at $dockerPath. Please start Docker manually."
        exit 1
    }
}
else {
    Write-Host "✅ Docker is running."
}

Write-Host "�� Cleaning up old instances..."
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
