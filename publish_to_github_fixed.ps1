param(
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl
)

$ErrorActionPreference = "Stop"

Write-Host "Initializing local Git repository..."

if (-not (Test-Path ".git")) {
    git init
    if ($LASTEXITCODE -ne 0) {
        throw "git init failed."
    }

    git branch -M main
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to rename branch to main."
    }
}

$remoteExists = $false
git remote get-url origin *> $null
if ($LASTEXITCODE -eq 0) {
    $remoteExists = $true
}

if (-not $remoteExists) {
    git remote add origin $RepoUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to add origin remote."
    }
} else {
    $currentRemote = git remote get-url origin
    if ($currentRemote -ne $RepoUrl) {
        git remote set-url origin $RepoUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to update origin remote."
        }
    }
}

git add .
if ($LASTEXITCODE -ne 0) {
    throw "git add failed."
}

git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "feat: initialize Chinese economics journal RSS"
    if ($LASTEXITCODE -ne 0) {
        throw "git commit failed."
    }
} else {
    Write-Host "No new changes to commit."
}

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    throw "git push failed. Check GitHub authentication and repository URL."
}

Write-Host ""
Write-Host "Upload completed."
Write-Host "Next steps:"
Write-Host "1. Open GitHub Actions and run: Update journal RSS"
Write-Host "2. Open Settings -> Pages"
Write-Host "3. Select branch main and folder /docs"
