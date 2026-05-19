@echo off
setlocal
cd /d "%~dp0\.."
python -m pip install --quiet --disable-pip-version-check pyinstaller pyyaml || goto :error
python -m PyInstaller packaging\compositor.spec --noconfirm --clean
if errorlevel 1 goto :error

echo.
echo Built: %CD%\dist\compositor.exe
for %%I in ("dist\compositor.exe") do echo Size:  %%~zI bytes

echo.
echo Computing SHA256...
certutil -hashfile dist\compositor.exe SHA256 | findstr /v ":" | findstr /v "CertUtil" > dist\compositor.exe.sha256
type dist\compositor.exe.sha256
echo (saved to dist\compositor.exe.sha256)

endlocal
exit /b 0
:error
echo Build failed.
endlocal
exit /b 1
