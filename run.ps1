param([string]$DataDir = '')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $runtimePath)) {
    Write-Host '请先依照 README.md 创建 .venv 并安装 requirements.txt。'
    exit 1
}
$arguments = @((Join-Path $projectRoot 'main.py'))
if ($DataDir) { $arguments += @('--data-dir', $DataDir) }
& $runtimePath @arguments
exit $LASTEXITCODE
