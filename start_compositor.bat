@echo off
setlocal
cd /d "%~dp0"
python -c "import yaml" 1>nul 2>nul
if errorlevel 1 (
    echo Installing PyYAML...
    python -m pip install --quiet --disable-pip-version-check pyyaml || goto :error
)
set PYTHONPATH=%cd%\src
python -m compositor --open
endlocal
exit /b 0
:error
echo Compositor: dependency install failed.
endlocal
exit /b 1
