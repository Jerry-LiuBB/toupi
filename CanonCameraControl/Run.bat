@echo off
echo ========================================
echo Canon Camera Control - Run Script
echo ========================================
echo.

cd /d "%~dp0"

set DOWNLOAD_PATH=C:\Users\dell\Downloads\CanonCameraPhotos
set NUM_PHOTOS=1
set DELAY=2000

echo Current settings:
echo   Download Path: %DOWNLOAD_PATH%
echo   Number of Photos: %NUM_PHOTOS%
echo   Delay between photos: %DELAY%ms
echo.
echo To customize, edit this file or pass arguments:
echo   Run.bat "D:\Photos" 5 3000
echo.

dotnet run --project CanonCameraControl.csproj -c Release -- %DOWNLOAD_PATH% %NUM_PHOTOS% %DELAY%

pause
