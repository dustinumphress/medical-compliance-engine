# 1. Ask for the Image URI
Write-Host "--------------------------------------------------" -ForegroundColor Cyan
Write-Host " [LAUNCHER] Medical Audit Demo Deployment " -ForegroundColor Cyan
Write-Host "--------------------------------------------------"
$ImageUri = Read-Host -Prompt "Paste your full ECR Image URI"

# 2. Check input
if ([string]::IsNullOrWhiteSpace($ImageUri)) {
    Write-Host " [ERROR] Image URI cannot be empty." -ForegroundColor Red
    exit 1
}

Write-Host "--------------------------------------------------" -ForegroundColor Yellow
Write-Host " [Deploying] Image: $ImageUri" -ForegroundColor Yellow
Write-Host "--------------------------------------------------"

# 3. Run AWS Command
aws cloudformation deploy `
    --template-file serverless_deploy.yaml `
    --stack-name MedicalDemoStack `
    --parameter-overrides ImageUri="$ImageUri" `
    --capabilities CAPABILITY_NAMED_IAM

Write-Host "[SUCCESS] Deployment Complete!" -ForegroundColor Green