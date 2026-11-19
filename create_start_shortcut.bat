@echo off
setlocal enabledelayedexpansion

echo ===================================================================
echo   Discord Activity Customizer - Start Menu Shortcut Setup
echo ===================================================================
echo.

set "EXE_PATH=%~dp0dist\DiscordActivityCustomizer.exe"
set "ICON_PATH=%~dp0assets\app_icon.ico"
set "START_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

if not exist "!EXE_PATH!" (
    echo [ERROR] Could not find executable at: !EXE_PATH!
    echo Please run build_exe.bat first or check the dist folder.
    pause
    exit /b 1
)

echo [INFO] Creating Start Menu shortcut: "Discord Activity Customizer"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$s = $ws.CreateShortcut('!START_MENU!\Discord Activity Customizer.lnk'); " ^
    "$s.TargetPath = '!EXE_PATH!'; " ^
    "$s.WorkingDirectory = '%~dp0dist'; " ^
    "if (Test-Path '!ICON_PATH!') { $s.IconLocation = '!ICON_PATH!, 0' } else { $s.IconLocation = '!EXE_PATH!, 0' }; " ^
    "$s.Description = 'Customize Discord Rich Presence locally'; " ^
    "$s.Save()"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ===================================================================
    echo [SUCCESS] Shortcut created successfully!
    echo.
    echo You can now press your Windows Key and type:
    echo   "Discord Activity Customizer"
    echo.
    echo It will appear in Windows Search as an installed app (without .exe)!
    echo ===================================================================
) else (
    echo [ERROR] Failed to create shortcut.
)

echo.
pause
