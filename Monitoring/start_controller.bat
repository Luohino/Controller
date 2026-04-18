@echo off
echo [SYSTEM] INITIALIZING CORE CONTROLLER...
echo [SYSTEM] CHECKING DEPENDENCIES...
pip install -r requirements.txt
echo.

:loop
echo [SYSTEM] STARTING MONITORING APP...
python main.py
echo.
echo ============================================
echo   Press R to RESTART  or  Q to QUIT
echo ============================================
set /p choice=">> "
if /i "%choice%"=="r" goto loop
if /i "%choice%"=="q" goto end
goto loop

:end
echo [SYSTEM] Controller stopped.
