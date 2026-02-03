@echo off
REM chcp 65001 >nul
echo ==============================
echo 京东万商爬虫 - 安装依赖
echo ==============================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo X 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do echo √ %%i

REM 创建虚拟环境
if not exist "venv" (
    echo → 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
echo → 激活虚拟环境...
call venv\Scripts\activate.bat

REM 升级 pip
echo → 升级 pip...
python -m pip install --upgrade pip -q

REM 安装依赖
echo → 安装依赖包...
pip install -r requirements.txt -q

REM 安装 Playwright 浏览器
echo → 安装 Playwright 浏览器 (Chromium)...
playwright install chromium

echo.
echo ==============================
echo √ 安装完成！
echo ==============================
echo.
echo 下一步：
echo 1. 复制 .env.example 为 .env 并填写账号密码
echo    copy .env.example .env
echo.
echo 2. 运行爬虫
echo    run.bat
echo.
pause
