@echo off
rem Define a codificacao para UTF-8 para suporte a acentos
chcp 65001 >nul
setlocal
title IPTV Player

echo ========================================
echo       IPTV Player - A iniciar...
echo ========================================
echo.

rem Muda o diretorio atual para a pasta do script.
cd /d "%~dp0"

rem --- Verificacao do VLC ---
echo A verificar a instalacao do VLC...
set "VLC_FOUND=0"
if exist "C:\Program Files\VideoLAN\VLC\vlc.exe" set "VLC_FOUND=1"
if exist "C:\Program Files (x86)\VideoLAN\VLC\vlc.exe" set "VLC_FOUND=1"
if %VLC_FOUND% equ 0 (
    reg query "HKLM\SOFTWARE\VideoLAN\VLC" /v InstallDir >nul 2>&1 && set "VLC_FOUND=1"
)
if %VLC_FOUND% equ 0 (
    reg query "HKLM\SOFTWARE\WOW6432Node\VideoLAN\VLC" /v InstallDir >nul 2>&1 && set "VLC_FOUND=1"
)
if %VLC_FOUND% equ 0 (
    reg query "HKCU\Software\VideoLAN\VLC" /v InstallDir >nul 2>&1 && set "VLC_FOUND=1"
)

if %VLC_FOUND% equ 0 (
    echo [^!] AVISO: O VLC Media Player nao parece estar instalado.
    echo     A aplicacao pode necessitar do VLC instalado para reproduzir video.
    echo     Download gratuito em: https://www.videolan.org/vlc/
    echo.
)

rem --- Definicao do Ambiente Virtual ---
set "VENV_DIR=%~dp0.venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    if exist "%~dp0..\.venv\Scripts\python.exe" (
        set "VENV_DIR=%~dp0..\.venv"
    )
)
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

rem Se o ambiente virtual nao existir, tenta criar
if not exist "%PYTHON_EXE%" (
    echo [^!] Ambiente virtual nao encontrado. A criar em %VENV_DIR%...
    py -3 -m venv "%VENV_DIR%" 2>nul
    if errorlevel 1 (
        python -m venv "%VENV_DIR%" 2>nul
    )
)

if not exist "%PYTHON_EXE%" (
    echo [^!] ERRO: Nao foi possivel criar o ambiente virtual.
    echo     Verifica se o Python 3.10+ esta instalado e disponivel no PATH.
    pause
    exit /b 1
)

echo A verificar dependencias no ambiente virtual...
"%PYTHON_EXE%" -c "import PySide6, vlc, requests, keyring, aiohttp, lxml, m3u8, aiofiles; from Crypto.Cipher import AES" 2>nul
if %errorlevel% neq 0 (
    echo [^!] A instalar/atualizar dependencias necessarias...
    echo [i] A atualizar o gestor pip...
    "%PYTHON_EXE%" -m pip install --upgrade pip >"pip_upgrade.log" 2>&1
    echo [i] A instalar pacotes de requirements.txt...
    "%PYTHON_EXE%" -m pip install -r requirements.txt >"pip_install.log" 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo [^!] ERRO: Nao foi possivel instalar as dependencias.
        echo     Consulta o ficheiro 'pip_install.log' para mais detalhes.
        pause
        exit /b 1
    )
)

if /I "%~1"=="--check" (
    "%PYTHON_EXE%" -c "import sys, keyring; print('Python:', sys.executable); print('Dependencias: OK')"
    if %errorlevel% neq 0 exit /b 1
    exit /b 0
)

echo.
echo A iniciar o IPTV Player...
echo.
"%PYTHON_EXE%" main.py %*

if %errorlevel% neq 0 (
    echo.
    echo [^!] A aplicacao terminou com erro ou foi encerrada.
    echo.
    pause
)

endlocal
