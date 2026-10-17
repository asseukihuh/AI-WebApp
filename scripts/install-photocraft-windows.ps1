# Download photocraft-web release zip into vendor/photocraft-web/ (fork-first).
# Optional: pre-download Windows photocraft-cli portable (otherwise first poster generation does).
param(
    [switch]$IncludeCli
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $Root "vendor\photocraft-web"
$Version = $env:PHOTOCRAFT_WEB_VERSION

$ForkRepo = if ($env:PHOTOCRAFT_FORK_REPO) { $env:PHOTOCRAFT_FORK_REPO } else { "asseukihuh/photocraft" }
$UpstreamRepo = if ($env:PHOTOCRAFT_UPSTREAM_REPO) { $env:PHOTOCRAFT_UPSTREAM_REPO } else { "storytold/photocraft" }
$FallbackVersion = if ($env:PHOTOCRAFT_WEB_FALLBACK_VERSION) { $env:PHOTOCRAFT_WEB_FALLBACK_VERSION } else { "0.9.0" }
$FallbackAssetUrl = "https://github.com/storytold/photocraft/releases/download/v$FallbackVersion/photocraft-web-$FallbackVersion.zip"

function Get-LatestReleaseTag([string]$Repo) {
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "CommMaker-Windows-Install" }
        $tag = $release.tag_name
        if (-not $tag) { return $null }
        return $tag.TrimStart("v")
    } catch {
        return $null
    }
}

function Get-WebZipUrl([string]$Repo, [string]$Ver) {
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/v$Ver" -Headers @{ "User-Agent" = "CommMaker-Windows-Install" }
        foreach ($asset in $release.assets) {
            $name = $asset.name
            if ($name -like "photocraft-web-*" -and $name -like "*.zip") {
                return @{ Url = $asset.browser_download_url; Repo = $Repo }
            }
        }
    } catch {
        return $null
    }
    return $null
}

function Write-CommmakerSourceJson([string]$DestDir, [string]$Repo, [string]$Ref, [string]$Method) {
    $builtAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
    $payload = @{
        repo    = $Repo
        ref     = $Ref
        method  = $Method
        builtAt = $builtAt
    } | ConvertTo-Json -Depth 3
    $metaPath = Join-Path $DestDir ".commmaker-source.json"
    [System.IO.File]::WriteAllText($metaPath, $payload + "`n")
}

function Install-PhotocraftZip([string]$AssetUrl, [string]$DestDir, [string]$SourceRepo, [string]$Ref) {
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("commmaker-pc-" + [guid]::NewGuid().ToString("n"))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $zipPath = Join-Path $tmp "photocraft-web.zip"
    $stageDir = Join-Path $tmp "stage"

    try {
        Invoke-WebRequest -Uri $AssetUrl -OutFile $zipPath -Headers @{ "User-Agent" = "CommMaker-Windows-Install" }

        $extractRoot = Join-Path $tmp "extract"
        Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force
        $inner = Get-ChildItem -Path $extractRoot -Directory | Select-Object -First 1
        if (-not $inner) {
            throw "Unexpected zip layout (no top-level folder)"
        }

        New-Item -ItemType Directory -Path $stageDir -Force | Out-Null
        Copy-Item -Path (Join-Path $inner.FullName "*") -Destination $stageDir -Recurse -Force

        if (-not (Test-Path (Join-Path $stageDir "index.html"))) {
            throw "index.html missing after extract"
        }

        Write-CommmakerSourceJson -DestDir $stageDir -Repo $SourceRepo -Ref $Ref -Method "release"

        $parent = Split-Path -Parent $DestDir
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        if (Test-Path $DestDir) {
            Remove-Item -Path $DestDir -Recurse -Force
        }
        Move-Item -Path $stageDir -Destination $DestDir
    } finally {
        if (Test-Path $tmp) {
            Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not $Version) {
    $Version = Get-LatestReleaseTag $ForkRepo
    if (-not $Version) {
        $Version = Get-LatestReleaseTag $UpstreamRepo
    }
    if (-not $Version) {
        $Version = $FallbackVersion
        Write-Host "note: using fallback photocraft-web version v$FallbackVersion (GitHub API unavailable or fork has no release)" -ForegroundColor Yellow
    }
}

$pick = Get-WebZipUrl $ForkRepo $Version
if (-not $pick) {
    $pick = Get-WebZipUrl $UpstreamRepo $Version
}

if (-not $pick) {
    if ($Version -eq $FallbackVersion) {
        $pick = @{ Url = $FallbackAssetUrl; Repo = $UpstreamRepo }
        Write-Host "note: using upstream fallback release zip (v$FallbackVersion)" -ForegroundColor Yellow
    } else {
        Write-Error "No photocraft-web zip for version $Version on $ForkRepo or $UpstreamRepo."
    }
}

Write-Host "Fetching photocraft-web $Version from $($pick.Repo) ..."
Install-PhotocraftZip -AssetUrl $pick.Url -DestDir $Dest -SourceRepo $pick.Repo -Ref "v$Version"
Write-Host "Installed to $Dest (version $Version)"
Write-Host "OK: $(Join-Path $Dest 'index.html')"

if ($IncludeCli) {
    Write-Host "Pre-downloading photocraft-cli (Windows portable) ..."
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Warning "python not on PATH; skip CLI pre-download (first poster generation will try again)."
        exit 0
    }
    Push-Location $Root
    try {
        & python -c @"
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'scripts'))
from photocraft_cli import ensure_cli
path = ensure_cli(os.getcwd())
print(path or 'download failed')
sys.exit(0 if path else 1)
"@
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "photocraft-cli pre-download failed; Crisis generate will retry on first use."
        }
    } finally {
        Pop-Location
    }
}
