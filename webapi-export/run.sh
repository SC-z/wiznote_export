#!/bin/bash
# 为知笔记团队备份工具启动脚本

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误：未找到Python3，请先安装Python 3.6或更高版本"
    exit 1
fi

# 检查是否在正确的目录
if [ ! -f "main.py" ]; then
    echo "错误：请在项目根目录运行此脚本"
    exit 1
fi

# 检查虚拟环境
if [ -d "venv" ]; then
    echo "激活虚拟环境..."
    source venv/bin/activate
elif [ -d "$HOME/python-env" ]; then
    echo "激活用户虚拟环境..."
    source "$HOME/python-env/bin/activate"
fi

# 检查依赖
echo "检查依赖..."
pip install -q -r requirements.txt

# 运行主程序
echo "启动为知笔记备份工具..."
python3 main.py "$@"