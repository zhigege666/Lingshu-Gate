$ErrorActionPreference = "Stop"

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

Write-Host "Lingshu Gate local environment check" -ForegroundColor Cyan

$failed = $false

if (Test-CommandExists "python") {
    $pythonVersionOutput = (python --version 2>&1 | Out-String).Trim()
    Write-Host "[OK] python: $pythonVersionOutput" -ForegroundColor Green
    if ($pythonVersionOutput -notmatch 'Python\s+(\d+)\.(\d+)') {
        Write-Host "[FAIL] Unable to determine the Python version." -ForegroundColor Red
        $failed = $true
    } elseif (([int]$Matches[1] -lt 3) -or (([int]$Matches[1] -eq 3) -and ([int]$Matches[2] -lt 11))) {
        Write-Host "[FAIL] Python 3.11 or newer is required." -ForegroundColor Red
        $failed = $true
    }
} else {
    Write-Host "[FAIL] python not found. Install Python 3.11 or newer." -ForegroundColor Red
    $failed = $true
}

if (Test-CommandExists "node") {
    $nodeVersionOutput = (node --version 2>&1 | Out-String).Trim()
    Write-Host "[OK] node: $nodeVersionOutput" -ForegroundColor Green
    if ($nodeVersionOutput -notmatch '^v(\d+)\.') {
        Write-Host "[FAIL] Unable to determine the Node.js version." -ForegroundColor Red
        $failed = $true
    } elseif ([int]$Matches[1] -lt 22) {
        Write-Host "[FAIL] Node.js 22 or newer is required." -ForegroundColor Red
        $failed = $true
    }
} else {
    Write-Host "[FAIL] node not found. Install Node.js 22 or newer." -ForegroundColor Red
    $failed = $true
}

if (Test-CommandExists "npm") {
    $npmVersion = (npm --version 2>&1 | Out-String).Trim()
    Write-Host "[OK] npm: $npmVersion" -ForegroundColor Green
} else {
    Write-Host "[FAIL] npm not found. Install the npm version bundled with Node.js 22 or newer." -ForegroundColor Red
    $failed = $true
}

if ($failed) {
    exit 1
}

Write-Host "Environment check passed." -ForegroundColor Green
