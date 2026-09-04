[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RequiredEnvironmentVariable {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required environment variable '$Name' is not set."
    }
    return $value
}

$target = (Resolve-Path -LiteralPath $Path).Path
$endpoint = Get-RequiredEnvironmentVariable "ARTIFACT_SIGNING_ENDPOINT"
$account = Get-RequiredEnvironmentVariable "ARTIFACT_SIGNING_ACCOUNT"
$profile = Get-RequiredEnvironmentVariable "ARTIFACT_SIGNING_PROFILE"

$programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
if ([string]::IsNullOrWhiteSpace($programFilesX86)) {
    throw "ProgramFiles(x86) is not available."
}

$dlibCandidates = @(
    (Join-Path $programFilesX86 "Microsoft\ArtifactSigningClientTools\bin\Azure.CodeSigning.Dlib.dll"),
    (Join-Path $programFilesX86 "Microsoft\ArtifactSigningClientTools\bin\x64\Azure.CodeSigning.Dlib.dll")
)
$dlib = $dlibCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $dlib) {
    throw "Azure.CodeSigning.Dlib.dll was not found. Install Microsoft Artifact Signing Client Tools first."
}

$sdkBin = Join-Path $programFilesX86 "Windows Kits\10\bin"
$signtoolCandidates = @(Get-ChildItem -Path (Join-Path $sdkBin "*\x64\signtool.exe") -File -ErrorAction SilentlyContinue)
if ($signtoolCandidates.Count -eq 0) {
    throw "A 64-bit Windows SDK signtool.exe was not found under '$sdkBin'."
}

$signtool = $signtoolCandidates |
    Sort-Object -Property @{ Expression = {
        try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" }
    } } -Descending |
    Select-Object -First 1 -ExpandProperty FullName

$metadataPath = Join-Path $env:RUNNER_TEMP "vaporstep-artifact-signing-metadata.json"
$metadata = @{
    Endpoint = $endpoint
    CodeSigningAccountName = $account
    CertificateProfileName = $profile
    CorrelationId = "$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT"
    ExcludeCredentials = @(
        "EnvironmentCredential",
        "WorkloadIdentityCredential",
        "ManagedIdentityCredential",
        "SharedTokenCacheCredential",
        "VisualStudioCredential",
        "VisualStudioCodeCredential",
        "AzurePowerShellCredential",
        "AzureDeveloperCliCredential",
        "InteractiveBrowserCredential"
    )
} | ConvertTo-Json -Depth 4

[System.IO.File]::WriteAllText(
    $metadataPath,
    $metadata,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host "Signing '$target' with Artifact Signing profile '$profile'."
& $signtool sign `
    /v `
    /fd SHA256 `
    /tr "http://timestamp.acs.microsoft.com" `
    /td SHA256 `
    /dlib $dlib `
    /dmdf $metadataPath `
    $target

if ($LASTEXITCODE -ne 0) {
    throw "SignTool failed with exit code $LASTEXITCODE while signing '$target'."
}
