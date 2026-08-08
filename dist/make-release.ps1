# Cut a new Smiteless release so your brother's copy can update itself.
#
#   powershell -ExecutionPolicy Bypass -File dist\make-release.ps1 -Version 1.1.0 `
#     [-Notes "what changed"]
#
# It bumps VERSION, builds SmitelessSetup.exe, commits, tags, and publishes a GitHub Release
# with the installer attached. The installed app checks that release and offers the update.
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = "",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$ver  = $Version.TrimStart('v')

Write-Host "==> set VERSION = $ver" -ForegroundColor Cyan
[IO.File]::WriteAllText((Join-Path $repo "VERSION"), $ver)

Write-Host "==> build" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "build.ps1") -Python $Python
$setup = Join-Path $repo "build\SmitelessSetup.exe"
if (-not (Test-Path $setup)) { throw "build did not produce SmitelessSetup.exe" }

Write-Host "==> commit + push VERSION" -ForegroundColor Cyan
git -C $repo add VERSION
git -C $repo commit -m "Release v$ver"
git -C $repo push origin main

Write-Host "==> publish GitHub release v$ver" -ForegroundColor Cyan
if (-not $Notes) { $Notes = "Smiteless v$ver" }
# gh may not be logged in (a fresh shell, a cloud session, a rotated host). The push above
# already proved git HAS a working github.com credential, so borrow it rather than failing
# at the last step - a build that ships everything except the release the updater reads is
# the worst possible outcome.
# `git credential fill` reads its query from stdin, and PowerShell's pipe does NOT deliver a
# here-string to a native command's stdin (it arrives empty and git exits 128) - so the query
# goes through a temp file redirect via cmd.
if (-not $env:GH_TOKEN -and -not $env:GITHUB_TOKEN) {
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, "protocol=https`nhost=github.com`n`n")
        $m = (cmd /c "git credential fill < `"$tmp`"" 2>$null) | Select-String '^password=(.+)$'
        if ($m) {
            $env:GH_TOKEN = $m.Matches.Groups[1].Value
            Write-Host "    (using git's stored github.com credential)" -ForegroundColor DarkGray
        }
    } finally { try { [IO.File]::Delete($tmp) } catch {} }
}
gh release create "v$ver" $setup --repo bobbyroylee/smiteless --title "Smiteless v$ver" --notes $Notes
if ($LASTEXITCODE -ne 0) { throw "gh release create failed - v$ver is pushed but NOT published, so the in-app updater will not offer it. Fix auth and re-run: gh release create v$ver `"$setup`" --repo bobbyroylee/smiteless --title `"Smiteless v$ver`" --notes `"$Notes`"" }

Write-Host "`nReleased v$ver. Installed copies will offer the update on next launch." -ForegroundColor Green
