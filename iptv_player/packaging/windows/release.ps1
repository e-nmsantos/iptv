param(
    [switch]$SkipBuild,
    [switch]$FinalizeOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PyProject = Get-Content (Join-Path $ProjectRoot "pyproject.toml") -Raw
$VersionMatch = [regex]::Match($PyProject, '(?m)^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"')
if (-not $VersionMatch.Success) {
    throw "Não foi possível determinar a versão em pyproject.toml."
}
$Version = $VersionMatch.Groups[1].Value
$DistDir = Join-Path $ProjectRoot "dist\IPTVPlayer"
$ReleaseDir = Join-Path $ProjectRoot "release"
$PortableName = "IPTVPlayer-$Version-windows-x86_64.zip"
$PortablePath = Join-Path $ReleaseDir $PortableName

if (-not $SkipBuild -and -not $FinalizeOnly) {
    & (Join-Path $PSScriptRoot "build.ps1")
}
if (-not (Test-Path (Join-Path $DistDir "IPTVPlayer.exe"))) {
    throw "Build em falta: $DistDir"
}
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
if (-not $FinalizeOnly) {
    Compress-Archive -Path (Join-Path $DistDir "*") -DestinationPath $PortablePath -Force
}
if (-not (Test-Path $PortablePath)) {
    throw "Pacote portátil em falta: $PortablePath"
}

$Artifacts = @()
function Add-ReleaseArtifact([string]$Path, [string]$Platform) {
    $Item = Get-Item $Path
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Item.FullName).Hash.ToLowerInvariant()
    $script:Artifacts += [ordered]@{
        platform = $Platform
        filename = $Item.Name
        url = ""
        sha256 = $Hash
        size = $Item.Length
    }
}

Add-ReleaseArtifact $PortablePath "windows-x86_64-portable"

$IsccCommand = Get-Command iscc -ErrorAction SilentlyContinue
$IsccCandidates = @(
    $(if ($IsccCommand) { $IsccCommand.Source }),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path $_) }
$IsccPath = $IsccCandidates | Select-Object -First 1
if ($IsccPath -and -not $FinalizeOnly) {
    & $IsccPath "/DMyAppVersion=$Version" (Join-Path $PSScriptRoot "installer.iss")
} elseif (-not $IsccPath -and -not $FinalizeOnly) {
    Write-Warning "Inno Setup não encontrado; o ZIP portátil foi criado sem instalador."
}
$InstallerPath = Join-Path $ReleaseDir "IPTVPlayer-$Version-Setup.exe"
if (Test-Path $InstallerPath) {
    Add-ReleaseArtifact $InstallerPath "windows-x86_64-installer"
}

$Manifest = [ordered]@{
    schema_version = 1
    version = $Version
    published_at = [DateTime]::UtcNow.ToString("o")
    notes_url = ""
    artifacts = $Artifacts
}
$ManifestPath = Join-Path $ReleaseDir "update-manifest.json"
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding utf8

$ChecksumLines = foreach ($Artifact in $Artifacts) {
    "$($Artifact.sha256)  $($Artifact.filename)"
}
$ChecksumLines | Set-Content -LiteralPath (Join-Path $ReleaseDir "SHA256SUMS.txt") -Encoding ascii

Write-Host "Release $Version criada em $ReleaseDir"
Get-ChildItem $ReleaseDir | Select-Object Name, Length, LastWriteTime
