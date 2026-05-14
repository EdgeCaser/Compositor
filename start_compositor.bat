@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%cd%\src
python -m compositor --open
endlocal
