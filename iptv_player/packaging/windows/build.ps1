$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Push-Location $ProjectRoot
try {
    python -m pip install -r requirements-dev.txt
    python -m pytest
    python -m PyInstaller --noconfirm --clean packaging\windows\iptv_player.spec
    Write-Host "Build criado em dist\IPTVPlayer"
    Write-Host "O VLC deve estar instalado no computador de destino."
}
finally {
    Pop-Location
}

