@echo off
setlocal

set BASE_DIR=C:\Users\sandeep\Downloads\Claudes
set SUITE_DIR=%BASE_DIR%\Script_to_run_all_LinkedIn_Instagram_scripts
set FIREFOX=C:\Program Files\Mozilla Firefox\firefox.exe
set LINKEDIN_URL=https://www.linkedin.com/feed/

echo ============================================================
echo   Zlinkedin_suite (Z-edition)
echo   LinkedIn + Instagram tasks in one Firefox session
echo ============================================================
echo.
echo   REQUIREMENTS before the Python script runs:
echo   1. Firefox must be running WITH Marionette enabled
echo   2. A Firefox window title must contain "LinkedIn" (logged in)
echo      OR "Instagram" if LinkedIn is not open (Task 7 only)
echo.
echo   This batch file will:
echo   - Start Firefox with --marionette and open LinkedIn feed
echo   - Wait 15 seconds for the page to load
echo   - Run Zlinkedin_suite.py (you pick tasks 1-8 at the prompt)
echo.
echo   Tip: choice 5 = Everything (LinkedIn tasks + Instagram + Fund Raising)
echo   Tip: choice 8 = Fund Raising AI comment (funding required, any startup sector)
echo.

if not exist "%FIREFOX%" (
    echo ERROR: Firefox not found at:
    echo   %FIREFOX%
    echo Edit FIREFOX in this .bat if installed elsewhere.
    pause
    exit /b 1
)

echo Starting Firefox with Marionette + LinkedIn...
start "" "%FIREFOX%" --marionette "%LINKEDIN_URL%"

echo Waiting 15 seconds for LinkedIn to load...
timeout /t 15 /nobreak >nul

cd /d "%SUITE_DIR%"
python "%SUITE_DIR%\Zlinkedin_suite.py"

echo.
echo ============================================================
echo   Batch finished. Browser closed; check logs_and_reports\
echo ============================================================
pause
endlocal
