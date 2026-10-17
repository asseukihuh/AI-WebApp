# One-command CommMaker pre-MVP dev server on Windows (PowerShell).
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ServeArgs
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $Root "vendor\photocraft-web"
$Port = if ($env:COMMMAKER_PORT) { $env:COMMMAKER_PORT } else { "8000" }

function Find-GitBash {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Git\bin\bash.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Git\bin\bash.exe")
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            return $path
        }
    }
    return $null
}

function Invoke-RepoBashScript([string]$RelativeScript) {
    $bash = Find-GitBash
    if (-not $bash) {
        return $false
    }
    $unixRoot = ($Root -replace '\\', '/')
    $unixScript = ($RelativeScript -replace '\\', '/')
    & $bash -lc "cd '$unixRoot' && ./$unixScript"
    if ($LASTEXITCODE -ne 0) {
        throw "Bash script failed: $RelativeScript (exit $LASTEXITCODE)"
    }
    return $true
}

function Ensure-PhotocraftWeb {
    $index = Join-Path $Dest "index.html"
    $meta = Join-Path $Dest ".commmaker-source.json"
    $installFork = Join-Path $Root "scripts\install-photocraft-from-fork.sh"
    $fetchSh = Join-Path $Root "scripts\fetch-photocraft-web.sh"
    $installPs = Join-Path $PSScriptRoot "install-photocraft-windows.ps1"

    if (-not (Test-Path -LiteralPath $index)) {
        Write-Host "PhotoCraft web assets missing; installing (fork-first) ..."
        if ((Test-Path -LiteralPath $installFork) -and (Find-GitBash)) {
            Invoke-RepoBashScript "scripts/install-photocraft-from-fork.sh"
            return
        }
        if ((Test-Path -LiteralPath $fetchSh) -and (Find-GitBash)) {
            Invoke-RepoBashScript "scripts/fetch-photocraft-web.sh"
            return
        }
        if (-not (Test-Path -LiteralPath $installPs)) {
            throw "No install script found. Install Git Bash or use scripts/install-photocraft-windows.ps1."
        }
        & $installPs
        return
    }

    if (-not (Test-Path -LiteralPath $meta)) {
        Write-Host "Refreshing PhotoCraft vendor metadata ..."
        if ((Test-Path -LiteralPath $fetchSh) -and (Find-GitBash)) {
            Invoke-RepoBashScript "scripts/fetch-photocraft-web.sh"
            return
        }
        & $installPs
    }
}

Ensure-PhotocraftWeb

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "python not found on PATH. Install Python 3.11+ from https://www.python.org/downloads/ and enable Add to PATH."
}

$serve = Join-Path $Root "scripts\serve-static.py"
Write-Host "Starting CommMaker dev server on http://localhost:${Port}/home.html"

$allArgs = @($serve, "--port", $Port) + $ServeArgs
& python @allArgs
