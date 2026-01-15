# update.ps1

# --- CONFIGURATION ---
$Region = "us-east-1"
$RepoName = "medical-audit-demo"
$LambdaName = "MedicalAuditDemo"
# ---------------------

Write-Host "🚀 STARTING FAST DEPLOY..." -ForegroundColor Cyan

# 1. Dynamically get the Account ID (No hardcoding!)
Write-Host "1. Fetching Account ID..." -ForegroundColor Yellow
try {
    $AccountId = aws sts get-caller-identity --query Account --output text
    if (-not $AccountId) { throw "Could not fetch Account ID" }
}
catch {
    Write-Error "❌ Error: Could not get AWS Account ID. Run 'aws configure' first."
    exit 1
}

$EcrUrl = "$AccountId.dkr.ecr.$Region.amazonaws.com"
$ImageUri = "$EcrUrl/$RepoName`:latest"

# 2. Login to ECR
Write-Host "2. Logging into ECR..." -ForegroundColor Yellow
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $EcrUrl
if ($LASTEXITCODE -ne 0) { Write-Error "Login Failed"; exit }

# 3. Build (With Platform Flag)
Write-Host "3. Building Docker Image..." -ForegroundColor Yellow
docker build --platform linux/amd64 -t $RepoName .
if ($LASTEXITCODE -ne 0) { Write-Error "Build Failed"; exit }

# 4. Push
Write-Host "4. Pushing to ECR..." -ForegroundColor Yellow
docker tag "$RepoName`:latest" $ImageUri
docker push $ImageUri
if ($LASTEXITCODE -ne 0) { Write-Error "Push Failed"; exit }

# 5. Update Lambda
Write-Host "5. Updating Lambda Function..." -ForegroundColor Yellow
aws lambda update-function-code --function-name $LambdaName --image-uri $ImageUri > $null

Write-Host "--------------------------------------------------" -ForegroundColor Green
Write-Host "✅ DONE! Your changes are live." -ForegroundColor Green
Write-Host "--------------------------------------------------" -ForegroundColor Green