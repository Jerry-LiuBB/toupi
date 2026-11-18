@echo off
echo ========================================
echo Canon Camera Control - Build Script
echo ========================================
echo.

cd /d "%~dp0"

echo Building project...
dotnet build CanonCameraControl.csproj -c Release

if %ERRORLEVEL% NEQ 0 (
    echo Build failed
    pause
    exit /b 1
)

echo.
echo [Success] Build completed!
echo.
echo To run the program:
echo   dotnet run --project CanonCameraControl.csproj -c Release
echo.
echo Or double-click Run.bat
echo.

pause
