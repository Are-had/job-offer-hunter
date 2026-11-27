@echo off
REM Double-click to start Job Offer Hunter: it opens http://127.0.0.1:8600 in your browser. Close this window to stop it.
REM The first time, run setup.bat (it installs everything inside this folder).
cd /d "%~dp0"

set "ENV=%~dp0.conda"
if not exist "%ENV%\python.exe" (
    echo Job Offer Hunter is not installed yet: double-click setup.bat first.
    pause
    exit /b 1
)
set "PATH=%ENV%;%ENV%\Scripts;%PATH%"
set "PLAYWRIGHT_BROWSERS_PATH=%ENV%\ms-playwright"
REM only the packages of .conda: never those installed for your user elsewhere on the computer
set "PYTHONNOUSERSITE=1"

if not exist "frontend\dist\index.html" (
    echo Building the pages, once...
    pushd frontend
    call npm run build
    popd
)

echo.
echo   Job Offer Hunter: open  http://127.0.0.1:8600  in your browser
echo   (it opens by itself in a few seconds; close this window to stop the app)
echo.
REM the browser, once the server is up; a default browser Windows refuses to open (Avast's...) only leaves the address above
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 3; try { Start-Process 'http://127.0.0.1:8600' -ErrorAction Stop } catch {}"
"%ENV%\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8600
pause
