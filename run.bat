@echo off
REM chcp 65001 >nul
echo ==============================
echo 京东万商爬虫 - 启动
echo ==============================

REM 检查虚拟环境
if not exist "venv" (
    echo X 未找到虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)

REM 检查 .env 文件
if not exist ".env" (
    echo X 未找到 .env 文件
    echo   请复制 .env.example 为 .env 并填写账号密码
    echo   copy .env.example .env
    pause
    exit /b 1
)

REM 激活虚拟环境并运行
call venv\Scripts\activate.bat
echo √ 已激活虚拟环境
echo.

python crawler_full.py

pause
