@echo off
setlocal

set "APP_PATH=%~1"
set "PYTHON_EXE=%APP_PATH%\python\python.exe"
set "VENV_DIR=%APP_PATH%\.venv"

echo "A criar ambiente virtual em %VENV_DIR%..."
"%PYTHON_EXE%" -m venv "%VENV_DIR%"

echo "A instalar dependências..."
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%APP_PATH%\requirements.txt"

endlocal
exit /b 0