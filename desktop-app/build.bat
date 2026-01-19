@echo off
REM Build script for JWhite Employee Status Desktop App
REM Creates a single .exe file using PyInstaller

echo ================================
echo JWhite Employee Status - Build
echo ================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

REM Build the executable
echo.
echo Building executable...
pyinstaller --onefile --noconsole ^
    --name "JWhiteEmployeeStatus" ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    --hidden-import=pystray._win32 ^
    --hidden-import=PIL._tkinter_finder ^
    employee_status_app.py

echo.
echo ================================
echo Build complete!
echo Executable: dist\JWhiteEmployeeStatus.exe
echo ================================

REM Deactivate virtual environment
deactivate
