@echo off
REM Installs everything Job Offer Hunter needs INSIDE this folder (.conda\): Python 3.11, Node.js, the Python packages,
REM the pages (React) and the browser Playwright drives. Nothing is installed elsewhere on the computer.
REM To remove it all: delete the .conda folder (and frontend\node_modules, frontend\dist).
cd /d "%~dp0"

set "CONDA=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not exist "%CONDA%" set "CONDA=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not exist "%CONDA%" (
    echo Anaconda or Miniconda was not found in %USERPROFILE%. Install Miniconda first: https://docs.conda.io/
    pause
    exit /b 1
)

set "ENV=%~dp0.conda"
if not exist "%ENV%\python.exe" (
    echo [1/4] Python 3.11 and Node.js, in %ENV%
    call "%CONDA%" create -y -p "%ENV%" -c conda-forge --override-channels python=3.11 "nodejs>=20" || goto :fail
)
set "PATH=%ENV%;%ENV%\Scripts;%PATH%"
set "PLAYWRIGHT_BROWSERS_PATH=%ENV%\ms-playwright"
REM only the packages of .conda: never those installed for your user elsewhere on the computer
set "PYTHONNOUSERSITE=1"

echo [2/4] Python packages
"%ENV%\python.exe" -m pip install -q -r requirements.txt || goto :fail
echo [3/4] The browser for the websites that need one (Chromium, in .conda\ms-playwright)
"%ENV%\python.exe" -m playwright install chromium || goto :fail
echo [4/4] The pages
pushd frontend
call npm install --no-audit --no-fund || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd

echo.
echo Done. Double-click run.bat to start Job Offer Hunter.
pause
exit /b 0

:fail
echo.
echo The setup stopped on an error (above). Run setup.bat again once it is fixed.
pause
exit /b 1
