# Build a portable Thoth Windows folder (tray app + local server payload).
# Run on Windows: powershell -ExecutionPolicy Bypass -File scripts\build_windows_app.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Dist = Join-Path $Root "dist"
$Out = Join-Path $Dist "ThothWindows"
$HomePayload = Join-Path $Out "ThothHome"

Write-Host "==> Building ThothWindows"

if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory -Path $HomePayload -Force | Out-Null

$Version = (Get-Content (Join-Path $Root "extension\manifest.json") -Raw | ConvertFrom-Json).version

$CopyPaths = @(
  "server.py",
  "writing_agent.py",
  "claim_check.py",
  "security.py",
  "cloud_ai.py",
  "rag.py",
  "grammar_rules.json",
  "generate_feature_rules.json",
  "requirements.txt",
  "scripts\ollama_gpu_env.sh",
  "extension"
)

foreach ($rel in $CopyPaths) {
  $src = Join-Path $Root $rel
  $dst = Join-Path $HomePayload $rel
  if (Test-Path $src -PathType Container) {
    Copy-Item -Path $src -Destination $dst -Recurse -Force
  } elseif (Test-Path $src) {
    $parent = Split-Path $dst -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Copy-Item -Path $src -Destination $dst -Force
  }
}

Copy-Item -Path (Join-Path $Root "macos") -Destination (Join-Path $HomePayload "macos") -Recurse -Force
Copy-Item -Path (Join-Path $Root "windows") -Destination (Join-Path $HomePayload "windows") -Recurse -Force

$AssetsDst = Join-Path $HomePayload "assets"
New-Item -ItemType Directory -Path $AssetsDst -Force | Out-Null
Copy-Item -Path (Join-Path $Root "assets\logo.png") -Destination $AssetsDst -Force -ErrorAction SilentlyContinue
Copy-Item -Path (Join-Path $Root "assets\menubar-logo.png") -Destination $AssetsDst -Force -ErrorAction SilentlyContinue
Copy-Item -Path (Join-Path $Root "assets\menubar-mask.png") -Destination $AssetsDst -Force -ErrorAction SilentlyContinue

$IconDir = Join-Path $HomePayload "macos\menubar\icons"
$ExtIconDir = Join-Path $HomePayload "extension\icons"
python -c "import sys; from pathlib import Path; sys.path.insert(0, r'$Root'); from macos.menubar.icons_util import write_status_icons, write_extension_icons; write_status_icons(Path(r'$IconDir')); write_extension_icons(Path(r'$ExtIconDir'))"

Copy-Item -Path (Join-Path $Root "Start Thoth.bat") -Destination (Join-Path $Out "Start Thoth.bat") -Force

$Readme = @"
Thoth for Windows (v$Version)
=============================

1. Install Python 3.10+, Ollama, Java 11+, and Chrome.
2. Double-click Start Thoth.bat (tray icon — no console window).
3. Install the Chrome extension:
   https://chromewebstore.google.com/detail/begfbbjincimcjcimpfpkoilbhjphppn?utm_source=item-share-cb

Full guide: https://github.com/Eshan-khan1/Thoth/blob/main/docs/INSTALL_WINDOWS.md
"@
Set-Content -Path (Join-Path $Out "README.txt") -Value $Readme -Encoding UTF8

$Zip = Join-Path $Dist "Thoth-Windows-v$Version.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path $Out -DestinationPath $Zip -Force
Copy-Item $Zip (Join-Path $Dist "Thoth-Windows.zip") -Force

Write-Host "Built: $Out"
Write-Host "Zip:   $Zip"
