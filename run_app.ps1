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

Write-Host "🦙 Checking Ollama (local vision model for image transcription)..."
$visionModel = "qwen2.5vl:7b"
$ollamaOk = $false

# Is the Ollama server already listening?
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 | Out-Null
    $ollamaOk = $true
    Write-Host "✅ Ollama is running."
}
catch {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-Host "   -> Starting Ollama server..."
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
        $retries = 15
        while ($retries -gt 0) {
            Start-Sleep -Seconds 2
            try {
                Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 | Out-Null
                $ollamaOk = $true
                Write-Host "✅ Ollama is ready!"
                break
            }
            catch { Write-Host -NoNewline "." }
            $retries--
        }
    }
    else {
        Write-Host "⚠️ Ollama is not installed. Image transcription will be unavailable."
    }
}

# Make sure the vision model is actually pulled (6 GB - only downloads once)
if ($ollamaOk) {
    $tags = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5
    if (-not ($tags.models.name -contains $visionModel)) {
        Write-Host "   -> Vision model '$visionModel' not found. Pulling (~6 GB, one time)..."
        ollama pull $visionModel
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️ Pull failed. Image transcription will be unavailable."
            $ollamaOk = $false
        }
    }
    else {
        Write-Host "✅ Vision model '$visionModel' is available."
    }
}

if (-not $ollamaOk) {
    Write-Host "⚠️ Continuing without local transcription - text paste still works."
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

# Run with --rm (auto-delete on exit) and --name (easy to identify).
# OLLAMA_URL must point at the HOST, not the container: inside the container
# "localhost" is the container itself, so the default localhost:11434 never
# reaches the Ollama server running on this machine. host.docker.internal is
# mapped explicitly via --add-host so this works on Docker Engine too, not
# just Docker Desktop.
docker run --rm --name medical-audit `
    --env-file .env `
    -e OLLAMA_URL="http://host.docker.internal:11434" `
    --add-host=host.docker.internal:host-gateway `
    -p 5000:5000 medical-audit
