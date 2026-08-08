param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Install", "Remove")]
    [string]$Action,
    [string]$CertificatePath,
    [string]$Thumbprint
)

$ErrorActionPreference = "Stop"
$expectedSubject = "CN=Smiteless Development"
$store = "Cert:\LocalMachine\TrustedPeople"

if ($Action -eq "Install") {
    if (-not $CertificatePath) { throw "CertificatePath is required for Install." }
    $resolved = (Resolve-Path -LiteralPath $CertificatePath).Path
    $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($resolved)
    if ($certificate.Subject -ne $expectedSubject -or $certificate.Issuer -ne $expectedSubject) {
        throw "Refusing certificate with unexpected subject or issuer."
    }
    $codeSigning = @($certificate.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.37" } |
        ForEach-Object { $_.Format($false) }) -join " "
    if ($codeSigning -notmatch "1\.3\.6\.1\.5\.5\.7\.3\.3|Code Signing|Assinatura do C.digo") {
        throw "Refusing certificate without the Code Signing EKU."
    }
    if ($certificate.NotAfter -gt (Get-Date).AddDays(8) -or $certificate.NotAfter -le (Get-Date)) {
        throw "Refusing certificate outside the bounded development validity window."
    }
    $existing = Join-Path $store $certificate.Thumbprint
    if (-not (Test-Path -LiteralPath $existing)) {
        Import-Certificate -FilePath $resolved -CertStoreLocation $store | Out-Null
    }
    Write-Output $certificate.Thumbprint
    exit 0
}

$normalized = ($Thumbprint -replace "[^0-9A-Fa-f]", "").ToUpperInvariant()
if ($normalized.Length -ne 40) { throw "A full SHA-1 Thumbprint is required for Remove." }
$target = Join-Path $store $normalized
if (Test-Path -LiteralPath $target) {
    $certificate = Get-Item -LiteralPath $target
    if ($certificate.Subject -ne $expectedSubject) {
        throw "Refusing to remove a certificate with an unexpected subject."
    }
    Remove-Item -LiteralPath $target
}
Write-Output $normalized
