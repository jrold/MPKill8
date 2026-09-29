$ErrorActionPreference = "Stop"

$UpdaterUrl = "https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/MPKmini3_Updater_v1.26_WIN.zip"
$StockRegionSha = "b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392"
$PatchedRegionSha = "b7121c28293201a031200b56058fc5bee1fdbfdf053582d99e1fbea8029f3087"

$RegionOffset = 0x28C144
$RegionSize = 0x20000
$PatchOffset = 0x0E5EC
$ChecksumOffset = 0x1FFFF

function Get-Sha256Bytes([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($Bytes)
        return ([BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Slice-Bytes([byte[]]$Bytes, [int]$Offset, [int]$Length) {
    $out = New-Object byte[] $Length
    [Array]::Copy($Bytes, $Offset, $out, 0, $Length)
    return $out
}

if ($env:OS -ne "Windows_NT") {
    throw "MPKill8 installer must be run on Windows because Akai's updater is a Windows executable."
}

Write-Host ""
Write-Host "MPKill8 installer" -ForegroundColor Cyan
Write-Host "=================" -ForegroundColor Cyan
Write-Host ""

# Safety check: confirm this is the exact hardware family we reverse engineered.
$device = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
    Where-Object { $_.PNPDeviceID -match 'VID_09E8&PID_1049' } |
    Select-Object -First 1

if (-not $device) {
    Write-Host "No normal-mode MPK Mini 3 with VID 09E8 / PID 1049 was detected." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Connect the MPK Mini 3 normally over USB and run install.bat again."
    Write-Host "This check intentionally refuses to patch/launch for another hardware revision."
    exit 2
}

Write-Host "Found supported controller:"
Write-Host "  $($device.Name)"
Write-Host "  VID 09E8 / PID 1049"
Write-Host ""

$root = Split-Path -Parent $PSScriptRoot
if ((Split-Path -Leaf $PSScriptRoot) -ne "tools") {
    $root = $PSScriptRoot
}

$vendor = Join-Path $root "vendor"
$dist = Join-Path $root "dist"
$work = Join-Path $dist "mpkill8_updater"
$zipPath = Join-Path $vendor "MPKmini3_Updater_v1.26_WIN.zip"

New-Item -ItemType Directory -Force -Path $vendor | Out-Null
New-Item -ItemType Directory -Force -Path $dist | Out-Null

if (-not (Test-Path $zipPath)) {
    Write-Host "Downloading official Akai MPK Mini 3 v1.26 updater..."
    Invoke-WebRequest -Uri $UpdaterUrl -OutFile $zipPath -UseBasicParsing
}
else {
    Write-Host "Using cached official updater:"
    Write-Host "  $zipPath"
}

if (Test-Path $work) {
    Remove-Item -Recurse -Force $work
}
New-Item -ItemType Directory -Force -Path $work | Out-Null

Write-Host "Extracting updater..."
Expand-Archive -Path $zipPath -DestinationPath $work -Force

$exe = Get-ChildItem -Path $work -Filter "*.exe" -Recurse | Select-Object -First 1
if (-not $exe) {
    throw "Could not find the Akai updater EXE inside the official ZIP."
}

[byte[]]$bytes = [System.IO.File]::ReadAllBytes($exe.FullName)

if ($bytes.Length -lt ($RegionOffset + $RegionSize)) {
    throw "Updater EXE is smaller than the verified v1.26 layout. Refusing to patch."
}

[byte[]]$stockRegion = Slice-Bytes $bytes $RegionOffset $RegionSize
$actualStockSha = Get-Sha256Bytes $stockRegion

if ($actualStockSha -ne $StockRegionSha) {
    throw @"
Official updater firmware hash mismatch. Refusing to patch.

Expected Region 3:
  $StockRegionSha

Actual:
  $actualStockSha

Akai may have changed the download. Do not continue until MPKill8 is updated.
"@
}

$insnAbsolute = $RegionOffset + $PatchOffset
$checksumAbsolute = $RegionOffset + $ChecksumOffset

if ($bytes[$insnAbsolute] -ne 0x08) {
    throw ("Expected stock byte 08 at firmware offset 0x0E5EC, found {0:X2}. Refusing to patch." -f $bytes[$insnAbsolute])
}
if ($bytes[$checksumAbsolute] -ne 0xFF) {
    throw ("Expected stock checksum byte FF at firmware offset 0x1FFFF, found {0:X2}. Refusing to patch." -f $bytes[$checksumAbsolute])
}

Write-Host "Applying MPKill8 firmware patch..."
$bytes[$insnAbsolute] = 0x07
$bytes[$checksumAbsolute] = 0xFE

[byte[]]$patchedRegion = Slice-Bytes $bytes $RegionOffset $RegionSize
$actualPatchedSha = Get-Sha256Bytes $patchedRegion

if ($actualPatchedSha -ne $PatchedRegionSha) {
    throw @"
Patched firmware verification failed. Refusing to launch updater.

Expected:
  $PatchedRegionSha

Actual:
  $actualPatchedSha
"@
}

$patchedExe = Join-Path $dist "MPKmini3_Updater_v1.26_MPKILL8.exe"
[System.IO.File]::WriteAllBytes($patchedExe, $bytes)

Write-Host ""
Write-Host "PATCH VERIFIED" -ForegroundColor Green
Write-Host "  Stock firmware:   $StockRegionSha"
Write-Host "  Patched firmware: $PatchedRegionSha"
Write-Host ""
Write-Host "Only these firmware bytes changed:"
Write-Host "  0x0E5EC: 08 -> 07   (encoder loop processes K1-K7 only)"
Write-Host "  0x1FFFF: FF -> FE   (firmware checksum)"
Write-Host ""
Write-Host "Patched updater:"
Write-Host "  $patchedExe"
Write-Host ""
Write-Host "IMPORTANT:" -ForegroundColor Yellow
Write-Host "  This is custom firmware. Keep the official updater ZIP in vendor\ for recovery."
Write-Host "  Windows may warn that the modified EXE no longer has Akai's original signature."
Write-Host ""
Write-Host "Launching Akai updater..."
Write-Host "When required by the updater, reconnect the MPK while holding BANK + PROG SELECT."
Write-Host ""

Start-Process -FilePath $patchedExe
