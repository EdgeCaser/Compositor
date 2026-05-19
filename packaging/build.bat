@echo off
setlocal
cd /d "%~dp0\.."
python -m pip install --quiet --disable-pip-version-check pyinstaller pyyaml || goto :error
python -m PyInstaller packaging\compositor.spec --noconfirm --clean
if errorlevel 1 goto :error
echo.
echo Built: %CD%\dist\compositor.exe
endlocal
exit /b 0
:error
echo Build failed.
endlocal
exit /b 1
