@echo off
rem Define o modo de execucao para evitar que os comandos sejam exibidos.
setlocal
title IPTV Player
echo ========================================
echo       IPTV Player - A iniciar...
echo ========================================
echo.

rem Muda o diretorio atual para o diretorio do script.
cd /d "%~dp0"

rem --- Verificação do VLC ---
echo A verificar a instalação do VLC...
reg query "HKLM\SOFTWARE\VideoLAN\VLC" /v InstallDir >nul 2>&1
if %errorlevel% neq 0 (
    echo [^!] AVISO: O VLC Media Player não parece estar instalado.
    echo     A aplicação pode não funcionar corretamente.
    echo     Visite https://www.videolan.org/vlc/ para o instalar.
    echo.
)

rem Define os caminhos para o ambiente virtual e o executavel Python.
set "VENV_DIR=%~dp0..\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

rem Verifica se o ambiente virtual existe, caso contrario, cria-o.
if not exist "%PYTHON_EXE%" (
    echo [^!] Ambiente virtual nao encontrado. A criar...
    rem Tenta criar o ambiente virtual com 'py -3', com fallback para 'python'.
    py -3 -m venv "%VENV_DIR%" 2>NUL
    if errorlevel 1 (
        echo [i] 'py -3' falhou ou nao foi encontrado. A tentar com 'python'...
        python -m venv "%VENV_DIR%"
    )
)

if not exist "%PYTHON_EXE%" (
    echo [^!] ERRO: Nao foi possivel criar o ambiente virtual.
    echo     Verifica se o Python esta instalado e disponivel no PATH.
    pause
    exit /b 1
)

echo A verificar dependencias no ambiente virtual...
"%PYTHON_EXE%" -c "import PySide6, vlc, requests, keyring; from Crypto.Cipher import AES" 2>nul
if %errorlevel% neq 0 (
    echo [^!] A instalar dependencias...
    rem Atualiza o pip para a versao mais recente.
    echo [i] A atualizar o pip...
    "%PYTHON_EXE%" -m pip install --upgrade pip >"pip_upgrade.log" 2>&1
    rem Instala as dependencias a partir do ficheiro requirements.txt.
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
"%PYTHON_EXE%" main.py

if %errorlevel% neq 0 (
    echo.
    echo [^!] Erro ao iniciar. Verifica os detalhes acima.
    echo.
    pause
)

endlocal
