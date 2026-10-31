@echo off
setlocal
rem Procura um JDK 21: Eclipse Adoptium (qualquer versao) e depois o JBR do Android Studio.
rem Se nenhum existir, fica o JAVA_HOME que ja estiver definido no sistema.
set "FOUND_JDK="
for /d %%D in ("C:\Program Files\Eclipse Adoptium\jdk-21*") do (
    if exist "%%~D\bin\javac.exe" set "FOUND_JDK=%%~D"
)
if not defined FOUND_JDK if exist "C:\Program Files\Android\Android Studio\jbr\bin\javac.exe" (
    set "FOUND_JDK=C:\Program Files\Android\Android Studio\jbr"
)
if defined FOUND_JDK set "JAVA_HOME=%FOUND_JDK%"
if defined JAVA_HOME (
    echo A usar JAVA_HOME=%JAVA_HOME%
    set "PATH=%JAVA_HOME%\bin;%PATH%"
) else (
    echo Aviso: nenhum JDK encontrado, o Gradle vai tentar usar o java do PATH.
)

rem Por omissao gera a versao release (R8, mais rapida na box). "build_apk.bat debug" gera a de debug.
set "VARIANT=release"
set "GRADLE_TASK=assembleRelease"
if /i "%~1"=="debug" (
    set "VARIANT=debug"
    set "GRADLE_TASK=assembleDebug"
)
set "APK=app\build\outputs\apk\%VARIANT%\app-%VARIANT%.apk"

cd /d "%~dp0"
call "%~dp0gradlew.bat" %GRADLE_TASK%
if errorlevel 1 (
    echo.
    echo Build falhou. O APK nao foi copiado.
    set "EXIT_CODE=1"
    goto end
)

if not exist "%APK%" (
    echo Build terminou mas %APK% nao foi encontrado.
    set "EXIT_CODE=1"
    goto end
)
copy /y "%APK%" "..\IPTV-Player-TV.apk" >nul
if errorlevel 1 (
    echo Erro ao copiar o APK para IPTV-Player-TV.apk.
    set "EXIT_CODE=1"
    goto end
)
echo APK %VARIANT% copiado para IPTV-Player-TV.apk com sucesso!
set "EXIT_CODE=0"

:end
rem So pausa quando aberto com duplo clique (cmd /c), nao quando corrido num terminal.
echo %cmdcmdline% | find /i "/c" >nul && pause
exit /b %EXIT_CODE%
