@echo off
set "JAVA_HOME=C:\Program Files\Android\Android Studio\jbr"
set "PATH=C:\Program Files\Android\Android Studio\jbr\bin;%PATH%"
cd /d "%~dp0"
call "%~dp0gradlew.bat" assembleDebug
if exist "app\build\outputs\apk\debug\app-debug.apk" (
    copy /y "app\build\outputs\apk\debug\app-debug.apk" "..\IPTV-Player-TV.apk"
    echo APK copiado para IPTV-Player-TV.apk com sucesso!
)
