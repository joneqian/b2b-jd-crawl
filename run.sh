#!/bin/bash
# Mac/Linux 启动脚本

echo "=============================="
echo "京东万商爬虫 - 启动"
echo "=============================="

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "✗ 未找到虚拟环境，请先运行 ./install.sh"
    exit 1
fi

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "✗ 未找到 .env 文件"
    echo "  请复制 .env.example 为 .env 并填写账号密码"
    echo "  cp .env.example .env"
    exit 1
fi

# 激活虚拟环境并运行
source venv/bin/activate
echo "✓ 已激活虚拟环境"
echo ""

python3 crawler_full.py
