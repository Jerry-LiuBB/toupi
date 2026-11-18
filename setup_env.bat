@echo off
chcp 65001 >nul
title 头皮检测系统 - 环境配置脚本

echo ============================================================
echo          头皮检测系统 - 一键环境配置脚本
echo ============================================================
echo.

set "PYTHON_MIN_VERSION=3.8"
set "VENV_DIR=venv"
set "REQUIREMENTS_FILE=requirements.txt"

echo [1/6] 检查 Python 安装...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: 未检测到 Python，请先安装 Python %PYTHON_MIN_VERSION%+
    echo        下载地址: https://www.python.org/downloads/windows/
    echo        安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYTHON_VERSION=%%v
echo       Python 版本: %PYTHON_VERSION%

echo.
echo [2/6] 检查 pip 是否可用...
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: pip 不可用，请检查 Python 安装
    pause
    exit /b 1
)
echo       pip 可用

echo.
echo [3/6] 创建虚拟环境...
if exist "%VENV_DIR%" (
    echo       虚拟环境已存在，跳过创建
) else (
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo ERROR: 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo       虚拟环境创建成功
)

echo.
echo [4/6] 激活虚拟环境并安装依赖...
call "%VENV_DIR%\Scripts\activate.bat"

pip install --upgrade pip >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: 更新 pip 失败，继续安装依赖
)

pip install -r "%REQUIREMENTS_FILE%"
if %errorlevel% neq 0 (
    echo ERROR: 安装依赖失败
    pause
    exit /b 1
)
echo       依赖安装成功

echo.
echo [5/6] 验证依赖安装...
echo       正在验证 numpy...
python -c "import numpy; print('  numpy:', numpy.__version__)" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: numpy 验证失败
    pause
    exit /b 1
)

echo       正在验证 opencv-python...
python -c "import cv2; print('  opencv-python:', cv2.__version__)" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: opencv-python 验证失败
    pause
    exit /b 1
)

echo       正在验证 pyrealsense2...
python -c "import pyrealsense2 as rs; print('  pyrealsense2:', rs.__version__)" >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: pyrealsense2 验证失败，请确保已安装 RealSense SDK
    echo          下载地址: https://dev.intelrealsense.com/docs/deployment
)

echo       正在验证 flask...
python -c "import flask; print('  flask:', flask.__version__)" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: flask 验证失败
    pause
    exit /b 1
)

echo       正在验证 Pillow...
python -c "from PIL import Image; print('  Pillow:', Image.__version__)" >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Pillow 未安装，将安装...
    pip install Pillow >nul 2>&1
    if %errorlevel% neq 0 (
        echo ERROR: Pillow 安装失败
        pause
        exit /b 1
    )
    echo       Pillow 安装成功
)

echo.
echo [6/6] 配置完成！
echo ============================================================
echo.
echo 运行方式：
echo   1. 双击运行 run_server.bat
echo   2. 打开浏览器访问: http://127.0.0.1:8080
echo   3. 点击"开始检测"按钮
echo.
echo 注意事项：
echo   - 确保 RealSense D435 相机已连接
echo   - 确保 Canon 相机已连接
echo   - 确保机械臂已连接并开机
echo.
echo 按任意键退出...
pause >nul