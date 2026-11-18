@echo off
chcp 65001 >nul
title 头皮检测系统 - 服务端

echo ============================================================
echo          头皮检测系统 - 服务端启动
echo ============================================================
echo.

set "VENV_DIR=venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo ERROR: 虚拟环境不存在，请先运行 setup_env.bat
    pause
    exit /b 1
)

echo [1/2] 激活虚拟环境...
call "%VENV_DIR%\Scripts\activate.bat"

echo [2/2] 启动服务...
echo.
echo 服务已启动，请打开浏览器访问: http://127.0.0.1:8080
echo 按 Ctrl+C 停止服务
echo.

python src/scalp_detection_server.py

pause