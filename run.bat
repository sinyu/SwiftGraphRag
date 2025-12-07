@echo off
SETLOCAL

REM Check for Python
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in PATH. Please install Python 3.10+.
    PAUSE
    EXIT /B 1
)

REM Create Virtual Environment if it doesn't exist
IF NOT EXIST "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate Virtual Environment
call venv\Scripts\activate

REM Install Dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Check if Django project exists, if not create it
IF NOT EXIST "graphrag_marketplace" (
    echo Creating Django project...
    django-admin startproject graphrag_marketplace .
)

REM Run Migrations
echo Running migrations...
python manage.py migrate

REM Create Default Admin (Custom command to be implemented)
echo Checking/Creating default admin...
python manage.py init_admin

REM Start Server
echo Starting server at http://127.0.0.1:8000
python manage.py runserver 0.0.0.0:8000

ENDLOCAL
