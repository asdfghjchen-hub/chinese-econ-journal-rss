param(
    [Parameter(Mandatory=$true)]
    [string]$RepoUrl
)

$ErrorActionPreference = "Stop"

Write-Host "初始化本地 Git 仓库..."
if (-not (Test-Path ".git")) {
    git init
    git branch -M main
}

$currentRemote = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) {
    git remote add origin $RepoUrl
} elseif ($currentRemote -ne $RepoUrl) {
    git remote set-url origin $RepoUrl
}

git add .
git commit -m "feat: initialize Chinese economics journal RSS"
git push -u origin main

Write-Host ""
Write-Host "上传完成。接下来："
Write-Host "1. 在 GitHub 仓库的 Actions 页面启用并运行 Update journal RSS"
Write-Host "2. 在 Settings -> Pages 中选择 main 分支和 /docs 目录"
