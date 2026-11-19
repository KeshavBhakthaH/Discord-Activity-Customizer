@echo off
setlocal enabledelayedexpansion

echo ===================================================================
echo   Discord Activity Customizer - PyInstaller Standalone EXE Build
echo ===================================================================
echo.

:: Ensure python is available
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found in PATH. Please install Python or add it to PATH.
    pause
    exit /b 1
)

:: Ensure PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] PyInstaller not detected. Installing dependencies from requirements.txt...
    python -m pip install -r requirements.txt
)

echo [INFO] Building standalone Windows executable...
echo.

python -m PyInstaller --noconfirm DiscordActivityCustomizer.spec

echo.
if %ERRORLEVEL% EQU 0 (
    echo ===================================================================
    echo [SUCCESS] Build completed successfully!
    echo Executable is located at: dist\DiscordActivityCustomizer.exe
    echo ===================================================================
) else (
    echo ===================================================================
    echo [ERROR] Build failed with exit code %ERRORLEVEL%.
    echo Check the console output above for details.
    echo ===================================================================
)

echo.
pause
