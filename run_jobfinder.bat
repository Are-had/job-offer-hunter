@echo off
REM Double-click to start Job Finder with the "jobfinder" conda environment (Python 3.11).
cd /d "%~dp0"

set "PY=%USERPROFILE%\anaconda3\envs\jobfinder\python.exe"

if not exist "%PY%" (
    echo The "jobfinder" environment was not found at:
    echo   %PY%
    echo Open "Anaconda Prompt", cd to this folder and run:
    echo   conda create -n jobfinder python=3.11 -y
    echo   conda activate jobfinder
    echo   pip install -r requirements.txt
    echo   playwright install chromium
    pause
    exit /b 1
)

"%PY%" -m streamlit run app.py
pause
