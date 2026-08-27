param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 7860
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$env:PYTHONPATH = Join-Path $projectRoot "src"

$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    "F:\Python\Python310\python.exe",
    "python.exe"
)
$python = $pythonCandidates | Where-Object {
    if ([IO.Path]::IsPathRooted($_)) { Test-Path -LiteralPath $_ } else { Get-Command $_ -ErrorAction SilentlyContinue }
} | Select-Object -First 1

if (-not $python) {
    throw "未找到 Python 3.10+。请先安装 Python。"
}

& $python -c "import cryptography, fastapi, playwright, pydantic, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "依赖未安装。请执行: $python -m pip install -e `".[api,postgres,redis,mcp]`""
}

Set-Location -LiteralPath $projectRoot
Write-Host "WebAuto 控制台: http://${HostAddress}:$Port"
Write-Host "首次配置: http://${HostAddress}:$Port/setup"
& $python -m webauto.adapters.web_server --host $HostAddress --port $Port
