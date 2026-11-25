# Build "Zone Companion.exe" (Windows). Usage, from the project folder in PowerShell:
#   .\build.ps1
# Result: dist\Zone Companion.exe  (a single file you can copy to another PC)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Use the project's .venv if it exists, otherwise the Python on PATH.
$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

Write-Host "==> Installation des dépendances" -ForegroundColor Cyan
& $python -m pip install --upgrade pip | Out-Null
& $python -m pip install -r requirements.txt

Write-Host "==> Construction de l'exécutable" -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "Zone Companion" `
    --icon "zone_new_companion\icon\icon.ico" `
    --add-data "zone_new_companion\icon\icon.ico;zone_new_companion/icon" `
    --add-data "media;media" `
    --collect-submodules zone_new_companion `
    --hidden-import PyQt6.QtNetwork `
    --exclude-module matplotlib `
    --exclude-module scipy `
    --exclude-module tkinter `
    main.py

Write-Host ""
Write-Host "OK : dist\Zone Companion.exe" -ForegroundColor Green
Write-Host "Sur l'autre PC il faut seulement VLC (64 bits) : https://www.videolan.org/vlc/"
