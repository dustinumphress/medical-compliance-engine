# Helper script to run TruffleHog security scan via Docker
# Fixes PowerShell syntax issues with volume mounting

Write-Host "Starting Security Scan (TruffleHog)..." -ForegroundColor Cyan
Write-Host "   Target: $(Get-Location)" -ForegroundColor Gray

# Use ${PWD} so PowerShell doesn't get confused by the colon
docker run --rm -v "${PWD}:/pwd" trufflesecurity/trufflehog:latest git file:///pwd

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Scan Complete: No secrets found." -ForegroundColor Green
}
else {
    Write-Host "[FAIL] SECRETS FOUND! Check the output above." -ForegroundColor Red
}
