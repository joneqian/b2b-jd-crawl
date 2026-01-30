#!/bin/bash
# Mac/Linux 安装脚本

echo "=============================="
echo "京东万商爬虫 - 安装依赖"
echo "=============================="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "✗ 未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

echo "✓ Python 版本: $(python3 --version)"

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "→ 创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "→ 激活虚拟环境..."
source venv/bin/activate

# 升级 pip
echo "→ 升级 pip..."
pip install --upgrade pip -q

# 安装依赖
echo "→ 安装依赖包..."
pip install -r requirements.txt -q

# 安装 Playwright 浏览器
echo "→ 安装 Playwright 浏览器 (Chromium)..."
playwright install chromium

echo ""
echo "=============================="
echo "✓ 安装完成！"
echo "=============================="
echo ""
echo "下一步："
echo "1. 复制 .env.example 为 .env 并填写账号密码"
echo "   cp .env.example .env"
echo ""
echo "2. 运行爬虫"
echo "   ./run.sh"
echo ""
