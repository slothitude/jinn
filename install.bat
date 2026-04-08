@echo off
setlocal

echo ============================================
echo   JINN - Programmable Cognition System
echo   Windows Installer
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3.11+ and try again.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PYVER=%%v
echo [OK] Python %PYVER% found

:: Check Python version >= 3.11
python -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)"
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3.11+ required. Found %PYVER%
    pause
    exit /b 1
)

:: Install JINN
echo.
echo [1/3] Installing JINN...
pip install -e "%~dp0."
if %ERRORLEVEL% neq 0 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)

:: Install dev dependencies
echo.
echo [2/3] Installing dev dependencies...
pip install -e "%~dp0.[dev]"
if %ERRORLEVEL% neq 0 (
    echo [WARN] Dev dependencies failed. Core install OK.
)

:: Add to PATH
echo.
echo [3/3] Adding to PATH...
set "JINN_DIR=%~dp0"
set "JINN_DIR=%JINN_DIR:~0,-1%"

:: Check if already in PATH
echo %PATH% | findstr /i /c:"%JINN_DIR%" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Already in PATH
) else (
    powershell -Command "[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path', 'User') + ';%JINN_DIR%', 'User')"
    echo [OK] Added to user PATH
)

:: Done
echo.
echo ============================================
echo   Install complete!
echo   Open a new terminal and type: jinn
echo ============================================
echo.
pause
