param(
    [switch]$Pack
)

$ErrorActionPreference = "Stop"
$probeDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent (Split-Path -Parent $probeDir)
$output = Join-Path $repo "build\stt-probe"
$stage = Join-Path $output "package"
$exe = Join-Path $output "SmitelessSttProbe.exe"
$unpackagedExe = Join-Path $output "SmitelessSttProbe.Unpackaged.exe"
$apiSurfaceExe = Join-Path $output "SpeechRecognizerApiSurfaceProbe.exe"

$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$runtime = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Runtime.WindowsRuntime.dll"
$systemRuntime = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\System.Runtime.dll"
$windowsWinmd = Get-ChildItem -LiteralPath "C:\Program Files (x86)\Windows Kits\10\UnionMetadata" `
    -Recurse -Filter Windows.winmd -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "\\Facade\\" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1 -ExpandProperty FullName

if (-not (Test-Path -LiteralPath $csc)) {
    throw "64-bit .NET Framework C# compiler not found at $csc"
}
if (-not (Test-Path -LiteralPath $runtime)) {
    throw "System.Runtime.WindowsRuntime.dll not found at $runtime"
}
if (-not (Test-Path -LiteralPath $systemRuntime)) {
    throw "System.Runtime.dll facade not found at $systemRuntime"
}
if (-not $windowsWinmd) {
    throw "Windows SDK UnionMetadata Windows.winmd was not found. Install the Windows 10/11 SDK."
}

New-Item -ItemType Directory -Force -Path $output | Out-Null
$source = Join-Path $probeDir "SmitelessSttProbe.cs"
$apiSurfaceSource = Join-Path $probeDir "SpeechRecognizerApiSurfaceProbe.cs"
$appManifest = Join-Path $probeDir "SmitelessSttProbe.exe.manifest"
$unpackagedManifest = Join-Path $probeDir "SmitelessSttProbe.Unpackaged.exe.manifest"
$references = @(
    "/reference:$runtime",
    "/reference:$systemRuntime",
    "/reference:$windowsWinmd",
    "/reference:System.Web.Extensions.dll"
)
& $csc /nologo /target:exe /platform:x64 /optimize+ "/out:$apiSurfaceExe" `
    @references $apiSurfaceSource
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $apiSurfaceExe)) {
    throw "SpeechRecognizer API-surface probe compilation failed."
}
$apiSurfaceRaw = & $apiSurfaceExe
try {
    $apiSurface = $apiSurfaceRaw | ConvertFrom-Json
} catch {
    throw "SpeechRecognizer API-surface probe did not emit valid JSON: $apiSurfaceRaw"
}
if ($apiSurface.ok -ne $true -or $null -eq $apiSurface.explicit_endpoint_binding_supported) {
    throw "SpeechRecognizer API-surface JSON contract is incomplete."
}
Write-Host ("API surface: explicit endpoint binding={0}; MediaCapture AudioDeviceId={1}" -f `
    $apiSurface.explicit_endpoint_binding_supported, $apiSurface.media_capture_has_audio_device_id)

& $csc /nologo /target:exe /platform:x64 /optimize+ "/win32manifest:$unpackagedManifest" `
    "/out:$unpackagedExe" @references $source
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $unpackagedExe)) {
    throw "Unpackaged C# probe compilation failed."
}

$raw = & $unpackagedExe readiness pt-BR
if ($LASTEXITCODE -notin @(0, 2)) {
    throw "Readiness probe exited with code $LASTEXITCODE."
}
try {
    $readiness = $raw | ConvertFrom-Json
} catch {
    throw "Readiness probe did not emit valid JSON: $raw"
}
if ($null -eq $readiness.ok -or $readiness.command -ne "readiness") {
    throw "Readiness JSON contract is incomplete."
}
if ($readiness.capture_started -ne $false) {
    throw "Readiness must never start microphone capture."
}
Write-Host ("Readiness: package_identity={0}; pt-BR topic={1}; system={2}" -f `
    $readiness.package_identity, $readiness.topic_supported, $readiness.system_speech_language)

& $csc /nologo /target:exe /platform:x64 /optimize+ "/win32manifest:$appManifest" `
    "/out:$exe" @references $source
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $exe)) {
    throw "Identity-bound C# probe compilation failed."
}

if ($Pack) {
    $makeAppx = Get-ChildItem -LiteralPath "C:\Program Files (x86)\Windows Kits\10\bin" `
        -Recurse -Filter makeappx.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\x64\\makeappx\.exe$" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $makeAppx) {
        throw "MakeAppx.exe was not found. Install the Windows 10/11 SDK packaging tools."
    }
    $assets = Join-Path $stage "Assets"
    New-Item -ItemType Directory -Force -Path $assets | Out-Null
    Copy-Item -Force -LiteralPath (Join-Path $probeDir "Package.appxmanifest") `
        -Destination (Join-Path $stage "AppxManifest.xml")
    $pixel = [Convert]::FromBase64String(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    foreach ($name in @("StoreLogo.png", "Square150x150Logo.png", "Square44x44Logo.png")) {
        [IO.File]::WriteAllBytes((Join-Path $assets $name), $pixel)
    }
    $package = Join-Path $output "Smiteless.SttProbe.msix"
    # /nv is required for packages with external location because the executable and visual
    # assets are resolved from ExternalLocation at registration time, not stored in the MSIX.
    & $makeAppx pack /o /d $stage /nv /p $package
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $package)) {
        throw "Sparse package creation failed."
    }
    Write-Host "Unsigned sparse package: $package"
    Write-Warning "The package was not signed or registered. Follow README.md only after explicit approval."
}

Write-Host "Probe executable: $exe"
Write-Host "Unpackaged readiness executable: $unpackagedExe"
