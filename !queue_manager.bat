@echo off
setlocal

REM Check if .venv exists
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment
        pause
        exit /b 1
    )
    
    echo Installing requirements...
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Failed to install requirements
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists
)

REM Activate the virtual environment and run the script
call .\.venv\Scripts\activate.bat
.\.venv\Scripts\python queue_manager.py

pause