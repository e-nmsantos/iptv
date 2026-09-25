@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ========================================
echo    IPTV Player - Gerador de Instalador
echo ========================================
echo.

REM Resolve paths
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

REM Find Python in venv
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "..\.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_ROOT%..\.venv\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo [1/3] A verificar dependencias e testes unitarios...
"%PYTHON_EXE%" -m unittest discover -s tests -v
if errorlevel 1 (
    echo.
    echo [ERRO] Os testes unitarios falharam. O build foi cancelado.
    pause
    exit /b 1
)

echo.
echo [2/3] A compilar executavel com PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean "packaging\windows\iptv_player.spec"
if errorlevel 1 (
    echo.
    echo [ERRO] Falha na compilacao com PyInstaller.
    pause
    exit /b 1
)

echo.
echo [3/3] A gerar pacote de distribuicao...
REM Check for Inno Setup compiler
set "ISCC_EXE="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_EXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_EXE=C:\Program Files\Inno Setup 6\ISCC.exe"

if defined ISCC_EXE (
    echo A compilar instalador com Inno Setup...
    "%ISCC_EXE%" "packaging\windows\installer.iss"
    echo [SUCESSO] Instalador criado em: release\
) else (
    echo [AVISO] Inno Setup 6 nao encontrado. O executavel portatil esta disponivel em: dist\IPTVPlayer\
)

REM Create portable ZIP
powershell -Command "Compress-Archive -Path 'dist\IPTVPlayer\*' -DestinationPath 'release\IPTVPlayer-Portable.zip' -Force" -ErrorAction SilentlyContinue

echo.
echo ========================================
echo   Processo de build concluido com sucesso!
echo ========================================
echo   - Pasta Portatil: dist\IPTVPlayer\
echo   - Ficheiro Zip:   release\IPTVPlayer-Portable.zip
echo ========================================
echo.
pause

