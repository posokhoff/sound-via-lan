$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Out = Join-Path $Root "packages\windows"
$Work = Join-Path $Root "build\pyinstaller"
$Dist = Join-Path $Root "build\dist"

Write-Host "Installing build dependencies..."
python -m pip install -r requirements-build.txt

Remove-Item -Recurse -Force $Work, $Dist, $Out -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Out | Out-Null

Write-Host "Building transmitter..."
python -m PyInstaller packaging\transmitter.spec --noconfirm --clean --distpath $Dist --workpath $Work

Write-Host "Building receiver..."
python -m PyInstaller packaging\receiver.spec --noconfirm --clean --distpath $Dist --workpath $Work

Copy-Item -Recurse (Join-Path $Dist "sound-transmitter") (Join-Path $Out "sound-transmitter")
Copy-Item -Recurse (Join-Path $Dist "sound-receiver") (Join-Path $Out "sound-receiver")
$ConfigsOut = Join-Path $Out "configs"
New-Item -ItemType Directory -Force -Path $ConfigsOut | Out-Null
Copy-Item configs\transmitter.example.json, configs\receiver.example.json $ConfigsOut
Copy-Item README.md, DISTRIBUTION.md $Out -ErrorAction SilentlyContinue

$Zip = Join-Path $Root "packages\sound-via-lan-windows-x64.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $Out "*") -DestinationPath $Zip -Force

Write-Host "Windows package ready:"
Write-Host "  folder: $Out"
Write-Host "  zip:    $Zip"
