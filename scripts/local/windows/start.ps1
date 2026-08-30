$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepositoryDir = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
$LocalDir = Join-Path $RepositoryDir "local"
$ConfigDir = Join-Path $LocalDir "config\mcp.d"
$DataDir = Join-Path $LocalDir "data"
$WorkspaceDir = Join-Path $LocalDir "workspace"
$ConsoleIndex = Join-Path $RepositoryDir "src\lingshu_gate\static\console\index.html"

& (Join-Path $ScriptDir "check.ps1")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $WorkspaceDir | Out-Null

Push-Location $RepositoryDir
try {
    if (-not (Test-Path $ConsoleIndex)) {
        Write-Host "Building Console assets..." -ForegroundColor Cyan
        Push-Location (Join-Path $RepositoryDir "web")
        try {
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) {
                throw "npm ci failed with exit code $LASTEXITCODE"
            }
            npm run build
            if ($LASTEXITCODE -ne 0) {
                throw "npm run build failed with exit code $LASTEXITCODE"
            }
        } finally {
            Pop-Location
        }
    }

    if (-not (Test-Path ".venv")) {
        Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Python virtual environment creation failed with exit code $LASTEXITCODE"
        }
    }

    $Python = Join-Path $RepositoryDir ".venv\Scripts\python.exe"

    Write-Host "Installing locked Python dependencies..." -ForegroundColor Cyan
    & $Python -m pip install --require-hashes --requirement requirements.lock
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency installation failed with exit code $LASTEXITCODE"
    }

    $env:PYTHONPATH = Join-Path $RepositoryDir "src"
    $env:LINGSHU_GATE_ALLOWED_ROOT = $WorkspaceDir
    $env:LINGSHU_GATE_CONFIG_DIR = $ConfigDir
    $env:LINGSHU_GATE_DATA_DIR = $DataDir
    if (-not $env:LINGSHU_GATE_HOST) {
        $env:LINGSHU_GATE_HOST = "127.0.0.1"
    }
    if (-not $env:LINGSHU_GATE_PORT) {
        $env:LINGSHU_GATE_PORT = "8000"
    }
    if (-not $env:LINGSHU_GATE_LOG_LEVEL) {
        $env:LINGSHU_GATE_LOG_LEVEL = "INFO"
    }
    if (-not $env:LINGSHU_GATE_RUNTIME_ROLE) {
        $env:LINGSHU_GATE_RUNTIME_ROLE = "local"
    }

    Write-Host "Starting Lingshu Gate..." -ForegroundColor Green
    Write-Host "Console: http://$($env:LINGSHU_GATE_HOST):$($env:LINGSHU_GATE_PORT)/console" -ForegroundColor Cyan
    Write-Host "Config : $ConfigDir" -ForegroundColor DarkCyan
    Write-Host "Data   : $DataDir" -ForegroundColor DarkCyan
    Write-Host "Work   : $WorkspaceDir" -ForegroundColor DarkCyan

    & $Python -m lingshu_gate.cli
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
